"""
Agent Orchestrator — Director Node
==================================
Version 1.0 — November 2025

Director node for task management and orchestration.
"""

from typing import Any, Dict, List
from datetime import datetime
from state import OrchestratorState
from orchestrator_types import (
    Task, TaskStatus, TaskPhase, WorkerProfile,
    _dict_to_task, task_to_dict
)
from llm_client import get_llm
from pydantic import BaseModel, Field
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from langgraph.types import interrupt
import uuid


class TaskDefinition(BaseModel):
    """LLM-generated task definition."""
    title: str = Field(description="Short title")
    component: str = Field(description="Component name")
    phase: str = Field(description="plan, build, or test")
    description: str
    acceptance_criteria: List[str]
    depends_on_indices: List[int] = Field(default_factory=list)
    worker_profile: str = "code_worker"


class DecompositionResponse(BaseModel):
    """LLM response for task decomposition."""
    tasks: List[TaskDefinition]


class IntegratedTaskDefinition(BaseModel):
    """Task definition with resolved string dependencies."""
    title: str = Field(description="Task title")
    component: str = Field(description="Component name")
    phase: str = Field(description="plan, build, or test")
    description: str
    acceptance_criteria: List[str]
    depends_on: List[str] = Field(description="List of EXACT TITLES of other tasks this depends on")
    worker_profile: str = "code_worker"


class RejectedTask(BaseModel):
    """Task rejected during integration for being out of scope."""
    title: str
    reason: str = Field(description="Why this task was rejected")


class IntegrationResponse(BaseModel):
    """LLM response for global plan integration."""
    tasks: List[IntegratedTaskDefinition]
    rejected_tasks: List[RejectedTask] = Field(default_factory=list, description="Tasks rejected as out of scope")


from langchain_core.runnables import RunnableConfig


def _process_human_resolution(state: OrchestratorState, resolution: dict) -> Dict[str, Any]:
    """
    Process human resolution after interrupt resume.
    
    Called when graph resumes with Command(resume=resolution_data).
    Handles three actions: retry, spawn_new_task, abandon.
    """
    tasks = [_dict_to_task(t) for t in state.get("tasks", [])]
    updates = []
    
    task_id = resolution.get("task_id")
    task = next((t for t in tasks if t.id == task_id), None)
    
    if not task:
        print(f"  ERROR: Task {task_id} not found for resolution", flush=True)
        return {"tasks": [task_to_dict(t) for t in tasks], "_interrupt_data": None}
    
    action = resolution.get("action")
    
    if action == "retry":
        print(f"  Human approved retry for task {task.id}", flush=True)
        
        # Reset task for retry
        task.status = TaskStatus.PLANNED
        task.retry_count = 0
        task.updated_at = datetime.now()
        
        # Apply optional modifications
        if resolution.get("modified_description"):
            task.description = resolution["modified_description"]
            print(f"  Applied modified description", flush=True)
        
        if resolution.get("modified_criteria"):
            task.acceptance_criteria = resolution["modified_criteria"]
            print(f"  Applied modified criteria", flush=True)
        
        # Update this task in place
        for i, t in enumerate(tasks):
            if t.id == task_id:
                tasks[i] = task
                break
    
    elif action == "spawn_new_task":
        print(f"  Human requested new task to replace {task.id}", flush=True)
        
        # Mark original as abandoned
        task.status = TaskStatus.ABANDONED
        task.updated_at = datetime.now()
        
        # Update original task
        for i, t in enumerate(tasks):
            if t.id == task_id:
                tasks[i] = task
                break
        
        # Create new task from resolution data
        new_component = resolution.get("new_component", task.component)
        new_phase_str = resolution.get("new_phase", task.phase.value)
        new_title = f"{new_component} {new_phase_str} Task".title() # Default title
        
        # Append title to description so integrator can find it
        new_description = resolution["new_description"]
        if "Title: " not in new_description:
            new_description += f"\n\nTitle: {new_title}"

        new_task = Task(
            id=f"task_{uuid.uuid4().hex[:8]}",
            component=new_component,
            phase=TaskPhase(new_phase_str),
            status=TaskStatus.PLANNED,
            assigned_worker_profile=WorkerProfile(resolution.get("new_worker_profile", task.assigned_worker_profile.value)),
            description=new_description,
            acceptance_criteria=resolution.get("new_criteria", task.acceptance_criteria),
            depends_on=resolution.get("new_dependencies", []),
            created_at=datetime.now(),
            updated_at=datetime.now(),
            retry_count=0
        )
        
        tasks.append(new_task)
        print(f"  Created new task: {new_task.id} ({new_title})", flush=True)
        
        # [NEW] Dependency Re-linking
        # Find tasks that depended on the OLD task and point them to the NEW task
        relinked_count = 0
        for t in tasks:
            if t.id != new_task.id and t.id != task_id: # Don't update self or abandoned task
                if task_id in t.depends_on:
                    t.depends_on.remove(task_id)
                    t.depends_on.append(new_task.id)
                    t.updated_at = datetime.now()
                    relinked_count += 1
                    print(f"  Relinked dependency: {t.id} now depends on {new_task.id} (was {task_id})", flush=True)
        
        if relinked_count > 0:
            print(f"  Auto-relinked {relinked_count} tasks to the new task.", flush=True)

        # Trigger Replan to ensure graph integrity
        print(f"  Triggering smart replan to integrate new task...", flush=True)
        return {"tasks": [task_to_dict(t) for t in tasks], "replan_requested": True, "_interrupt_data": None}
    
    elif action == "abandon":
        print(f"  Human abandoned task {task.id}", flush=True)
        task.status = TaskStatus.ABANDONED
        task.updated_at = datetime.now()
        
        # Update this task
        for i, t in enumerate(tasks):
            if t.id == task_id:
                tasks[i] = task
                break
    
    else:
        print(f"  ERROR: Unknown action '{action}'", flush=True)
    
    # Clear persisted interrupt data to prevent stale data on next interrupt
    result = {"tasks": [task_to_dict(t) for t in tasks]}
    result["_interrupt_data"] = None  # Clear it
    return result



