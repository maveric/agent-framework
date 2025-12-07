"""
Agent Orchestrator — Worker Node  
================================
Version 1.0 — November 2025

Worker execution node with specialized handlers.
"""

from typing import Any, Dict, Callable, List
from datetime import datetime
import json

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage, AIMessage
from langchain_core.prompts import ChatPromptTemplate
from langgraph.prebuilt import create_react_agent

from state import OrchestratorState
from orchestrator_types import (
    Task, TaskStatus, TaskPhase, WorkerProfile, WorkerResult, AAR,
    _dict_to_task, task_to_dict, _aar_to_dict
)
from llm_client import get_llm
from config import OrchestratorConfig
from llm_logger import log_llm_request, validate_request_size, log_llm_response

# Import tools (ASYNC versions for non-blocking execution)
from tools import (
    read_file_async as read_file, 
    write_file_async as write_file, 
    list_directory_async as list_directory, 
    file_exists_async as file_exists, 
    run_python_async as run_python, 
    run_shell_async as run_shell
)

from langchain_core.runnables import RunnableConfig

import platform

PLATFORM = f"OS - {platform.system()}, Release: {platform.release()}"

async def worker_node(state: Dict[str, Any], config: RunnableConfig = None) -> Dict[str, Any]:
    """
    Worker: Execute task based on profile (async version).
    """
    print(f"DEBUG: worker_node state keys: {list(state.keys())}", flush=True)
    print(f"DEBUG: worker_node _workspace_path: {state.get('_workspace_path')}", flush=True)
    task_id = state.get("task_id")
    if not task_id:
        return {}
    
    task_dict = next((t for t in state.get("tasks", []) if t["id"] == task_id), None)
    if not task_dict:
        return {}
    
    task = _dict_to_task(task_dict)
    profile = task.assigned_worker_profile
    
    # Get handler for worker type
    handler = _get_handler(profile)
    
    # Create/get worktree for this task
    wt_manager = state.get("_wt_manager")
    worktree_path = None
    if wt_manager and not state.get("mock_mode", False):
        try:
            wt_info = wt_manager.create_worktree(task_id)
            worktree_path = wt_info.worktree_path
            print(f"  Created worktree: {worktree_path}", flush=True)
        except Exception as e:
            print(f"  Warning: Failed to create worktree: {e}", flush=True)
            worktree_path = state.get("_workspace_path")
    else:
        worktree_path = state.get("_workspace_path")
    
    # Inject worktree path into state for handlers
    state["worktree_path"] = worktree_path
    print(f"DEBUG: worker_node set state['worktree_path']={state.get('worktree_path')}", flush=True)
    
    # Execute handler
    print(f"Worker ({profile.value}): Starting task {task_id}", flush=True)
    
    # PERF: Calculate task execution time
    # Use started_at from task if available (when it became ACTIVE), otherwise measure from now
    import time
    from datetime import datetime
    
    if hasattr(task, 'started_at') and task.started_at:
        # Calculate from when task became ACTIVE
        task_start_time = task.started_at.timestamp()
    else:
        # Fallback: measure from worker entry (less accurate)
        task_start_time = time.time()
    
    try:
        result = await handler(task, state, config)
        
        # PERF: Log execution time from ACTIVE status
        task_duration = time.time() - task_start_time
        print(f"  ⏱️  Task {task_id[:8]} ({profile.value}) completed in {task_duration:.1f}s (active time)", flush=True)
        
    except Exception as e:
        task_duration = time.time() - task_start_time
        print(f"  ⏱️  Task {task_id[:8]} ({profile.value}) FAILED after {task_duration:.1f}s (active time)", flush=True)
        import traceback
        error_details = traceback.format_exc()
        print(f"Worker Error Details:", flush=True)
        print(error_details, flush=True)
        # Return failed result
        result = WorkerResult(
            status="failed",
            result_path="",
            aar=AAR(summary=f"Error: {str(e)[:200]}", approach="failed", challenges=[], decisions_made=[], files_modified=[])
        )
    
    # Commit changes if task completed successfully
    if result.status == "complete" and result.aar and result.aar.files_modified:
        if wt_manager and not state.get("mock_mode", False):
            try:
                # Filter out response.md - it's a debug fallback, not real work
                files_to_commit = [f for f in result.aar.files_modified if not f.endswith("response.md")]
                if files_to_commit:
                    commit_msg = f"[{task_id}] {task.phase.value if hasattr(task, 'phase') else 'work'}: {result.aar.summary[:50]}"
                    commit_hash = wt_manager.commit_changes(
                        task_id,
                        commit_msg,
                        files_to_commit
                    )
                    if commit_hash:
                        print(f"  Committed: {commit_hash[:8]}", flush=True)
                        
                        # Merge to main immediately for now to allow subsequent tasks to see changes
                        # In a full flow, this might be gated by QA, but for linear dependencies we need it.
                        try:
                            print(f"  [DEBUG] Calling merge_to_main for {task_id}...", flush=True)
                            merge_result = wt_manager.merge_to_main(task_id)
                            if merge_result.success:
                                print(f"  Merged to main", flush=True)
                            else:
                                # Merge failed - this should trigger Phoenix retry
                                print(f"  ❌ Merge failed: {merge_result.error_message}", flush=True)
                                # Override the result to failed status
                                result = WorkerResult(
                                    status="failed",
                                    result_path=result.result_path,
                                    aar=AAR(
                                        summary=f"Merge failed: {merge_result.error_message[:200]}",
                                        approach=result.aar.approach if result.aar else "unknown",
                                        challenges=[merge_result.error_message] if result.aar else [],
                                        decisions_made=result.aar.decisions_made if result.aar else [],
                                        files_modified=result.aar.files_modified if result.aar else []
                                    ),
                                    messages=result.messages if hasattr(result, 'messages') else []
                                )
                        except Exception as e:
                            print(f"  ❌ Merge exception: {e}", flush=True)
                            import traceback
                            traceback.print_exc()
                            # Override to failed
                            result = WorkerResult(
                                status="failed",
                                result_path="",
                                aar=AAR(
                                    summary=f"Merge exception: {str(e)[:200]}",
                                    approach="failed",
                                    challenges=[str(e)],
                                    decisions_made=[],
                                    files_modified=[]
                                )
                            )
                        
            except Exception as e:
                print(f"  Warning: Failed to commit: {e}", flush=True)
    
    # Update task with result
    task_dict["status"] = "awaiting_qa" if result.status == "complete" else "failed"
    task_dict["result_path"] = result.result_path
    task_dict["aar"] = _aar_to_dict(result.aar) if result.aar else None
    
    # Pass suggested tasks to state (for Director to process)
    if result.suggested_tasks:
        from orchestrator_types import _suggested_task_to_dict
        task_dict["suggested_tasks"] = [_suggested_task_to_dict(st) for st in result.suggested_tasks]
        
    task_dict["updated_at"] = datetime.now().isoformat()
    
    # Return tasks AND task_memories (logs)
    # We need to extract the messages from the result if available
    updates = {"tasks": [task_dict]}
    
    # If the result has messages (from the agent execution), pass them back
    # The state key is "task_memories" which is a dict mapping task_id -> list of messages
    if hasattr(result, "messages") and result.messages:
        updates["task_memories"] = {task_id: result.messages}
    elif hasattr(result, "aar") and result.aar and hasattr(result.aar, "messages"):
        # Fallback if messages are attached to AAR (unlikely but possible in some flows)
        updates["task_memories"] = {task_id: result.aar.messages}
        
    return updates


