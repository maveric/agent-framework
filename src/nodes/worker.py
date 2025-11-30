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
    Task, TaskStatus, WorkerProfile, WorkerResult, AAR,
    _dict_to_task, _task_to_dict, _aar_to_dict
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
    task_dict["updated_at"] = datetime.now().isoformat()
    
    return {"tasks": [task_dict]}


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
    Task, TaskStatus, WorkerProfile, WorkerResult, AAR,
    _dict_to_task, _task_to_dict, _aar_to_dict
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
                    
                    # Merge to main
                    try:
                        merge_result = wt_manager.merge_to_main(task_id)
                        if merge_result.success:
                            print(f"  Merged to main: {task_id}", flush=True)
                        else:
                            print(f"  Warning: Merge failed: {merge_result.error_message}", flush=True)
                    except Exception as e:
                        print(f"  Warning: Merge exception: {e}", flush=True)
            except Exception as e:
                print(f"  Warning: Failed to commit: {e}", flush=True)
    
    # Update task with result
    task_dict["status"] = "awaiting_qa" if result.status == "complete" else "failed"
    task_dict["result_path"] = result.result_path
    task_dict["aar"] = _aar_to_dict(result.aar) if result.aar else None
    task_dict["updated_at"] = datetime.now().isoformat()
    
    return {"tasks": [task_dict]}


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
    
    # Identify modified files from tool calls
    files_modified = []
    for msg in messages:
        if isinstance(msg, AIMessage) and msg.tool_calls:
            for tc in msg.tool_calls:
                if tc["name"] in ["write_file", "append_file"]:
                    path = tc["args"].get("path")
                    if path:
                        files_modified.append(path)
            
    # Remove duplicates
    files_modified = list(set(files_modified))
    
    # Fallback: If no files modified but task is complete, save the response to a file
    # This ensures we always have a commit and merge, preventing "empty worktree" issues for subsequent tasks
    if not files_modified and result["messages"]:
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
    workspace_path = state.get("workspace_path")
    result_path = log_llm_response(task.id, result, files_modified, status="complete", workspace_path=workspace_path)
    print(f"  [LOG] Files modified: {files_modified}", flush=True)
            
    # Generate AAR
    from orchestrator_types import AAR
    aar = AAR(
        summary=str(last_message.content)[:200] if isinstance(last_message, AIMessage) else "Task completed",
        approach="ReAct agent execution",
        challenges=[],
        decisions_made=[],
        files_modified=files_modified
    )
    
    return WorkerResult(
        status="complete",
        result_path=result_path,
        aar=aar
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

def _bind_tools(tools: List[Callable], state: Dict[str, Any]) -> List[Callable]:
    """Bind tools to the current worktree path."""
    worktree_path = state.get("worktree_path")
    if not worktree_path:
        return tools
        
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


def _code_handler(task: Task, state: Dict[str, Any], config: Dict[str, Any] = None) -> WorkerResult:
    """Coding tasks."""
    from tools import git_commit, git_status, git_diff, git_add
    
    # Use fewer tools to reduce token usage
    tools = [
        read_file, write_file, list_directory, file_exists
    ]
    
    # Bind tools to worktree
    tools = _bind_tools(tools, state)
    
    # Stronger system prompt to force file creation
    system_prompt = """You are a software engineer. Implement the requested feature.
    
    CRITICAL INSTRUCTIONS:
    1. You MUST use `write_file` to create or modify files.
    2. DO NOT output code in the chat. Only use the tools.
    3. You are working in a real file system. Your changes are persistent.
    4. Use `list_directory` and `read_file` to explore the codebase first.
    5. Keep your chat responses extremely concise (e.g., "Reading file...", "Writing index.html...").
    """
    
    return _execute_react_loop(task, tools, system_prompt, state, config)


def _plan_handler(task: Task, state: Dict[str, Any], config: Dict[str, Any] = None) -> WorkerResult:
    """Planning tasks."""
    tools = [read_file, list_directory, file_exists]
    tools = _bind_tools(tools, state)
    
    system_prompt = """You are a technical architect.
    Your goal is to create a detailed implementation plan.
    
    CRITICAL INSTRUCTIONS:
    1. Explore the codebase first using `list_directory` and `read_file`.
    2. You MUST write your plan to a file (e.g., `plan.md`) using `write_file`.
    3. DO NOT output the plan in the chat.
    4. Keep chat responses concise.
    """
    
    return _execute_react_loop(task, tools, system_prompt, state, config)


def _test_handler(task: Task, state: Dict[str, Any], config: Dict[str, Any] = None) -> WorkerResult:
    """Testing tasks."""
    tools = [read_file, write_file, list_directory, run_python, run_shell]
    tools = _bind_tools(tools, state)
    
    system_prompt = """You are a QA engineer.
    Your goal is to verify the implementation.
    
    CRITICAL INSTRUCTIONS:
    1. Run existing tests or create new ones using `write_file`.
    2. You MUST write a test report to a file (e.g., `test_results.md`) using `write_file`.
    3. DO NOT output code or long reports in the chat.
    4. Use `run_python` or `run_shell` to execute tests.
    """
    
    return _execute_react_loop(task, tools, system_prompt, state, config)


def _research_handler(task: Task, state: Dict[str, Any], config: Dict[str, Any] = None) -> WorkerResult:
    """Research tasks."""
    # Note: Web tools not yet implemented/imported, falling back to basic tools
    tools = [read_file, list_directory] 
    tools = _bind_tools(tools, state)
    
    system_prompt = """You are a researcher.
    Your goal is to gather information.
    """
    
    return _execute_react_loop(task, tools, system_prompt, state, config)


def _write_handler(task: Task, state: Dict[str, Any], config: Dict[str, Any] = None) -> WorkerResult:
    """Writing tasks."""
    tools = [read_file, write_file, list_directory]
    tools = _bind_tools(tools, state)
    
    system_prompt = """You are a technical writer.
    Your goal is to write documentation.
    
    CRITICAL INSTRUCTIONS:
    1. You MUST write documentation to files (e.g., `README.md`) using `write_file`.
    2. DO NOT output documentation in the chat.
    3. Keep chat responses concise.
    """
    
    return _execute_react_loop(task, tools, system_prompt, state, config)
