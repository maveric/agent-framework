"""
React loop execution for worker agents.
"""

from typing import Any, Dict, Callable, List
from datetime import datetime

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage, AIMessage
from langgraph.prebuilt import create_react_agent

from orchestrator_types import Task, TaskPhase, WorkerProfile, WorkerResult, AAR, SuggestedTask
from llm_client import get_llm
from config import OrchestratorConfig, ModelConfig
from llm_logger import log_llm_request, validate_request_size, log_llm_response

from .utils import _detect_modified_files_via_git, _mock_execution


async def _execute_react_loop(
    task: Task,
    tools: List[Callable],
    system_prompt: str,
    state: Dict[str, Any],
    config: Dict[str, Any] = None
) -> WorkerResult:
    """
    Execute a ReAct loop using LangGraph's prebuilt agent (async version).
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # Get configuration
    mock_mode = state.get("mock_mode", False)
    if not mock_mode and config and "configurable" in config:
        mock_mode = config["configurable"].get("mock_mode", False)

    if mock_mode:
        return _mock_execution(task)

    # Get orchestrator config from state (has user's model settings)
    orch_config = state.get("orch_config")
    if not orch_config:
        orch_config = OrchestratorConfig()

    # Select model based on worker profile
    # This allows different models for planning vs coding vs testing
    profile = task.assigned_worker_profile

    model_map = {
        WorkerProfile.PLANNER: getattr(orch_config, 'planner_model', None),
        WorkerProfile.CODER: getattr(orch_config, 'coder_model', None),
        WorkerProfile.TESTER: getattr(orch_config, 'tester_model', None),
        WorkerProfile.RESEARCHER: getattr(orch_config, 'researcher_model', None),
        WorkerProfile.WRITER: getattr(orch_config, 'writer_model', None),
    }

    # Use profile-specific model, or fall back to worker_model
    model_config = model_map.get(profile) or orch_config.worker_model

    # Setup LLM with worker model config and limit max tokens
    limited_config = ModelConfig(
        provider=model_config.provider,
        model_name=model_config.model_name,
        temperature=model_config.temperature,
        max_tokens=4096  # Increased from 1000 to allow full code generation
    )
    llm = get_llm(limited_config)

    # Create react agent (no state_modifier needed - we'll include system message in inputs)
    agent = create_react_agent(llm, tools)

    # Initial input with system message
    inputs = {
        "messages": [
            SystemMessage(content=system_prompt),
            HumanMessage(content=f"Task: {task.description}\n\nAcceptance Criteria:\n" + "\n".join(f"- {c}" for c in task.acceptance_criteria))
        ]
    }

    # Log request for debugging
    try:
        workspace_path = state.get("_workspace_path")
        stats = log_llm_request(task.id, inputs["messages"], tools, {}, workspace_path=workspace_path)
        print(f"  [LOG] Request: {stats['message_count']} msgs, {stats['total_chars']} chars (~{stats['estimated_tokens']} tokens)", flush=True)
        print(f"  [LOG] Tools: {stats['tool_count']}, Log: {stats['log_file']}", flush=True)

        # Validate size (max 100K chars to prevent issues)
        validate_request_size(stats, max_chars=100000)
    except Exception as e:
        print(f"  [LOG ERROR]: {e}", flush=True)
        if "too large" in str(e).lower():
            raise

    print(f"  Starting ReAct agent...", flush=True)

    # NOTE: The recursion_limit=150 is the circuit breaker for infinite loops.

    # Invoke agent
    # We use a recursion limit to prevent infinite loops
    try:
        # Increased recursion limit to prevent "Sorry, need more steps" error
        # Using ainvoke for async execution
        result = await agent.ainvoke(inputs, config={"recursion_limit": 150})
    except Exception as e:
        # Handle errors gracefully - return AAR instead of crashing
        error_type = type(e).__name__
        error_msg = str(e)

        # Detect specific error types
        is_rate_limit = "rate_limit" in error_msg.lower() or "429" in error_msg
        is_tool_error = "access denied" in error_msg.lower() or "outside workspace" in error_msg.lower()

        print(f"  [AGENT ERROR] {error_type}: {error_msg[:200]}", flush=True)

        # Create appropriate AAR based on error type
        if is_rate_limit:
            aar = AAR(
                summary=f"Task failed due to API rate limit. The LLM provider returned a 429 error.",
                approach="ReAct agent execution interrupted by rate limit",
                challenges=[
                    f"Rate limit error: {error_msg[:500]}",
                    "Too many API calls in short time period",
                    "Consider: reducing task complexity, using cheaper model, or waiting before retry"
                ],
                decisions_made=["Terminated execution due to rate limit"],
                files_modified=[]
            )
        elif is_tool_error:
            aar = AAR(
                summary=f"Task failed due to tool usage error: {error_msg[:200]}",
                approach="ReAct agent execution interrupted by tool error",
                challenges=[
                    f"Tool error: {error_msg[:500]}",
                    "Agent attempted invalid operation (e.g., accessing outside workspace)",
                    "This indicates either: tool misuse by agent, or overly restrictive tool validation"
                ],
                decisions_made=["Terminated execution due to tool error"],
                files_modified=[]
            )
        else:
            aar = AAR(
                summary=f"Task failed with unexpected error: {error_type}",
                approach="ReAct agent execution interrupted by exception",
                challenges=[
                    f"{error_type}: {error_msg[:500]}",
                    "Unexpected error during agent execution"
                ],
                decisions_made=["Terminated execution due to error"],
                files_modified=[]
            )

        workspace_path = state.get("_workspace_path")
        result_path = log_llm_response(task.id, {"messages": []}, [], status="failed", workspace_path=workspace_path)

        return WorkerResult(
            status="failed",
            result_path=result_path,
            aar=aar,
            suggested_tasks=[],
            messages=[]
        )

    # Extract results
    messages = result["messages"]
    last_message = messages[-1]

    # NOTE: Loop detection removed. The recursion_limit=150 is the real circuit breaker.
    # Previous detection counted consecutive calls to same tool NAME without checking
    # if the arguments were different, causing false positives on test workers that
    # legitimately run many different shell commands in a row.

    # Identify modified files and suggested tasks from tool calls

    # CRITICAL: Use GIT to detect actual file changes (more reliable)
    files_modified = []
    suggested_tasks = []
    explicitly_completed = False
    completion_details = {}

    # PRIMARY: Use git to detect actual file changes in the worktree
    worktree_path = state.get("worktree_path")
    if worktree_path:
        files_modified = _detect_modified_files_via_git(worktree_path)

    # FALLBACK: If git detection failed or found nothing, parse tool calls
    # This also handles the case where worktree_path is not set
    if not files_modified:
        print(f"  [FALLBACK] Using tool-call parsing for file detection", flush=True)

        # Build a map of tool_call_id -> ToolMessage for success checking
        tool_results = {}
        for msg in messages:
            if isinstance(msg, ToolMessage):
                tool_results[msg.tool_call_id] = msg

        print(f"  [DEBUG] Found {len(tool_results)} tool results", flush=True)

        for msg in messages:
            if isinstance(msg, AIMessage) and msg.tool_calls:
                for tc in msg.tool_calls:
                    tool_call_id = tc.get("id")

                    # Get the corresponding ToolMessage result
                    tool_result = tool_results.get(tool_call_id) if tool_call_id else None

                    if tc["name"] in ["write_file", "append_file"]:
                        path = tc["args"].get("path")
                        print(f"  [DEBUG] {tc['name']} call: id={tool_call_id}, path={path}, has_result={tool_result is not None}", flush=True)
                        if path:
                            # Only count as modified if the tool succeeded (no error in result)
                            if tool_result:
                                # Check if the result contains an error
                                result_content = str(tool_result.content).lower()
                                if "error" not in result_content and "field required" not in result_content:
                                    files_modified.append(path)
                                    print(f"  [TRACKED] {tc['name']}: {path}", flush=True)
                                else:
                                    print(f"  [SKIP] Tool call failed for {path}: {tool_result.content[:100]}", flush=True)
                            else:
                                # No result found - might be a partial execution, don't count it
                                print(f"  [SKIP] No result found for {tc['name']} call to {path}", flush=True)

    # Parse tool calls for task creation and completion markers (not file operations)
    # Build a map of tool_call_id -> ToolMessage for success checking
    tool_results = {}
    for msg in messages:
        if isinstance(msg, ToolMessage):
            tool_results[msg.tool_call_id] = msg

    for msg in messages:
        if isinstance(msg, AIMessage) and msg.tool_calls:
            for tc in msg.tool_calls:
                tool_call_id = tc.get("id")

                # Get the corresponding ToolMessage result
                tool_result = tool_results.get(tool_call_id) if tool_call_id else None

                if tc["name"] == "report_existing_implementation":
                    explicitly_completed = True
                    completion_details = tc["args"]
                    print(f"  [LOG] Task marked as already implemented: {tc['args'].get('file_path')}", flush=True)

                elif tc["name"] == "create_subtasks":
                    print(f"  [DEBUG] Tool call: {tc.get('name')} args keys: {list(tc.get('args', {}).keys())}", flush=True)
                    subtasks = tc["args"].get("subtasks", [])
                    print(f"  [LOG] Captured {len(subtasks)} suggested subtasks", flush=True)

                    # Convert dicts to SuggestedTask objects
                    import uuid

                    for st in subtasks:
                        try:
                            # STRICT VALIDATION: Only accept proper dict format
                            if not isinstance(st, dict):
                                print(f"  [ERROR] Invalid subtask format: expected dict, got {type(st).__name__}. Subtask will be skipped.", flush=True)
                                print(f"  [ERROR] LLM must call create_subtasks with a LIST of DICTS, not strings or other types.", flush=True)
                                continue

                            title = st.get("title", "Untitled")
                            desc = st.get("description", "No description")

                            # Prepend title to description so it's preserved for dependency resolution
                            # UPDATE: Appending instead of prepending to avoid confusing the LLM
                            full_desc = f"{desc}\n\nTitle: {title}"

                            # Generate a temporary ID if not provided
                            suggested_id = f"suggested_{uuid.uuid4().hex[:8]}"

                            suggested_tasks.append(SuggestedTask(
                                suggested_id=suggested_id,
                                component=st.get("component", task.component),
                                phase=TaskPhase(st.get("phase", "build")),
                                description=full_desc,
                                rationale=f"Suggested by planner task {task.id}",
                                depends_on=st.get("depends_on", []),
                                acceptance_criteria=st.get("acceptance_criteria", []),
                                suggested_by_task=task.id,
                                priority=st.get("priority", 5)
                            ))
                        except Exception as e:
                            print(f"  [ERROR] Failed to parse suggested task: {e}", flush=True)


    # Remove duplicates
    files_modified = list(set(files_modified))

    # Fallback: If no files modified but task is complete, save the response to a file
    # This ensures we always have a commit and merge, preventing "empty worktree" issues for subsequent tasks
    if not files_modified and not explicitly_completed and result["messages"]:
        last_msg = result["messages"][-1]
        if isinstance(last_msg, AIMessage) and last_msg.content:
            content = str(last_msg.content)
            if content.strip():
                fallback_file = "response.md"
                # We need to write this file using the tool logic (to respect worktree)
                # But we are outside the agent loop. We can use the bound tool directly if we can access it,
                # or just write to the worktree path directly since we are in the node.

                worktree_path = state.get("worktree_path")
                if worktree_path:
                    try:
                        target_path = worktree_path / fallback_file
                        with open(target_path, "w", encoding="utf-8") as f:
                            f.write(content)
                        files_modified.append(fallback_file)
                        print(f"  [Fallback] Saved response to {fallback_file}", flush=True)
                    except Exception as e:
                        print(f"  [Fallback Error] Failed to write response file: {e}", flush=True)

    # Log the response
    workspace_path = state.get("_workspace_path")
    result_path = log_llm_response(task.id, result, files_modified, status="complete", workspace_path=workspace_path)
    print(f"  [LOG] Files modified: {files_modified}", flush=True)

    # CRITICAL: Strict Success Check for BUILD tasks
    # Ensures BUILD tasks actually create/modify code files
    if task.phase == TaskPhase.BUILD:
        meaningful_files = [f for f in files_modified if not f.endswith("response.md")]
        if not meaningful_files and not explicitly_completed:
            print(f"  [FAILURE] Build task {task.id} failed: No code files modified.", flush=True)

            # Detailed feedback for LLM retry via Phoenix recovery
            failure_message = (
                "CRITICAL FAILURE: No code files were modified during this BUILD task.\n\n"
                "DIAGNOSIS:\n"
                "- You may have only used chat responses instead of the write_file tool\n"
                "- Tool calls may have failed (check for error messages in tool responses)\n"
                "- You may have explored the codebase but forgot to actually write code\n\n"
                "ACTION REQUIRED ON RETRY:\n"
                "1. Use write_file to create or modify project files (NOT in agents-work/)\n"
                "2. Verify each write_file call succeeded (check tool response)\n"
                "3. If code already exists and meets requirements, use report_existing_implementation\n"
                "4. DO NOT just describe what should be done - actually write the files\n\n"
                "Files tracked: " + (str(files_modified) if files_modified else "[]")
            )

            return WorkerResult(
                status="failed",
                result_path=result_path,
                aar=AAR(
                    summary=failure_message,
                    approach="ReAct agent execution - failed due to no file modifications",
                    challenges=[
                        "No code files were created or modified",
                        "write_file tool was either not used or calls failed",
                        "Task cannot be marked complete without tangible code changes"
                    ],
                    decisions_made=["Marked task as FAILED to trigger retry with feedback"],
                    files_modified=files_modified
                ),
                suggested_tasks=suggested_tasks,
                messages=result["messages"] if "messages" in result else []
            )

    # Generate AAR
    # If explicitly completed, use that for the summary
    summary = str(last_message.content)[:200] if isinstance(last_message, AIMessage) else "Task completed"
    if explicitly_completed:
        summary = f"ALREADY IMPLEMENTED: {completion_details.get('implementation_summary', '')}"

    aar = AAR(
        summary=summary,
        approach="ReAct agent execution",
        challenges=[],
        decisions_made=[f"Verified existing implementation in {completion_details.get('file_path')}: {completion_details.get('verification_details')}" ] if explicitly_completed else [],
        files_modified=files_modified
    )

    return WorkerResult(
        status="complete",
        result_path=result_path,
        aar=aar,
        suggested_tasks=suggested_tasks,
        messages=result["messages"] if "messages" in result else []
    )