def _get_handler(profile: WorkerProfile) -> Callable:
    """Get handler function for worker profile."""
    handlers = {
        WorkerProfile.PLANNER: _plan_handler,
        WorkerProfile.CODER: _code_handler,
        WorkerProfile.TESTER: _test_handler,
        WorkerProfile.RESEARCHER: _research_handler,
        WorkerProfile.WRITER: _write_handler,
    }
    return handlers.get(profile, _code_handler)


def _execute_react_loop(
    task: Task, 
    tools: List[Callable], 
    system_prompt: str,
    state: Dict[str, Any],
    config: Dict[str, Any] = None
) -> WorkerResult:
    """
    Execute a ReAct loop using LangGraph's prebuilt agent.
    """
    # Get configuration
    mock_mode = state.get("mock_mode", False)
    if not mock_mode and config and "configurable" in config:
        mock_mode = config["configurable"].get("mock_mode", False)
        
    if mock_mode:
        return _mock_execution(task)

    # Get orchestrator config from state (has user's model settings)
    from config import OrchestratorConfig
    orch_config = state.get("orch_config")
    if not orch_config:
        orch_config = OrchestratorConfig()
    
    # Select model based on worker profile
    # This allows different models for planning vs coding vs testing
    profile = task.assigned_worker_profile
    
    from orchestrator_types import WorkerProfile
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
    from config import ModelConfig
    limited_config = ModelConfig(
        provider=model_config.provider,
        model_name=model_config.model_name,
        temperature=model_config.temperature,
        max_tokens=1000  # Reasonable output limit (was causing 812K token requests!)
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
        stats = log_llm_request(task.id, inputs["messages"], tools, {})
        print(f"  [LOG] Request: {stats['message_count']} msgs, {stats['total_chars']} chars (~{stats['estimated_tokens']} tokens)", flush=True)
        print(f"  [LOG] Tools: {stats['tool_count']}, Log: {stats['log_file']}", flush=True)
        
        # Validate size (max 100K chars to prevent issues)
        validate_request_size(stats, max_chars=100000)
    except Exception as e:
        print(f"  [LOG ERROR]: {e}", flush=True)
        if "too large" in str(e).lower():
            raise
    
    print(f"  Starting ReAct agent...", flush=True)
    
    # Invoke agent
    # We use a recursion limit to prevent infinite loops
    try:
        result = agent.invoke(inputs, config={"recursion_limit": 50})
    except Exception as e:
        # Log token info if it's a rate limit error
        if "812" in str(e) or "token" in str(e).lower():
            print(f"  DEBUG: Token error - inspecting agent state", flush=True)
            # print(f"  DEBUG: Inputs had {total_chars} chars", flush=True)
        raise
    
    # Extract results
    messages = result["messages"]
    last_message = messages[-1]
    
    # Identify modified files from tool calls
    files_modified = []
    for msg in messages:
        if isinstance(msg, ToolMessage) and msg.name in ["write_file", "append_file"]:
            # We'd need to parse the tool call args from the preceding AIMessage to get the path
            # But ToolMessage doesn't store args directly usually, it stores output.
            # The preceding AIMessage has the tool_calls with args.
            pass
            
    # Scan for tool calls in AIMessages
    for msg in messages:
        if isinstance(msg, AIMessage) and msg.tool_calls:
            for tc in msg.tool_calls:
                tool_name = tc.get("name", "")
                if tool_name in ["write_file", "append_file"]:
                    file_path = tc.get("args", {}).get("path")
                    if file_path:
                        files_modified.append(file_path)
                        print(f"  [TRACKED] write_file: {file_path}", flush=True)
                    else:
                        print(f"  [WARNING] write_file call missing path: {tc}", flush=True)

def _get_handler(profile: WorkerProfile) -> Callable:
    """Get handler function for worker profile."""
    handlers = {
        WorkerProfile.PLANNER: _plan_handler,
        WorkerProfile.CODER: _code_handler,
        WorkerProfile.TESTER: _test_handler,
        WorkerProfile.RESEARCHER: _research_handler,
        WorkerProfile.WRITER: _write_handler,
    }
    return handlers.get(profile, _code_handler)


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
    from config import OrchestratorConfig
    orch_config = state.get("orch_config")
    if not orch_config:
        orch_config = OrchestratorConfig()
    
    # Select model based on worker profile
    # This allows different models for planning vs coding vs testing
    profile = task.assigned_worker_profile
    
    from orchestrator_types import WorkerProfile
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
    from config import ModelConfig
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
        from orchestrator_types import AAR
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


def _detect_modified_files_via_git(worktree_path) -> list[str]:
    """
    Use git to detect actual file changes in the worktree.
    More reliable than parsing tool calls - catches all changes including deletions.
    
    Returns:
        List of modified file paths (relative to worktree root)
    """
    files_modified = []
    
    try:
        import subprocess
        from pathlib import Path
        
        # Get list of modified, added, and deleted files using git status
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=worktree_path,
            capture_output=True,
            text=True,
            timeout=5
        )
        
        if result.returncode == 0:
            # Parse git status output
            # Format: XY filename
            # X = status in index, Y = status in worktree
            # M = modified, A = added, D = deleted, R = renamed, etc.
            for line in result.stdout.strip().split('\n'):
                if line:
                    # Extract filename (everything after first 3 characters)
                    # Handle both "M  file.py" and " M file.py" formats
                    status_part = line[:2]
                    filename = line[3:].strip()
                    
                    # Skip if filename is empty or is in .git directory
                    if filename and not filename.startswith('.git/'):
                        # Handle renamed files (format: "old_name -> new_name")
                        if ' -> ' in filename:
                            filename = filename.split(' -> ')[1]
                        
                        files_modified.append(filename)
                        print(f"  [GIT-TRACKED] {status_part.strip()} {filename}", flush=True)
            
            print(f"  [GIT] Detected {len(files_modified)} modified file(s) via git status", flush=True)
        else:
            print(f"  [GIT-WARNING] git status failed: {result.stderr}", flush=True)
            
    except Exception as e:
        print(f"  [GIT-ERROR] Failed to detect file changes via git: {e}", flush=True)
    
    return files_modified
    
    
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
                    from orchestrator_types import SuggestedTask
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
            from orchestrator_types import AAR
            
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
    from orchestrator_types import AAR
    
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





