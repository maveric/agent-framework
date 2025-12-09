"""
Agent Orchestrator — Director Node
==================================
Version 2.0 — December 2025

Director node for task management and orchestration.

REFACTORED: Extracted helper functions into focused modules:
- director/decomposition.py - Objective breakdown & spec creation
- director/integration.py - Plan merging & dependency resolution
- director/readiness.py - Task readiness evaluation
- director/hitl.py - Human-in-the-loop resolution
- director/graph_utils.py - Cycle detection
"""

import logging
from typing import Any, Dict, List
from datetime import datetime
from state import OrchestratorState
from orchestrator_types import (
    Task, TaskStatus, TaskPhase, WorkerProfile,
    _dict_to_task, task_to_dict
)
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from langchain_core.runnables import RunnableConfig
from langgraph.types import interrupt
import uuid

# Import extracted functions from director package
from .director import (
    mock_decompose,
    decompose_objective,
    integrate_plans,
    evaluate_readiness,
    process_human_resolution,
    detect_and_break_cycles
)

logger = logging.getLogger(__name__)


async def director_node(state: OrchestratorState, config: RunnableConfig = None) -> Dict[str, Any]:
    """
    Director: Task decomposition and readiness evaluation (async version).

    Core responsibilities:
    - Initial objective decomposition into tasks
    - Task readiness evaluation (dependency checking)
    - Phoenix retry protocol for failed tasks
    - Human-in-the-loop intervention handling
    - Plan integration from multiple planners
    """
    tasks = state.get("tasks", [])

    # HITL: Check if we're resuming from an interrupt
    # When Command(resume=value) is called, LangGraph restarts the node from the beginning
    # and passes the resume value which becomes the return value of interrupt()
    if config and config.get("configurable", {}).get("__pregel_resuming"):
        resume_value = config.get("configurable", {}).get("__pregel_resume")
        if resume_value:
            logger.info("Director: Resuming from interrupt, processing human resolution")
            return process_human_resolution(state, resume_value)

    # MANUAL INTERRUPT: Check if there's a pending resolution in state
    # This handles manual interrupts where Command(resume=...) doesn't work
    pending_resolution = state.get("pending_resolution")
    if pending_resolution:
        logger.info("Director: Found pending resolution from manual interrupt, processing")
        # Clear the pending resolution and process it
        result = process_human_resolution(state, pending_resolution)
        # Add clearing of pending_resolution to the result
        result["pending_resolution"] = None
        return result

    # Get configuration
    mock_mode = state.get("mock_mode", False)
    if not mock_mode and config and "configurable" in config:
        mock_mode = config["configurable"].get("mock_mode", False)

    # Initial decomposition if no tasks exist
    if not tasks:
        logger.info("Director: Initial decomposition")
        objective = state.get("objective", "")

        if mock_mode:
            new_tasks = mock_decompose(objective)
        else:
            new_tasks = await decompose_objective(objective, state.get("spec", {}), state)
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
        logger.info("="*60)
        logger.info("📊 BATCH STATUS SUMMARY")
        logger.info("="*60)
        logger.info(f"  ✅ Complete/QA: {completed_count}")
        logger.info(f"  🔄 Active:      {active_count}")
        logger.info(f"  📋 Ready:       {ready_count}")
        logger.info(f"  ⏳ Pending:     {blocked_count}")
        logger.info(f"  ❌ Failed:      {failed_count}")

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
                    logger.info(f"  {status_icon} {task_id} ({phase}): {duration:.1f}s")
                except:
                    logger.info(f"  {status_icon} {task_id} ({phase})")
            else:
                logger.info(f"  {status_icon} {task_id} ({phase})")
        logger.info("="*60)

    MAX_RETRIES = 4  # Maximum number of retries before giving up

    for task in all_tasks:
        # Phoenix recovery: Retry failed tasks
        if task.status == TaskStatus.FAILED:
            retry_count = task.retry_count if task.retry_count is not None else 0

            if retry_count < MAX_RETRIES:
                logger.info(f"Phoenix: Retrying task {task.id} (attempt {retry_count + 1}/{MAX_RETRIES})")

                # SPECIAL HANDLING: If TEST task failed QA, check if it's a code issue or test worker error
                if task.phase == TaskPhase.TEST and task.qa_verdict and not task.qa_verdict.passed:
                    feedback = task.qa_verdict.overall_feedback

                    # Detect if this is a TEST WORKER ERROR (missing test results file)
                    # vs an actual TEST EXECUTION FAILURE (code bugs found)
                    is_test_worker_error = "MISSING TEST RESULTS FILE" in feedback

                    if is_test_worker_error:
                        # TEST WORKER ERROR: Just retry the TEST task itself
                        logger.info("  QA Failure: Test worker error (missing results file). Retrying TEST task")
                        task.status = TaskStatus.PLANNED
                        task.retry_count = retry_count + 1
                        task.updated_at = datetime.now()

                        # Append feedback to description so test worker sees it on retry
                        if "MISSING TEST RESULTS FILE" not in task.description:
                            task.description += f"\n\nPREVIOUS FAILURE: {feedback}"

                        # Immediately evaluate readiness for instant retry
                        new_status = evaluate_readiness(task, all_tasks)
                        if new_status == TaskStatus.READY:
                            logger.info(f"  Phoenix: Task {task.id} immediately READY for retry")
                            task.status = new_status

                        updates.append(task_to_dict(task))
                    else:
                        # ACTUAL TEST EXECUTION FAILURE: Spawn a BUILD task to fix code issues
                        logger.info("  QA Failure: Test execution failed. Spawning fix task")
                        logger.info(f"  Feedback: {feedback[:100]}...")

                        # Create a new BUILD task to fix the issues
                        fix_task_id = f"task_{uuid.uuid4().hex[:8]}"
                        fix_task = Task(
                            id=fix_task_id,
                            component=task.component,
                            phase=TaskPhase.BUILD,
                            status=TaskStatus.PLANNED,
                            assigned_worker_profile=WorkerProfile.CODER,
                            description=f"Fix issues in {task.component} reported by QA.\n\nQA FEEDBACK (MUST ADDRESS):\n{feedback}",
                            acceptance_criteria=[
                                "Address all QA feedback points",
                                "Ensure code compiles/runs",
                                "Verify fix before re-testing"
                            ],
                            depends_on=task.depends_on.copy(),
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
                        task.status = evaluate_readiness(task, all_tasks)

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
                        logger.info(f"  Previous failure: {failure_reason[:100]}")
                        # Append to description if not already there to avoid duplication
                        if "PREVIOUS FAILURE:" not in task.description and "QA FEEDBACK:" not in task.description:
                             task.description += f"\n\n{failure_reason}"

                    # Immediately evaluate readiness for instant retry
                    new_status = evaluate_readiness(task, all_tasks)
                    if new_status == TaskStatus.READY:
                        logger.info(f"  Phoenix: Task {task.id} immediately READY for retry")
                        task.status = new_status

                    updates.append(task_to_dict(task))
            else:
                # HUMAN-IN-THE-LOOP: Request intervention for max retry exceeded
                logger.warning(f"Phoenix: Task {task.id} exceeded max retries ({MAX_RETRIES}), requesting human intervention")

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
                try:
                    resolution = interrupt(interrupt_data)

                    if resolution:
                        logger.info(f"Director: Resumed with resolution: {resolution}")
                        return process_human_resolution(state, resolution)
                except RuntimeError as e:
                    if "outside of a runnable context" in str(e):
                        logger.info("  (Running outside LangGraph - task paused with WAITING_HUMAN status)")
                    else:
                        raise

                continue

        # Standard readiness evaluation for planned tasks
        elif task.status == TaskStatus.PLANNED:
            new_status = evaluate_readiness(task, all_tasks)
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
    planner_tasks = [t for t in all_tasks if t.assigned_worker_profile == WorkerProfile.PLANNER]
    active_planners = [t for t in planner_tasks if t.status not in [TaskStatus.COMPLETE, TaskStatus.FAILED, TaskStatus.AWAITING_QA]]

    # Only print waiting message when count changes
    prev_active_planners = state.get("_prev_active_planners", -1)

    if active_planners:
        if len(active_planners) != prev_active_planners:
            logger.info(f"Director: Waiting for {len(active_planners)} planners to complete before integrating plans")
    elif replan_requested:
        # MANUAL REPLAN TRIGGER
        logger.info("Director: Manual replan requested. Re-integrating pending tasks")

        # Gather all pending tasks (PLANNED)
        pending_tasks = [t for t in all_tasks if t.status == TaskStatus.PLANNED]

        if pending_tasks:
            # Convert to dicts for the integrator
            suggestions = [task_to_dict(t) for t in pending_tasks]

            try:
                # Re-run integration
                new_tasks = await integrate_plans(suggestions, state)
                updates.extend([task_to_dict(t) for t in new_tasks])
            except Exception as e:
                logger.error(f"Director Error: Replan failed: {e}")
    else:
        # 2. Collect suggestions from ALL completed/failed tasks
        all_suggestions = []
        tasks_with_suggestions = []

        for task in all_tasks:
            if task.status in [TaskStatus.COMPLETE, TaskStatus.FAILED, TaskStatus.AWAITING_QA]:
                raw_task = next((t for t in tasks if t["id"] == task.id), None)
                if raw_task and raw_task.get("suggested_tasks"):
                    all_suggestions.extend(raw_task["suggested_tasks"])
                    tasks_with_suggestions.append(raw_task)

        if all_suggestions:
            logger.info(f"Director: Integrating {len(all_suggestions)} task suggestions")

            try:
                new_tasks = await integrate_plans(all_suggestions, state)
                updates.extend([task_to_dict(t) for t in new_tasks])

                # Clear suggestions so we don't re-process
                for raw_t in tasks_with_suggestions:
                    raw_t["suggested_tasks"] = []
                    updates.append(raw_t)
            except Exception as e:
                logger.error(f"Director Error: Integration failed: {e}")
                import traceback
                traceback.print_exc()

    # Capture Director logs
    director_messages = []

    # PENDING REORG: Block new task starts, wait for active tasks, then reorg
    pending_reorg = state.get("pending_reorg", False)
    if pending_reorg:
        active_tasks = [t for t in all_tasks if t.status == TaskStatus.ACTIVE]

        if active_tasks:
            logger.info(f"Director: Reorg pending. Waiting on {len(active_tasks)} active tasks to finish")
            return {"pending_reorg": True}
        else:
            # All active tasks done - execute reorg NOW
            logger.info("Director: All tasks complete. Executing reorg now")

            # Gather all PLANNED tasks for reorganization
            planned_tasks = [t for t in all_tasks if t.status == TaskStatus.PLANNED]

            if planned_tasks:
                suggestions = [task_to_dict(t) for t in planned_tasks]
                try:
                    new_tasks = await integrate_plans(suggestions, state)
                    updates.extend([task_to_dict(t) for t in new_tasks])
                    logger.info(f"Director: Reorganized {len(new_tasks)} tasks")
                except Exception as e:
                    logger.error(f"Director Error: Reorg failed: {e}")
                    import traceback
                    traceback.print_exc()

            # Clear the flag - reorg complete
            result = {"tasks": updates, "pending_reorg": False} if updates else {"pending_reorg": False}
            if director_messages:
                result["task_memories"] = {"director": director_messages}
            return result

    # Check if all tasks are in terminal states (complete/abandoned/waiting_human)
    all_terminal = all(
        t.status in [TaskStatus.COMPLETE, TaskStatus.ABANDONED, TaskStatus.WAITING_HUMAN]
        for t in all_tasks
    )

    # Initialize result dict
    result = {}

    if all_terminal and all_tasks:
        logger.info("Director: All tasks in terminal states - marking run as COMPLETE")
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
        result["task_memories"] = {"director": director_messages}

    return result
