"""
Dispatch Loop and Execution Logic
==================================
Continuous task dispatch loop and orchestrator execution management.
"""

import asyncio
import logging
import platform
import os
from datetime import datetime
from pathlib import Path

from state import tasks_reducer, task_memories_reducer, insights_reducer, design_log_reducer
from orchestrator_types import task_to_dict, serialize_messages
from config import OrchestratorConfig
from git_manager import AsyncWorktreeManager as WorktreeManager
from git_manager import AsyncWorktreeManager as WorktreeManager, initialize_git_repo_async as initialize_git_repo

# Import global state
import api.state as api_state
from api.state import runs_index, run_states, get_orchestrator_graph


logger = logging.getLogger(__name__)

# =============================================================================
# HEARTBEAT DIAGNOSTIC - Tracks exact location of silent failures
# =============================================================================
_HEARTBEAT_FILE = os.path.join(os.path.dirname(__file__), "..", "..", "heartbeat.log")

def _heartbeat(run_id: str, msg: str):
    """Write heartbeat to file with fsync. Cross-platform (Windows/Linux)."""
    try:
        with open(_HEARTBEAT_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now().isoformat()}] [{run_id[:8]}] {msg}\n")
            f.flush()
            os.fsync(f.fileno())
    except:
        pass
# =============================================================================



