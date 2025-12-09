"""
Director Module - Task Readiness Evaluation
===========================================
Evaluates whether tasks are ready to execute based on dependencies.
"""

import logging
from typing import List
from orchestrator_types import Task, TaskStatus

logger = logging.getLogger(__name__)


def evaluate_readiness(task: Task, all_tasks: List[Task]) -> TaskStatus:
    """
    Check if task dependencies are met and task is ready to execute.

    Args:
        task: Task to evaluate
        all_tasks: Complete list of tasks for dependency lookup

    Returns:
        TaskStatus indicating readiness (READY, PLANNED, BLOCKED, or current status)
    """
    if task.status != TaskStatus.PLANNED:
        return task.status

    # Check all dependencies are complete
    for dep_id in task.depends_on:
        dep = next((t for t in all_tasks if t.id == dep_id), None)

        # Safety check for abandoned dependencies
        if dep and dep.status == TaskStatus.ABANDONED:
            logger.warning(f"Task {task.id} BLOCKED: Dependency {dep_id} was ABANDONED")
            return TaskStatus.BLOCKED

        if not dep:
            # Dependency not found yet (may be created later)
            return TaskStatus.PLANNED

        if dep.status != TaskStatus.COMPLETE:
            # Dependency not yet complete
            return TaskStatus.PLANNED

    # All dependencies met
    return TaskStatus.READY