def _create_read_file_wrapper(tool, worktree_path):
    async def read_file_wrapper(path: str, encoding: str = "utf-8"):
        """Read the contents of a file."""
        return await tool(path, encoding, root=worktree_path)
    return read_file_wrapper

def _create_write_file_wrapper(tool, worktree_path):
    async def write_file_wrapper(path: str, content: str, encoding: str = "utf-8"):
        """Write content to a file."""
        return await tool(path, content, encoding, root=worktree_path)
    return write_file_wrapper

def _create_append_file_wrapper(tool, worktree_path):
    async def append_file_wrapper(path: str, content: str, encoding: str = "utf-8"):
        """Append content to an existing file."""
        return await tool(path, content, encoding, root=worktree_path)
    return append_file_wrapper

def _create_list_directory_wrapper(tool, worktree_path):
    async def list_directory_wrapper(path: str = ".", recursive: bool = False, pattern: str = "*"):
        """List files and directories."""
        return await tool(path, recursive, pattern, root=worktree_path)
    return list_directory_wrapper

def _create_file_exists_wrapper(tool, worktree_path):
    async def file_exists_wrapper(path: str):
        """Check if a file or directory exists."""
        return await tool(path, root=worktree_path)
    return file_exists_wrapper

def _create_delete_file_wrapper(tool, worktree_path):
    async def delete_file_wrapper(path: str, confirm: bool):
        """Delete a file."""
        return await tool(path, confirm, root=worktree_path)
    return delete_file_wrapper

def _create_run_python_wrapper(tool, worktree_path, workspace_path=None):
    async def run_python_wrapper(code: str, timeout: int = 30):
        """Execute Python code using shared venv if available."""
        return await tool(code, timeout, cwd=worktree_path, workspace_path=workspace_path)
    return run_python_wrapper

def _create_run_shell_wrapper(tool, worktree_path):
    async def run_shell_wrapper(command: str, timeout: int = 30):
        """Execute shell command."""
        return await tool(command, timeout, cwd=worktree_path)
    return run_shell_wrapper

def _create_subtasks_wrapper(tool, worktree_path):
    def create_subtasks_wrapper(subtasks: List[Dict[str, Any]]):
        """Create subtasks for the project."""
        return tool(subtasks)  # This one is sync (create_subtasks is sync)
    return create_subtasks_wrapper

