"""
React loop execution for worker agents.

Includes Guardian integration for drift detection - every N tool calls,
the guardian checks if the agent is on track and can inject nudges.
"""

import logging
from typing import Any, Dict, Callable, List
from datetime import datetime

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage, AIMessage, BaseMessage
from langgraph.prebuilt import create_react_agent

from orchestrator_types import Task, TaskPhase, WorkerProfile, WorkerResult, AAR, SuggestedTask
from llm_client import get_llm
from config import OrchestratorConfig, ModelConfig
from llm_logger import log_llm_request, validate_request_size, log_llm_response

from .utils import _detect_modified_files_via_git, _mock_execution
from .guardian import check_agent_alignment

logger = logging.getLogger(__name__)


def _count_tool_calls(messages: List[BaseMessage]) -> int:
    """Count the number of tool calls in message history."""
    count = 0
    for msg in messages:
        if isinstance(msg, AIMessage) and hasattr(msg, 'tool_calls') and msg.tool_calls:
            count += len(msg.tool_calls)
    return count


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
        WorkerProfile.MERGER: getattr(orch_config, 'merger_model', None),
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
        logs_base_path = state.get("_logs_base_path")  # Logs outside workspace
        stats = log_llm_request(task.id, inputs["messages"], tools, {}, workspace_path=workspace_path, logs_base_path=logs_base_path)
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
    # With guardian enabled, we run in smaller chunks and check alignment between chunks.

    # Check if guardian is enabled
    guardian_enabled = orch_config.enable_guardian
    check_interval = orch_config.guardian_check_interval if guardian_enabled else 150
    total_limit = 150  # Overall limit

    # Invoke agent - with guardian, we run in chunks
    try:
        current_messages = inputs["messages"].copy()
        total_tool_calls = 0
        last_check_at = 0

        while True:
            # Calculate how many iterations until next guardian check
            iterations_until_check = check_interval - (total_tool_calls - last_check_at)
            # Use smaller of: iterations until check, or remaining limit
            chunk_limit = min(iterations_until_check, total_limit - total_tool_calls, check_interval)

            if chunk_limit <= 0:
                logger.warning(f"  [AGENT] Reached total iteration limit ({total_limit})")
                break

            # Run agent for this chunk
            # NOTE: LangGraph counts ALL graph steps (reasoning + tool calls + responses), not just tool calls
            # So we need a much larger buffer: ~3x the tool call limit to account for reasoning steps
            chunk_inputs = {"messages": current_messages}
            recursion_limit = max(chunk_limit * 3, 50)  # At least 50, or 3x the tool calls
            result = await agent.ainvoke(chunk_inputs, config={"recursion_limit": recursion_limit})

            # Update message history
            current_messages = result["messages"]
            new_tool_calls = _count_tool_calls(current_messages)
            tool_calls_this_chunk = new_tool_calls - total_tool_calls
            total_tool_calls = new_tool_calls

            # Check if agent completed (last message is AI without tool calls)
            last_msg = current_messages[-1] if current_messages else None
            agent_done = (
                isinstance(last_msg, AIMessage) and
                (not hasattr(last_msg, 'tool_calls') or not last_msg.tool_calls)
            )

            # CRITICAL: Detect "need more steps" message - this means agent hit recursion limit, NOT completion
            # This is the PERFECT time for guardian to check in and provide guidance
            if agent_done and last_msg and hasattr(last_msg, 'content'):
                content = str(last_msg.content).lower()
                if "need more steps" in content or ("sorry" in content and "steps" in content):
                    logger.warning(f"  [AGENT] Hit recursion limit - invoking guardian for guidance...")
                    agent_done = False  # Force continuation

                    # Guardian check at recursion limit - agent needs help continuing
                    if orch_config.enable_guardian:
                        nudge = await check_agent_alignment(
                            task=task,
                            messages=current_messages,
                            config=orch_config,
                            iteration_count=total_tool_calls
                        )
                        if nudge:
                            nudge_msg = HumanMessage(content=f"[GUIDANCE]: {nudge.message}")
                            current_messages.append(nudge_msg)
                            logger.info(f"  [GUARDIAN] Injected guidance for continuation")
                        else:
                            # Guardian says on track - just encourage continuation
                            continue_msg = HumanMessage(content="[GUIDANCE]: You're making good progress. Please continue with the task.")
                            current_messages.append(continue_msg)
                            logger.info(f"  [GUARDIAN] Agent on track, encouraging continuation")
                    else:
                        # Guardian disabled - just inject a simple continuation prompt
                        continue_msg = HumanMessage(content="Please continue with the task.")
                        current_messages.append(continue_msg)
                        logger.info(f"  [AGENT] Injected continuation prompt")

            if agent_done:
                logger.info(f"  [AGENT] Completed after {total_tool_calls} tool calls")
                break

            # Guardian check every N tool calls
            if guardian_enabled and (total_tool_calls - last_check_at) >= check_interval:
                last_check_at = total_tool_calls

                nudge = await check_agent_alignment(
                    task=task,
                    messages=current_messages,
                    config=orch_config,
                    iteration_count=total_tool_calls
                )

                if nudge:
                    # Inject nudge as a HumanMessage (appears as user feedback)
                    nudge_msg = HumanMessage(content=f"[GUIDANCE]: {nudge.message}")
                    current_messages.append(nudge_msg)
                    logger.info(f"  [GUARDIAN] Injected nudge into conversation")

            # Safety: if no tool calls happened in this chunk, agent might be stuck
            if tool_calls_this_chunk == 0 and not agent_done:
                logger.warning(f"  [AGENT] No tool calls in chunk - agent may be stuck")
                break

        # Ensure result contains all messages including any injected nudges
        result["messages"] = current_messages

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
        logs_base_path = state.get("_logs_base_path")  # Logs outside workspace
        result_path = log_llm_response(task.id, {"messages": []}, [], status="failed", workspace_path=workspace_path, logs_base_path=logs_base_path)

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
        files_modified = await _detect_modified_files_via_git(worktree_path)

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

                            # Check required fields
                            if "title" not in st or not st["title"]:
                                error_msg = f"Subtask #{idx+1}: Missing required field 'title'"
                                parse_errors.append(error_msg)
                                logger.error(f"  [ERROR] {error_msg}")
                                continue

                            if "description" not in st or not st["description"]:
                                error_msg = f"Subtask #{idx+1}: Missing required field 'description'"
                                parse_errors.append(error_msg)
                                logger.error(f"  [ERROR] {error_msg}")
                                continue
                            
                            # Validate phase
                            phase_value = st.get("phase", "build")
                            try:
                                phase = TaskPhase(phase_value)
                            except ValueError:
                                valid_phases = [p.value for p in TaskPhase]
                                error_msg = f"Subtask '{st.get('title', 'Untitled')}' (#{idx+1}): invalid phase '{phase_value}'. Valid phases: {valid_phases}"
                                parse_errors.append(error_msg)
                                logger.error(f"  [ERROR] {error_msg}")
                                continue

                            # Generate a temporary ID if not provided
                            suggested_id = f"suggested_{uuid.uuid4().hex[:8]}"
                            
                            # Keep title and description separate (don't embed title in description)
                            title = st.get("title", "Untitled")
                            desc = st.get("description", "No description")

                            suggested_tasks.append(SuggestedTask(
                                suggested_id=suggested_id,
                                title=title,
                                component=st.get("component", task.component),
                                phase=phase,
                                description=desc,
                                rationale=f"Suggested by planner task {task.id}",
                                depends_on=st.get("depends_on", []),
                                dependency_queries=st.get("dependency_queries", []),
                                acceptance_criteria=st.get("acceptance_criteria", []),
                                suggested_by_task=task.id,
                                priority=st.get("priority", 5),
                                test_file_paths=st.get("test_file_paths", [])  # TDD: Tests this task must pass
                            ))
                        except Exception as e:
                            error_msg = f"Subtask '{st.get('title', 'Unknown')}' (#{idx+1}): {e}"
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
    logs_base_path = state.get("_logs_base_path")  # Logs outside workspace
    result_path = log_llm_response(task.id, result, files_modified, status="complete", workspace_path=workspace_path, logs_base_path=logs_base_path)
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
    # NOTE: Do NOT truncate - fixer workers need full details when tests fail
    summary = str(last_message.content) if isinstance(last_message, AIMessage) else "Task completed"
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
