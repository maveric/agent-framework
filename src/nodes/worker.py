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

# Import tools
from tools import (
    read_file, write_file, list_directory, file_exists, 
    run_python, run_shell
)

from langchain_core.runnables import RunnableConfig

def worker_node(state: Dict[str, Any], config: RunnableConfig = None) -> Dict[str, Any]:
    """
    Worker: Execute task based on profile.
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
    try:
        result = handler(task, state, config)
    except Exception as e:
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
                commit_msg = f"[{task_id}] {task.phase.value if hasattr(task, 'phase') else 'work'}: {result.aar.summary[:50]}"
                commit_hash = wt_manager.commit_changes(
                    task_id,
                    commit_msg,
                    result.aar.files_modified
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
                            print(f"  Warning: Merge failed: {merge_result.error_message}", flush=True)
                    except Exception as e:
                        print(f"  Warning: Merge exception: {e}", flush=True)
                        import traceback
                        traceback.print_exc()
                        
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
    
    model_config = orch_config.worker_model
    
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
                if tc["name"] in ["write_file", "append_file"]:
                    files_modified.append(tc["args"].get("path"))
    
from state import OrchestratorState
from orchestrator_types import (
    Task, TaskStatus, WorkerProfile, WorkerResult, AAR, TaskPhase,
    _dict_to_task, task_to_dict, _aar_to_dict
)
from llm_client import get_llm
from config import OrchestratorConfig
from llm_logger import log_llm_request, validate_request_size, log_llm_response

# Import tools
from tools import (
    read_file, write_file, list_directory, file_exists, 
    run_python, run_shell
)

def worker_node(state: Dict[str, Any], config: Dict[str, Any] = None) -> Dict[str, Any]:
    """
    Worker: Execute task based on profile.
    """
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
    
    # Execute handler
    print(f"Worker ({profile.value}): Starting task {task_id}", flush=True)
    try:
        result = handler(task, state, config)
    except Exception as e:
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
                commit_msg = f"[{task_id}] {task.phase.value if hasattr(task, 'phase') else 'work'}: {result.aar.summary[:50]}"
                commit_hash = wt_manager.commit_changes(
                    task_id,
                    commit_msg,
                    result.aar.files_modified
                )
                if commit_hash:
                    print(f"  Committed: {commit_hash[:8]}", flush=True)
                    
                    # MERGE LOGIC:
                    # - PLAN/BUILD tasks: Merge immediately (no QA needed)
                    # - TEST tasks: Wait for QA approval (merge happens in strategist_node)
                    if task.phase in [TaskPhase.PLAN, TaskPhase.BUILD]:
                        try:
                            merge_result = wt_manager.merge_to_main(task_id)
                            if merge_result.success:
                                print(f"  Merged to main: {task_id}", flush=True)
                            else:
                                print(f"  Warning: Merge failed: {merge_result.error_message}", flush=True)
                        except Exception as e:
                            print(f"  Warning: Merge exception: {e}", flush=True)
                    else:
                        print(f"  Skipping merge (TEST phase - awaiting QA)", flush=True)
            except Exception as e:
                print(f"  Warning: Failed to commit: {e}", flush=True)
    
    # Update task with result
    task_dict["status"] = "awaiting_qa" if result.status == "complete" else "failed"
    task_dict["result_path"] = result.result_path
    task_dict["aar"] = _aar_to_dict(result.aar) if result.aar else None
    task_dict["updated_at"] = datetime.now().isoformat()
    
    # Persist suggested tasks if any (for hierarchical planning)
    if result.suggested_tasks:
        from orchestrator_types import _suggested_task_to_dict
        task_dict["suggested_tasks"] = [_suggested_task_to_dict(st) for st in result.suggested_tasks]
    
    # Capture task memories (LLM conversation history)
    task_memories = {task_id: result.messages} if result.messages else {}

    return {"tasks": [task_dict], "task_memories": task_memories}


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
    
    model_config = orch_config.worker_model
    
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
    
    # LOOP DETECTION: Track consecutive tool calls to detect infinite loops
    # This catches patterns like: write_file → write_file → write_file (20x)
    consecutive_tool_tracker = {}  # {tool_name: count}
    last_tool_name = None
    LOOP_THRESHOLD = 10
    
    # Invoke agent
    # We use a recursion limit to prevent infinite loops
    try:
        # Increased recursion limit to prevent "Sorry, need more steps" error
        result = agent.invoke(inputs, config={"recursion_limit": 150})
    except Exception as e:
        # Log token info if it's a rate limit error
        if "812" in str(e) or "token" in str(e).lower():
            print(f"  DEBUG: Token error - inspecting agent state", flush=True)
            # print(f"  DEBUG: Inputs had {total_chars} chars", flush=True)
        raise
    
    # Extract results
    messages = result["messages"]
    last_message = messages[-1]
    
    # LOOP DETECTION: Check for repetitive tool calls
    tool_call_sequence = []
    for msg in messages:
        if isinstance(msg, AIMessage) and msg.tool_calls:
            for tc in msg.tool_calls:
                tool_name = tc.get("name")
                if tool_name:
                    tool_call_sequence.append(tool_name)
    
    # Count consecutive calls
    loop_detected = False
    loop_tool = None
    loop_count = 0
    
    if tool_call_sequence:
        from collections import Counter
        # Look for runs of the same tool
        max_consecutive = 1
        current_tool = None
        current_count = 0
        
        for tool in tool_call_sequence:
            if tool == current_tool:
                current_count += 1
                if current_count > max_consecutive:
                    max_consecutive = current_count
                    loop_tool = current_tool
                    loop_count = current_count
            else:
                current_tool = tool
                current_count = 1
        
        if max_consecutive >= LOOP_THRESHOLD:
            loop_detected = True
            print(f"  [LOOP DETECTED] '{loop_tool}' called {loop_count} times consecutively", flush=True)
            print(f"  [LOOP DETECTED] Task failed - LLM stuck in repetitive pattern", flush=True)
            
            # FAIL THE TASK with clear feedback for retry
            from orchestrator_types import AAR
            workspace_path = state.get("_workspace_path")
            result_path = log_llm_response(task.id, result, [], status="failed", workspace_path=workspace_path)
            
            return WorkerResult(
                status="failed",
                result_path=result_path,
                aar=AAR(
                    summary=f"LOOP DETECTED: Task failed due to repetitive tool usage. The LLM called '{loop_tool}' {loop_count} times in a row.",
                    approach="ReAct agent execution - interrupted due to loop",
                    challenges=[
                        f"Loop pattern detected: {loop_tool} called {loop_count} times consecutively",
                        "This often indicates wrapper scripts calling wrapper scripts",
                        "Task may be too complex and needs to be broken down into smaller subtasks",
                        "Or: Approach needs to be simplified to avoid recursion"
                    ],
                    decisions_made=[
                        "Terminated execution to prevent infinite loop",
                        "Recommend breaking task into smaller pieces or using simpler approach"
                    ],
                    files_modified=[]
                ),
                suggested_tasks=[],
                messages=result["messages"] if "messages" in result else []
            )
    
    # Identify modified files and suggested tasks from tool calls
    # CRITICAL: Only count files as modified if the tool call SUCCEEDED
    files_modified = []
    suggested_tasks = []
    explicitly_completed = False
    completion_details = {}
    
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
                
                if tc["name"] in ["write_file", "append_file"]:
                    path = tc["args"].get("path")
                    if path:
                        # Only count as modified if the tool succeeded (no error in result)
                        if tool_result:
                            # Check if the result contains an error
                            result_content = str(tool_result.content).lower()
                            if "error" not in result_content and "field required" not in result_content:
                                files_modified.append(path)
                            else:
                                print(f"  [SKIP] Tool call failed for {path}: {tool_result.content[:100]}", flush=True)
                        else:
                            # No result found - might be a partial execution, don't count it
                            print(f"  [SKIP] No result found for {tc['name']} call to {path}", flush=True)
                            
                elif tc["name"] == "report_existing_implementation":
                    explicitly_completed = True
                    completion_details = tc["args"]
                    print(f"  [LOG] Task marked as already implemented: {tc['args'].get('file_path')}", flush=True)
                    
                elif tc["name"] == "create_subtasks":
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
    
    # Strict Success Check for BUILD tasks
    # If a build task didn't modify any files (except the fallback response.md) AND wasn't explicitly completed, it failed.
    if task.phase == TaskPhase.BUILD:
        meaningful_files = [f for f in files_modified if not f.endswith("response.md")]
        if not meaningful_files and not explicitly_completed:
            print(f"  [FAILURE] Build task {task.id} failed: No code files modified (only response.md).", flush=True)
            from orchestrator_types import AAR
            return WorkerResult(
                status="failed",
                result_path=result_path,
                aar=AAR(
                    summary="Build task failed: No code files were modified.",
                    approach="ReAct agent execution",
                    challenges=["Agent failed to modify any project files"],
                    decisions_made=[],
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
    def read_file_wrapper(path: str, encoding: str = "utf-8"):
        """Read the contents of a file."""
        return tool(path, encoding, root=worktree_path)
    return read_file_wrapper

def _create_write_file_wrapper(tool, worktree_path):
    def write_file_wrapper(path: str, content: str, encoding: str = "utf-8"):
        """Write content to a file."""
        return tool(path, content, encoding, root=worktree_path)
    return write_file_wrapper

def _create_append_file_wrapper(tool, worktree_path):
    def append_file_wrapper(path: str, content: str, encoding: str = "utf-8"):
        """Append content to an existing file."""
        return tool(path, content, encoding, root=worktree_path)
    return append_file_wrapper

def _create_list_directory_wrapper(tool, worktree_path):
    def list_directory_wrapper(path: str = ".", recursive: bool = False, pattern: str = "*"):
        """List files and directories."""
        return tool(path, recursive, pattern, root=worktree_path)
    return list_directory_wrapper

def _create_file_exists_wrapper(tool, worktree_path):
    def file_exists_wrapper(path: str):
        """Check if a file or directory exists."""
        return tool(path, root=worktree_path)
    return file_exists_wrapper

def _create_delete_file_wrapper(tool, worktree_path):
    def delete_file_wrapper(path: str, confirm: bool):
        """Delete a file."""
        return tool(path, confirm, root=worktree_path)
    return delete_file_wrapper

def _create_run_python_wrapper(tool, worktree_path):
    def run_python_wrapper(code: str, timeout: int = 30):
        """Execute Python code."""
        return tool(code, timeout, cwd=worktree_path)
    return run_python_wrapper

def _create_run_shell_wrapper(tool, worktree_path):
    def run_shell_wrapper(command: str, timeout: int = 30):
        """Execute shell command."""
        return tool(command, timeout, cwd=worktree_path)
    return run_shell_wrapper

def _create_subtasks_wrapper(tool, worktree_path):
    def create_subtasks_wrapper(subtasks: List[Dict[str, Any]]):
        """Create subtasks for the project."""
        return tool(subtasks)
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
        if tool.__name__ in ["read_file", "write_file", "append_file", "list_directory", "file_exists", "delete_file"]:
            
            # Use factory functions to avoid closure loop variable capture issues
            if tool.__name__ == "read_file":
                wrapper = _create_read_file_wrapper(tool, worktree_path)
                bound_tools.append(StructuredTool.from_function(wrapper, name="read_file"))
                
            elif tool.__name__ == "write_file":
                wrapper = _create_write_file_wrapper(tool, worktree_path)
                bound_tools.append(StructuredTool.from_function(wrapper, name="write_file"))
                
            elif tool.__name__ == "append_file":
                wrapper = _create_append_file_wrapper(tool, worktree_path)
                bound_tools.append(StructuredTool.from_function(wrapper, name="append_file"))
                
            elif tool.__name__ == "list_directory":
                wrapper = _create_list_directory_wrapper(tool, worktree_path)
                bound_tools.append(StructuredTool.from_function(wrapper, name="list_directory"))
                
            elif tool.__name__ == "file_exists":
                wrapper = _create_file_exists_wrapper(tool, worktree_path)
                bound_tools.append(StructuredTool.from_function(wrapper, name="file_exists"))
                
            elif tool.__name__ == "delete_file":
                wrapper = _create_delete_file_wrapper(tool, worktree_path)
                bound_tools.append(StructuredTool.from_function(wrapper, name="delete_file"))
                
        elif tool.__name__ in ["run_python", "run_shell"]:
            if tool.__name__ == "run_python":
                wrapper = _create_run_python_wrapper(tool, worktree_path)
                bound_tools.append(StructuredTool.from_function(wrapper, name="run_python"))
            elif tool.__name__ == "run_shell":
                wrapper = _create_run_shell_wrapper(tool, worktree_path)
                bound_tools.append(StructuredTool.from_function(wrapper, name="run_shell"))
        
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


def _code_handler(task: Task, state: Dict[str, Any], config: Dict[str, Any] = None) -> WorkerResult:
    """Coding tasks."""
    from tools import git_commit, git_status, git_diff, git_add
    
    # Use fewer tools to reduce token usage
    tools = [
        read_file, write_file, list_directory, file_exists, report_existing_implementation
    ]
    
    # Bind tools to worktree
    tools = _bind_tools(tools, state, WorkerProfile.CODER)
    
    # Stronger system prompt to force file creation
    system_prompt = """You are a software engineer. Implement the requested feature.
    
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
    
    **CRITICAL WARNING - DO NOT HANG THE PROCESS**:
    - NEVER run a blocking command like `python -m http.server` or `npm start` directly. The agent will hang forever.
    - If you need to verify your code with a server, use the **TEST HARNESS PATTERN**:
      Write a Python script that:
      1. Starts the server in a subprocess (`subprocess.Popen`)
      2. Waits for it to be ready (poll localhost)
      3. Sends requests to test it
      4. Kills the subprocess
      5. Prints the results
    - ALWAYS ensure your commands exit.
    
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
    """
    
    return _execute_react_loop(task, tools, system_prompt, state, config)


def _plan_handler(task: Task, state: Dict[str, Any], config: Dict[str, Any] = None) -> WorkerResult:
    """Planning tasks."""
    
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

    # UNIFIED PLANNER PROMPT - All planners work the same way
    system_prompt = f"""You are a component planner.