def _bind_tools(tools: List[Callable], state: Dict[str, Any], profile: WorkerProfile = None) -> List[Callable]:
    """
    Bind tools to the worktree context.
    Wraps filesystem and execution tools to operate within the task's worktree.
    
    Args:
        tools: List of tool functions/objects
        state: Orchestrator state (containing worktree manager)
        profile: Worker profile (optional, for permission checks)
    """
    worktree_path = state.get("worktree_path") or state.get("_workspace_path")
    
    if not worktree_path:
        print("WARNING: No worktree_path or _workspace_path found in state", flush=True)
        return tools
        
    print(f"DEBUG: Binding tools to path: {worktree_path}", flush=True)
    
    from langchain_core.tools import StructuredTool
    
    bound_tools = []
    for tool in tools:
        # Check if tool accepts 'root' argument (filesystem tools)
        # NOTE: Handle both sync names (read_file) and async names (read_file_async)
        fs_tools = ["read_file", "write_file", "append_file", "list_directory", "file_exists", "delete_file",
                    "read_file_async", "write_file_async", "append_file_async", "list_directory_async", 
                    "file_exists_async", "delete_file_async"]
        if tool.__name__ in fs_tools:
            
            # Use factory functions to avoid closure loop variable capture issues
            # NOTE: Pass coroutine= directly - LangChain infers schema from the async function signature
            if tool.__name__ in ["read_file", "read_file_async"]:
                wrapper = _create_read_file_wrapper(tool, worktree_path)
                bound_tools.append(StructuredTool.from_function(func=wrapper, coroutine=wrapper, name="read_file", description="Read the contents of a file.", handle_tool_error=True))
                
            elif tool.__name__ in ["write_file", "write_file_async"]:
                wrapper = _create_write_file_wrapper(tool, worktree_path)
                bound_tools.append(StructuredTool.from_function(func=wrapper, coroutine=wrapper, name="write_file", description="Write content to a file.", handle_tool_error=True))
                
            elif tool.__name__ in ["append_file", "append_file_async"]:
                wrapper = _create_append_file_wrapper(tool, worktree_path)
                bound_tools.append(StructuredTool.from_function(func=wrapper, coroutine=wrapper, name="append_file", description="Append content to an existing file.", handle_tool_error=True))
                
            elif tool.__name__ in ["list_directory", "list_directory_async"]:
                wrapper = _create_list_directory_wrapper(tool, worktree_path)
                bound_tools.append(StructuredTool.from_function(func=wrapper, coroutine=wrapper, name="list_directory", description="List files and directories.", handle_tool_error=True))
                
            elif tool.__name__ in ["file_exists", "file_exists_async"]:
                wrapper = _create_file_exists_wrapper(tool, worktree_path)
                bound_tools.append(StructuredTool.from_function(func=wrapper, coroutine=wrapper, name="file_exists", description="Check if a file or directory exists.", handle_tool_error=True))
                
            elif tool.__name__ in ["delete_file", "delete_file_async"]:
                wrapper = _create_delete_file_wrapper(tool, worktree_path)
                bound_tools.append(StructuredTool.from_function(func=wrapper, coroutine=wrapper, name="delete_file", description="Delete a file.", handle_tool_error=True))
                
        elif tool.__name__ in ["run_python", "run_shell", "run_python_async", "run_shell_async"]:
            workspace_path = state.get("_workspace_path")  # For shared venv lookup
            if tool.__name__ in ["run_python", "run_python_async"]:
                wrapper = _create_run_python_wrapper(tool, worktree_path, workspace_path=workspace_path)
                bound_tools.append(StructuredTool.from_function(func=wrapper, coroutine=wrapper, name="run_python", description="Execute Python code using shared venv if available.", handle_tool_error=True))
            elif tool.__name__ in ["run_shell", "run_shell_async"]:
                wrapper = _create_run_shell_wrapper(tool, worktree_path)
                bound_tools.append(StructuredTool.from_function(func=wrapper, coroutine=wrapper, name="run_shell", description="Execute shell command.", handle_tool_error=True))
        
        elif tool.__name__ == "create_subtasks":
             # Allow Planners, Testers, and Coders to create subtasks
             if profile in [WorkerProfile.PLANNER, WorkerProfile.TESTER, WorkerProfile.CODER]:
                 bound_tools.append(tool)
             else:
                 # Skip for other profiles
                 pass
        
        elif tool.__name__ == "report_existing_implementation":
            # Convert plain function to StructuredTool for proper LLM usage
            bound_tools.append(StructuredTool.from_function(tool, name="report_existing_implementation"))
                
        else:
            bound_tools.append(tool)
            
    return bound_tools


def _mock_execution(task: Task) -> WorkerResult:
    """Mock execution for testing."""
    print("  MOCK: Executing task...", flush=True)
    return WorkerResult(
        status="complete",
        result_path="mock_output.py",
        aar=AAR(
            summary="Mock execution",
            approach="Mock",
            challenges=[],
            decisions_made=[],
            files_modified=["mock_output.py"]
        )
    )


# =============================================================================
# SHARED TOOL: create_subtasks (used by planners and testers)
# =============================================================================

def create_subtasks(subtasks: List[Dict[str, Any]]) -> str:
    """
    Create COMMIT-LEVEL subtasks to be executed by other workers.
    
    IMPORTANT: Think in terms of GIT COMMITS, not components!
    Each task should represent ONE atomic, reviewable change.
    
    Args:
        subtasks: List of dicts, each containing:
            - title: str (concise, commit-message-style)
            - description: str (what changes, why, acceptance criteria)
            - phase: "build" | "test" (NOT separate - build includes inline tests)
            - component: str (optional, use feature name instead of "backend"/"frontend")
            - depends_on: List[str] (titles of tasks this depends on)
            - worker_profile: "code_worker" | "test_worker" (default based on phase)
    
    EXAMPLES OF GOOD TASKS:
    {
      "title": "Create tasks table in SQLite database",
      "description": "Set up database schema with id, title, status columns. Include migration script and verification query.",
      "phase": "build",
      "depends_on": []
    },
    {
      "title": "Implement GET /api/tasks endpoint",
      "description": "Create Flask route to return all tasks as JSON. Include unit test for happy path and empty state.",
      "phase": "build",
      "depends_on": ["Create tasks table in SQLite database"]
    },
    {
      "title": "Playwright test: Add and view task",
      "description": "E2E test that adds a task via UI and verifies it appears in correct column.",
      "phase": "test",
      "depends_on": ["Implement POST /api/tasks endpoint", "Add task creation UI component"]
    }
    
    Returns:
        Status message or error
    """
    # ENFORCE LIMITS TO PREVENT TASK EXPLOSION
    # Note: This limits each CALL to create_subtasks, not total tasks.
    # A planner can call this multiple times if needed for complex projects.
    MAX_SUBTASKS_PER_CALL = 15
    
    if len(subtasks) > MAX_SUBTASKS_PER_CALL:
        return f"ERROR: Too many subtasks ({len(subtasks)}). Maximum allowed is {MAX_SUBTASKS_PER_CALL}. Break into smaller logical groups or prioritize the most critical tasks."
    
    if len(subtasks) == 0:
        return "ERROR: No subtasks provided. You must create at least one subtask."
    
    return f"Created {len(subtasks)} subtasks. They will be added to the task graph by the Director."


