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
    
    # Execute handler
    print(f"Worker ({profile.value}): Starting task {task_id}", flush=True)
    try:
        result = handler(task, state, config)
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"Worker Error: {e}", flush=True)
        # Return failed result
        result = WorkerResult(
            status="failed",
            result_path="",
            aar=AAR(summary=f"Error: {e}", approach="failed", challenges=[], decisions_made=[], files_modified=[])
        )
    
    # Commit changes if task completed successfully
    if result.status == "complete" and result.aar and result.aar.files_modified:
        wt_manager = state.get("_wt_manager")
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

    # Setup LLM
    llm = get_llm()
    
    # Create agent
    agent = create_react_agent(llm, tools, state_modifier=system_prompt)
    
    # Initial input
    inputs = {
        "messages": [
            HumanMessage(content=f"Task: {task.description}\n\nAcceptance Criteria:\n" + "\n".join(f"- {c}" for c in task.acceptance_criteria))
        ]
    }
    
    print(f"  Starting ReAct agent...", flush=True)
    
    # Invoke agent
    # We use a recursion limit to prevent infinite loops
    result = agent.invoke(inputs, config={"recursion_limit": 50})
    
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
            
    # Generate AAR
    return WorkerResult(
        status="complete",
        result_path=files_modified[0] if files_modified else "output.txt",
        aar=AAR(
            summary=f"Completed task: {task.description}",
            approach="ReAct agent execution",
            challenges=[],
            decisions_made=[],
            files_modified=list(set(files_modified))
        )
    )


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
    
    tools = [
        read_file, write_file, list_directory, file_exists, 
        run_python, run_shell,
        git_commit, git_status, git_diff, git_add
    ]
    
    system_prompt = """You are a senior software engineer. 
    Your goal is to implement the requested feature or fix.
    
    1. Explore the codebase first using list_directory and read_file.
    2. Create or modify files using write_file.
    3. Verify your work using run_python or run_shell.
    4. When done, provide a final summary.
    """
    
    return _execute_react_loop(task, tools, system_prompt, state, config)


def _plan_handler(task: Task, state: Dict[str, Any], config: Dict[str, Any] = None) -> WorkerResult:
    """Planning tasks."""
    tools = [read_file, list_directory, file_exists]
    
    system_prompt = """You are a technical architect.
    Your goal is to create a detailed implementation plan.
    
    1. Explore the codebase to understand context.
    2. Write a plan to 'plan.md' or similar.
    """
    
    return _execute_react_loop(task, tools, system_prompt, state, config)


def _test_handler(task: Task, state: Dict[str, Any], config: Dict[str, Any] = None) -> WorkerResult:
    """Testing tasks."""
    tools = [read_file, write_file, list_directory, run_python, run_shell]
    
    system_prompt = """You are a QA engineer.
    Your goal is to verify the implementation.
    
    1. Run existing tests.
    2. Create new tests if needed.
    3. Report results.
    """
    
    return _execute_react_loop(task, tools, system_prompt, state, config)


def _research_handler(task: Task, state: Dict[str, Any], config: Dict[str, Any] = None) -> WorkerResult:
    """Research tasks."""
    # Note: Web tools not yet implemented/imported, falling back to basic tools
    tools = [read_file, list_directory] 
    
    system_prompt = """You are a researcher.
    Your goal is to gather information.
    """
    
    return _execute_react_loop(task, tools, system_prompt, state, config)


def _write_handler(task: Task, state: Dict[str, Any], config: Dict[str, Any] = None) -> WorkerResult:
    """Writing tasks."""
    tools = [read_file, write_file, list_directory]
    
    system_prompt = """You are a technical writer.
    Your goal is to write documentation.
    """
    
    return _execute_react_loop(task, tools, system_prompt, state, config)