async def director_node(state: OrchestratorState, config: RunnableConfig = None) -> Dict[str, Any]:
    """
    Director: Task decomposition and readiness evaluation (async version).
    """
    tasks = state.get("tasks", [])
    
    # HITL: Check if we're resuming from an interrupt
    # When Command(resume=value) is called, LangGraph restarts the node from the beginning
    # and passes the resume value which becomes the return value of interrupt()
    if config and config.get("configurable", {}).get("__pregel_resuming"):
        resume_value = config.get("configurable", {}).get("__pregel_resume")
        if resume_value:
            print(f"Director: Resuming from interrupt, processing human resolution", flush=True)
            return _process_human_resolution(state, resume_value)
    
    # MANUAL INTERRUPT: Check if there's a pending resolution in state
    # This handles manual interrupts where Command(resume=...) doesn't work
    pending_resolution = state.get("pending_resolution")
    if pending_resolution:
        print(f"Director: Found pending resolution from manual interrupt, processing...", flush=True)
        # Clear the pending resolution and process it
        result = _process_human_resolution(state, pending_resolution)
        # Add clearing of pending_resolution to the result
        result["pending_resolution"] = None
        return result
    
    # Get configuration
    mock_mode = state.get("mock_mode", False)
    if not mock_mode and config and "configurable" in config:
        mock_mode = config["configurable"].get("mock_mode", False)
    
    # Initial decomposition if no tasks exist
    if not tasks:
        print("Director: Initial decomposition", flush=True)
        objective = state.get("objective", "")
        
        if mock_mode:
            new_tasks = _mock_decompose(objective)
        else:
            new_tasks = await _decompose_objective(objective, state.get("spec", {}), state)
        # Convert to dicts for state
        tasks = [task_to_dict(t) for t in new_tasks]
        # Fall through to readiness evaluation
    
    # Evaluate task readiness and handle failed tasks (Phoenix recovery)
    all_tasks = [_dict_to_task(t) for t in tasks]
    updates = []
    
    # PERF: Print batch summary ONLY when counts change
    completed_count = len([t for t in tasks if t.get("status") == "complete" or t.get("status") == "awaiting_qa"])
    failed_count = len([t for t in tasks if t.get("status") == "failed"])
    active_count = len([t for t in tasks if t.get("status") == "active"])
    ready_count = len([t for t in tasks if t.get("status") == "ready"])
    blocked_count = len([t for t in tasks if t.get("status") == "planned"])
    
    # Track previous counts in state
    prev_counts = state.get("_director_prev_counts", {})
    current_counts = {
        "complete": completed_count,
        "failed": failed_count, 
        "active": active_count,
        "ready": ready_count,
        "blocked": blocked_count
    }
    
    # Only print if counts have changed
    if current_counts != prev_counts and (completed_count or failed_count or active_count or blocked_count):
        print(f"\n{'='*60}", flush=True)
        print(f"📊 BATCH STATUS SUMMARY", flush=True)
        print(f"{'='*60}", flush=True)
        print(f"  ✅ Complete/QA: {completed_count}", flush=True)
        print(f"  🔄 Active:      {active_count}", flush=True)
        print(f"  📋 Ready:       {ready_count}", flush=True)
        print(f"  ⏳ Pending:      {blocked_count}", flush=True)
        print(f"  ❌ Failed:      {failed_count}", flush=True)
        
        # Show individual task timings for recently changed tasks
        completed_tasks = [t for t in tasks if t.get("status") == "complete" or t.get("status") == "awaiting_qa"]
        failed_tasks = [t for t in tasks if t.get("status") == "failed"]
        for t in [*completed_tasks[-5:], *failed_tasks[-3:]]:  # Last 5 complete, 3 failed
            status_icon = "✅" if t.get("status") in ["complete", "awaiting_qa"] else "❌"
            task_id = t.get("id", "?")[:8]
            phase = t.get("phase", "?")[:6]
            # Calculate duration if we have timestamps
            started = t.get("started_at")
            updated = t.get("updated_at")
            if started and updated:
                try:
                    start_dt = datetime.fromisoformat(started.replace('Z', '+00:00'))
                    end_dt = datetime.fromisoformat(updated.replace('Z', '+00:00'))
                    duration = (end_dt - start_dt).total_seconds()
                    print(f"  {status_icon} {task_id} ({phase}): {duration:.1f}s", flush=True)
                except:
                    print(f"  {status_icon} {task_id} ({phase})", flush=True)
            else:
                print(f"  {status_icon} {task_id} ({phase})", flush=True)
        print(f"{'='*60}\n", flush=True)
    
    MAX_RETRIES = 4  # Maximum number of retries before giving up
    
    for task in all_tasks:
        # Phoenix recovery: Retry failed tasks
        if task.status == TaskStatus.FAILED:
            retry_count = task.retry_count if task.retry_count is not None else 0
            
            if retry_count < MAX_RETRIES:
                print(f"Phoenix: Retrying task {task.id} (attempt {retry_count + 1}/{MAX_RETRIES})", flush=True)
                
                # SPECIAL HANDLING: If TEST task failed QA, check if it's a code issue or test worker error
                # Note: task.qa_verdict is a QAVerdict object, not a dict
                if task.phase == TaskPhase.TEST and task.qa_verdict and not task.qa_verdict.passed:
                    feedback = task.qa_verdict.overall_feedback
                    
                    # Detect if this is a TEST WORKER ERROR (missing test results file)
                    # vs an actual TEST EXECUTION FAILURE (code bugs found)
                    is_test_worker_error = "MISSING TEST RESULTS FILE" in feedback
                    
                    if is_test_worker_error:
                        # TEST WORKER ERROR: Just retry the TEST task itself
                        # The test worker needs to write the results file - no code fix needed
                        print(f"  QA Failure: Test worker error (missing results file). Retrying TEST task.", flush=True)
                        task.status = TaskStatus.PLANNED
                        task.retry_count = retry_count + 1
                        task.updated_at = datetime.now()
                        
                        # Append feedback to description so test worker sees it on retry
                        if "MISSING TEST RESULTS FILE" not in task.description:
                            task.description += f"\n\nPREVIOUS FAILURE: {feedback}"
                        
                        # Immediately evaluate readiness for instant retry
                        new_status = _evaluate_readiness(task, all_tasks)
                        if new_status == TaskStatus.READY:
                            print(f"  Phoenix: Task {task.id} immediately READY for retry", flush=True)
                            task.status = new_status
                        
                        updates.append(task_to_dict(task))
                    else:
                        # ACTUAL TEST EXECUTION FAILURE: Spawn a BUILD task to fix code issues
                        print(f"  QA Failure: Test execution failed. Spawning fix task.", flush=True)
                        print(f"  Feedback: {feedback[:100]}...", flush=True)
                        
                        # Create a new BUILD task to fix the issues
                        fix_task_id = f"task_{uuid.uuid4().hex[:8]}"
                        fix_task = Task(
                            id=fix_task_id,
                            component=task.component,
                            phase=TaskPhase.BUILD,
                            status=TaskStatus.PLANNED,
                            assigned_worker_profile=WorkerProfile.CODER,  # Default to Coder for fixes
                            description=f"Fix issues in {task.component} reported by QA.\n\nQA FEEDBACK (MUST ADDRESS):\n{feedback}",
                            acceptance_criteria=[
                                "Address all QA feedback points",
                                "Ensure code compiles/runs",
                                "Verify fix before re-testing"
                            ],
                            depends_on=task.depends_on.copy(),  # Depend on what the test depended on
                            created_at=datetime.now(),
                            updated_at=datetime.now()
                        )
                        
                        # Add the fix task
                        updates.append(task_to_dict(fix_task))
                        
                        # Update the TEST task to depend on the fix task
                        task.depends_on.append(fix_task_id)
                        task.status = TaskStatus.PLANNED
                        task.retry_count = retry_count + 1
                        task.updated_at = datetime.now()
                        
                        # Evaluate readiness (will be PLANNED since it now depends on fix_task)
                        # But good to be explicit about status
                        task.status = _evaluate_readiness(task, all_tasks)
                        
                        updates.append(task_to_dict(task))
                    
                else:
                    # Standard retry (reset to PLANNED)
                    task.status = TaskStatus.PLANNED
                    task.retry_count = retry_count + 1
                    task.updated_at = datetime.now()
                    
                    # Include QA feedback OR AAR failure reason in description
                    failure_reason = ""
                    if task.qa_verdict and hasattr(task.qa_verdict, 'overall_feedback'):
                        failure_reason = f"QA FEEDBACK: {task.qa_verdict.overall_feedback}"
                    elif task.aar and task.aar.summary:
                         failure_reason = f"PREVIOUS FAILURE: {task.aar.summary}"
                    
                    if failure_reason:
                        print(f"  Previous failure: {failure_reason[:100]}", flush=True)
                        # Append to description if not already there to avoid duplication
                        if "PREVIOUS FAILURE:" not in task.description and "QA FEEDBACK:" not in task.description:
                             task.description += f"\n\n{failure_reason}"
                    
                    # Immediately evaluate readiness for instant retry
                    new_status = _evaluate_readiness(task, all_tasks)
                    if new_status == TaskStatus.READY:
                        print(f"  Phoenix: Task {task.id} immediately READY for retry", flush=True)
                        task.status = new_status
                    
                    updates.append(task_to_dict(task))
            else:
                # HUMAN-IN-THE-LOOP: Request intervention for max retry exceeded
                print(f"Phoenix: Task {task.id} exceeded max retries ({MAX_RETRIES}), requesting human intervention", flush=True)
                
                # Update status to indicate waiting for human input
                task.status = TaskStatus.WAITING_HUMAN
                task.updated_at = datetime.now()
                updates.append(task_to_dict(task))
                
                # Prepare interrupt payload with all task context
                interrupt_data = {
                    "type": "task_exceeded_retries",
                    "task_id": task.id,
                    "task_description": task.description,
                    "component": task.component,
                    "phase": task.phase.value,
                    "retry_count": retry_count,
                    "failure_reason": task.aar.summary if task.aar else "No details available",
                    "acceptance_criteria": task.acceptance_criteria,
                    "files_modified": task.aar.files_modified if task.aar else [],
                    "assigned_worker_profile": task.assigned_worker_profile.value,
                    "depends_on": task.depends_on
                }
                
                # Try to use LangGraph interrupt() for HITL
                # If we're running outside LangGraph context (continuous dispatch), 
                # just return with updates - the WAITING_HUMAN status will pause the task
                try:
                    resolution = interrupt(interrupt_data)
                    
                    if resolution:
                        print(f"Director: Resumed with resolution: {resolution}", flush=True)
                        return _process_human_resolution(state, resolution)
                except RuntimeError as e:
                    if "outside of a runnable context" in str(e):
                        print(f"  (Running outside LangGraph - task paused with WAITING_HUMAN status)", flush=True)
                        # Return updates so the WAITING_HUMAN status is saved
                        # The continuous dispatch loop will detect this and pause the run
                    else:
                        raise
                
                continue
        
        # Standard readiness evaluation for planned tasks
        elif task.status == TaskStatus.PLANNED:
            new_status = _evaluate_readiness(task, all_tasks)
            if new_status != task.status:
                task.status = new_status
                task.updated_at = datetime.now()
                updates.append(task_to_dict(task))
            # If it was just created (and thus not in original state), we must add it
            elif task.id not in [t["id"] for t in state.get("tasks", [])]:
                updates.append(task_to_dict(task))

    # GLOBAL PLAN INTEGRATION (Sync & Link)
    
    # Check for manual replan request
    replan_requested = state.get("replan_requested", False)
    
    # 1. Check for Active Planners (Blocking Condition)
    # We still want to wait for the initial planning phase to complete globally
    planner_tasks = [t for t in all_tasks if t.assigned_worker_profile == WorkerProfile.PLANNER]
    # NOTE: AWAITING_QA counts as "done" for planners - they don't need QA, their output is suggestions
    active_planners = [t for t in planner_tasks if t.status not in [TaskStatus.COMPLETE, TaskStatus.FAILED, TaskStatus.AWAITING_QA]]
    
    # Only print waiting message when count changes
    # Only print waiting message when count changes
    prev_active_planners = state.get("_director_prev_counts", {}).get("active_planners", -1) # Use dedicated key if possible, or fallback
    # Actually we stored it in _prev_active_planners in the return
    prev_active_planners = state.get("_prev_active_planners", -1)
    
    if active_planners:
        if len(active_planners) != prev_active_planners:
            print(f"Director: Waiting for {len(active_planners)} planners to complete before integrating plans.", flush=True)
        # BLOCK: Do not proceed to integration or replan
        # We just return the updates (status changes, etc.)
        # We need to make sure we return result at the end
    elif replan_requested:
        # MANUAL REPLAN TRIGGER
        print("Director: Manual replan requested. Re-integrating pending tasks...", flush=True)
        
        # Gather all pending tasks (PLANNED)
        # We exclude COMPLETE, FAILED, and ACTIVE tasks from being reshuffled, 
        # but we include them in the integration context so dependencies can point to them.
        pending_tasks = [t for t in all_tasks if t.status == TaskStatus.PLANNED]
        
        if pending_tasks:
            # Convert to dicts for the integrator
            suggestions = [task_to_dict(t) for t in pending_tasks]
            
            try:
                # Re-run integration
                new_tasks = await _integrate_plans(suggestions, state)
                
                # Update the pending tasks with new definitions (dependencies, etc.)
                # We match by ID if possible, or replace if IDs changed (though _integrate_plans tries to preserve)
                # Actually _integrate_plans generates NEW IDs usually. 
                # To avoid duplicates, we should probably mark the old pending tasks as "replaced" or just update them in place.
                # For simplicity in this v1, let's try to update them if titles match, or replace them.
                
                # Strategy: The integrator returns a list of Task objects.
                # We need to update the state.
                
                # Since _integrate_plans returns NEW task objects with potentially new IDs,
                # we need to be careful.
                # Let's just append the new ones and mark the old pending ones as FAILED (or removed).
                # BUT, removing tasks is hard in append-only log.
                # BETTER STRATEGY: Update the EXISTING task objects in place if possible.
                
                # _integrate_plans uses title matching to map to existing IDs.
                # So it SHOULD return tasks with the SAME IDs if the titles match.
                
                updates.extend([task_to_dict(t) for t in new_tasks])
                
                # Reset flag
                # We can't easily "remove" the flag from state in LangGraph without a specific reducer.
                # But we can set it to False in the update.
                # Assuming the state schema allows overwriting.
                # For now, we'll just print it. The state update needs to handle this.
                # We'll return it in the result.
                
            except Exception as e:
                print(f"Director Error: Replan failed: {e}", flush=True)
    else:
        # 2. Collect suggestions from ALL completed/failed tasks
        # (Not just planners, but any task that might have used create_subtasks, e.g. Testers)
        all_suggestions = []
        tasks_with_suggestions = []
        
        for task in all_tasks:
            # We only process suggestions from tasks that are done running
            # NOTE: AWAITING_QA counts as "done" - planners complete with this status
            if task.status in [TaskStatus.COMPLETE, TaskStatus.FAILED, TaskStatus.AWAITING_QA]:
                raw_task = next((t for t in tasks if t["id"] == task.id), None)
                if raw_task and raw_task.get("suggested_tasks"):
                    all_suggestions.extend(raw_task["suggested_tasks"])
                    tasks_with_suggestions.append(raw_task)
        
        
        if all_suggestions:
            print(f"Director: Integrating {len(all_suggestions)} task suggestions...", flush=True)
            
            try:
                new_tasks = await _integrate_plans(all_suggestions, state)
                updates.extend([task_to_dict(t) for t in new_tasks])
                
                # Clear suggestions so we don't re-process
                for raw_t in tasks_with_suggestions:
                    raw_t["suggested_tasks"] = []
                    updates.append(raw_t)
            except Exception as e:
                print(f"Director Error: Integration failed: {e}", flush=True)
                import traceback
                traceback.print_exc()

    # Capture Director logs
    # We construct a synthetic message history for the Director's actions
    director_messages = []
    
    # 1. Spec Creation Log
    if 'spec_prompt' in locals() and 'spec_response' in locals():
        director_messages.extend([
            SystemMessage(content="Director: Creating Design Specification"),
            HumanMessage(content=spec_prompt.format(objective=state.get("objective", ""))[0].content), # Approximate prompt
            AIMessage(content=str(spec_response.content))
        ])
        
    # 2. Decomposition Log
    if 'decomp_prompt' in locals() and 'response' in locals():
        director_messages.extend([
            SystemMessage(content="Director: Decomposing Objective into Tasks"),
            HumanMessage(content=f"Objective: {state.get('objective', '')}\n\nSpec Summary: {spec_summary if 'spec_summary' in locals() else '...'}"),
            AIMessage(content=f"Created {len(tasks) if 'tasks' in locals() else 0} planner tasks.")
        ])
        
    # 3. Integration Log
    if 'all_suggestions' in locals() and all_suggestions:
        director_messages.extend([
            SystemMessage(content="Director: Integrating Plans"),
            HumanMessage(content=f"Integrating {len(all_suggestions)} suggestions..."),
            AIMessage(content=f"Integrated {len(new_tasks) if 'new_tasks' in locals() else 0} new tasks.")
        ])



    # PENDING REORG: Block new task starts, wait for active tasks, then reorg
    pending_reorg = state.get("pending_reorg", False)
    if pending_reorg:
        active_tasks = [t for t in all_tasks if t.status == TaskStatus.ACTIVE]
        
        if active_tasks:
            # Still have active tasks - block new task dispatch
            print(f"Director: Reorg pending. Waiting on {len(active_tasks)} active tasks to finish. No new tasks started.", flush=True)
            # Don't update tasks or dispatch - just return with flag still set
            return {"pending_reorg": True}  # Keep flag set
        else:
            # All active tasks done - execute reorg NOW
            print("Director: All tasks complete. Executing reorg now...", flush=True)
            
            # Gather all PLANNED tasks for reorganization
            planned_tasks = [t for t in all_tasks if t.status == TaskStatus.PLANNED]
            
            if planned_tasks:
                suggestions = [task_to_dict(t) for t in planned_tasks]
                try:
                    new_tasks = await _integrate_plans(suggestions, state)
                    updates.extend([task_to_dict(t) for t in new_tasks])
                    print(f"Director: Reorganized {len(new_tasks)} tasks", flush=True)
                except Exception as e:
                    print(f"Director Error: Reorg failed: {e}", flush=True)
                    import traceback
                    traceback.print_exc()
            
            # Clear the flag - reorg complete
            result = {"tasks": updates, "pending_reorg": False} if updates else {"pending_reorg": False}
            if director_messages:
                result["task_memories"] = {"director": director_messages}
            return result
    
    # Check if all tasks are in terminal states (complete/abandoned/waiting_human)
    # If so, mark the run as complete
    all_terminal = all(
        t.status in [TaskStatus.COMPLETE, TaskStatus.ABANDONED, TaskStatus.WAITING_HUMAN]
        for t in all_tasks
    )
    
    # Initialize result dict
    result = {}
    
    if all_terminal and all_tasks:
        print("Director: All tasks in terminal states - marking run as COMPLETE", flush=True)
        result["strategy_status"] = "complete"
    
    # Return updates and logs
    if updates:
        result["tasks"] = updates
    
    # Only clear replan_requested if it was set
    if state.get("replan_requested"):
        result["replan_requested"] = False
    
    # Save state for log de-duplication
    result["_director_prev_counts"] = current_counts
    if 'active_planners' in locals():
        result["_prev_active_planners"] = len(active_planners)

    
    if director_messages:
        # We use a special key "director" for these logs. 
        # The frontend will need to be updated to display them, or we can attach them to a dummy task.
        # For now, we just expose them in the state.
        result["task_memories"] = {**result.get("task_memories", {}), "director": director_messages}
        
    return result