async def continuous_dispatch_loop(run_id: str, state: dict, run_config: dict):
    """
    Run the orchestrator with continuous task dispatch.

    Unlike LangGraph's superstep model which blocks until ALL workers complete,
    this loop dispatches workers as background tasks and immediately continues
    to check for newly-ready tasks.

    Flow:
        Director → spawn(workers) → poll completions → Director → spawn more...
    """
    from task_queue import TaskCompletionQueue
    from nodes.director_main import director_node
    from nodes.worker import worker_node
    from nodes.strategist import strategist_node

    # Get max concurrent workers from config
    orch_config = state.get("orch_config")
    max_concurrent = getattr(orch_config, "max_concurrent_workers", 5) if orch_config else 5
    task_queue = TaskCompletionQueue(max_concurrent=max_concurrent)
    logger.info(f"🔧 Max concurrent workers set to: {max_concurrent}")
    iteration = 0
    max_iterations = 500  # Safety limit

    # Deadlock detection: track consecutive iterations with no progress
    iterations_without_progress = 0
    max_iterations_without_progress = 10  # Break after 10 cycles with no status changes
    last_task_statuses = {}

    # Register task queue for external access (task-specific interrupts)
    api_state.active_task_queues[run_id] = task_queue

    logger.info(f"🚀 Starting continuous dispatch loop for run {run_id}")
    _heartbeat(run_id, "DISPATCH_LOOP_START")

    try:
        while iteration < max_iterations:
            _heartbeat(run_id, f"LOOP_ITER_{iteration}_START")
            # IMMEDIATE CHECK: If cancelled externally, stop immediately
            if runs_index.get(run_id, {}).get("status") == "cancelled":
                logger.info(f"🛑 Loop detected cancellation for run {run_id}, exiting.")
                break

            # Reset activity flag for this cycle
            activity_occurred = False

            # ========== PHASE 1: Collect ALL completed workers (SINGLE COLLECTION POINT) ==========
            # This is the ONLY place we collect completions in the entire loop.
            # All workers that completed since last iteration are processed here.
            completed = task_queue.collect_completed()

            if completed:
                logger.info(f"  📥 Processing {len(completed)} completed task(s)")

                for c in completed:
                    logger.info(f"    → {c.task_id[:12]}: merging results")
                    logger.info(f"       [DEBUG] Result type: {type(c.result)}, has task_memories: {'task_memories' in c.result if isinstance(c.result, dict) else 'N/A'}")

                    for task in state.get("tasks", []):
                        if task.get("id") == c.task_id:
                            if c.error:
                                task["status"] = "failed"
                                task["error"] = str(c.error)
                                logger.error(f"       ❌ Failed: {c.error}")
                            else:
                                # Worker returns state updates with modified task
                                if c.result and isinstance(c.result, dict):
                                    # CRITICAL: Merge task_memories FIRST, before updating task status
                                    # This ensures memories are in state before Director/QA see the task
                                    if "task_memories" in c.result:
                                        worker_memories = c.result["task_memories"]
                                        if worker_memories:
                                            # Apply reducer to preserve existing memories
                                            for tid, msgs in worker_memories.items():
                                                existing_count = len(state.get("task_memories", {}).get(tid, []))
                                                logger.info(f"       [task_memories] Merging {tid[:12]}: existing={existing_count}, adding={len(msgs)}")
                                            state["task_memories"] = task_memories_reducer(
                                                state.get("task_memories", {}),
                                                worker_memories
                                            )
                                            for tid, msgs in worker_memories.items():
                                                merged_count = len(state.get("task_memories", {}).get(tid, []))
                                                logger.info(f"       [task_memories] After merge {tid[:12]}: total={merged_count}")
                                    else:
                                        logger.warning(f"       ⚠️  Worker completion has no task_memories!")

                                    # Find the updated task in the result
                                    result_tasks = c.result.get("tasks", [])
                                    for rt in result_tasks:
                                        if rt.get("id") == c.task_id:
                                            # Merge updates
                                            task.update(rt)
                                            break

                                    logger.info(f"       ✅ Status: {task.get('status')}")

                                    # Log files modified if any
                                    if task.get("aar") and task["aar"].get("files_modified"):
                                        files = task["aar"]["files_modified"]
                                        logger.info(f"       📂 Modified {len(files)} file(s): {', '.join(files)}")

                                    # Activity occurred
                                    activity_occurred = True
                            break

                # Save checkpoint to database after ALL worker updates
                if runs_index.get(run_id, {}).get("status") != "cancelled":
                    from run_persistence import save_run_state
                    try:
                        # Update in-memory state
                        run_states[run_id] = state
                        # Save to database
                        await save_run_state(run_id, state, status=runs_index[run_id]["status"])
                    except Exception as e:
                        logger.error(f"Failed to save checkpoint: {e}")

                # Broadcast state update
                await broadcast_state_update(run_id, state)

            # ========== PHASE 2: Run Director (evaluates readiness, creates tasks) ==========
            
            # Broadcast 'replanning' status to UI when replan is triggered
            if state.get("replan_requested"):
                logger.info(f"📋 Replanning triggered for run {run_id}")
                runs_index[run_id]["status"] = "replanning"
                await api_state.manager.broadcast_to_run(run_id, {
                    "type": "state_update",
                    "payload": {
                        "status": "replanning",
                        "message": "Reorganizing task plan..."
                    }
                })
            
            # Director modifies state directly
            _heartbeat(run_id, f"ITER_{iteration}_DIRECTOR_CALL_START")
            director_result = await director_node(state, run_config)
            _heartbeat(run_id, f"ITER_{iteration}_DIRECTOR_CALL_END")

            if director_result:
                # Only count as activity if meaningful state changed (ignore internal counters)
                meaningful_keys = ["tasks", "insights", "design_log", "replan_requested"]
                if any(key in director_result for key in meaningful_keys):
                    activity_occurred = True

                # Merge director updates into state (applying reducers)
                for key, value in director_result.items():
                    if key == "tasks":
                        state["tasks"] = tasks_reducer(state.get("tasks", []), value)
                    elif key == "task_memories":
                        state["task_memories"] = task_memories_reducer(state.get("task_memories", {}), value)
                    elif key == "insights":
                        state["insights"] = insights_reducer(state.get("insights", []), value)
                    elif key == "design_log":
                        state["design_log"] = design_log_reducer(state.get("design_log", []), value)
                    elif key != "_wt_manager":  # Don't overwrite internal objects
                        state[key] = value

                # Save checkpoint to database after director updates
                if runs_index.get(run_id, {}).get("status") != "cancelled":
                    from run_persistence import save_run_state
                    try:
                        # Update in-memory state
                        run_states[run_id] = state
                        # Save to database
                        await save_run_state(run_id, state, status=runs_index[run_id]["status"])
                    except Exception as e:
                        logger.error(f"Failed to save checkpoint: {e}")

                # Reset status from 'replanning' back to 'running' after director completes
                if runs_index.get(run_id, {}).get("status") == "replanning":
                    runs_index[run_id]["status"] = "running"
                
                # Always broadcast after Director - ensures promoted states are visible in UI
                await broadcast_state_update(run_id, state)


            # ========== PHASE 3: Find and dispatch ready tasks ==========
            ready_tasks = [t for t in state.get("tasks", []) if t.get("status") == "ready"]

            # Dispatch ready tasks (up to available slots)
            dispatched = 0
            for task in ready_tasks[:task_queue.available_slots]:
                task_id = task.get("id")
                if task_queue.is_running(task_id):
                    continue  # Already running

                # Mark as active
                task["status"] = "active"
                task["started_at"] = datetime.now().isoformat()

                # Create worktree if needed
                wt_manager = state.get("_wt_manager")
                if wt_manager and not state.get("mock_mode", False):
                    try:
                        await wt_manager.create_worktree(task_id)
                    except Exception as e:
                        logger.warning(f"Failed to create worktree: {e}")

                # Spawn worker as background task
                worker_state = {**state, "task_id": task_id}
                _heartbeat(run_id, f"ITER_{iteration}_WORKER_SPAWN_{task_id[:8]}")
                task_queue.spawn(task_id, worker_node(worker_state, run_config))
                dispatched += 1
                activity_occurred = True

                logger.info(f"  🚀 Dispatched: {task_id[:12]} ({task.get('assigned_worker_profile', 'unknown')})")

            if dispatched > 0:
                await broadcast_state_update(run_id, state)

            # ========== PHASE 4: Run Strategist for QA (Test tasks or Awaiting QA) ==========
            # Workers now return copies (don't mutate state directly), so all worker results
            # are collected in Phase 1 and task_memories are merged atomically with task updates.
            # Director promotes pending states, then QA sees tasks with their memories.
            tasks_requiring_qa = [t for t in state.get("tasks", [])
                               if t.get("status") == "awaiting_qa"
                               or (t.get("status") == "complete" and t.get("phase") == "test" and not t.get("qa_verdict"))]

            for task in tasks_requiring_qa:
                # CHECK: Cancellation might happen during long operations
                if runs_index.get(run_id, {}).get("status") == "cancelled":
                    break

                task_id_short = task.get('id', '')[:12]
                _heartbeat(run_id, f"ITER_{iteration}_STRATEGIST_START_{task_id_short}")
                logger.info(f"  🔍 QA evaluating: {task_id_short}")
                strategist_result = await strategist_node({**state, "task_id": task.get("id")}, run_config)
                _heartbeat(run_id, f"ITER_{iteration}_STRATEGIST_END_{task_id_short}")
                if strategist_result:
                    activity_occurred = True
                    for key, value in strategist_result.items():
                        if key == "tasks":
                            # Update existing tasks OR add new tasks (like merge tasks!)
                            existing_ids = {t.get("id") for t in state["tasks"]}
                            for rt in value:
                                task_id = rt.get("id")
                                if task_id in existing_ids:
                                    # Update existing task
                                    for t in state["tasks"]:
                                        if t.get("id") == task_id:
                                            t.update(rt)
                                            break
                                else:
                                    # NEW task (e.g., merge task) - append to state!
                                    logger.info(f"  [NEW TASK] Strategist added new task: {task_id}")
                                    state["tasks"].append(rt)
                        elif key == "task_memories":
                            # DEBUG: Log before and after to track memory loss
                            for tid, msgs in value.items():
                                existing_count = len(state.get("task_memories", {}).get(tid, []))
                                new_count = len(msgs)
                                logger.info(f"  [DEBUG task_memories] Strategist merging {tid[:12]}: existing={existing_count}, adding={new_count}")
                            state["task_memories"] = task_memories_reducer(state.get("task_memories", {}), value)
                            for tid, msgs in value.items():
                                merged_count = len(state.get("task_memories", {}).get(tid, []))
                                logger.info(f"  [DEBUG task_memories] After merge {tid[:12]}: total={merged_count}")
                        elif key != "_wt_manager":
                            state[key] = value
                await broadcast_state_update(run_id, state)

            # ========== PHASE 5: Check completion ==========
            all_tasks = state.get("tasks", [])

            # Check for pending states that need Director promotion
            # If ANY task is pending_*, we MUST continue the loop for Director to promote it
            pending_states = {"pending_awaiting_qa", "pending_complete", "pending_failed"}
            has_pending = any(t.get("status") in pending_states for t in all_tasks)
            
            if has_pending:
                # Force another iteration - Director will promote these pending states
                activity_occurred = True

            # Exit conditions - ONLY truly terminal statuses
            # waiting_human and awaiting_qa are NOT terminal - they need action!
            terminal_statuses = {"complete", "abandoned"}
            all_terminal = all(t.get("status") in terminal_statuses for t in all_tasks) if all_tasks else False

            if all_terminal and not task_queue.has_work and not has_pending:
                logger.info(f"✅ All tasks complete! Ending run {run_id}")
                runs_index[run_id]["status"] = "completed"

                # Save completed state to database
                from run_persistence import save_run_state
                await save_run_state(run_id, state, status="completed")

                await broadcast_state_update(run_id, state)
                break

            # Check for HITL interrupts
            waiting_human = [t for t in all_tasks if t.get("status") == "waiting_human"]
            if waiting_human and not task_queue.has_work:
                logger.info(f"⏸️  Run paused for human intervention")
                runs_index[run_id]["status"] = "interrupted"

                # Save interrupted state to database
                from run_persistence import save_run_state
                await save_run_state(run_id, state, status="interrupted")
                break

            # No work and no ready tasks? Check if we're stuck
            # CRITICAL: Also check if there are completed workers waiting to be collected!
            # Workers may complete between Phase 1 and here, so we must not exit if there are completions pending
            
            # DEBUG: Log all conditions
            logger.debug(f"  [DEBUG EXIT CHECK] has_work={task_queue.has_work}, has_completed={task_queue.has_completed}, "
                        f"ready_tasks={len(ready_tasks)}, tasks_requiring_qa={len(tasks_requiring_qa)}, has_pending={has_pending}")
            
            if not task_queue.has_work and not task_queue.has_completed and not ready_tasks and not tasks_requiring_qa and not has_pending:
                # Check for planned tasks that might become ready
                planned = [t for t in all_tasks if t.get("status") == "planned"]

                # Also check for completed planners with suggestions that need integration
                # These are awaiting_qa but have suggested_tasks that Director needs to process
                awaiting_planners = [t for t in all_tasks
                                    if t.get("status") == "awaiting_qa"
                                    and t.get("assigned_worker_profile") == "planner_worker"
                                    and t.get("suggested_tasks")]

                # DEBUG: Log task statuses
                status_counts = {}
                for t in all_tasks:
                    s = t.get("status", "unknown")
                    status_counts[s] = status_counts.get(s, 0) + 1
                logger.warning(f"  [DEBUG] About to break! Task statuses: {status_counts}")
                logger.warning(f"  [DEBUG] planned={len(planned)}, awaiting_planners={len(awaiting_planners)}")

                # DEADLOCK DETECTION: Check if any task statuses changed
                current_statuses = {t["id"]: t.get("status") for t in all_tasks}

                # Also check for "active" status tasks (might not be in task_queue due to race conditions)
                active_tasks = [t for t in all_tasks if t.get("status") == "active"]

                if current_statuses == last_task_statuses and not active_tasks:
                    iterations_without_progress += 1
                    logger.warning(f"  [DEADLOCK CHECK] No progress for {iterations_without_progress}/{max_iterations_without_progress} iterations")
                else:
                    if active_tasks:
                        logger.debug(f"  Progress detected: {len(active_tasks)} active task(s) running")
                    iterations_without_progress = 0  # Reset counter
                    last_task_statuses = current_statuses

                # Break if deadlocked (no progress for N iterations)
                if iterations_without_progress >= max_iterations_without_progress:
                    logger.error(f"🚨 DEADLOCK DETECTED: No task progress for {max_iterations_without_progress} iterations!")
                    logger.error(f"   Stuck tasks: {len(planned)} planned, {len(awaiting_planners)} awaiting planners")
                    logger.error(f"   This likely indicates circular dependencies or dependencies on WAITING_HUMAN tasks")
                    break

                if not planned and not awaiting_planners:
                    logger.warning(f"⚠️  No more work to do, but not all tasks complete")
                    break
                elif awaiting_planners:
                    logger.info(f"  📋 {len(awaiting_planners)} planners have suggestions pending integration")
                # Otherwise director will evaluate readiness on next cycle

            # ========== PHASE 6: Wait for completions ==========
            if task_queue.has_work:
                # Wait a bit for workers to complete
                await task_queue.wait_for_any(timeout=1.0)
            else:
                # Small delay to prevent tight loop
                await asyncio.sleep(0.1)

            # CRITICAL CHECK after wait: did we get cancelled while waiting?
            if runs_index.get(run_id, {}).get("status") == "cancelled":
                logger.info(f"🛑 Run {run_id} was cancelled during wait, exiting loop")
                break

            # Only increment iteration if something actually happened
            # This prevents 500 max_iterations from being reached just by idling
            if activity_occurred:
                iteration += 1

            # Update run status IF NOT CANCELLED
            if runs_index.get(run_id, {}).get("status") != "cancelled":
                runs_index[run_id].update({
                    "status": "running",
                    "updated_at": datetime.now().isoformat(),
                    "task_counts": {
                        "planned": len([t for t in all_tasks if t.get("status") == "planned"]),
                        "active": len([t for t in all_tasks if t.get("status") == "active"]),
                        "completed": len([t for t in all_tasks if t.get("status") == "complete"]),
                        "failed": len([t for t in all_tasks if t.get("status") == "failed"]),
                    }
                })

                # Save full state for restart capability (both in-memory and database)
                run_states[run_id] = state.copy()

                # Persist to database
                from run_persistence import save_run_state
                await save_run_state(run_id, state, status="running")

        if iteration >= max_iterations:
            logger.error(f"❌ Max iterations ({max_iterations}) reached for run {run_id}")
            runs_index[run_id]["status"] = "failed"

            # Save failed state to database
            from run_persistence import save_run_state
            await save_run_state(run_id, state, status="failed")

    except asyncio.CancelledError:
        logger.warning(f"🛑 Orchestrator run {run_id} execution cancelled.")
        runs_index[run_id]["status"] = "cancelled"

        # Save cancelled state
        try:
            from run_persistence import save_run_state
            await save_run_state(run_id, state, status="cancelled")
        except Exception as e:
            logger.error(f"Failed to save cancelled state: {e}", exc_info=True)

        # Don't re-raise, graceful exit
        return

    except Exception as e:
        # CRITICAL: Log ALL unexpected exceptions
        _heartbeat(run_id, f"EXCEPTION: {type(e).__name__}: {str(e)[:100]}")
        logger.error(f"💥 FATAL ERROR in dispatch loop for run {run_id}: {e}", exc_info=True)
        logger.error(f"   Exception type: {type(e).__name__}")
        logger.error(f"   Exception args: {e.args}")

        import traceback
        logger.error("   Full traceback:")
        logger.error(traceback.format_exc())

        runs_index[run_id]["status"] = "failed"

        # Save failed state
        try:
            from run_persistence import save_run_state
            await save_run_state(run_id, state, status="failed")
        except Exception as save_err:
            logger.error(f"Failed to save failed state: {save_err}", exc_info=True)

        # Re-raise to ensure it's visible
        raise

    # NOTE: Previous code had a second "except Exception" handler here that was unreachable
    # (dead code) because the first handler catches all exceptions and re-raises.
    # That dead code has been removed.

    except BaseException as e:
        # Catch EVERYTHING including SystemExit, KeyboardInterrupt
        # This ensures we always log what killed the process
        _heartbeat(run_id, f"BASE_EXCEPTION: {type(e).__name__}: {str(e)[:100]}")
        import sys
        logger.error(f"💀 CRITICAL: BaseException caught in dispatch loop: {type(e).__name__}: {e}")
        sys.stdout.flush()
        sys.stderr.flush()
        raise

    finally:
        # DEFENSIVE: Ensure this message is always visible
        import sys
        logger.info(f"🏁 Run {run_id} entering finally block after {iteration} iterations")
        sys.stdout.flush()
        sys.stderr.flush()

        # Cancel any remaining workers
        try:
            await task_queue.cancel_all()
        except Exception as cancel_err:
            logger.error(f"Error cancelling workers: {cancel_err}")

        # Unregister task queue
        api_state.active_task_queues.pop(run_id, None)

        # Final broadcast
        try:
            await api_state.manager.broadcast({"type": "run_list_update", "payload": list(runs_index.values())})
        except Exception as broadcast_err:
            logger.error(f"Error in final broadcast: {broadcast_err}")

        logger.info(f"🏁 Run {run_id} cleanup complete")
        sys.stdout.flush()
        sys.stderr.flush()


