"""
Runs API Routes
===============
FastAPI routes for managing orchestrator runs.
"""

import asyncio
import logging
import uuid
from datetime import datetime
from typing import List

from fastapi import APIRouter, HTTPException, BackgroundTasks, Query, Request
from pathlib import Path
from slowapi import Limiter
from slowapi.util import get_remote_address

# Import API modules
from api.types import CreateRunRequest, RunSummary, HumanResolution, PaginatedResponse
from api.state import runs_index, running_tasks, run_states, get_orchestrator_graph, manager, global_checkpointer
from api.dispatch import run_orchestrator, continuous_dispatch_loop

# Import orchestrator types
from orchestrator_types import task_to_dict, serialize_messages, TaskStatus
from git_manager import AsyncWorktreeManager as WorktreeManager

logger = logging.getLogger(__name__)

# Create router with prefix and tags
router = APIRouter(prefix="/api/v1/runs", tags=["runs"])

# Rate limiter
limiter = Limiter(key_func=get_remote_address)


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

async def ensure_run_in_index(run_id: str) -> bool:
    """
    Ensure run is in runs_index by looking it up in database if needed.

    This allows API endpoints to work with CLI-initiated runs that aren't
    in the in-memory runs_index.

    Returns:
        True if run found (already in index or added from DB), False if not found.
    """
    # Already in index
    if run_id in runs_index:
        logger.debug(f"Run {run_id} already in index")
        return True

    # Try to find in database
    logger.info(f"🔍 Looking up run {run_id} in database (CLI-initiated run?)")
    try:
        get_orchestrator_graph()

        # Get async connection from checkpointer
        conn = global_checkpointer.conn
        cursor = await conn.cursor()
        await cursor.execute("SELECT DISTINCT thread_id FROM checkpoints")
        rows = await cursor.fetchall()
        thread_ids = [row[0] for row in rows]
        logger.info(f"   Found {len(thread_ids)} thread(s) in database")

        for thread_id in thread_ids:
            config = {"configurable": {"thread_id": thread_id}}
            state_snapshot = await global_checkpointer.aget(config)

            if state_snapshot and "channel_values" in state_snapshot:
                state = state_snapshot["channel_values"]
                found_run_id = state.get("run_id", thread_id)

                if found_run_id == run_id:
                    # Found it! Add to index
                    runs_index[run_id] = {
                        "run_id": run_id,
                        "thread_id": thread_id,
                        "objective": state.get("objective", ""),
                        "status": "running",
                        "created_at": state.get("created_at", ""),
                        "updated_at": state.get("updated_at", ""),
                        "task_counts": {},
                        "tags": state.get("tags", [])
                    }
                    logger.info(f"✅ Found and added run {run_id} (thread: {thread_id})")
                    return True

        logger.warning(f"❌ Run {run_id} not found in database")
        return False

    except Exception as e:
        logger.error(f"Error looking up run in database: {e}")
        return False


def _serialize_orch_config(config):
    """Serialize OrchestratorConfig to dict for API response."""
    if not config:
        return None

    try:
        return {
            "director_model": {
                "provider": config.director_model.provider,
                "model_name": config.director_model.model_name,
                "temperature": config.director_model.temperature
            },
            "worker_model": {
                "provider": config.worker_model.provider,
                "model_name": config.worker_model.model_name,
                "temperature": config.worker_model.temperature
            },
            "strategist_model": {
                "provider": config.strategist_model.provider,
                "model_name": config.strategist_model.model_name,
                "temperature": config.strategist_model.temperature
            }
        }
    except Exception as e:
        logger.error(f"Error serializing config: {e}")
        return None


# =============================================================================
# ROUTES
# =============================================================================