def _mock_decompose(objective: str) -> List[Task]:
    """Mock decomposition for testing - creates realistic task breakdown."""
    print(f"MOCK: Decomposing '{objective}' without LLM", flush=True)
    
    # Generate base IDs
    base_id = uuid.uuid4().hex[:6]
    plan_id = f"task_{base_id}_plan"
    impl_id = f"task_{base_id}_impl"
    test_id = f"task_{base_id}_test"
    
    return [
        # Task 1: Planning
        Task(
            id=plan_id,
            component="api",
            phase=TaskPhase.PLAN,
            status=TaskStatus.PLANNED,
            assigned_worker_profile=WorkerProfile.PLANNER,
            description="Design API architecture and endpoints",
            acceptance_criteria=[
                "Architecture document created",
                "Endpoints documented"
            ],
            depends_on=[],
            created_at=datetime.now(),
            updated_at=datetime.now()
        ),
        # Task 2: Implementation (depends on plan)
        Task(
            id=impl_id,
            component="api",
            phase=TaskPhase.BUILD,
            status=TaskStatus.PLANNED,
            assigned_worker_profile=WorkerProfile.CODER,
            description="Implement API endpoints based on design",
            acceptance_criteria=[
                "API code implemented",
                "Unit tests written",
                "Code committed"
            ],
            depends_on=[plan_id],
            created_at=datetime.now(),
            updated_at=datetime.now()
        ),
        # Task 3: Testing (depends on implementation)
        Task(
            id=test_id,
            component="api",
            phase=TaskPhase.TEST,
            status=TaskStatus.PLANNED,
            assigned_worker_profile=WorkerProfile.TESTER,
            description="Validate API meets acceptance criteria",
            acceptance_criteria=[
                "Integration tests pass",
                "API responds correctly"
            ],
            depends_on=[impl_id],
            created_at=datetime.now(),
            updated_at=datetime.now()
        )
    ]


