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

    # ==========================================================================
    # PHASE 0: STATE PROMOTION (Director is the sole authority for transitions)
    # ==========================================================================
    # Workers and Strategist set PENDING states. Director confirms them here.
    # This eliminates race conditions by making all transitions synchronous.
    pending_promotions = {
        "pending_awaiting_qa": TaskStatus.AWAITING_QA,
        "pending_complete": TaskStatus.COMPLETE,
        "pending_failed": TaskStatus.FAILED,
    }
    
    for task in all_tasks:
        current_status = task.status.value if hasattr(task.status, 'value') else str(task.status)
        if current_status in pending_promotions:
            new_status = pending_promotions[current_status]
            logger.info(f"  📤 Promoting {task.id[:12]}: {current_status} → {new_status.value}")
            task.status = new_status
            task.updated_at = datetime.now()
            updates.append(task_to_dict(task))

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
        # User says dependency tree is wrong - ask LLM to rebuild depends_on relationships
        logger.info("Director: Manual replan requested. Rebuilding dependency tree")

        # Gather all incomplete tasks (PLANNED, READY, ACTIVE)
        incomplete_statuses = {TaskStatus.PLANNED, TaskStatus.READY, TaskStatus.ACTIVE}
        incomplete_tasks = [t for t in all_tasks if t.status in incomplete_statuses]

        if incomplete_tasks:
            logger.info(f"  Rebuilding dependencies for {len(incomplete_tasks)} incomplete tasks")
            
            # Build a simple prompt for dependency rebuilding
            from llm_client import get_llm
            from config import OrchestratorConfig
            
            # Get config - try state first, fall back to default
            orch_config = state.get("orch_config")
            if not orch_config:
                orch_config = OrchestratorConfig()
            
            llm = get_llm(orch_config.director_model)
            
            task_summaries = []
            for t in incomplete_tasks:
                task_summaries.append(f"- {t.id}: {t.description[:100]}")
            
            prompt = f"""Given these incomplete tasks, determine their dependencies.
Each task should depend on tasks that must complete BEFORE it can start.

CRITICAL: Maximize parallelism while respecting necessary ordering.
- Tasks that CAN run in parallel SHOULD (e.g., frontend + backend simultaneously)
- Only add dependencies where there's a real blocker (e.g., API depends on database models)
- Create proper layering: foundation tasks → mid-level tasks → integration tasks
- Avoid unnecessary dependencies that would force serial execution

Tasks:
{chr(10).join(task_summaries)}

Return ONLY a JSON object mapping task_id -> list of dependency task_ids:
{{"task_xxx": ["task_yyy", "task_zzz"], ...}}

Keep dependencies minimal - only include direct blockers, not transitive dependencies.
Tasks with no dependencies should map to empty array: {{"task_xxx": []}}
"""
            
            try:
                response = await llm.ainvoke(prompt)
                import json
                # Parse JSON from response
                content = str(response.content)
                # Try to extract JSON from markdown code blocks
                if "```json" in content:
                    content = content.split("```json")[1].split("```")[0].strip()
                elif "```" in content:
                    content = content.split("```")[1].split("```")[0].strip()
                
                dependency_map = json.loads(content)

                # CRITICAL: Reset ALL incomplete tasks to PLANNED first
                # This ensures evaluate_readiness actually checks their dependencies
                logger.info(f"  Resetting {len(incomplete_tasks)} tasks to PLANNED status")
                updated_task_ids = set()
                for task in incomplete_tasks:
                    if task.status in {TaskStatus.READY, TaskStatus.ACTIVE}:
                        old_status = task.status
                        task.status = TaskStatus.PLANNED
                        task.updated_at = datetime.now()
                        updated_task_ids.add(task.id)  # Mark as updated
                        logger.info(f"  Task {task.id[:12]} reset: {old_status.value} → PLANNED")

                # Update tasks with new dependencies
                for task in incomplete_tasks:
                    if task.id in dependency_map:
                        new_deps = dependency_map[task.id]
                        if new_deps != task.depends_on:
                            task.depends_on = new_deps
                            task.updated_at = datetime.now()
                            updated_task_ids.add(task.id)
                            logger.info(f"  Task {task.id[:12]} dependencies updated: {len(new_deps)} deps")

                # Now re-evaluate readiness for ALL incomplete tasks
                # (they're all PLANNED now, so evaluate_readiness will actually check dependencies)
                logger.info(f"  Re-evaluating readiness after dependency changes...")
                for task in incomplete_tasks:
                    old_status = task.status
                    new_status = evaluate_readiness(task, all_tasks)

                    if new_status != old_status:
                        task.status = new_status
                        task.updated_at = datetime.now()
                        updated_task_ids.add(task.id)
                        logger.info(f"  Task {task.id[:12]} status: {old_status.value} → {new_status.value}")

                # Add all updated tasks to updates
                for task in incomplete_tasks:
                    if task.id in updated_task_ids:
                        updates.append(task_to_dict(task))

                logger.info(f"  ✅ Dependency tree rebuilt: {len(updated_task_ids)} tasks updated")
            except Exception as e:
                logger.error(f"Director Error: Dependency rebuild failed: {e}")
                import traceback
                traceback.print_exc()
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

    # Check if all tasks are truly terminal (complete/abandoned only)
    # waiting_human and awaiting_qa require action - NOT terminal!
    all_terminal = all(
        t.status in [TaskStatus.COMPLETE, TaskStatus.ABANDONED]
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
