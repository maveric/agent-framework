# Performance Instrumentation Guide

**Purpose**: Identify bottlenecks and measure system performance

## Current Blind Spots

You're flying blind because you don't have:
- Task execution timings
- Node transition times  
- Queue depth metrics
- LLM API latency breakdown
- Waiting vs working time ratios

## Quick Wins: Add Timing Instrumentation

### 1. Task-Level Timing (Worker Node)

Add to `worker_node()` at start and end:

```python
# At start
start_time = datetime.now()
task_dict["started_at"] = start_time.isoformat()

# At end (before return)
end_time = datetime.now()
duration = (end_time - start_time).total_seconds()
task_dict["duration_seconds"] = duration
print(f"  ⏱️  Task {task_id[:8]} completed in {duration:.1f}s", flush=True)
```

### 2. Node Execution Timing (All Nodes)

Add decorator to director, worker, strategist:

```python
import functools
import time

def time_node(node_name):
    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            start = time.time()
            result = await func(*args, **kwargs)
            duration = time.time() - start
            print(f"📊 Node '{node_name}' took {duration:.2f}s", flush=True)
            return result
        return wrapper
    return decorator

# Usage:
@time_node("director")
async def director_node(...):
    ...
```

### 3. LLM API Latency Tracking

Already have `llm_logger.py` - enhance it:

```python
# Add to log_llm_response
def log_llm_response(task_id, response, duration_ms):
    print(f"  🤖 LLM responded in {duration_ms}ms", flush=True)
    # Log to file with histogram data
```

### 4. Queue Metrics (Routing)

Add to `route_after_director`:

```python
ready_count = len(ready_tasks)
active_count = len([t for t in tasks if t.get("status") == "active"])
waiting_count = len([t for t in tasks if t.get("status") == "planned"])

print(f"📈 Queue: {ready_count} ready, {active_count} active, {waiting_count} waiting", flush=True)
```

## Where to Look First

### Hypothesis 1: LLM API Latency
**Check**: Are you spending most time waiting for OpenAI/Anthropic?

```python
# Add in _execute_react_loop before agent.invoke
llm_start = time.time()
result = await agent.ainvoke(inputs, config={"recursion_limit": 50})
llm_duration = time.time() - llm_start
print(f"  🕐 LLM execution: {llm_duration:.1f}s", flush=True)
```

**If this is slow**: Consider parallel LLM calls, cheaper models for simple tasks, or caching.

### Hypothesis 2: File I/O in Worktrees
**Check**: Is git worktree creation/commits slow?

```python
# Add timing in git_manager.py create_worktree and commit_changes
start = time.time()
subprocess.run(...)
print(f"  Git operation took {time.time() - start:.2f}s", flush=True)
```

**If this is slow**: Consider batching commits or using git worktree less aggressively.

### Hypothesis 3: Superstep Blocking
**Check**: Are tasks waiting unnecessarily?

Look for patterns like:
```
Task A: 30s
Task B: 600s  ← Blocking everything
Task C: 30s
Next batch starts at 600s (could've started at 30s)
```

**If this is the issue**: Implement continuous dispatch optimization.

### Hypothesis 4: Sequential Node Execution
**Check**: Is the Director → Worker → Strategist → Director cycle slow?

Time the full loop:
```python
# In server.py _stream_and_broadcast
loop_start = time.time()
# ... after each node
print(f"Graph loop iteration: {time.time() - loop_start:.1f}s", flush=True)
```

## Performance Dashboard

Create a simple performance log aggregator:

```python
# src/perf_stats.py
from collections import defaultdict
from datetime import datetime

class PerfStats:
    def __init__(self):
        self.timings = defaultdict(list)
    
    def record(self, category, duration_s):
        self.timings[category].append({
            "timestamp": datetime.now().isoformat(),
            "duration": duration_s
        })
    
    def summary(self):
        for category, records in self.timings.items():
            durations = [r["duration"] for r in records]
            avg = sum(durations) / len(durations)
            p50 = sorted(durations)[len(durations)//2]
            p95 = sorted(durations)[int(len(durations)*0.95)]
            print(f"{category}: avg={avg:.1f}s, p50={p50:.1f}s, p95={p95:.1f}s")

# Global instance
perf_stats = PerfStats()
```

Use it:
```python
start = time.time()
result = await some_operation()
perf_stats.record("worker_execution", time.time() - start)
```

## Action Plan

1. **Add task duration logging** (5 minutes)
2. **Add queue depth metrics** (10 minutes)  
3. **Run a test objective** and capture logs
4. **Analyze where time is spent**:
   - Waiting for LLM?
   - Git operations?
   - Task batching?
5. **Optimize the actual bottleneck** (don't guess!)

## Expected Findings

My bet based on your architecture:
- **60-80%** time in LLM API calls (network + inference)
- **10-20%** time in git operations (worktree + commits)
- **5-10%** time in superstep synchronization
- **5-10%** everything else

If I'm wrong and superstep sync is >30%, then the continuous dispatch optimization is worth it.
