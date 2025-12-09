"""
Interrupts API Routes
=====================
FastAPI routes for managing task interrupts and human-in-the-loop interventions.
"""

import asyncio
import logging
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException, BackgroundTasks

# Import API modules
from api.types import HumanResolution
from api.state import runs_index, running_tasks, run_states, get_orchestrator_graph, manager
from api.dispatch import continuous_dispatch_loop

# Import orchestrator types
from orchestrator_types import task_to_dict, TaskStatus
from git_manager import WorktreeManager

logger = logging.getLogger(__name__)

# Create router with prefix and tags
router = APIRouter(prefix="/api/runs/{run_id}", tags=["interrupts"])


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
    from api.state import global_checkpointer

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


# =============================================================================
# ROUTES
# =============================================================================

@router.post("/tasks/{task_id}/interrupt")
async def interrupt_task(run_id: str, task_id: str):
    """
    Force interrupt a specific task:
    1. Cancel the running orchestrator task
    2. Update the specific task status to WAITING_HUMAN
    3. Update run status to 'interrupted'
    """
    if run_id not in runs_index:
        raise HTTPException(status_code=404, detail="Run not found")

    # 1. Cancel the running task if it exists
    if run_id in running_tasks:
        logger.info(f"Force interrupting run {run_id} for task {task_id}")
        task = running_tasks[run_id]
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            logger.info(f"Run {run_id} cancelled successfully")
        except Exception as e:
            logger.error(f"Error cancelling run {run_id}: {e}")

    # 2. Update state to mark task as waiting_human
    try:
        from run_persistence import load_run_state, save_run_state

        # Try to get state from memory first, then DB
        state = run_states.get(run_id)
        if not state:
            state = await load_run_state(run_id)

        if not state:
             raise HTTPException(status_code=404, detail="State not found")

        tasks = state.get("tasks", [])
        task_found = False

        # Modify the specific task
        updated_tasks = []
        interrupted_task_item = None

        for t in tasks:
            # Handle both object and dict representation
            t_id = t.id if hasattr(t, "id") else t.get("id")

            if t_id == task_id:
                logger.info(f"Marking task {task_id} as WAITING_HUMAN")
                task_found = True

                # Update status
                if hasattr(t, "status"):
                    t.status = TaskStatus.WAITING_HUMAN
                    t.updated_at = datetime.now()
                else:
                    t["status"] = "waiting_human"
                    t["updated_at"] = datetime.now().isoformat()

                interrupted_task_item = t

            updated_tasks.append(t)

        if not task_found:
            raise HTTPException(status_code=404, detail=f"Task {task_id} not found in state")

        # Persist the update
        state["tasks"] = updated_tasks

        # Build complete interrupt data matching server-initiated format
        task_dict = task_to_dict(interrupted_task_item) if hasattr(interrupted_task_item, "status") else interrupted_task_item

        interrupt_data = {
            "type": "manual_interrupt",
            "task_id": task_id,
            "task_description": task_dict.get("description", ""),
            "component": task_dict.get("component", ""),
            "phase": task_dict.get("phase", "build"),
            "retry_count": task_dict.get("retry_count", 0),
            "failure_reason": "Manually interrupted by user",
            "acceptance_criteria": task_dict.get("acceptance_criteria", []),
            "assigned_worker_profile": task_dict.get("assigned_worker_profile", "code_worker"),
            "depends_on": task_dict.get("depends_on", [])
        }

        # Update run status and persist interrupt data
        runs_index[run_id]["status"] = "interrupted"
        runs_index[run_id]["interrupt_data"] = interrupt_data

        # Update state object
        state["_interrupt_data"] = interrupt_data

        # Save to DB and Memory
        await save_run_state(run_id, state, status="interrupted")
        run_states[run_id] = state

        # Broadcast update - send BOTH state_update (for general UI) and interrupted (for modal)
        tasks_payload = [task_to_dict(t) if hasattr(t, "status") else t for t in updated_tasks]

        await manager.broadcast_to_run(run_id, {
            "type": "state_update",
            "payload": {
                "status": "interrupted",
                "tasks": tasks_payload,
                "interrupt_data": interrupt_data
            }
        })

        await manager.broadcast_to_run(run_id, {
            "type": "interrupted",
            "payload": {
                "status": "interrupted",
                "data": interrupt_data
            }
        })

        return {"status": "interrupted", "task_id": task_id}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating state for interrupt: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/interrupts")