@router.get("", response_model=PaginatedResponse[RunSummary])
@limiter.limit("60/minute")
async def list_runs(
    request: Request,
    limit: int = Query(default=50, ge=1, le=100, description="Maximum number of runs to return"),
    offset: int = Query(default=0, ge=0, description="Number of runs to skip")
):
    """
    List all runs from database and merge with in-memory active runs.

    Supports pagination via limit and offset query parameters.
    Results are sorted by created_at descending (most recent first).
    Rate limited to 60 requests per minute per IP.
    """
    from run_persistence import list_all_runs

    logger.info(f"📊 /api/v1/runs called - querying database (limit={limit}, offset={offset})...")

    # Get runs from our custom table
    db_runs = await list_all_runs()

    # Convert to RunSummary objects
    summaries = []
    seen_run_ids = set()

    for run_data in db_runs:
        run_id = run_data.get("run_id")
        seen_run_ids.add(run_id)

        summaries.append(RunSummary(
            run_id=run_id,
            objective=run_data.get("objective", ""),
            status=run_data.get("status", "unknown"),
            created_at=run_data.get("created_at", ""),
            updated_at=run_data.get("updated_at", ""),
            task_counts=run_data.get("task_counts", {}),
            tags=run_data.get("tags", []),
            workspace_path=run_data.get("workspace_path", "")
        ))

        # Update runs_index for other endpoints
        if run_id not in runs_index:
            runs_index[run_id] = run_data

    # CRITICAL: Include active runs from in-memory runs_index
    # These may not be in the database yet
    for run_id, run_data in runs_index.items():
        if run_id not in seen_run_ids:
            summaries.append(RunSummary(
                run_id=run_data.get("run_id", run_id),
                objective=run_data.get("objective", ""),
                status=run_data.get("status", "running"),
                created_at=run_data.get("created_at", ""),
                updated_at=run_data.get("updated_at", ""),
                task_counts=run_data.get("task_counts", {}),
                tags=run_data.get("tags", []),
                workspace_path=run_data.get("workspace_path", "")
            ))

    # Sort by created_at descending (most recent first)
    summaries.sort(key=lambda x: x.created_at, reverse=True)

    # Apply pagination
    total = len(summaries)
    paginated_items = summaries[offset:offset + limit]
    has_more = offset + limit < total

    return PaginatedResponse(
        items=paginated_items,
        total=total,
        limit=limit,
        offset=offset,
        has_more=has_more
    )


@router.post("")
@limiter.limit("10/minute")
async def create_run(request: Request, run_request: CreateRunRequest, background_tasks: BackgroundTasks):
    run_id = f"run_{uuid.uuid4().hex[:8]}"
    thread_id = str(uuid.uuid4())

    # Initialize run record
    runs_index[run_id] = {
        "run_id": run_id,
        "thread_id": thread_id,
        "objective": run_request.objective,
        "status": "running",
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat(),
        "task_counts": {"planned": 0, "completed": 0},
        "tags": run_request.tags or []
    }

    # Broadcast new run to all clients
    await manager.broadcast({
        "type": "run_list_update",
        "payload": list(runs_index.values())
    })

    # Start the run in background and track the task
    task = asyncio.create_task(run_orchestrator(run_id, thread_id, run_request.objective, run_request.spec, run_request.workspace))
    running_tasks[run_id] = task

    # Cleanup task when done
    def cleanup_task(t):
        import sys
        # Force flush to ensure we see this message
        logger.info(f"📍 Done callback fired for run {run_id}")
        sys.stdout.flush()
        sys.stderr.flush()

        running_tasks.pop(run_id, None)
        # CRITICAL: Check if task raised an exception - don't let it silently disappear!
        try:
            exc = t.exception()
            if exc:
                logger.error(f"💥 BACKGROUND TASK FAILED for run {run_id}: {exc}")
                import traceback
                logger.error("".join(traceback.format_exception(type(exc), exc, exc.__traceback__)))
                # Update run status to failed
                runs_index[run_id]["status"] = "failed"
            else:
                logger.info(f"✅ Task completed successfully for run {run_id}")
        except asyncio.CancelledError:
            logger.info(f"Task for run {run_id} was cancelled")
        except asyncio.InvalidStateError:
            # Task not done yet (shouldn't happen in done_callback)
            logger.warning(f"Task for run {run_id} in invalid state during cleanup")
        except Exception as callback_err:
            logger.error(f"❌ Error in done_callback itself: {callback_err}")
            import traceback
            traceback.print_exc()

        sys.stdout.flush()
        sys.stderr.flush()

    task.add_done_callback(cleanup_task)

    return {"run_id": run_id}


