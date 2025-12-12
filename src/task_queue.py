"""
Agent Orchestrator — Task Completion Queue
==========================================
Version 1.0 — December 2025

Background task queue for continuous dispatch.
Tracks running workers and collects their results without blocking.
"""

import asyncio
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class CompletedTask:
    """Result from a completed background worker."""
    task_id: str
    result: Any
    error: Optional[Exception] = None
    completed_at: str = field(default_factory=lambda: datetime.now().isoformat())


class TaskCompletionQueue:
    """
    Tracks background worker tasks and collects results.
    
    Usage:
        queue = TaskCompletionQueue()
        queue.spawn("task_123", worker_coro)
        
        # Later...
        for completed in queue.collect_completed():
            apply_result(state, completed)
    """
    
    def __init__(self, max_concurrent: int = 5):
        self._running: Dict[str, asyncio.Task] = {}
        self._completed: List[CompletedTask] = []
        self._max_concurrent = max_concurrent
        self._lock = asyncio.Lock()
    
    def spawn(self, task_id: str, coro) -> bool:
        """
        Spawn worker as background task.
        
        Args:
            task_id: Unique task identifier
            coro: Coroutine to run (e.g., worker_node(...))
            
        Returns:
            True if spawned, False if at capacity
        """
        if len(self._running) >= self._max_concurrent:
            return False
        
        if task_id in self._running:
            print(f"  ⚠️ Task {task_id} already running, skipping spawn", flush=True)
            return False
        
        async_task = asyncio.create_task(self._wrap(task_id, coro))
        self._running[task_id] = async_task
        print(f"  🚀 Spawned background worker for {task_id} ({len(self._running)}/{self._max_concurrent} active)", flush=True)
        return True
    
    async def _wrap(self, task_id: str, coro):
        """Wrap coroutine to capture result/error."""
        import logging
        logger = logging.getLogger(__name__)

        try:
            result = await coro
            async with self._lock:
                self._completed.append(CompletedTask(task_id, result))
            print(f"  ✅ Background worker {task_id[:12]} completed", flush=True)
        except Exception as e:
            async with self._lock:
                self._completed.append(CompletedTask(task_id, None, e))
            logger.error(f"  ❌ Background worker {task_id[:12]} failed: {e}", exc_info=True)
            print(f"  ❌ Background worker {task_id[:12]} failed: {e}", flush=True)
        finally:
            self._running.pop(task_id, None)
    
    def collect_completed(self) -> List[CompletedTask]:
        """Pop all completed tasks (non-blocking)."""
        completed = self._completed
        self._completed = []
        return completed
    
    @property
    def active_count(self) -> int:
        """Number of currently running workers."""
        return len(self._running)
    
    @property
    def available_slots(self) -> int:
        """Number of workers we can still spawn."""
        return self._max_concurrent - len(self._running)
    
    @property
    def has_work(self) -> bool:
        """True if any workers are still running."""
        return bool(self._running)
    
    @property
    def has_completed(self) -> bool:
        """True if there are completed tasks waiting to be collected."""
        return bool(self._completed)
    
    def is_running(self, task_id: str) -> bool:
        """Check if a specific task is currently running."""
        return task_id in self._running
    
    async def wait_for_any(self, timeout: float = 0.5) -> None:
        """
        Wait for at least one task to complete, or timeout.
        
        CRITICAL: This does NOT collect completed tasks - that's Phase 1's job.
        This only waits for tasks to finish, leaving collection to the caller.
        
        Args:
            timeout: Max seconds to wait
        """
        if not self._running:
            return
        
        # Wait for any task to complete or timeout
        try:
            await asyncio.wait(
                list(self._running.values()),
                timeout=timeout,
                return_when=asyncio.FIRST_COMPLETED
            )
        except Exception as e:
            # Log the exception - don't swallow silently!
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Error in wait_for_any: {e}", exc_info=True)

        # Do NOT collect here - Phase 1 is the sole collection point
    
    async def cancel_task(self, task_id: str) -> bool:
        """
        Cancel a specific running task by ID.
        
        Args:
            task_id: The task to cancel
            
        Returns:
            True if task was running and cancelled, False if not found
        """
        if task_id not in self._running:
            return False
        
        task = self._running[task_id]
        print(f"  ⚠️ Cancelling specific task {task_id[:12]}", flush=True)
        task.cancel()
        
        # Wait for cancellation to complete
        try:
            await task
        except asyncio.CancelledError:
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"Task {task_id[:12]} was cancelled during cancellation cleanup")
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Error cancelling task {task_id[:12]}: {e}", exc_info=True)
        
        self._running.pop(task_id, None)
        return True

    async def cancel_all(self):
        """Cancel all running tasks (for shutdown)."""
        for task_id, task in list(self._running.items()):
            print(f"  ⚠️ Cancelling task {task_id}", flush=True)
            task.cancel()
        
        # Wait for cancellations to complete
        if self._running:
            await asyncio.gather(*self._running.values(), return_exceptions=True)
        
        self._running.clear()

