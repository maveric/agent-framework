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