def report_existing_implementation(file_path: str, implementation_summary: str, verification_details: str) -> str:
    """
    Report that a PREVIOUS task already implemented the requested feature.
    
    **CRITICAL RULE**: This tool is ONLY for pre-existing code you FOUND in the codebase.
    
    DO NOT use this tool if:
    - You just created or modified files in THIS session
    - You wrote ANY code to complete the task
    - You used write_file, append_file, or any file modification tools
    
    ONLY use this tool if:
    - You explored the codebase and found that a PREVIOUS task already did your work
    - The existing code fully satisfies your task requirements
    - You made ZERO modifications to any files
    
    If you created files, your work needs to be committed. Do NOT call this tool.
    
    Args:
        file_path: Path to the EXISTING file that already has the implementation
        implementation_summary: Brief description of what the existing code does
        verification_details: Explanation of why it meets YOUR task requirements
        
    Returns:
        Status message
    """
    return "Implementation reported successfully."


async def _code_handler(task: Task, state: Dict[str, Any], config: Dict[str, Any] = None) -> WorkerResult:
    """Coding tasks (async)."""
    from tools import git_commit, git_status, git_diff, git_add
    
    # Tools for code workers - includes execution for verification
    tools = [
        read_file, write_file, list_directory, file_exists, 
        run_python, run_shell, report_existing_implementation
    ]
    
    # Bind tools to worktree
    tools = _bind_tools(tools, state, WorkerProfile.CODER)
    
    # Platform-specific shell warning (must be at TOP to be seen)
    is_windows = platform.system() == 'Windows'
    correct_path = "python folder\\\\script.py" if is_windows else "python folder/script.py"
    correct_pytest = "python -m pytest tests\\\\" if is_windows else "python -m pytest tests/"
    
    # Shared venv path at workspace root (not in worktree)
    workspace_path = state.get("_workspace_path", ".")
    if is_windows:
        venv_python = f"{workspace_path}\\\\.venv\\\\Scripts\\\\python.exe"
        venv_pip = f"{workspace_path}\\\\.venv\\\\Scripts\\\\pip.exe"
    else:
        venv_python = f"{workspace_path}/.venv/bin/python"
        venv_pip = f"{workspace_path}/.venv/bin/pip"
    platform_warning = f"""
**🚨 CRITICAL - SHELL COMMANDS ({platform.system()}) 🚨**:
{"⚠️ YOU ARE ON WINDOWS - NEVER USE && IN COMMANDS!" if is_windows else "Unix shell: Use && or ; for chaining"}
- ❌ FORBIDDEN: `cd folder && python script.py` (BREAKS ON WINDOWS)
- ❌ FORBIDDEN: `cd . && python test.py` (USELESS AND BREAKS)
- ✅ CORRECT: `{correct_path}` (Run from project root)
- ✅ CORRECT: `{correct_pytest}` (Use -m for modules)
The run_shell tool ALREADY runs in the correct working directory. DO NOT use cd.
"""

    # Stronger system prompt to force file creation
    system_prompt = f"""You are a software engineer. Implement the requested feature.

⚠️ CRITICAL: NEVER HTML-ESCAPE CODE ⚠️
When calling write_file, you MUST pass raw, unescaped code EXACTLY as it should appear in the file.

WRONG (will break ALL code files):
- &lt;div&gt; instead of <div>
- &quot;hello&quot; instead of "hello"  
- &amp;lt; instead of &lt;
- &gt; instead of >
- &amp; instead of &

CORRECT - Write the LITERAL characters:
- <html><body><div class="example">
- "hello world" or 'test'
- if (x < y && a > b)

HTML/XML entities will completely DESTROY all code files. Write raw strings ONLY.

{platform_warning}

CRITICAL INSTRUCTIONS:
1. **THE SPEC IS THE BIBLE**: Check `design_spec.md` in the project root. You MUST follow it exactly for API routes, data models, and file structure.
2. BEFORE coding, check agents-work/plans/ folder for any relevant plans.
3. Read any plan files to understand the intended design and architecture.
4. Use `list_directory` and `read_file` to explore the codebase FIRST.
5. **CHECK IF ALREADY IMPLEMENTED (BEFORE YOU START WORK)**:
   - If a PREVIOUS task already completed your assigned work, use `report_existing_implementation`
   - This tool is ONLY for pre-existing code that you FOUND, NOT code you just created
   - **CRITICAL**: If YOU wrote files in THIS session, DO NOT call this tool - your work needs to be committed!
   - Only use this to avoid duplicate work when another agent already finished the task
6. If the feature does NOT exist, use `write_file` to create or modify files.
7. DO NOT output code in the chat. Only use the tools.
8. You are working in a real file system. Your changes are persistent.
9. Keep your chat responses extremely concise (e.g., "Reading file...", "Writing index.html...").

Remember: agents-work/ has plans and test results. Your code goes in the project root.

**🔒 DEPENDENCY ISOLATION - SHARED VENV 🔒**:
- **NEVER install packages globally** - this pollutes the host machine
- **Python**: A SHARED venv exists at the workspace root. Use it:
  - Run: `{venv_python}` 
  - Install: `{venv_pip} install package`
  - If packages are missing: `{venv_pip} install -r requirements.txt`
  - **NEVER** use bare `pip install` or `python -m pip install`
- **Node.js**: Use `npm install` (creates local node_modules, already isolated)
  - Run via: `npx`, `npm run`, or `node ./node_modules/.bin/tool`
- **Other stacks**: Check design_spec.md for isolation requirements

**🚨🚨🚨 CRITICAL - BLOCKING COMMANDS WILL HANG FOREVER 🚨🚨🚨**:
**BANNED COMMANDS** (these NEVER exit and will freeze the agent):
- `python app.py` / `python backend/app.py` / `python server.py`
- `flask run` / `python -m flask run`
- `npm start` / `npm run dev` / `npm run serve`
- `python -m http.server`
- ANY command that starts a web server or long-running process

**YOU MUST USE THE TEST HARNESS PATTERN**:
If you need to verify a server works, write a Python test script that:
```python
import subprocess, time, requests
# 1. Start server as subprocess (don't block!)
proc = subprocess.Popen(['python', 'app.py'])
time.sleep(2)  # Wait for startup
try:
    # 2. Test it
    resp = requests.get('http://localhost:5000/api/tasks')
    print(f"Status: {{resp.status_code}}, Body: {{resp.text[:100]}}")
finally:
    # 3. ALWAYS kill the process
    proc.terminate()
    proc.wait()
```
- ALWAYS use `subprocess.Popen` to start servers
- ALWAYS `terminate()` and `wait()` to clean up
- NEVER run server commands directly

**ABSOLUTE SCOPE CONSTRAINTS - ZERO TOLERANCE:**
- **NO SCOPE EXPANSION**: You have ZERO authority to add features not in your task description
- **IMPLEMENT ONLY WHAT'S ASSIGNED**: Only write code for the specific feature/component in your task
- **NO EXTRAS**: Do NOT add Docker files, CI/CD configs, deployment scripts, monitoring, logging frameworks, or ANY extras
- **STICK TO THE SPEC**: If design_spec.md says "CRUD API", build ONLY that. NOT: admin panels, authentication, rate limiting, etc.
- **IF NOT IN TASK**: Don't build it. Period.

**REQUESTING MISSING DEPENDENCIES**:
- If you discover missing files/work that BLOCKS YOUR CURRENT TASK, you may use `create_subtasks`
- **ONLY FOR IN-SCOPE BLOCKERS**: The missing item must be:
  * Required by design_spec.md
  * Needed to complete YOUR assigned task
  * NOT a "nice-to-have" or optimization
- **DETAILED RATIONALE REQUIRED**: In the `rationale` field, explain:
  * What you were trying to implement
  * What specific file/component is missing
  * Why you cannot complete your task without it
  * Evidence it's in scope (reference design_spec.md)
- **EXAMPLES**:
  * ✅ GOOD: "Need backend/models.py to define API routes. design_spec.md requires User model for /api/users endpoint."
  * ❌ BAD: "Should add Redis caching for better performance"
  * ❌ BAD: "Need authentication system" (too broad, not your task)
- **CONSTRAINTS**:
  * Do NOT suggest nice-to-haves, performance optimizations, or scope expansion
  * Do NOT suggest tasks unrelated to YOUR current assignment
  * If rejected by Director, find an alternative approach or work around it

**ALREADY IMPLEMENTED?**:
- If you find the code ALREADY EXISTS and meets requirements:
- Do NOT modify the file just to "touch" it.
- Use the `report_existing_implementation` tool to prove you checked it.
- Provide the file path and a summary of why it's correct.

**IF YOUR TASK INVOLVES WRITING TESTS**:
If your task description includes writing tests, running tests, or verifying functionality:
1. Write the test files to the appropriate location (e.g., `tests/` folder)
2. Run the tests using `run_shell` or `run_python`
3. **MANDATORY**: Write a test results file to `agents-work/test-results/test-{{component}}.md`

Use this template:
```markdown
# Test Results: {{component}}

## Command Run
`python -m pytest tests/test_example.py -v`

## Output
```
(paste actual test output here)
```

## Summary
✅ All tests passed (X/Y) OR ❌ X tests failed
```

If you don't create the results file, QA will fail your task.
"""

    
    return await _execute_react_loop(task, tools, system_prompt, state, config)