**TOOL USAGE RULES**:
- Use `list_directory(".")` to see the project root (NOT list_directory("/") - that's invalid)
- Use relative paths: "design_spec.md" or "agents-work/plans/" (NOT "/design_spec.md")  
- Use `read_file()` for FILES only, use `list_directory()` for directories

Your goal is to create a detailed implementation plan for YOUR COMPONENT and break it into executable build/test tasks.
    
CRITICAL INSTRUCTIONS:
1. **READ THE SPEC FIRST**: Check `design_spec.md` in the project root - this is YOUR CONTRACT
2. Explore the codebase using `list_directory` and `read_file`
3. Write your plan to `agents-work/plans/plan-{{component}}.md` using `write_file`
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
- ❌ Tasks too large (>100 LOC changes) or too small (trivial changes)
- ❌ Vague criteria like "make it work"
"""
    
    result = _execute_react_loop(task, tools, system_prompt, state, config)
    
    # VALIDATION: Planners MUST create tasks
    if not result.suggested_tasks or len(result.suggested_tasks) == 0:
        print(f"  [ERROR] Planner {task.id} completed without creating any tasks!", flush=True)
        # Return failed result
        from orchestrator_types import AAR
        return WorkerResult(
            status="failed",
            result_path=result.result_path,
            aar=AAR(
                summary="FAILED: Planner did not create any tasks. Must call create_subtasks.",
                approach="N/A",
                challenges=["Did not call create_subtasks"],
                decisions_made=[],
                files_modified=result.aar.files_modified if result.aar else []
            ),
            suggested_tasks=[]
        )
    
    print(f"  [SUCCESS] Planner created {len(result.suggested_tasks)} tasks", flush=True)
    return result


def _test_handler(task: Task, state: Dict[str, Any], config: Dict[str, Any] = None) -> WorkerResult:
    """Testing tasks."""
    # Tester now has create_subtasks to reject work and request fixes
    tools = [read_file, write_file, list_directory, run_python, run_shell, create_subtasks]
    tools = _bind_tools(tools, state, WorkerProfile.TESTER)
    
    # Create a clean filename from task description
    task_desc = task.description[:50].lower().replace(" ", "-").replace(",", "")
    task_desc = "".join(c for c in task_desc if c.isalnum() or c == "-")
    
    system_prompt = f"""You are a QA engineer who writes and runs UNIT TESTS for this specific feature.
    
    Your job: Test THIS feature in isolation, not integration between features.
    
    CRITICAL RULES:
    1. **THE SPEC IS THE BIBLE**: Check `design_spec.md` to know what to test (routes, selectors, etc.).
    2. MUST use `run_python` or `run_shell` to actually EXECUTE tests
    3. Use `python` (not `python3`) for compatibility
    4. Verify file existence with `list_directory` before running tests
    5. Focus on unit testing THIS feature (not integration)
    5. Capture REAL output (errors, pass/fail, counts)
    6. Write results to `agents-work/test-results/test-{task_desc}.md` with:
       - Command run
       - Actual execution output
       - Pass/fail summary
    7. Create the `agents-work/test-results/` directory if it does not exist
    8. If tests fail, include real error messages
    9. For small projects (HTML/JS), document manual tests if no test framework available
    
    **CRITICAL WARNING - DO NOT HANG THE PROCESS**:
    - NEVER run blocking commands like `python app.py`, `flask run`, or `npm start` directly
    - These will hang forever and block the workflow
    - Use the **TEST HARNESS PATTERN** instead:
      1. Write a test script that starts the server in a subprocess (`subprocess.Popen`)
      2. Wait for it to be ready (poll localhost with timeout)
      3. Send test requests to verify functionality
      4. Kill the subprocess
      5. Print test results
    - Example: test_server.py that starts Flask, tests endpoints, then kills the process
    - ALWAYS ensure your commands exit with results
    
    **MANDATORY FOR QA APPROVAL**:
    - You MUST create a markdown file in `agents-work/test-results/` named `test-{task_desc}.md`.
    - This file MUST contain the actual output of your tests.
    - If this file is missing, QA WILL FAIL.
    
    **CRITICAL WARNING - DO NOT HANG THE PROCESS**:
    - NEVER run a blocking command like `python -m http.server` or `npm start` directly. The agent will hang forever.
    - If you need to test a server, use the **TEST HARNESS PATTERN**:
      Write a Python script that:
      1. Starts the server in a subprocess (`subprocess.Popen`)
      2. Waits for it to be ready (poll localhost)
      3. Sends requests to test it
      4. Kills the subprocess
      5. Prints the results
    - ALWAYS ensure your commands exit.

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
    
    The agents-work/ folder is for agent artifacts, NOT project code.
    Write test files to the project root, but test RESULTS to agents-work/test-results/.
    
    **ABSOLUTE SCOPE CONSTRAINTS - ZERO TOLERANCE:**
    - **TEST ONLY WHAT'S ASSIGNED**: Only test the specific feature/component in your task description
    - **NO SCOPE EXPANSION**: Do NOT add integration tests, performance tests, security tests, or coverage reports unless explicitly requested
    - **NO INFRASTRUCTURE TESTING**: Do NOT test deployment, CI/CD, monitoring, or any infrastructure not in the task
    - **STICK TO THE TASK**: If task says "test CRUD API", test ONLY that. NOT: authentication, rate limiting, caching, etc.
    - **IF NOT IN TASK**: Don't test it. Period.
    """
    
    return _execute_react_loop(task, tools, system_prompt, state, config)


def _research_handler(task: Task, state: Dict[str, Any], config: Dict[str, Any] = None) -> WorkerResult:
    """Research tasks."""
    # Note: Web tools not yet implemented/imported, falling back to basic tools
    tools = [read_file, list_directory] 
    tools = _bind_tools(tools, state, WorkerProfile.RESEARCHER)
    
    system_prompt = """You are a researcher.
    Your goal is to gather information.
    """
    
    return _execute_react_loop(task, tools, system_prompt, state, config)


def _write_handler(task: Task, state: Dict[str, Any], config: Dict[str, Any] = None) -> WorkerResult:
    """Writing tasks."""
    tools = [read_file, write_file, list_directory]
    tools = _bind_tools(tools, state, WorkerProfile.WRITER)
    
    system_prompt = """You are a technical writer.
    Your goal is to write documentation.
    
    CRITICAL INSTRUCTIONS:
    1. You MUST write documentation to files (e.g., `README.md`) using `write_file`.
    2. DO NOT output documentation in the chat.
    3. Keep chat responses concise.
    """
    
    return _execute_react_loop(task, tools, system_prompt, state, config)