async def _decompose_objective(objective: str, spec: Dict[str, Any], state: Dict[str, Any]) -> List[Task]:
    """
    Director: High-level decomposition + spec creation (async version).
    
    The Director (using the smartest model) has leeway to decide what's best.
    Creates the design_spec.md and delegates to 1-5 component planners.
    """
    # Get orchestrator config from state (has user's model settings)
    orch_config = state.get("orch_config")
    if not orch_config:
        from config import OrchestratorConfig
        orch_config = OrchestratorConfig()
    
    model_config = orch_config.director_model
    workspace_path = state.get("_workspace_path")
    
    llm = get_llm(model_config)
    
    # STEP 0: Explore existing project structure (if workspace exists)
    # Using direct filesystem access (not tools) since director is trusted
    project_context = ""
    if workspace_path:
        print("Director: Exploring existing project structure...", flush=True)
        from pathlib import Path
        import os
        
        try:
            # List root directory
            ws_path = Path(workspace_path)
            if ws_path.exists():
                entries = os.listdir(ws_path)
                # Format as a tree-like listing
                listing_lines = []
                for entry in sorted(entries):
                    entry_path = ws_path / entry
                    if entry_path.is_dir():
                        listing_lines.append(f"📁 {entry}/")
                    else:
                        listing_lines.append(f"📄 {entry}")
                root_listing = "\n".join(listing_lines[:50])  # Limit to 50 entries
                if len(entries) > 50:
                    root_listing += f"\n... and {len(entries) - 50} more files"
                project_context += f"## Existing Project Structure\n```\n{root_listing}\n```\n\n"
            
            # Check for common config files
            common_files = [
                "package.json", "requirements.txt", "pyproject.toml", 
                "README.md", "design_spec.md", "tsconfig.json",
                "vite.config.ts", "vite.config.js"
            ]
            
            for filename in common_files:
                filepath = ws_path / filename
                if filepath.exists():
                    try:
                        content = filepath.read_text(encoding="utf-8")
                        # Truncate very long files
                        if len(content) > 2000:
                            content = content[:2000] + "\n... (truncated)"
                        project_context += f"## {filename}\n```\n{content}\n```\n\n"
                        print(f"  Read: {filename}", flush=True)
                    except Exception as e:
                        print(f"  Warning: Could not read {filename}: {e}", flush=True)
            
            print(f"  Project exploration complete. Found {len(project_context)} chars of context.", flush=True)
        except Exception as e:
            print(f"  Warning: Project exploration failed: {e}", flush=True)

    
    # STEP 1: Write design specification
    print("Director: Creating design specification...", flush=True)

    
    spec_prompt = ChatPromptTemplate.from_messages([
        ("system", """You are a Lead Architect creating a design specification.

CRITICAL INSTRUCTIONS:
1. Analyze the objective and determine the necessary components (e.g., Backend, Frontend, Database, Testing)
2. Create a comprehensive design specification that will guide all workers
3. You have leeway to make architectural decisions that best serve the objective
4. Focus on MVP - deliver the core functionality requested, avoid unnecessary extras
5. **ALWAYS include dependency isolation** to prevent package pollution across projects
6. **CONSIDER EXISTING PROJECT STRUCTURE** - if files already exist, build upon them rather than recreating

{project_context}

OUTPUT:
Write a design specification in markdown format with these sections:
- **Overview**: Brief project summary
- **Components**: List each component (Backend, Frontend, etc.)
- **Existing Code Analysis**: If project files exist, describe what's already there and what needs work
- **Dependency Isolation**: MANDATORY instructions for isolated environments
  * Python: Use `python -m venv .venv` and activate it before installing packages
  * Node.js: Use `npm install` (creates local node_modules)
  * Other: Specify equivalent isolation mechanism
- **API Routes** (if applicable): Methods, paths, request/response formats
- **Data Models** (if applicable): Schemas, database tables, field types
- **File Structure**: Where files should be created
- **Technology Stack**: What frameworks/libraries to use
- **.gitignore Requirements**: MANDATORY - must include: .venv/, venv/, node_modules/, __pycache__/, *.pyc, .env

  * **CRITICAL**: Make sure the design spec includes a .gitignore that excludes:
    - .venv/ or venv/
    - node_modules/
    - __pycache__/
    - *.pyc
    - *.db (if using SQLite for development)
    - Any other generated files
  * This prevents worktree pollution and keeps git operations fast

Be specific enough that workers can implement without ambiguity."""),
        ("user", "Objective: {objective}")

    ])
    
    # LOG: Director spec creation request
    from pathlib import Path
    import json
    if workspace_path:
        log_dir = Path(workspace_path) / ".llm_logs" / "director"
        log_dir.mkdir(parents=True, exist_ok=True)
        from datetime import datetime
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        request_log = log_dir / f"spec_request_{timestamp}.json"
        with open(request_log, 'w', encoding='utf-8') as f:
            json.dump({
                "timestamp": datetime.now().isoformat(),
                "type": "spec_creation",
                "objective": objective,
                "project_context_length": len(project_context)
            }, f, indent=2)
        print(f"  [LOG] Director spec request: {request_log}", flush=True)
    
    try:
        spec_response = await llm.ainvoke(spec_prompt.format(objective=objective, project_context=project_context))
        spec_content = str(spec_response.content)
        
        # LOG: Director spec response
        if workspace_path:
            response_log = log_dir / f"spec_response_{timestamp}.json"
            with open(response_log, 'w', encoding='utf-8') as f:
                json.dump({
                    "timestamp": datetime.now().isoformat(),
                    "type": "spec_creation",
                    "spec_length": len(spec_content),
                    "spec_preview": spec_content[:1000] + "..." if len(spec_content) > 1000 else spec_content
                }, f, indent=2)
            print(f"  [LOG] Director spec response: {response_log} ({len(spec_content)} chars)", flush=True)        
        # Write spec to workspace
        if workspace_path:
            from pathlib import Path
            spec_path = Path(workspace_path) / "design_spec.md"
            spec_path.write_text(spec_content, encoding="utf-8")
            print(f"  Written: design_spec.md", flush=True)
            
            # Commit to main to avoid merge conflicts later
            wt_manager = state.get("_wt_manager")
            if wt_manager and not state.get("mock_mode", False):
                try:
                    wt_manager.commit_to_main(
                        message="Director: Add design specification",
                        files=["design_spec.md"]
                    )
                    print(f"  Committed: design_spec.md", flush=True)
                except Exception as e:
                    print(f"  Warning: Failed to commit spec: {e}", flush=True)
    except Exception as e:
        print(f"  Warning: Failed to create spec: {e}", flush=True)
        spec_content = f"# Design Spec\n\nObjective: {objective}\n\nPlease create a minimal viable implementation."
    
    # STEP 2: Decompose into 1-5 component planner tasks
    print("Director: Creating component planner tasks...", flush=True)
    
    structured_llm = llm.with_structured_output(DecompositionResponse)
    
    decomp_prompt = ChatPromptTemplate.from_messages([
    ("system", """You are the Director decomposing a project into FEATURE-LEVEL planners.

CRITICAL INSTRUCTIONS - FEATURE-BASED DECOMPOSITION:

1. **FIRST: Check if infrastructure planner is needed**
   - Does design spec require: Flask setup, database init, React config, etc?
   - If YES: Create "Set up [project] infrastructure" planner as FIRST task
   
2. **THEN: Create planners for user-facing features**
   - Think "User can..." or "System provides..."
   - Order logically: foundational features before dependent ones
   - Example: "User can add items" before "User can delete items"
   
3. **FINALLY: Create validation planner** 
   - "System validates with [test framework]"
   - Always last

FEATURE PLANNER EXAMPLES:

✅ INFRASTRUCTURE (if needed, always FIRST):
- Component: "infrastructure", Description: "Set up kanban application infrastructure"
- Component: "infrastructure", Description: "Initialize React dashboard with routing"

✅ USER FEATURES (in logical order):
- Component: "add-items", Description: "User can add items to the system"
- Component: "view-items", Description: "User can view items in organized layout"
- Component: "modify-items", Description: "User can modify item properties"
- Component: "delete-items", Description: "User can delete items"

✅ VALIDATION (always LAST):
- Component: "validation", Description: "System validates core functionality with Playwright"

❌ NEVER DO THIS:
- Component: "backend" (too technical, not feature-based)
- Component: "frontend" (too technical, not feature-based)
- Component: "testing" (testing is part of features)
- Component: "database" (unless it's the infrastructure planner)

RULES:
- Create 1-7 planner tasks (infra + features + validation)
- Each task should have phase="plan" and worker_profile="planner_worker"
- Do NOT create build or test tasks - planners will create those
- Component name should be the feature slug (e.g., "add-items", "infrastructure")
- Features should be user-facing capabilities, NOT technical components

OUTPUT:
Create planner tasks following this schema. Order them: infrastructure -> features -> validation."""),
    ("user", """Objective: {objective}

Design Spec Summary:
{spec_summary}

Create feature-level planner tasks based on the design spec. Remember:
- Infrastructure first (if needed)
- User features in logical order
- Validation last""")
])
    
    try:
        # Use first 500 chars of spec as summary
        spec_summary = spec_content[:500] + "..." if len(spec_content) > 500 else spec_content
        
        response = await structured_llm.ainvoke(decomp_prompt.format(
            objective=objective,
            spec_summary=spec_summary
        ))
        
        tasks = []
        for t_def in response.tasks:
            # Ensure it's a planner task
            if t_def.phase.lower() != "plan":
                print(f"  Warning: Director tried to create {t_def.phase} task, converting to 'plan'", flush=True)
            
            task = Task(
                id=f"task_{uuid.uuid4().hex[:8]}",
                component=t_def.component,
                phase=TaskPhase.PLAN,
                status=TaskStatus.PLANNED,
                assigned_worker_profile=WorkerProfile.PLANNER,
                description=f"{t_def.description}\n\nREFERENCE: design_spec.md for architecture details.",
                acceptance_criteria=t_def.acceptance_criteria,
                depends_on=[],
                created_at=datetime.now(),
                updated_at=datetime.now()
            )
            tasks.append(task)
        
        print(f"  Created {len(tasks)} planner task(s)", flush=True)
        return tasks
        
    except Exception as e:
        print(f"Decomposition error: {e}, using fallback", flush=True)
        # Fallback: single planner for the entire project
        return [Task(
            id=f"task_{uuid.uuid4().hex[:8]}",
            component="main",
            phase=TaskPhase.PLAN,
            status=TaskStatus.PLANNED,
            assigned_worker_profile=WorkerProfile.PLANNER,
            description=f"Plan implementation for: {objective}\n\nREFERENCE: design_spec.md for architecture details.",
            acceptance_criteria=["Create implementation plan", "Define build and test tasks"],
            depends_on=[],
            created_at=datetime.now(),
            updated_at=datetime.now()
        )]