async def _plan_handler(task: Task, state: Dict[str, Any], config: Dict[str, Any] = None) -> WorkerResult:
    """Planning tasks (async)."""
    
    # PREVENT PLANNER EXPLOSION: Count existing planners
    existing_tasks = state.get("tasks", [])
    planner_count = sum(1 for t in existing_tasks 
                       if (hasattr(t, 'assigned_worker_profile') and t.assigned_worker_profile == WorkerProfile.PLANNER)
                       or (isinstance(t, dict) and t.get('assigned_worker_profile') == 'planner_worker'))
    
    MAX_PLANNERS = 10  # Hard limit: should be plenty
    if planner_count >= MAX_PLANNERS:
        print(f"  [WARNING] Max planner limit reached ({MAX_PLANNERS}). Forcing direct task creation.", flush=True)

    tools = [read_file, write_file, list_directory, file_exists, create_subtasks]
    tools = _bind_tools(tools, state, WorkerProfile.PLANNER)

    # Platform-specific shell warning
    is_windows = platform.system() == 'Windows'
    correct_path = "python folder\\\\script.py" if is_windows else "python folder/script.py"
    platform_warning = f"""
**🚨 CRITICAL - SHELL COMMANDS ({platform.system()}) 🚨**:
{"⚠️ YOU ARE ON WINDOWS - NEVER USE && IN COMMANDS!" if is_windows else "Unix shell: Use && or ; for chaining"}
- ❌ FORBIDDEN: `cd folder && python script.py` (BREAKS ON WINDOWS)
- ❌ FORBIDDEN: `cd . && python test.py` (USELESS AND BREAKS)
- ✅ CORRECT: `{correct_path}` (Run from project root)
The run_shell tool ALREADY runs in the correct working directory. DO NOT use cd.
"""

    # UNIFIED PLANNER PROMPT - All planners work the same way
    system_prompt = f"""You are a component planner.
{platform_warning}

**TOOL USAGE RULES**:
- Use `list_directory(".")` to see the project root (NOT list_directory("/") - that's invalid)
- Use relative paths: "design_spec.md" or "agents-work/plans/" (NOT "/design_spec.md")  
- Use `read_file()` for FILES only, use `list_directory()` for directories



Your goal is to create a detailed implementation plan for YOUR COMPONENT and break it into executable build/test tasks.
    
CRITICAL INSTRUCTIONS:
1. **READ THE SPEC FIRST**: Check `design_spec.md` in the project root - this is YOUR CONTRACT
2. Explore the codebase using `list_directory` and `read_file`
3. Write your plan to `agents-work/plans/plan-{{component}}-{task.id[:8]}.md` using `write_file` (UNIQUE filename with task ID!)
4. **CREATE COMMIT-LEVEL TASKS**: Use `create_subtasks` to define atomic, reviewable changes:
   
   GRANULARITY: Think in terms of GIT COMMITS
   - ✅ GOOD: "Implement POST /api/tasks endpoint with validation"
   - ✅ GOOD: "Add drag-drop UI for task movement"
   - ✅ GOOD: "Add Playwright test for task creation flow"
   - ❌ TOO BIG: "Build entire backend API"
   - ❌ TOO SMALL: "Add import statement"
   
   Each task should:
   - Implement ONE atomic, testable change
   - Be reviewable as a standalone PR
   - Include its own verification (unit test in same commit, or integration test right after)
   - Have 3-6 clear acceptance criteria
   
   BUILD TESTING INTO YOUR TASKS:
   - Don't separate "build" from "test" - test what you build
   - Unit tests: Include in same task as code
   - Integration tests: Separate task that depends on the feature tasks
   - E2E tests: Final task after feature is complete
   
   DEPENDENCIES:
   - Link tasks in logical build order
   - Database/models → API endpoints → UI → Integration tests
   - Tasks within same feature can run parallel if independent
5. **MANDATORY**: In EVERY subtask description, explicitly reference the spec: "Follow design_spec.md"
6. **CRITICAL**: Include at least ONE TEST task to validate your component
7. DO NOT output the plan in the chat - use tools only

**ABSOLUTE SCOPE CONSTRAINTS - ZERO TOLERANCE:**
- **NO SCOPE EXPANSION**: You have ZERO authority to expand scope beyond design_spec.md
- **STICK TO THE SPEC**: Only create tasks that implement what's in design_spec.md
- **NO EXTRAS**: Do NOT add Docker, CI/CD, deployment, monitoring, logging, analytics, or ANY "nice-to-haves"
- **NO "BEST PRACTICES" ADDITIONS**: Do not add infrastructure that "would be good in production"
- **MINIMUM VIABLE**: Create ONLY the tasks needed for core functionality in the spec
- **EXAMPLE**: If spec says "REST API with CRUD", create ONLY: models, routes, basic validation. NOT: caching, rate limiting, webhooks, admin panel, etc.
- **IF IN DOUBT**: Leave it out. The Director has already decided the scope. Your job is execution only.

Remember: The spec is law. You execute, you don't expand.

TASK QUALITY REQUIREMENTS:
1. **Commit-level granularity**: Reviewable as one PR
2. **Self-contained**: Includes build + verification
3. **Clear scope**: 3-6 specific acceptance criteria
4. **Logical order**: Dependencies make sense in development flow

AVOID THESE PATTERNS:
- ❌ Creating "backend" vs "frontend" silos
- ❌ Separating all building from all testing
- ❌ Tasks too large (>400 LOC changes) or too small (trivial changes)
- ❌ Vague criteria like "make it work"
"""
    
    result = await _execute_react_loop(task, tools, system_prompt, state, config)
    
    # VALIDATION: Planners MUST create tasks
    if not result or not result.suggested_tasks or len(result.suggested_tasks) == 0:
        print(f"  [ERROR] Planner {task.id} completed without creating any tasks!", flush=True)
        # Return failed result
        from orchestrator_types import AAR
        return WorkerResult(
            status="failed",
            result_path=result.result_path if result else "",
            aar=AAR(
                summary="FAILED: Planner did not create any tasks. Must call create_subtasks.",
                approach="N/A",
                challenges=["Did not call create_subtasks"],
                decisions_made=[],
                files_modified=result.aar.files_modified if result and result.aar else []
            ),
            suggested_tasks=[]
        )

    
    print(f"  [SUCCESS] Planner created {len(result.suggested_tasks)} tasks", flush=True)
    return result