async def get_interrupts(run_id: str):
    """Check if run is paused waiting for human input."""
    # Ensure run is in index (may be CLI-initiated)
    if not await ensure_run_in_index(run_id):
        raise HTTPException(status_code=404, detail="Run not found")

    try:
        orchestrator = get_orchestrator_graph()
        thread_id = runs_index[run_id]["thread_id"]
        config = {"configurable": {"thread_id": thread_id}}

        # Get current state snapshot (correct LangGraph API)
        snapshot = await orchestrator.aget_state(config)

        # Check if graph is paused (snapshot.next is non-empty when waiting)
        if snapshot.next:
            logger.info(f"⏸️  Run {run_id} is PAUSED (snapshot.next = {snapshot.next})")
            # Check for dynamic interrupt - this is where LangGraph stores interrupt() payloads
            # Based on user research and LangGraph docs
            if snapshot.tasks and len(snapshot.tasks) > 0 and snapshot.tasks[0].interrupts:
                # Extract the interrupt data we passed to interrupt()
                interrupt_data = snapshot.tasks[0].interrupts[0].value
                logger.info(f"   Found interrupt: task_id={interrupt_data.get('task_id')}, type={interrupt_data.get('type')}")
                return {
                    "interrupted": True,
                    "data": interrupt_data
                }

        return {"interrupted": False}

    except Exception as e:
        logger.error(f"Error checking interrupts: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/resolve")
async def resolve_interrupt(run_id: str, resolution: HumanResolution, background_tasks: BackgroundTasks):
    """Resume execution with human decision."""
    # Ensure run is in index (may be CLI-initiated)
    if not await ensure_run_in_index(run_id):
        raise HTTPException(status_code=404, detail="Run not found")

    try:
        from langgraph.types import Command

        orchestrator = get_orchestrator_graph()
        thread_id = runs_index[run_id]["thread_id"]
        config = {"configurable": {"thread_id": thread_id}}

        # Check if there's a real interrupt in the graph (from interrupt() call)
        snapshot = await orchestrator.aget_state(config)
        has_real_interrupt = (
            snapshot and
            snapshot.tasks and
            len(snapshot.tasks) > 0 and
            snapshot.tasks[0].interrupts
        )

        logger.info(f"▶️  Resuming run {run_id} with action '{resolution.action}'")
        logger.info(f"   Has real interrupt: {has_real_interrupt}")
        if resolution.action == "retry" and resolution.modified_description:
            logger.info(f"   Modified description: {resolution.modified_description[:100]}...")

        async def resume_execution():
            try:
                # CRITICAL: Cancel any existing dispatch loop FIRST
                # Otherwise the old loop keeps running and ignores our pending_resolution
                if run_id in running_tasks and not running_tasks[run_id].done():
                    logger.info(f"   Cancelling existing dispatch loop for {run_id}")
                    running_tasks[run_id].cancel()
                    try:
                        await running_tasks[run_id]
                    except asyncio.CancelledError:
                        logger.info(f"   ✓ Old dispatch loop cancelled")
                    except Exception as e:
                        logger.warning(f"   Old dispatch loop ended with: {e}")

                # CRITICAL: Always use continuous dispatch loop, not super-step mode
                # Load current state from database to continue where we left off
                from run_persistence import load_run_state

                state = await load_run_state(run_id)
                if not state:
                    logger.error(f"   No saved state found for run {run_id}")
                    return

                # CRITICAL: Reinitialize _wt_manager after loading from DB
                # The _wt_manager object is not serializable, so we must recreate it
                workspace_path = state.get("_workspace_path")
                if workspace_path:
                    workspace_path_obj = Path(workspace_path)
                    worktree_base = workspace_path_obj / ".worktrees"
                    worktree_base.mkdir(exist_ok=True)
                    state["_wt_manager"] = WorktreeManager(
                        repo_path=workspace_path_obj,
                        worktree_base=worktree_base
                    )
                    logger.info(f"   Restored _workspace_path: {workspace_path}")
                    logger.info(f"   Reinitialized _wt_manager at: {worktree_base}")
                else:
                    logger.warning(f"   ⚠️ _workspace_path not found in loaded state!")

                # Apply the resolution directly to state
                # The director will process it via pending_resolution
                state["pending_resolution"] = resolution.model_dump()

                logger.info(f"   Continuing dispatch loop with {len(state.get('tasks', []))} tasks")

                # Resume the continuous dispatch loop (not super-step mode!)
                await continuous_dispatch_loop(run_id, state, config)

                logger.info(f"✅ Successfully resumed run {run_id} with action: {resolution.action}")

            except Exception as e:
                logger.error(f"❌ Error during resume execution: {e}")
                import traceback
                traceback.print_exc()

        background_tasks.add_task(resume_execution)

        return {"status": "resuming", "action": resolution.action}

    except Exception as e:
        logger.error(f"Error resuming run: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