def _evaluate_readiness(task: Task, all_tasks: List[Task]) -> TaskStatus:
    """Check if task dependencies are met."""
    if task.status != TaskStatus.PLANNED:
        return task.status
    
    # Check all dependencies are complete
    for dep_id in task.depends_on:
        dep = next((t for t in all_tasks if t.id == dep_id), None)
        
        # [NEW] Safety check for abandoned dependencies
        if dep and dep.status == TaskStatus.ABANDONED:
            print(f"  Task {task.id} BLOCKED: Dependency {dep_id} was ABANDONED", flush=True)
            # We can't proceed. Mark as BLOCKED (or FAILED) to stop the loop.
            # We'll modify the task object in place (though this function returns status)
            # Ideally we should return a BLOCKED status if we had one, or FAILED.
            # Let's use FAILED with a clear reason so Phoenix/User can see it.
            # But wait, _evaluate_readiness returns TaskStatus.
            # If we return FAILED, Phoenix might try to retry it.
            # If we return BLOCKED, it's a valid status.
            return TaskStatus.BLOCKED
            
        if not dep:
            # print(f"  Task {task.id} waiting: Dependency {dep_id} NOT FOUND", flush=True)
            return TaskStatus.PLANNED
            
        if dep.status != TaskStatus.COMPLETE:
            # Only print if dependency is not PLANNED (to avoid spamming for deep chains)
            # if dep.status != TaskStatus.PLANNED:
            #     print(f"  Task {task.id} waiting: {dep.component} ({dep.id}) is {dep.status}", flush=True)
            return TaskStatus.PLANNED
    
    return TaskStatus.READY