async def broadcast_state_update(run_id: str, state: dict):
    """Broadcast state update to connected clients."""
    try:
        serialized_tasks = [task_to_dict(t) if hasattr(t, "status") else t for t in state.get("tasks", [])]

        # Serialize task_memories (LLM conversations)
        task_memories = {}
        raw_memories = state.get("task_memories", {})
        for task_id, messages in raw_memories.items():
            task_memories[task_id] = serialize_messages(messages)

        await api_state.manager.broadcast_to_run(run_id, {
            "type": "state_update",
            "payload": {
                "tasks": serialized_tasks,
                "status": runs_index[run_id].get("status", "running"),
                "task_counts": runs_index[run_id].get("task_counts", {}),
                "task_memories": task_memories
            }
        })
    except Exception as e:
        logger.error(f"Failed to broadcast state: {e}")


async def execute_run_logic(run_id: str, thread_id: str, objective: str, spec: dict, workspace_path):
    """Core execution logic for the run."""
    try:
        # Send initialization started message
        await api_state.manager.broadcast_to_run(run_id, {
            "type": "status",
            "payload": {"message": "Initializing workspace...", "phase": "init"}
        })

        # Initialize git
        await initialize_git_repo(workspace_path)
        await api_state.manager.broadcast_to_run(run_id, {
            "type": "status",
            "payload": {"message": "Git repository initialized", "phase": "init"}
        })

        # Create SHARED venv at workspace root (all worktrees will use this)
        venv_path = workspace_path / ".venv"
        if not venv_path.exists():
            await api_state.manager.broadcast_to_run(run_id, {
                "type": "status",
                "payload": {"message": "Creating Python virtual environment...", "phase": "init"}
            })
            logger.info(f"Creating shared venv at {venv_path}...")
            try:
                # Create venv asynchronously
                process = await asyncio.create_subprocess_exec(
                    "python", "-m", "venv", str(venv_path),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=str(workspace_path)
                )
                try:
                    await asyncio.wait_for(process.communicate(), timeout=120.0)
                    if process.returncode != 0:
                        raise Exception("Venv creation failed")
                except asyncio.TimeoutError:
                    process.kill()
                    await process.wait()
                    raise Exception("Venv creation timed out")

                logger.info(f"✅ Shared venv created at {venv_path}")
                await api_state.manager.broadcast_to_run(run_id, {
                    "type": "status",
                    "payload": {"message": "Virtual environment created", "phase": "init"}
                })

                # Install basic packages (requests for test harness pattern)
                pip_exe = venv_path / "Scripts" / "pip.exe" if platform.system() == "Windows" else venv_path / "bin" / "pip"
                if pip_exe.exists():
                    # Install requests
                    await api_state.manager.broadcast_to_run(run_id, {
                        "type": "status",
                        "payload": {"message": "Installing Python packages (requests)...", "phase": "init"}
                    })
                    process = await asyncio.create_subprocess_exec(
                        str(pip_exe), "install", "requests",
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                        cwd=str(workspace_path)
                    )
                    try:
                        await asyncio.wait_for(process.communicate(), timeout=120.0)
                    except asyncio.TimeoutError:
                        process.kill()
                        await process.wait()

                    logger.info(f"✅ Installed 'requests' in shared venv")
                    await api_state.manager.broadcast_to_run(run_id, {
                        "type": "status",
                        "payload": {"message": "Python packages installed", "phase": "init"}
                    })

                    # Install nodeenv and set up Node.js in the venv
                    await api_state.manager.broadcast_to_run(run_id, {
                        "type": "status",
                        "payload": {"message": "Installing Node.js environment (this may take a minute)...", "phase": "init"}
                    })
                    logger.info(f"Installing nodeenv for npm support...")
                    process = await asyncio.create_subprocess_exec(
                        str(pip_exe), "install", "nodeenv",
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                        cwd=str(workspace_path)
                    )
                    try:
                        await asyncio.wait_for(process.communicate(), timeout=120.0)
                    except asyncio.TimeoutError:
                        process.kill()
                        await process.wait()

                    # Add Node.js to the venv using nodeenv -p (prebuilt binaries)
                    python_exe = venv_path / "Scripts" / "python.exe" if platform.system() == "Windows" else venv_path / "bin" / "python"
                    try:
                        process = await asyncio.create_subprocess_exec(
                            str(python_exe), "-m", "nodeenv", "-p", "--prebuilt",
                            stdout=asyncio.subprocess.PIPE,
                            stderr=asyncio.subprocess.PIPE,
                            cwd=str(workspace_path)
                        )
                        await asyncio.wait_for(process.communicate(), timeout=300.0)
                        logger.info(f"✅ Installed Node.js/npm in shared venv via nodeenv")
                        await api_state.manager.broadcast_to_run(run_id, {
                            "type": "status",
                            "payload": {"message": "Node.js environment ready", "phase": "init"}
                        })
                    except asyncio.TimeoutError:
                        logger.warning(f"nodeenv installation timed out - agents may need npm globally")
                        await api_state.manager.broadcast_to_run(run_id, {
                            "type": "status",
                            "payload": {"message": "Node.js setup timed out (agents will use global npm)", "phase": "init"}
                        })
                    except Exception as e:
                        logger.warning(f"nodeenv installation failed: {e} - agents may need npm globally")
                        await api_state.manager.broadcast_to_run(run_id, {
                            "type": "status",
                            "payload": {"message": "Node.js setup failed (agents will use global npm)", "phase": "init"}
                        })
            except asyncio.TimeoutError:
                logger.warning(f"Venv creation timed out - agents may need to create manually")
            except Exception as e:
                logger.warning(f"Venv creation failed: {e} - agents may need to create manually")
        else:
            logger.info(f"Shared venv already exists at {venv_path}")
            await api_state.manager.broadcast_to_run(run_id, {
                "type": "status",
                "payload": {"message": "Using existing virtual environment", "phase": "init"}
            })

        # Create config
        config = OrchestratorConfig(mock_mode=False)

        # Create worktree manager (uses run-data path OUTSIDE workspace)
        worktree_base = config.get_worktree_base(run_id)
        worktree_base.mkdir(parents=True, exist_ok=True)

        wt_manager = WorktreeManager(
            repo_path=workspace_path,
            worktree_base=worktree_base
        )

        # Create graph
        orchestrator = get_orchestrator_graph()

        # Initial state
        initial_state = {
            "run_id": run_id,
            "objective": objective,
            "spec": spec or {},
            "tasks": [],
            "insights": [],
            "design_log": [],
            "task_memories": {},
            "filesystem_index": {},
            "guardian": {},
            "strategy_status": "progressing",
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
            "mock_mode": False,
            "_wt_manager": wt_manager,
            "_workspace_path": str(workspace_path),
            "_worktree_base_path": str(worktree_base),  # Worktrees outside workspace
            "_logs_base_path": str(config.get_llm_logs_path(run_id)),  # LLM logs outside workspace
            "orch_config": config,
        }

        run_config = {
            "configurable": {
                "thread_id": thread_id,
                "mock_mode": False
            }
        }

        # Send initialization complete message
        await api_state.manager.broadcast_to_run(run_id, {
            "type": "status",
            "payload": {"message": "Initialization complete - starting orchestrator...", "phase": "ready"}
        })

        # Use continuous dispatch (non-blocking worker execution)
        # instead of LangGraph's blocking superstep model
        await continuous_dispatch_loop(run_id, initial_state, run_config)

    except Exception as e:
        logger.error(f"Critical error in run execution logic: {e}")
        import traceback
        traceback.print_exc()


async def run_orchestrator(run_id: str, thread_id: str, objective: str, spec: dict = None, workspace: str = None):
    """
    Execute the orchestrator graph.
    """
    logger.info(f"Starting run {run_id}")

    # Setup workspace
    if not workspace:
        workspace = "projects/workspace"

    workspace_path = Path(workspace).resolve()
    workspace_path.mkdir(parents=True, exist_ok=True)

    # Setup file logging for this run
    # This mimics main.py's logging behavior
    log_dir = workspace_path / "logs"
    log_dir.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = log_dir / f"run_{timestamp}.log"

    # Add file handler to root logger
    file_handler = logging.FileHandler(log_file, encoding='utf-8')
    file_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
    root_logger = logging.getLogger()
    root_logger.addHandler(file_handler)
    logger.info(f"📝 Logging run to: {log_file}")

    try:
        await execute_run_logic(run_id, thread_id, objective, spec, workspace_path)
    finally:
        # Clean up file handler
        root_logger.removeHandler(file_handler)
        file_handler.close()
        logger.info(f"📝 Closed log file: {log_file}")