@router.get("/{run_id}")
@limiter.limit("100/minute")
async def get_run(request: Request, run_id: str):
    from run_persistence import load_run_state

    # Try to refresh from DB if not in memory
    if run_id not in runs_index:
        # Refresh runs_index from database
        from run_persistence import list_all_runs
        db_runs = await list_all_runs()
        for run_data in db_runs:
            rid = run_data.get("run_id")
            if rid not in runs_index:
                runs_index[rid] = run_data

    if run_id not in runs_index:
        raise HTTPException(status_code=404, detail="Run not found")

    run_data = runs_index[run_id]

    # First try in-memory state
    state = run_states.get(run_id)

    # Fallback to database
    if not state:
        state = await load_run_state(run_id)

    if state:
        # Serialize task memories
        task_memories = {}
        raw_memories = state.get("task_memories", {})
        logger.info(f"🔍 get_run found task_memories for: {list(raw_memories.keys())}")
        for task_id, messages in raw_memories.items():
            task_memories[task_id] = serialize_messages(messages)

        # Check for interrupt data - prioritize persisted data from state
        interrupt_data = None
        tasks = state.get("tasks", [])  # Define early since both branches need it

        # FIRST: Check for persisted interrupt data (most accurate after server restart)
        if state.get("_interrupt_data"):
            logger.info(f"🔍 Found persisted _interrupt_data in state")
            persisted = state["_interrupt_data"]

            # Build full interrupt_data from persisted data
            task_id = persisted.get("task_id")
            interrupt_data = {
                "task_id": task_id,
                "task_description": persisted.get("task_description", ""),
                "acceptance_criteria": persisted.get("acceptance_criteria", []),
                "failure_reason": persisted.get("failure_reason", ""),
                "retry_count": persisted.get("retry_count", 0),
                "max_retries": persisted.get("max_retries", 3),
                "tasks": [task_to_dict(task) if hasattr(task, "status") else task for task in tasks],
                "reason": "Task requires human intervention"
            }

        # FALLBACK: Search for waiting_human tasks (for backwards compatibility)
        if not interrupt_data:

            for t in tasks:
                status = t.get("status") if isinstance(t, dict) else getattr(t, "status", None)
                task_id = t.get("id") if isinstance(t, dict) else getattr(t, "id", None)

                if status == "waiting_human" or status == TaskStatus.WAITING_HUMAN:
                    logger.info(f"🔍 Found waiting_human task in get_run: {task_id}")

                    # Extract task details for the modal
                    task_dict = t if isinstance(t, dict) else task_to_dict(t)

                    # Get blocked_reason or escalation for failure reason
                    failure_reason = ""
                    if task_dict.get("blocked_reason"):
                        blocked = task_dict["blocked_reason"]
                        if isinstance(blocked, dict):
                            failure_reason = blocked.get("reason", "")
                        else:
                            failure_reason = str(blocked)

                    if task_dict.get("escalation"):
                        escalation = task_dict["escalation"]
                        if isinstance(escalation, dict):
                            failure_reason = escalation.get("reason", failure_reason)

                    interrupt_data = {
                        "task_id": task_id,
                        "task_description": task_dict.get("description", ""),
                        "acceptance_criteria": task_dict.get("acceptance_criteria", []),
                        "failure_reason": failure_reason,
                        "retry_count": task_dict.get("retry_count", 0),
                        "max_retries": task_dict.get("max_retries", 3),
                        "tasks": [task_to_dict(task) if hasattr(task, "status") else task for task in tasks],
                        "reason": "Task requires human intervention"
                    }
                    break


        if not interrupt_data:
            logger.info("ℹ️ No interrupt data found in get_run")
        else:
            run_data["interrupt_data"] = interrupt_data
            run_data["status"] = "interrupted"

        return {
            **run_data,
            "spec": state.get("spec", {}),
            "strategy_status": state.get("strategy_status", "active"),
            "tasks": [task_to_dict(t) if hasattr(t, "status") else t for t in tasks],
            "insights": state.get("insights", []),
            "design_log": state.get("design_log", []),
            "guardian": state.get("guardian", {}),
            "workspace_path": state.get("_workspace_path", run_data.get("workspace_path", "")),
            "model_config": _serialize_orch_config(state.get("orch_config")),
            "task_memories": task_memories,
            "interrupt_data": interrupt_data
        }

    # No state found - return minimal data with default config
    from config import OrchestratorConfig
    logger.warning(f"⚠️ No state found for run {run_id}")
    return {
        **run_data,
        "spec": {},
        "strategy_status": "unknown",
        "tasks": [],
        "insights": [],
        "design_log": [],
        "guardian": {},
        "task_memories": {},
        "model_config": _serialize_orch_config(OrchestratorConfig())  # Use default config
    }


