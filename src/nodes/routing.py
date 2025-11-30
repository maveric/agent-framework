"""
Agent Orchestrator — Routing Logic
==================================
Version 1.0 — November 2025

Conditional routing between nodes.
"""

from typing import Literal
from langgraph.types import Send
from state import OrchestratorState


def route_after_director(state: OrchestratorState):
    """
    Route after Director - dispatch ready tasks to workers or end.
    """
    tasks = state.get("tasks", [])
    
    # If no tasks yet, end (will create tasks on first run)
    if not tasks:
        return "__end__"
    
    # Check if all tasks are complete
    all_complete = all(
        t.get("status") in ["complete", "failed", "abandoned"] 
        for t in tasks
    )
    if all_complete:
        print("\nAll tasks complete!", flush=True)
        return "__end__"
    
    # Find ready tasks
    ready_tasks = [t for t in tasks if t.get("status") == "ready"]
    
    if not ready_tasks:
        # No ready tasks but not all complete - might be waiting
        print("No ready tasks, ending run", flush=True)
        return "__end__"
    
    # Dispatch first ready task to worker
    task_id = ready_tasks[0]["id"]
    
    # Create worktree for this task (if not in mock mode)
    wt_manager = state.get("_wt_manager")
    if wt_manager and not state.get("mock_mode", False):
        try:
            info = wt_manager.create_worktree(task_id)
            print(f"Created worktree: {info.worktree_path}", flush=True)
        except Exception as e:
            print(f"Warning: Failed to create worktree: {e}", flush=True)
    
    print(f"Dispatching task: {task_id}", flush=True)
    return [Send("worker", {"task_id": task_id, **state})]


def route_after_worker(state: OrchestratorState, task_id: str) -> Literal["strategist", "director"]:
    """Route after worker completes."""
    task = next((t for t in state.get("tasks", []) if t["id"] == task_id), None)
    
    if task and task.get("status") == "awaiting_qa":
        return "strategist"
    return "director"


def route_after_strategist(state: OrchestratorState) -> Literal["director"]:
    """Always return to director after QA."""
    return "director"
