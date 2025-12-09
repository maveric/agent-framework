"""
Director Module - Human-in-the-Loop Resolution
==============================================
Handles human intervention and resolution of stuck tasks.
"""

import logging
import uuid
from datetime import datetime
from typing import Any, Dict, List
from orchestrator_types import Task, TaskStatus, TaskPhase, WorkerProfile, task_to_dict, _dict_to_task
from state import OrchestratorState

logger = logging.getLogger(__name__)


def process_human_resolution(state: OrchestratorState, resolution: dict) -> Dict[str, Any]:
    """
    Process human resolution after interrupt resume.

    Called when graph resumes with Command(resume=resolution_data).
    Handles three actions: retry, spawn_new_task, abandon.

    Args:
        state: Current orchestrator state
        resolution: Human resolution data containing action and modifications

    Returns:
        State updates to apply (tasks, replan_requested, etc.)
    """
    tasks = [_dict_to_task(t) for t in state.get("tasks", [])]

    task_id = resolution.get("task_id")
    task = next((t for t in tasks if t.id == task_id), None)

    if not task:
        logger.error(f"Task {task_id} not found for resolution")
        return {"tasks": [task_to_dict(t) for t in tasks], "_interrupt_data": None}

    action = resolution.get("action")

    if action == "retry":
        logger.info(f"Human approved retry for task {task.id}")

        # Reset task for retry
        task.status = TaskStatus.PLANNED
        task.retry_count = 0
        task.updated_at = datetime.now()

        # Apply optional modifications
        if resolution.get("modified_description"):
            task.description = resolution["modified_description"]
            logger.info(f"Applied modified description to task {task.id}")

        if resolution.get("modified_criteria"):
            task.acceptance_criteria = resolution["modified_criteria"]
            logger.info(f"Applied modified criteria to task {task.id}")

        # Update this task in place
        for i, t in enumerate(tasks):
            if t.id == task_id:
                tasks[i] = task
                break

    elif action == "spawn_new_task":
        logger.info(f"Human requested new task to replace {task.id}")

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
        new_phase_str = resolution.get("new_phase") or (task.phase.value if task.phase else "build")
        new_title = f"{new_component} {new_phase_str} Task".title()

        # Validate required fields
        new_description = resolution.get("new_description")
        if not new_description:
            logger.error("HITL resolution missing required field: new_description")
            return {"tasks": [task_to_dict(t) for t in tasks], "pending_resolution": None}

        # Validate phase is valid
        valid_phases = ["build", "test", "plan"]
        if new_phase_str not in valid_phases:
            logger.warning(f"Invalid phase '{new_phase_str}'. Must be one of: {valid_phases}. Defaulting to 'build'")
            new_phase_str = "build"

        if "Title: " not in new_description:
            new_description += f"\n\nTitle: {new_title}"

        # Get worker profile with validation
        new_worker_profile_str = resolution.get("new_worker_profile") or (
            task.assigned_worker_profile.value if task.assigned_worker_profile else "code_worker"
        )

        new_task = Task(
            id=f"task_{uuid.uuid4().hex[:8]}",
            component=new_component,
            phase=TaskPhase(new_phase_str),
            status=TaskStatus.PLANNED,
            assigned_worker_profile=WorkerProfile(new_worker_profile_str),
            description=new_description,
            acceptance_criteria=resolution.get("new_criteria", task.acceptance_criteria),
            depends_on=resolution.get("new_dependencies", []),
            created_at=datetime.now(),
            updated_at=datetime.now(),
            retry_count=0
        )

        tasks.append(new_task)
        logger.info(f"Created new task: {new_task.id} ({new_title})")

        # Dependency Re-linking
        # Find tasks that depended on the OLD task and point them to the NEW task
        relinked_count = 0
        for t in tasks:
            if t.id != new_task.id and t.id != task_id:  # Don't update self or abandoned task
                if task_id in t.depends_on:
                    t.depends_on.remove(task_id)
                    t.depends_on.append(new_task.id)
                    t.updated_at = datetime.now()
                    relinked_count += 1
                    logger.info(f"Relinked dependency: {t.id} now depends on {new_task.id} (was {task_id})")

        if relinked_count > 0:
            logger.info(f"Auto-relinked {relinked_count} tasks to the new task")

        # Trigger Replan to ensure graph integrity
        logger.info("Triggering smart replan to integrate new task")
        return {"tasks": [task_to_dict(t) for t in tasks], "replan_requested": True, "_interrupt_data": None}

    elif action == "abandon":
        logger.info(f"Human abandoned task {task.id}")
        task.status = TaskStatus.ABANDONED
        task.updated_at = datetime.now()

        # Update this task
        for i, t in enumerate(tasks):
            if t.id == task_id:
                tasks[i] = task
                break

        # Trigger replan so director can handle dependent tasks
        logger.info("Triggering replan to handle abandoned task")
        return {"tasks": [task_to_dict(t) for t in tasks], "replan_requested": True, "_interrupt_data": None}

    else:
        logger.error(f"Unknown action '{action}'")

    # Clear persisted interrupt data to prevent stale data on next interrupt
    result = {"tasks": [task_to_dict(t) for t in tasks]}
    result["_interrupt_data"] = None
    return result