@router.post("/{run_id}/pause")
async def pause_run(run_id: str):
    if run_id not in runs_index:
        raise HTTPException(status_code=404, detail="Run not found")
    runs_index[run_id]["status"] = "paused"
    await manager.broadcast_to_run(run_id, {"type": "state_update", "payload": {"status": "paused"}})
    return {"status": "paused"}


@router.post("/{run_id}/resume")
async def resume_run(run_id: str):
    if run_id not in runs_index:
        raise HTTPException(status_code=404, detail="Run not found")
    runs_index[run_id]["status"] = "running"
    await manager.broadcast_to_run(run_id, {"type": "state_update", "payload": {"status": "running"}})
    return {"status": "running"}


@router.post("/{run_id}/replan")
async def replan_run(run_id: str):
    """
    Trigger a re-planning: Pause all active tasks → LLM reorganizes → Resume with new tree.

    Flow:
    1. Cancel any running worker coroutines
    2. Reset ACTIVE tasks back to PLANNED
    3. Set replan_requested flag in shared memory
    4. Restart the dispatch loop (Director will see flag and call _integrate_plans)
    """
    if run_id not in runs_index:
        raise HTTPException(status_code=404, detail="Run not found")

    try:
        # 1. Get current state from shared memory
        state = run_states.get(run_id)
        if not state:
            # Try loading from DB
            from run_persistence import load_run_state
            state = await load_run_state(run_id)
            if not state:
                raise HTTPException(status_code=404, detail="Run state not found")

        # 2. Cancel running dispatch loop (this stops all active workers)
        if run_id in running_tasks:
            logger.info(f"🛑 Cancelling current dispatch loop for replan...")
            running_tasks[run_id].cancel()
            try:
                await running_tasks[run_id]
            except asyncio.CancelledError:
                pass
            except Exception:
                pass

        # 3. Reset ACTIVE tasks to PLANNED (they'll be re-dispatched after reorg)
        tasks = state.get("tasks", [])
        reset_count = 0
        for task in tasks:
            if task.get("status") == "active":
                task["status"] = "planned"
                task["updated_at"] = datetime.now().isoformat()
                reset_count += 1

        logger.info(f"🔄 Reset {reset_count} active tasks to PLANNED for reorg")

        # 4. Set replan_requested flag in shared memory (Director will see this)
        state["replan_requested"] = True
        run_states[run_id] = state

        # 5. Restart dispatch loop with updated state
        run_config = {
            "configurable": {
                "thread_id": runs_index[run_id]["thread_id"],
                "mock_mode": state.get("mock_mode", False)
            }
        }

        runs_index[run_id]["status"] = "running"
        runs_index[run_id]["updated_at"] = datetime.now().isoformat()

        task = asyncio.create_task(continuous_dispatch_loop(run_id, state, run_config))
        running_tasks[run_id] = task

        def cleanup(t):
            running_tasks.pop(run_id, None)
            # CRITICAL: Check if task raised an exception
            try:
                exc = t.exception()
                if exc:
                    logger.error(f"💥 REPLAN TASK FAILED for run {run_id}: {exc}")
                    import traceback
                    logger.error("".join(traceback.format_exception(type(exc), exc, exc.__traceback__)))
                    runs_index[run_id]["status"] = "failed"
            except asyncio.CancelledError:
                logger.info(f"Replan task for run {run_id} was cancelled")
            except asyncio.InvalidStateError:
                pass
        task.add_done_callback(cleanup)

        logger.info(f"✅ Replan triggered for run {run_id}. Director will reorganize tasks.")

        # Broadcast update
        await manager.broadcast_to_run(run_id, {
            "type": "state_update",
            "payload": {"status": "running", "message": "Replanning in progress..."}
        })

        return {"status": "replan_triggered", "tasks_reset": reset_count}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to trigger replan: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{run_id}/cancel")
