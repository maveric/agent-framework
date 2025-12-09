"""
Director Module - Graph Utilities
==================================
Graph algorithms for task dependency management.
"""

import logging
from typing import List
from orchestrator_types import Task

logger = logging.getLogger(__name__)


def detect_and_break_cycles(tasks: List[Task]) -> int:
    """
    Detect circular dependencies in the task graph and break them.
    Uses DFS-based cycle detection.

    Args:
        tasks: List of tasks to check for cycles

    Returns:
        Number of cycles broken
    """
    # Build adjacency map: task_id -> list of dependency IDs
    task_by_id = {t.id: t for t in tasks}

    # Track visited nodes and recursion stack for DFS
    WHITE, GRAY, BLACK = 0, 1, 2  # unvisited, in-progress, done
    color = {t.id: WHITE for t in tasks}
    cycles_broken = 0

    def dfs(task_id: str, path: List[str]) -> bool:
        """DFS that returns True if a cycle was found and broken."""
        nonlocal cycles_broken

        if task_id not in task_by_id:
            return False  # Dependency on external/completed task

        if color[task_id] == GRAY:
            # Found a cycle! The path contains the cycle
            cycle_start_idx = path.index(task_id)
            cycle = path[cycle_start_idx:]
            logger.warning(f"Cycle detected: {' → '.join(cycle)} → {task_id}")

            # Break the cycle by removing the last dependency that created it
            # (remove task_id from the depends_on of the task that pointed to it)
            if len(path) > 0:
                parent_id = path[-1]
                if parent_id in task_by_id:
                    parent_task = task_by_id[parent_id]
                    if task_id in parent_task.depends_on:
                        parent_task.depends_on.remove(task_id)
                        logger.info(f"Broke cycle by removing {task_id} from {parent_id}'s depends_on")
                        cycles_broken += 1
            return True

        if color[task_id] == BLACK:
            return False  # Already fully processed

        color[task_id] = GRAY
        task = task_by_id[task_id]

        for dep_id in list(task.depends_on):  # list() to allow modification
            if dfs(dep_id, path + [task_id]):
                # A cycle was broken, need to restart (graph structure changed)
                return True

        color[task_id] = BLACK
        return False

    # Run DFS from each unvisited node, restart if cycle broken
    max_iterations = len(tasks) * 2  # Safety limit
    iteration = 0

    while iteration < max_iterations:
        iteration += 1
        cycle_found = False

        # Reset colors for new pass
        color = {t.id: WHITE for t in tasks}

        for task in tasks:
            if color[task.id] == WHITE:
                if dfs(task.id, []):
                    cycle_found = True
                    break  # Restart DFS after breaking cycle

        if not cycle_found:
            break  # No more cycles

    return cycles_broken
