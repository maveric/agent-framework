# Continuous Task Dispatch Optimization

**Status**: Future Enhancement  
**Problem**: LangGraph superstep synchronization causes batch blocking  
**Impact**: Long-running tasks delay dispatch of newly-ready tasks

## Current Architecture Limitation

LangGraph executes in **supersteps**:

```
Director → [Send(worker1), Send(worker2), Send(worker3)]
         ↓ (all run in parallel)
    Wait for ALL to complete (even if worker2 takes 10 minutes)
         ↓
Director → Evaluate newly-ready tasks → Next batch
```

**Bottleneck**: If one task in a batch takes significantly longer than others, all newly-unblocked tasks must wait.

## Proposed Solution: Background Task Queue

Replace `Send()` dispatch with a continuous polling loop:

### Architecture Changes

1. **Task Completion Queue** (`src/task_queue.py`)
   - Tracks background asyncio tasks
   - Collects completion results
   - Provides active task count

2. **Modified Routing** (`route_after_director`)
   - Dispatch tasks via `asyncio.create_task()` (non-blocking)
   - Immediately return to Director (no waiting)
   - Director polls for completions on each cycle

3. **Continuous Loop**
   ```
   Director → Dispatch ready tasks as background
           ↓ (returns immediately)
   Director → Check completions, dispatch newly-ready
           ↓ (loop continues while work active)
   Director → Process results, dispatch more...
   ```

### Benefits

- **2-3x throughput** with mixed task durations
- Long tasks don't block short tasks
- Better resource utilization
- Keep LangGraph for state/checkpointing

### Tradeoffs

- Polling overhead (Director runs continuously)
- State updates happen "between" graph steps
- More complex testing/debugging

### Implementation Outline

See conversation for detailed code examples of:
- `TaskCompletionQueue` class
- `route_after_director` modifications  
- `_run_worker_background` function
- Director completion processing

### When to Implement

Implement this if profiling shows:
- High variance in task execution times (10s vs 10min)
- Many tasks blocked waiting for batch completion
- Superstep synchronization is a proven bottleneck

**Recommendation**: Profile first (see `performance-instrumentation.md`), implement if needed.

## Alternative: Temporal.io

For production scale-out (multiple machines, true distributed parallelism), consider migrating to Temporal.io workflow engine. Significant refactor but designed for this use case.

---

## Implementation Plan (Active)

**Status**: IN PROGRESS  
**Started**: December 2025

### Phase 1: Task Completion Queue

Create `src/task_queue.py`:

```python
import asyncio
from typing import Dict, Any, Optional
from dataclasses import dataclass

@dataclass
class CompletedTask:
    task_id: str
    result: Any
    error: Optional[Exception] = None

class TaskCompletionQueue:
    """Tracks background worker tasks and collects results."""
    
    def __init__(self):
        self._running: Dict[str, asyncio.Task] = {}
        self._completed: list[CompletedTask] = []
    
    def spawn(self, task_id: str, coro) -> None:
        """Spawn worker as background task."""
        async_task = asyncio.create_task(self._wrap(task_id, coro))
        self._running[task_id] = async_task
    
    async def _wrap(self, task_id: str, coro):
        try:
            result = await coro
            self._completed.append(CompletedTask(task_id, result))
        except Exception as e:
            self._completed.append(CompletedTask(task_id, None, e))
        finally:
            self._running.pop(task_id, None)
    
    def collect_completed(self) -> list[CompletedTask]:
        completed = self._completed
        self._completed = []
        return completed
    
    @property
    def active_count(self) -> int:
        return len(self._running)
    
    @property
    def has_work(self) -> bool:
        return bool(self._running)
```

### Phase 2: Modify Director Node

Add at start of `director_node()` in `src/nodes/director.py`:

```python
# Process completed background workers
task_queue = state.get("_task_queue")
if task_queue:
    for c in task_queue.collect_completed():
        for t in state["tasks"]:
            if t["id"] == c.task_id:
                if c.error:
                    t["status"] = "failed"
                    t["error"] = str(c.error)
                else:
                    _apply_worker_result(t, c.result)
                break
```

### Phase 3: Replace Send() in Routing

Modify `route_after_director()` in `src/nodes/routing.py`:

```python
task_queue = state.get("_task_queue")
if task_queue:
    for t in tasks_to_dispatch:
        t["status"] = "active"
        task_queue.spawn(t["id"], _run_worker_background(t["id"], state))
    
    # Return to director immediately
    if task_queue.has_work:
        return "director"
    return "__end__"
```

### Phase 4: Initialize Queue

Add to initial state in `server.py` and `langgraph_definition.py`:

```python
"_task_queue": TaskCompletionQueue(),
```

### Files Changed

| File | Change |
|------|--------|
| `src/task_queue.py` | NEW |
| `src/nodes/director.py` | Add completion processing |
| `src/nodes/routing.py` | Replace Send() with spawn() |
| `src/langgraph_definition.py` | Add queue to state |
| `src/server.py` | Add queue to state |