async def cancel_run(run_id: str):
    """Cancel a running task."""
    from run_persistence import save_run_state

    logger.info(f"🛑 Cancel requested for run {run_id}")
    logger.info(f"   runs_index keys: {list(runs_index.keys())}")
    logger.info(f"   running_tasks keys: {list(running_tasks.keys())}")

    if run_id not in runs_index:
        raise HTTPException(status_code=404, detail="Run not found")

    if run_id not in running_tasks:
        # Already completed or not running
        logger.warning(f"   Run {run_id} has no active dispatch loop - returning early")
        return {"status": runs_index[run_id].get("status", "unknown"), "message": "Run not active"}

    task = running_tasks[run_id]
    logger.info(f"   Dispatch loop found: done={task.done()}, cancelled={task.cancelled()}")

    if task.done():
        return {"status": "already_completed"}

    # Mark as cancelled FIRST so dispatch loop sees it immediately
    runs_index[run_id]["status"] = "cancelled"
    runs_index[run_id]["updated_at"] = datetime.now().isoformat()

    # Cancel the task
    task.cancel()
    logger.info(f"   Cancel signal sent to task")

    # Wait briefly for cancellation - don't block forever if LLM calls are stuck
    try:
        await asyncio.wait_for(asyncio.shield(task), timeout=2.0)
    except asyncio.TimeoutError:
        logger.warning(f"   Task didn't stop within 2s - will terminate in background")
    except asyncio.CancelledError:
        logger.info(f"   ✓ Dispatch loop cancelled successfully")
    except Exception as e:
        logger.warning(f"   Dispatch loop ended with: {e}")

    logger.warning(f"🛑 Cancelled run {run_id}")

    # Save cancelled state to database
    if run_id in run_states:
        await save_run_state(run_id, run_states[run_id], status="cancelled")

    # Broadcast cancellation
    await manager.broadcast_to_run(run_id, {
        "type": "cancelled",
        "payload": {"status": "cancelled", "message": "Run cancelled by user"}
    })

    # Broadcast run list update
    await manager.broadcast({
        "type": "run_list_update",
        "payload": list(runs_index.values())
    })

    return {"status": "cancelled", "run_id": run_id}



