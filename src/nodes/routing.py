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
    
    # Check if all tasks are complete (failed tasks can be retried by Phoenix)
    # WAITING_HUMAN tasks are paused for human intervention, also terminal
    all_complete = all(
        t.get("status") in ["complete", "abandoned", "waiting_human"] 
        for t in tasks
    )
    if all_complete:
        print("\nAll tasks complete or awaiting human intervention!", flush=True)
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
    
    # Dispatch ALL ready tasks to workers in parallel
    # BUT respect max_concurrent_workers limit to avoid LLM rate limits
    from datetime import datetime
    
    # Get max concurrent limit from config (default 5)
    orch_config = state.get("orch_config")
    max_concurrent = getattr(orch_config, "max_concurrent_workers", 5) if orch_config else 5
    
    # Count currently active tasks
    active_count = sum(1 for t in tasks if t.get("status") == "active")
    available_slots = max_concurrent - active_count
    
    if available_slots <= 0:
        print(f"  Max concurrent workers ({max_concurrent}) reached, waiting...", flush=True)
        return "__end__"  # Will retry on next director cycle
    
    # Limit ready tasks to available slots
    tasks_to_dispatch = ready_tasks[:available_slots]
    
    # PERF: Log queue depth metrics
    waiting_count = len([t for t in tasks if t.get("status") == "planned"])
    print(f"  📊 Dispatching {len(tasks_to_dispatch)}/{len(ready_tasks)} ready tasks (active={active_count}/{max_concurrent}, waiting={waiting_count})", flush=True)
    
    updated_tasks = []
    sends = []
    
    for t in tasks:
        task_updated = False
        # Check if this task is ready and should be dispatched
        for ready_task in tasks_to_dispatch:  # Only dispatch limited subset
            if t["id"] == ready_task["id"]:
                # Update to ACTIVE status
                t["status"] = "active"
                t["started_at"] = datetime.now().isoformat()
                task_updated = True
                
                # Create worktree for this task (if not in mock mode)
                wt_manager = state.get("_wt_manager")
                if wt_manager and not state.get("mock_mode", False):
                    try:
                        info = wt_manager.create_worktree(t["id"])
                        print(f"Created worktree: {info.worktree_path}", flush=True)
                    except Exception as e:
                        print(f"Warning: Failed to create worktree: {e}", flush=True)
                
                print(f"Dispatching task: {t['id']}", flush=True)
                break
        
        updated_tasks.append(t)
    
    # Create Send objects for limited tasks (respecting concurrency limit)
    for ready_task in tasks_to_dispatch:
        sends.append(Send("worker", {"task_id": ready_task["id"], "tasks": updated_tasks, **state}))
    
    # Return all sends to dispatch tasks in parallel
    return sends


def route_after_worker(state: OrchestratorState):
    """
    Route after worker completes.
    
    Dispatches ALL test tasks in awaiting_qa to Strategist in parallel.
    Marks non-test tasks (plan/build) as complete and returns to Director.
    """
    tasks = state.get("tasks", [])
    qa_tasks = [t for t in tasks if t.get("status") == "awaiting_qa"]
    
    if not qa_tasks:
        return "director"
    
    # Separate test tasks from non-test tasks
    test_tasks = []
    updated_tasks = []
    
    for t in tasks:
        if t.get("status") == "awaiting_qa":
            phase = t.get("phase", "")
            if phase == "test":
                # Route to strategist for QA
                test_tasks.append(t)
                updated_tasks.append(t)
            else:
                # Non-test tasks (plan/build) skip QA and go straight to complete
                # Worker.py already handled the merge, so we just mark it complete
                print(f"  Task {t['id'][:8]} ({phase}) skipping QA - marking complete...", flush=True)
                t["status"] = "complete"
                updated_tasks.append(t)
        else:
            updated_tasks.append(t)
    
    # If we have test tasks, dispatch them ALL to strategist in parallel
    if test_tasks:
        print(f"  Dispatching {len(test_tasks)} test task(s) to QA in parallel", flush=True)
        sends = []
        for test_task in test_tasks:
            sends.append(Send("strategist", {"task_id": test_task["id"], "tasks": updated_tasks, **state}))
        return sends
    else:
        # All non-test tasks were marked complete, return to director
        return "director"
