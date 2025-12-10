"""
React loop execution for worker agents.
"""

import logging
from typing import Any, Dict, Callable, List
from datetime import datetime

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage, AIMessage
from langgraph.prebuilt import create_react_agent

from orchestrator_types import Task, TaskPhase, WorkerProfile, WorkerResult, AAR, SuggestedTask
from llm_client import get_llm
from config import OrchestratorConfig, ModelConfig
from llm_logger import log_llm_request, validate_request_size, log_llm_response

from .utils import _detect_modified_files_via_git, _mock_execution

logger = logging.getLogger(__name__)


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
        logger.info(f"  [LOG] Request: {stats['message_count']} msgs, {stats['total_chars']} chars (~{stats['estimated_tokens']} tokens)")
        logger.info(f"  [LOG] Tools: {stats['tool_count']}, Log: {stats['log_file']}")

        # Validate size (max 100K chars to prevent issues)
        validate_request_size(stats, max_chars=100000)
    except Exception as e:
        logger.error(f"  [LOG ERROR]: {e}")
        if "too large" in str(e).lower():
            raise

    logger.info(f"  Starting ReAct agent...")

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

        logger.error(f"  [AGENT ERROR] {error_type}: {error_msg[:200]}")

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
        logger.info(f"  [FALLBACK] Using tool-call parsing for file detection")

        # Build a map of tool_call_id -> ToolMessage for success checking
        tool_results = {}
        for msg in messages:
            if isinstance(msg, ToolMessage):
                tool_results[msg.tool_call_id] = msg

        logger.info(f"  [DEBUG] Found {len(tool_results)} tool results")

        for msg in messages:
            if isinstance(msg, AIMessage) and msg.tool_calls:
                for tc in msg.tool_calls:
                    tool_call_id = tc.get("id")

                    # Get the corresponding ToolMessage result
                    tool_result = tool_results.get(tool_call_id) if tool_call_id else None

                    if tc["name"] in ["write_file", "append_file"]:
                        path = tc["args"].get("path")
                        logger.info(f"  [DEBUG] {tc['name']} call: id={tool_call_id}, path={path}, has_result={tool_result is not None}")
                        if path:
                            # Only count as modified if the tool succeeded (no error in result)
                            if tool_result:
                                # Check if the result contains an error
                                result_content = str(tool_result.content).lower()
                                if "error" not in result_content and "field required" not in result_content:
                                    files_modified.append(path)
                                    logger.info(f"  [TRACKED] {tc['name']}: {path}")
                                else:
                                    logger.info(f"  [SKIP] Tool call failed for {path}: {tool_result.content[:100]}")
                            else:
                                # No result found - might be a partial execution, don't count it
                                logger.info(f"  [SKIP] No result found for {tc['name']} call to {path}")

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
                    logger.info(f"  [LOG] Task marked as already implemented: {tc['args'].get('file_path')}")

                elif tc["name"] == "create_subtasks":
                    logger.info(f"  [DEBUG] Tool call: {tc.get('name')} args keys: {list(tc.get('args', {}).keys())}")
                    subtasks = tc["args"].get("subtasks", [])
                    logger.info(f"  [LOG] Captured {len(subtasks)} suggested subtasks")

                    # Convert dicts to SuggestedTask objects
                    import uuid
                    parse_errors = []  # Track validation errors

                    for idx, st in enumerate(subtasks):
                        try:
                            # STRICT VALIDATION: Only accept proper dict format
                            if not isinstance(st, dict):
                                error_msg = f"Subtask #{idx+1}: expected dict, got {type(st).__name__}"
                                parse_errors.append(error_msg)
                                logger.error(f"  [ERROR] {error_msg}")
                                continue
                            if not isinstance(subtask, dict):
                                error_msg = f"Subtask #{st_num}: expected dict, got {type(subtask).__name__}"
                                parse_errors.append(error_msg)
                                logger.error(f"  [ERROR] {error_msg}")
                                continue

                            # Check required fields
                            if "title" not in subtask or not subtask["title"]:
                                parse_errors.append(f"Subtask #{st_num}: Missing required field 'title'")
                                continue # Skip this subtask if title is missing

                            if "description" not in subtask or not subtask["description"]:
                                parse_errors.append(f"Subtask #{st_num}: Missing required field 'description'")
                                continue # Skip this subtask if description is missing
                            
                            # Validate phase
                            phase_value = subtask.get("phase", "build")
                            try:
                                phase = TaskPhase(phase_value)
                            except ValueError:
                                valid_phases = [p.value for p in TaskPhase]
                                error_msg = f"Subtask '{subtask.get('title', 'Untitled')}' (#{st_num}): invalid phase '{phase_value}'. Valid phases: {valid_phases}"
                                parse_errors.append(error_msg)
                                logger.error(f"  [ERROR] {error_msg}")
                                continue

                            # Generate a temporary ID if not provided
                            suggested_id = f"suggested_{uuid.uuid4().hex[:8]}"
                            
                            # Keep title and description separate (don't embed title in description)
                            title = subtask.get("title", "Untitled")
                            desc = subtask.get("description", "No description")

                            suggested_tasks.append(SuggestedTask(
                                suggested_id=suggested_id,
                                title=title,
                                component=subtask.get("component", task.component),
                                phase=phase,
                                description=desc,
                                rationale=f"Suggested by planner task {task.id}",
                                depends_on=subtask.get("depends_on", []),
                                acceptance_criteria=subtask.get("acceptance_criteria", []),
                                suggested_by_task=task.id,
                                priority=subtask.get("priority", 5)
                            ))
                        except Exception as e:
                            error_msg = f"Subtask '{subtask.get('title', 'Unknown')}' (#{idx+1}): {e}"
                            parse_errors.append(error_msg)
                            logger.error(f"  [ERROR] {error_msg}")
                    
                    # If we have parse errors and it's a planner task, track them for potential failure
                    if parse_errors and task.assigned_worker_profile == "planner_worker":
                        # Store for later check
                        if not hasattr(task, '_parse_errors'):
                            task._parse_errors = []
                        task._parse_errors.extend(parse_errors)


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
                        logger.info(f"  [Fallback] Saved response to {fallback_file}")
                    except Exception as e:
                        logger.error(f"  [Fallback Error] Failed to write response file: {e}")

    # Log the response
    workspace_path = state.get("_workspace_path")
    result_path = log_llm_response(task.id, result, files_modified, status="complete", workspace_path=workspace_path)
    logger.info(f"  [LOG] Files modified: {files_modified}")

    # CRITICAL: Strict Success Check for BUILD tasks
    # Ensures BUILD tasks actually create/modify code files
    if task.phase == TaskPhase.BUILD:
        meaningful_files = [f for f in files_modified if not f.endswith("response.md")]
        if not meaningful_files and not explicitly_completed:
            logger.error(f"  [FAILURE] Build task {task.id} failed: No code files modified.")

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
    
    # CRITICAL: Validation Check for PLAN tasks
    # If planner created 0 tasks due to parse errors, fail with detailed feedback
    if task.phase == TaskPhase.PLAN and not suggested_tasks:
        # Check if we have parse errors from create_subtasks
        parse_errors = getattr(task, '_parse_errors', [])
        
        if parse_errors:
            logger.error(f"  [FAILURE] Plan task {task.id} failed: All subtasks had validation errors.")
            
            error_details = "\n".join(f"  - {err}" for err in parse_errors)
            failure_message = (
                f"CRITICAL FAILURE: All {len(parse_errors)} subtasks failed validation.\n\n"
                "VALIDATION ERRORS:\n"
                f"{error_details}\n\n"
                "COMMON MISTAKES:\n"
                "- Using invalid 'phase' values like 'setup', 'backend', 'frontend', 'integration'\n"
                "- Valid phase values are: 'plan', 'build', 'test'\n"
                "- 'plan' = planning/design tasks that create more subtasks\n"
                "- 'build' = coding/implementation tasks that write actual code\n"
                "- 'test' = testing tasks that run tests and verify functionality\n\n"
                "ACTION REQUIRED ON RETRY:\n"
                "1. Use ONLY valid phase values: 'plan', 'build', or 'test'\n"
                "2. For frontend/backend work, use phase='build' (not 'frontend' or 'backend')\n"
                "3. For setup/initialization work, use phase='build' (not 'setup')\n"
                "4. For integration work, use phase='build' or 'test' (not 'integration')\n"
                "5. Ensure each subtask dict has required fields: title, description, phase, component"
            )
            
            return WorkerResult(
                status="failed",
                result_path=result_path,
                aar=AAR(
                    summary=failure_message,
                    approach="ReAct agent execution - failed due to invalid subtask phases",
                    challenges=[
                        f"All {len(parse_errors)} subtasks failed validation",
                        "Invalid 'phase' values used in subtask definitions",
                        "Must use only: 'plan', 'build', or 'test'"
                    ],
                    decisions_made=["Marked task as FAILED to trigger retry with validation guidance"],
                    files_modified=files_modified
                ),
                suggested_tasks=[],
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