async def _test_handler(task: Task, state: Dict[str, Any], config: Dict[str, Any] = None) -> WorkerResult:
    """Testing tasks (async)."""
    # Tester now has create_subtasks to reject work and request fixes
    tools = [read_file, write_file, list_directory, run_python, run_shell, create_subtasks]
    tools = _bind_tools(tools, state, WorkerProfile.TESTER)
    
    # Shared venv path at workspace root (not in worktree)
    is_windows = platform.system() == 'Windows'
    workspace_path = state.get("_workspace_path", ".")
    if is_windows:
        venv_python = f"{workspace_path}\\.venv\\Scripts\\python.exe"
        venv_pip = f"{workspace_path}\\.venv\\Scripts\\pip.exe"
    else:
        venv_python = f"{workspace_path}/.venv/bin/python"
        venv_pip = f"{workspace_path}/.venv/bin/pip"
    
    # CRITICAL: Use component field for filename to match what QA expects
    # QA looks for: agents-work/test-results/test-{component}.md
    task_filename = task.component if task.component else task.id
    
    system_prompt = f"""You are a QA engineer who writes and runs UNIT TESTS for this specific feature.

🚨🚨🚨 YOUR #1 MANDATORY REQUIREMENT - READ THIS FIRST 🚨🚨🚨
**BEFORE YOU FINISH, YOU MUST CREATE THIS FILE:**
    
    File path: `agents-work/test-results/test-{task_filename}.md`
    
**YOUR TASK WILL AUTOMATICALLY FAIL IF THIS FILE DOES NOT EXIST!**

The file must contain:
- The exact command(s) you ran
- The ACTUAL output from running tests (copy/paste the real output)
- Pass/fail summary

Example - use write_file to create this:
```markdown
# Test Results: {task_filename}

## Command Run
`python -m pytest tests/test_api.py -v`

## Output
```
tests/test_api.py::test_get_tasks PASSED
tests/test_api.py::test_create_task PASSED
2 passed in 0.45s
```

## Summary
✅ All tests passed (2/2)
```

**DO NOT PROCEED WITHOUT WRITING THIS FILE. QA CHECKS FOR IT AUTOMATICALLY.**

---

    
CRITICAL RULES:
1. **THE SPEC IS THE BIBLE**: Check `design_spec.md` to know what to test (routes, selectors, etc.).
2. MUST use `run_python` or `run_shell` to actually EXECUTE tests
3. Use `python` (not `python3`) for compatibility
4. Verify file existence with `list_directory` before running tests
5. Focus on unit testing THIS feature (not integration)
6. Capture REAL output (errors, pass/fail, counts)
7. **WRITE THE RESULTS FILE** - `agents-work/test-results/test-{task_filename}.md`
8. Create the `agents-work/test-results/` directory if it does not exist
9. If tests fail, include real error messages
10. For small projects (HTML/JS), document manual tests if no test framework available

**🔒 DEPENDENCY ISOLATION - SHARED VENV 🔒**:
- **Python**: A SHARED venv exists at the workspace root. Use it:
  - Run tests: `{venv_python} test.py`
  - Install deps: `{venv_pip} install pytest`
  - **NEVER** create a new venv or use bare `pip install`
- **Node.js**: Use `npm test` or `npx jest` (uses local node_modules)

Platform - {PLATFORM}
CRITICAL - SHELL COMMAND SYNTAX:
{'- Windows PowerShell: Use semicolons (;) NOT double-ampersand (&&)' if platform.system() == 'Windows' else '- Unix shell: Use double-ampersand (&&) or semicolons (;)'}
**BEST PRACTICE - AVOID CHAINING**:
    - ❌ FORBIDDEN: cd backend && python test.py
    - ✅ CORRECT: `{venv_python} backend\\test.py` (Windows)
    - ✅ CORRECT: `{venv_python} backend/test.py` (Unix)

**🚨🚨🚨 BLOCKING COMMANDS WILL HANG FOREVER 🚨🚨🚨**:
**BANNED COMMANDS**: `python app.py`, `flask run`, `npm start`, `npm run dev`
**USE TEST HARNESS PATTERN INSTEAD**:
```python
import subprocess, time, requests
proc = subprocess.Popen(['python', 'app.py'])
time.sleep(2)
try:
    resp = requests.get('http://localhost:5000/api/tasks')
    print(f"Status: {{resp.status_code}}")
finally:
    proc.terminate()
    proc.wait()
```

    **BROWSER/UI TESTING**:
    - Use `playwright` (python) for browser automation.
    - MUST use `headless=True` to avoid GUI issues.
    - Example pattern:
      ```python
      from playwright.sync_api import sync_playwright
      # ... inside test harness ...
      with sync_playwright() as p:
          browser = p.chromium.launch(headless=True)
          page = browser.new_page()
          page.goto("http://localhost:5000")
          # Use auto-waiting selectors: page.click("text=Add Task")
          # Verify state: assert page.is_visible(".task-card")
          browser.close()
      ```
    **CRITICAL INSTRUCTION**:
    The agents-work/ folder is for agent artifacts, NOT project code.
    Write test files to the project root, but test RESULTS **must** be written to to agents-work/test-results/test-{task_filename}.md or your task will not pass QA.
    
    **ABSOLUTE SCOPE CONSTRAINTS - ZERO TOLERANCE:**
    - **TEST ONLY WHAT'S ASSIGNED**: Only test the specific feature/component in your task description
    - **NO SCOPE EXPANSION**: Do NOT add integration tests, performance tests, security tests, or coverage reports unless explicitly requested
    - **NO INFRASTRUCTURE TESTING**: Do NOT test deployment, CI/CD, monitoring, or any infrastructure not in the task
    - **STICK TO THE TASK**: If task says "test CRUD API", test ONLY that. NOT: authentication, rate limiting, caching, etc.
    - **IF NOT IN TASK**: Don't test it. Period.
    """
    
    return await _execute_react_loop(task, tools, system_prompt, state, config)


async def _research_handler(task: Task, state: Dict[str, Any], config: Dict[str, Any] = None) -> WorkerResult:
    """Research tasks (async)."""
    # Note: Web tools not yet implemented/imported, falling back to basic tools
    tools = [read_file, list_directory] 
    tools = _bind_tools(tools, state, WorkerProfile.RESEARCHER)
    
    system_prompt = """You are a researcher.
    Your goal is to gather information.
    """
    
    return await _execute_react_loop(task, tools, system_prompt, state, config)


async def _write_handler(task: Task, state: Dict[str, Any], config: Dict[str, Any] = None) -> WorkerResult:
    """Writing tasks (async)."""
    tools = [read_file, write_file, list_directory]
    tools = _bind_tools(tools, state, WorkerProfile.WRITER)
    
    system_prompt = """You are a technical writer.
    Your goal is to write documentation.
    
    CRITICAL INSTRUCTIONS:
    1. You MUST write documentation to files (e.g., `README.md`) using `write_file`.
    2. DO NOT output documentation in the chat.
    3. Keep chat responses concise.
    """
    
    return await _execute_react_loop(task, tools, system_prompt, state, config)
