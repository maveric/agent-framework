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
        # Check if there are PLANNED tasks (e.g., from Phoenix recovery)
        planned_tasks = [t for t in tasks if t.get("status") == "planned"]
        if planned_tasks:
            # Route back to director to evaluate readiness
            print(f"  {len(planned_tasks)} planned task(s) need readiness evaluation", flush=True)
            return "director"
        
        # No ready or planned tasks but not all complete - might be waiting
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


def route_after_worker(state: OrchestratorState) -> Literal["strategist", "director"]:
    """
    Route after worker completes.
    
    Only TEST phase tasks go to Strategist for QA.
    PLAN and BUILD tasks return directly to Director to avoid echo chamber.
    """
    # Get the task that just completed
    tasks = state.get("tasks", [])
    # Find most recently updated task in awaiting_qa status
    qa_tasks = [t for t in tasks if t.get("status") == "awaiting_qa"]
    
    if not qa_tasks:
        return "director"
    
    # Get the most recent one (last updated)
    task = max(qa_tasks, key=lambda t: t.get("updated_at", ""))
    
    # Check phase - only TEST tasks go to QA
    phase = task.get("phase", "")
    if phase == "test":
        print(f"  Routing to QA (TEST phase)", flush=True)
        return "strategist"
    else:
        # PLAN and BUILD tasks skip QA, mark as complete and return to director
        print(f"  Skipping QA ({phase} phase) - marking complete", flush=True)
        task["status"] = "complete"
        return "director"