@router.post("/{run_id}/restart")
async def restart_run(run_id: str):
    """Restart a stopped/crashed/cancelled run from its last state."""
    from run_persistence import load_run_state

    state = None

    # Try in-memory first
    if run_id in run_states:
        state = run_states[run_id]
    else:
        # Try database
        state = await load_run_state(run_id)

    if not state:
        if run_id not in runs_index:
            raise HTTPException(status_code=404, detail="Run not found - no state available to restart")
        return {"status": "error", "message": "No saved state available for restart. Run data exists but full state was lost."}

    # Check if already running
    if run_id in running_tasks and not running_tasks[run_id].done():
        return {"status": "already_running", "message": "Run is already active"}


    # Get workspace and thread info from state
    workspace_path = state.get("_workspace_path", "")
    thread_id = runs_index.get(run_id, {}).get("thread_id", f"thread_{run_id}")

    # CRITICAL: Reinitialize _wt_manager after loading from DB
    # The _wt_manager object is not serializable, so we must recreate it
    # WITHOUT THIS, workers fall back to main workspace and files leak!
    workspace_path = state.get("_workspace_path", "")
    worktree_base_path = state.get("_worktree_base_path")  # Path outside workspace
    logs_base_path = state.get("_logs_base_path")  # Path outside workspace
    
    # Get or create config for path generation
    from config import OrchestratorConfig
    config = state.get("orch_config") or OrchestratorConfig()
    
    if workspace_path and worktree_base_path:
        workspace_path_obj = Path(workspace_path)
        worktree_base = Path(worktree_base_path)
        worktree_base.mkdir(parents=True, exist_ok=True)
        state["_wt_manager"] = WorktreeManager(
            repo_path=workspace_path_obj,
            worktree_base=worktree_base
        )
        logger.info(f"   Restored _wt_manager at: {worktree_base}")
    elif workspace_path:
        # OLD RUN: Generate NEW paths using config (outside workspace!)
        workspace_path_obj = Path(workspace_path)
        worktree_base = config.get_worktree_base(run_id)
        worktree_base.mkdir(parents=True, exist_ok=True)
        state["_wt_manager"] = WorktreeManager(
            repo_path=workspace_path_obj,
            worktree_base=worktree_base
        )
        # Update state with new paths for future restarts
        state["_worktree_base_path"] = str(worktree_base)
        logger.info(f"   Generated new worktree path for old run: {worktree_base}")
    else:
        logger.warning(f"   ⚠️ _workspace_path not found - workers will use fallback!")
    
    # Also fix logs path for old runs
    if workspace_path and not logs_base_path:
        logs_base_path = str(config.get_llm_logs_path(run_id))
        state["_logs_base_path"] = logs_base_path
        logger.info(f"   Generated new logs path for old run: {logs_base_path}")

    # Rebuild run_config
    run_config = {
        "configurable": {
            "thread_id": thread_id,
            "mock_mode": state.get("mock_mode", False)
        }
    }

    # Reset any 'active' tasks back to 'ready' so they get re-dispatched
    tasks = state.get("tasks", [])
    for task in tasks:
        if task.get("status") == "active":
            task["status"] = "ready"
            logger.info(f"  Reset active task {task.get('id')} to ready for restart")

    # Update status
    runs_index[run_id]["status"] = "running"
    runs_index[run_id]["updated_at"] = datetime.now().isoformat()

    logger.info(f"🔄 Restarting run {run_id}")

    # Create new background task for the dispatch loop
    task = asyncio.create_task(continuous_dispatch_loop(run_id, state, run_config))
    running_tasks[run_id] = task

    # Cleanup when done
    def cleanup(t):
        if run_id in running_tasks:
            del running_tasks[run_id]
        # CRITICAL: Check if task raised an exception
        try:
            exc = t.exception()
            if exc:
                logger.error(f"💥 RESTART TASK FAILED for run {run_id}: {exc}")
                import traceback
                logger.error("".join(traceback.format_exception(type(exc), exc, exc.__traceback__)))
                runs_index[run_id]["status"] = "failed"
            else:
                logger.info(f"Cleaned up task for run {run_id}")
        except asyncio.CancelledError:
            logger.info(f"Restart task for run {run_id} was cancelled")
        except asyncio.InvalidStateError:
            pass

    task.add_done_callback(cleanup)

    # Broadcast update
    await manager.broadcast({
        "type": "run_list_update",
        "payload": list(runs_index.values())
    })

    return {"status": "restarted", "run_id": run_id, "message": "Run restarted from saved state"}