async def _integrate_plans(suggestions: List[Dict[str, Any]], state: Dict[str, Any]) -> List[Task]:
    """
    Integrate proposed tasks from multiple planners into a cohesive plan (async version).
    Resolves cross-component dependencies.
    """
    # Get LLM
    orch_config = state.get("orch_config")
    if not orch_config:
        from config import OrchestratorConfig
        orch_config = OrchestratorConfig()
    
    model_config = orch_config.director_model
    llm = get_llm(model_config)
    
    # Prepare input for LLM
    tasks_input = []
    for s in suggestions:
        # Extract title if embedded in description
        desc = s.get("description", "")
        title = s.get("title", "Untitled")
        if "Title: " in desc and title == "Untitled":
             title = desc.split("Title: ")[-1].strip()
             
        tasks_input.append({
            "title": title,
            "component": s.get("component", "unknown"),
            "phase": s.get("phase", "build"),
            "description": desc,
            "depends_on": s.get("depends_on", []),
            "rationale": s.get("rationale", "")
        })
        
    prompt = ChatPromptTemplate.from_messages([
        ("system", """You are the Lead Architect integrating project plans.
        
        INPUT: A list of proposed tasks from different component planners (Frontend, Backend, etc.).
        
        YOUR JOB:
        1. **Deduplicate**: If multiple planners proposed the same task (e.g., "Create Database"), keep only one.
        2. **Link Dependencies**: Ensure logical flow across components.
           - **CRITICAL RULE**: Test tasks MUST depend on the Build tasks they are testing.
           - Frontend tasks MUST depend on their corresponding Backend tasks.
           - **Commit granularity**: Each task should be one atomic commit
           - **Parallel when possible**: Tasks within same feature can run parallel if deps allow
           - **SERIALIZE E2E/INTEGRATION TESTS**: Tests that start servers (e2e, integration, playwright) MUST run sequentially.
             * Add dependencies between e2e tests so only one runs at a time
             * Prevents port conflicts (all tests use same port)
             * Example: E2E test #2 depends_on: [build deps, "E2E test #1"]
             * Unit tests can still run in parallel
           - **Example flow**: 
            * Database schema -> API endpoint -> UI component -> Integration test
                * NOT: All backend -> All frontend -> All tests
        3. **Return**: The final, clean list of tasks with CORRECT `depends_on` lists (use exact titles).
        
        CHAIN OF THOUGHT (Internal):
        - First, identify all BUILD tasks.
        - Then, identify all TEST tasks.
        - For each TEST task, find the BUILD task it verifies and add it to `depends_on`.
        - For each FRONTEND task, find the BACKEND task it needs and add it to `depends_on`.
        - **SERIALIZE E2E**: Find all e2e/integration tests (look for keywords: e2e, integration, playwright, end-to-end).
          Chain them: each e2e test (except first) depends on the previous e2e test.
        
        CRITICAL:
        - Do not invent new tasks unless necessary for integration.
        - Ensure every task has a valid dependency path (no cycles).
        - Use the EXACT TITLES for dependencies.
        """),
        ("user", "Proposed Tasks:\n{tasks_json}")
    ])
    
    
    # Get design spec for scope context
    spec = state.get("spec", {})
    spec_content = spec.get("content", "No design specification")[:2000]  # Truncate if too long
    objective = state.get("objective", "")
    
    structured_llm = llm.with_structured_output(IntegrationResponse)
    
    print("  Calling LLM for plan integration...", flush=True)
    # Get design spec for scope context
    spec = state.get("spec", {})
    spec_content = spec.get("content", "No design specification available")
    objective = state.get("objective", "")
    
    # [NEW] Get Existing Pending/Active Tasks for Context
    # We want the LLM to be aware of what's already running or planned so it can
    # 1. Avoid duplication
    # 2. Reorganize/Link new suggestions to the correct place in the tree
    existing_tasks = state.get("tasks", [])
    relevant_existing_tasks = []
    
    for t_dict in existing_tasks:
        # We only care about active process tasks to integrate with
        # We filter out COMPLETE/FAILED/ABANDONED/WAITING_HUMAN/AWAITING_QA (mostly)
        # Actually, AWAITING_QA tasks are effectively complete.
        status = t_dict.get("status")
        if status in [TaskStatus.ACTIVE, TaskStatus.PLANNED, TaskStatus.READY]:
            # Extract title from description if possible
            desc = t_dict.get("description", "")
            title = "Untitled"
            if "Title: " in desc:
                 title = desc.split("Title: ")[-1].strip()
            
            relevant_existing_tasks.append({
                "id": t_dict.get("id"),
                "title": title,
                "component": t_dict.get("component"),
                "phase": t_dict.get("phase"),
                "status": status,
                "description": desc,
                "depends_on": t_dict.get("depends_on", [])
            })

    print(f"  Including {len(relevant_existing_tasks)} active/pending tasks in integration context.", flush=True)

    prompt = ChatPromptTemplate.from_messages([
        ("system", """You are the Lead Architect integrating project plans.
        
        OBJECTIVE: {objective}
        
        DESIGN SPECIFICATION (THE SCOPE BOUNDARY):
        {spec_content}
        
        EXISTING ACTIVE/PENDING TASKS (THE RUNNING SYSTEM):
        {existing_tasks_json}
        
        INPUT: Proposed tasks from planners and workers.
        
        YOUR JOB - IN THIS EXACT ORDER:
        1. **Deduplicate & Merge**: 
           - Check if proprosed tasks already exist in "EXISTING TASKS".
           - unmatched proposed tasks should be added.
           - If a proposed task matches an EXISTING task, UPDATE it (keep ID if possible? No, you return a list, we match by title).
           - MERGE duplicate suggestions.
        
        2. **Validate Scope**: Check EACH task against the design specification.
           - REJECT tasks that are not in the spec (accessibility, CI/CD, extensive testing utilities, etc.)
           - APPROVE tasks that implement the spec
           - Be strict - only what's in the spec gets built
           
        3. **Integration & Reorganization**:
           - You MUST Output the FULL list of tasks that should be in the plan (Existing + New).
           - **CRITICAL**: You can (and should) REWIRE dependencies of EXISTING ACTIVE tasks if necessary to fix the tree.
           - Ensure proper `depends_on` using EXACT TITLES.
           
        4. **Dependency Rules**:
           - **Backend first**: Frontend MUST depend on backend API.
           - **Tests last**: ALL test tasks MUST depend on what they're testing.
           - **Integration tests**: MUST depend on BOTH frontend AND backend.
           - **No independent trees**: Every task must trace back to root (or other tasks).
           
        5. **Return**: Two lists:
           - `tasks`: The COMPLETE validated task list (Existing + New).
           - `rejected_tasks`: Out-of-scope tasks with reasons.
        
        CRITICAL RULES:
        - Design spec is LAW.
        - INCLUDE ALL RELEVANT EXISTING TASKS in your output list if they are still valid.
        - If an existing task is no longer valid, do NOT include it (effectively removing it, or we handle abandonment later).
        - **EVERY PROJECT MUST HAVE AT LEAST ONE TEST TASK**.
        """),
        ("user", "Proposed Tasks:\n{tasks_json}")
    ])
    
    structured_llm = llm.with_structured_output(IntegrationResponse)
    
    print("  Calling LLM for plan integration with scope validation...", flush=True)
    
    # LOG: Director integration request
    # Save the full request for debugging
    from pathlib import Path
    import json
    workspace_path = state.get("_workspace_path")
    if workspace_path:
        log_dir = Path(workspace_path) / ".llm_logs" / "director"
        log_dir.mkdir(parents=True, exist_ok=True)
        from datetime import datetime
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        request_log = log_dir / f"integration_request_{timestamp}.json"
        with open(request_log, 'w', encoding='utf-8') as f:
            json.dump({
                "timestamp": datetime.now().isoformat(),
                "objective": objective,
                "spec_content_length": len(spec_content),
                "tasks_input_count": len(tasks_input),
                "existing_tasks_count": len(relevant_existing_tasks),
                "tasks_input": tasks_input,
                "existing_tasks_input": relevant_existing_tasks
            }, f, indent=2)
        print(f"  [LOG] Director request: {request_log} ({len(tasks_input)} new + {len(relevant_existing_tasks)} existing)", flush=True)
    
    try:
        response = await structured_llm.ainvoke(prompt.format(
            objective=objective,
            spec_content=spec_content[:3000],  # Truncate if too long
            tasks_json=str(tasks_input),
            existing_tasks_json=str(relevant_existing_tasks)
        ), config={"callbacks": []})
        
        # LOG: Director integration response
        if workspace_path:
            response_log = log_dir / f"integration_response_{timestamp}.json"
            with open(response_log, 'w', encoding='utf-8') as f:
                json.dump({
                    "timestamp": datetime.now().isoformat(),
                    "tasks_returned": len(response.tasks) if hasattr(response, 'tasks') else 0,
                    "tasks_rejected": len(response.rejected_tasks) if hasattr(response, 'rejected_tasks') else 0,
                    "total_accounted": (len(response.tasks) if hasattr(response, 'tasks') else 0) + 
                                       (len(response.rejected_tasks) if hasattr(response, 'rejected_tasks') else 0),
                    "tasks_input_count": len(tasks_input),
                    "MISSING_COUNT": len(tasks_input) - 
                                     ((len(response.tasks) if hasattr(response, 'tasks') else 0) + 
                                      (len(response.rejected_tasks) if hasattr(response, 'rejected_tasks') else 0)),
                    "response_tasks": [{"title": t.title, "phase": t.phase, "depends_on": t.depends_on} 
                                       for t in response.tasks] if hasattr(response, 'tasks') else [],
                    "rejected_tasks": [{"title": t.title, "reason": t.reason} 
                                       for t in response.rejected_tasks] if hasattr(response, 'rejected_tasks') else []
                }, f, indent=2)
            print(f"  [LOG] Director response: {response_log}", flush=True)
            print(f"  [LOG] Input: {len(tasks_input)} tasks -> Output: {len(response.tasks)} approved + {len(response.rejected_tasks)} rejected", flush=True)
            missing = len(tasks_input) - (len(response.tasks) + len(response.rejected_tasks))
            if missing > 0:
                print(f"  [WARNING] {missing} tasks UNACCOUNTED FOR by LLM (deduplicated/merged)!", flush=True)
        
    except Exception as e:
        print(f"  Integration LLM Error: {e}", flush=True)
        # Fallback: Return tasks as-is (converted to Task objects)
        # This prevents the pipeline from crashing, though dependencies might be broken
        print("  Fallback: Converting suggestions directly without integration.", flush=True)
        fallback_tasks = []
        for s in suggestions:
            t_id = f"task_{uuid.uuid4().hex[:8]}"
            fallback_tasks.append(Task(
                id=t_id,
                component=s.get("component", "unknown"),
                phase=TaskPhase(s.get("phase", "build")),
                status=TaskStatus.PLANNED,
                assigned_worker_profile=WorkerProfile.CODER, # Default
                description=s.get("description", ""),
                depends_on=[], # Lost dependencies in fallback
                created_at=datetime.now(),
                updated_at=datetime.now()
            ))
        return fallback_tasks


    # Convert response to Task objects
    new_tasks = []
    title_to_id_map = {}
    
    # Handle rejected tasks - send feedback to source workers
    if hasattr(response, 'rejected_tasks') and response.rejected_tasks:
        print(f"  LLM rejected {len(response.rejected_tasks)} tasks as out of scope:", flush=True)
        for rejected in response.rejected_tasks:
            print(f"    ✗ {rejected.title}: {rejected.reason}", flush=True)
            
            # Find the source task that suggested this
            for suggestion in suggestions:
                if suggestion.get("title") == rejected.title or rejected.title in suggestion.get("description", ""):
                    source_id = suggestion.get("suggested_by_task")
                    if source_id:
                        feedback = SystemMessage(
                            content=f"DIRECTOR FEEDBACK (LLM Validation): Task suggestion '{rejected.title}' was rejected by the Lead Architect.\n\n"
                                    f"Reason: {rejected.reason}\n\n"
                                    f"The suggested task does not align with the design specification. "
                                    f"Please continue your work within the defined scope or provide stronger justification if this is truly required."
                        )
                        if "task_memories" not in state:
                            state["task_memories"] = {}
                        if source_id not in state["task_memories"]:
                            state["task_memories"][source_id] = []
                        state["task_memories"][source_id].append(feedback)
                    break
    
    # 0. Pre-populate map with EXISTING tasks (to allow linking to completed tasks)
    existing_tasks = state.get("tasks", [])
    for t in existing_tasks:
        t_desc = t.get("description", "")
        t_title = ""
        if "Title: " in t_desc:
            t_title = t_desc.split("Title: ")[-1].strip()
        else:
            t_title = t_desc.split("\n")[0].strip()
        
        if t_title:
            title_to_id_map[t_title.lower()] = t["id"]
    
    # 1. Create IDs and Map Titles for NEW tasks
    for t_def in response.tasks:
        # [NEW] Check if title already exists in map (case-insensitive)
        existing_id = title_to_id_map.get(t_def.title.lower())
        
        if existing_id:
            # Reuse existing ID to prevent duplication
            print(f"    Reusing ID {existing_id} for '{t_def.title}'", flush=True)
        else:
            # Generate new ID
            new_id = f"task_{uuid.uuid4().hex[:8]}"
            title_to_id_map[t_def.title.lower()] = new_id
        
    # 2. Create Task Objects with Resolved Dependencies
    for t_def in response.tasks:
        new_id = title_to_id_map[t_def.title.lower()]
        
        resolved_deps = []
        for dep in t_def.depends_on:
            dep_lower = dep.lower().strip()
            
            # Exact match (new or existing)
            if dep_lower in title_to_id_map:
                resolved_deps.append(title_to_id_map[dep_lower])
            else:
                # Fuzzy match
                best_match = None
                best_score = 0
                for known_title, known_id in title_to_id_map.items():
                    if dep_lower in known_title or known_title in dep_lower:
                        score = len(known_title)
                        if score > best_score:
                            best_score = score
                            best_match = known_id
                
                if best_match:
                    resolved_deps.append(best_match)
                else:
                    print(f"    Warning: Could not resolve dependency '{dep}' for '{t_def.title}'", flush=True)
        
        # Determine profile
        profile = WorkerProfile.CODER
        phase = TaskPhase.BUILD
        
        p_str = t_def.phase.lower()
        if p_str == "test": 
            phase = TaskPhase.TEST
            profile = WorkerProfile.TESTER
        elif p_str == "plan":
            phase = TaskPhase.PLAN
            profile = WorkerProfile.PLANNER
        
        new_task = Task(
            id=new_id,
            component=t_def.component,
            phase=phase,
            status=TaskStatus.PLANNED,
            assigned_worker_profile=profile,
            description=f"{t_def.description}\n\nTitle: {t_def.title}",
            acceptance_criteria=t_def.acceptance_criteria,
            depends_on=resolved_deps,
            created_at=datetime.now(),
            updated_at=datetime.now()
        )
        new_tasks.append(new_task)
        
    print(f"  Integrated {len(new_tasks)} tasks into the graph.", flush=True)
    return new_tasks
