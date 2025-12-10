"""
Agent Orchestrator — Worker Node
================================
Version 1.0 — November 2025

Worker execution node with specialized handlers.
"""

import logging
from typing import Any, Dict, Callable
from datetime import datetime

from langchain_core.runnables import RunnableConfig

from state import OrchestratorState
from orchestrator_types import (
    Task, WorkerProfile, WorkerResult, AAR,
    _dict_to_task, _aar_to_dict
)

# Import from extracted modules
from .handlers import (
    _code_handler,
    _plan_handler,
    _test_handler,
    _research_handler,
    _write_handler
)

logger = logging.getLogger(__name__)


async def worker_node(state: Dict[str, Any], config: RunnableConfig = None) -> Dict[str, Any]:
    """
    Worker: Execute task based on profile (async version).
    """
    logger.info(f"DEBUG: worker_node state keys: {list(state.keys())}")
    logger.info(f"DEBUG: worker_node _workspace_path: {state.get('_workspace_path')}")
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

    # Create/get worktree for this task
    wt_manager = state.get("_wt_manager")
    worktree_path = None
    recovery_context = None  # Will contain info about recovered dirty worktree

    if wt_manager and not state.get("mock_mode", False):
        try:
            wt_info = wt_manager.create_worktree(task_id)
            worktree_path = wt_info.worktree_path
            logger.info(f"  Created worktree: {worktree_path}")

            # IMPORTANT: Check for and recover any dirty worktree state
            # This handles restarts/retries where previous agent left uncommitted changes
            recovery_result = wt_manager.recover_dirty_worktree(task_id)
            if recovery_result and recovery_result.get("had_changes"):
                recovery_context = recovery_result.get("summary", "")
                logger.info(f"  [RECOVERY] Found prior uncommitted work, see context below")
        except Exception as e:
            logger.warning(f"  Warning: Failed to create worktree: {e}")
            worktree_path = state.get("_workspace_path")
    else:
        worktree_path = state.get("_workspace_path")

    # Inject worktree path and recovery context into state for handlers
    state["worktree_path"] = worktree_path
    state["_recovery_context"] = recovery_context  # Handlers will inject this into prompts
    logger.info(f"DEBUG: worker_node set state['worktree_path']={state.get('worktree_path')}")

    # Execute handler
    logger.info(f"Worker ({profile.value}): Starting task {task_id}")

    # PERF: Calculate task execution time
    # Use started_at from task if available (when it became ACTIVE), otherwise measure from now
    import time

    if hasattr(task, 'started_at') and task.started_at:
        # Calculate from when task became ACTIVE
        task_start_time = task.started_at.timestamp()
    else:
        # Fallback: measure from worker entry (less accurate)
        task_start_time = time.time()

    try:
        result = await handler(task, state, config)

        # PERF: Log execution time from ACTIVE status
        task_duration = time.time() - task_start_time
        logger.info(f"  ⏱️  Task {task_id[:8]} ({profile.value}) completed in {task_duration:.1f}s (active time)")

    except Exception as e:
        task_duration = time.time() - task_start_time
        logger.error(f"  ⏱️  Task {task_id[:8]} ({profile.value}) FAILED after {task_duration:.1f}s (active time)")
        import traceback
        error_details = traceback.format_exc()
        logger.error(f"Worker Error Details:")
        logger.error(error_details)
        # Return failed result
        result = WorkerResult(
            status="failed",
            result_path="",
            aar=AAR(summary=f"Error: {str(e)[:200]}", approach="failed", challenges=[], decisions_made=[], files_modified=[])
        )

    # Commit changes if task completed successfully
    if result.status == "complete" and result.aar and result.aar.files_modified:
        if wt_manager and not state.get("mock_mode", False):
            try:
                # CRITICAL: Commit ALL changes in the worktree to prevent "MERGE BLOCKED" errors
                # If our file detection misses anything, we still commit it
                commit_msg = f"[{task_id}] {task.phase.value if hasattr(task, 'phase') else 'work'}: {result.aar.summary[:50]}"
                # Pass None to commit_changes to stage ALL files (git add -A)
                commit_hash = wt_manager.commit_changes(
                    task_id,
                    commit_msg,
                    None  # Commit all changes, not just detected files
                )
                if commit_hash:
                    logger.info(f"  Committed: {commit_hash[:8]}")

                    # Merge to main immediately for now to allow subsequent tasks to see changes
                    # In a full flow, this might be gated by QA, but for linear dependencies we need it.
                    try:
                        logger.info(f"  [DEBUG] Calling merge_to_main for {task_id}...")
                        merge_result = await wt_manager.merge_to_main(task_id)
                        if merge_result.success:
                            logger.info(f"  Merged to main")
                        else:
                            # Merge failed - this should trigger Phoenix retry
                            logger.error(f"  ❌ Merge failed: {merge_result.error_message}")
                            # Override the result to failed status
                            result = WorkerResult(
                                status="failed",
                                result_path=result.result_path,
                                aar=AAR(
                                    summary=f"Merge failed: {merge_result.error_message[:200]}",
                                    approach=result.aar.approach if result.aar else "unknown",
                                    challenges=[merge_result.error_message] if result.aar else [],
                                    decisions_made=result.aar.decisions_made if result.aar else [],
                                    files_modified=result.aar.files_modified if result.aar else []
                                ),
                                messages=result.messages if hasattr(result, 'messages') else []
                            )
                    except Exception as e:
                        logger.error(f"  ❌ Merge exception: {e}")
                        import traceback
                        traceback.print_exc()
                        # Override to failed
                        result = WorkerResult(
                            status="failed",
                            result_path="",
                            aar=AAR(
                                summary=f"Merge exception: {str(e)[:200]}",
                                approach="failed",
                                challenges=[str(e)],
                                decisions_made=[],
                                files_modified=[]
                            )
                        )

            except Exception as e:
                logger.warning(f"  Warning: Failed to commit: {e}")

    # CRITICAL: Create a COPY of the task dict for returning updates
    # DO NOT modify state["tasks"] directly - dispatch is the sole place that applies changes
    # This ensures task_memories and task updates are applied atomically
    import copy
    updated_task = copy.deepcopy(task_dict)
    
    # Apply result to the COPY, not the original
    updated_task["status"] = "pending_awaiting_qa" if result.status == "complete" else "pending_failed"
    updated_task["result_path"] = result.result_path
    updated_task["aar"] = _aar_to_dict(result.aar) if result.aar else None

    # Pass suggested tasks to state (for Director to process)
    if result.suggested_tasks:
        from orchestrator_types import _suggested_task_to_dict
        updated_task["suggested_tasks"] = [_suggested_task_to_dict(st) for st in result.suggested_tasks]

    updated_task["updated_at"] = datetime.now().isoformat()

    # Return the updated task copy AND task_memories (logs)
    # Dispatch Phase 1 will merge BOTH atomically
    updates = {"tasks": [updated_task]}

    # If the result has messages (from the agent execution), pass them back
    # The state key is "task_memories" which is a dict mapping task_id -> list of messages
    if hasattr(result, "messages") and result.messages:
        updates["task_memories"] = {task_id: result.messages}
        logger.info(f"  [DEBUG task_memories] Worker returning {len(result.messages)} messages for {task_id[:12]}")
    elif hasattr(result, "aar") and result.aar and hasattr(result.aar, "messages"):
        # Fallback if messages are attached to AAR (unlikely but possible in some flows)
        updates["task_memories"] = {task_id: result.aar.messages}
        logger.info(f"  [DEBUG task_memories] Worker returning {len(result.aar.messages)} messages (from AAR) for {task_id[:12]}")
    else:
        logger.info(f"  [DEBUG task_memories] Worker has NO messages for {task_id[:12]} (result.messages={hasattr(result, 'messages')} / len={len(result.messages) if hasattr(result, 'messages') and result.messages else 0})")

    return updates


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
