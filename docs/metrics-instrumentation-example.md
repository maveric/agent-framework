# Metrics Instrumentation Examples

## How to Add Metrics to git_manager.py

### Example 1: Track Merge Operations

```python
# In git_manager.py, update merge_to_main:

from metrics import git_metrics  # Add this import

async def merge_to_main(self, task_id: str) -> MergeResult:
    """Merge a task's branch to main (with metrics)."""

    # Track the merge operation
    with git_metrics.track_merge() as metadata:
        info = self.worktrees.get(task_id)
        if not info:
            metadata["result"] = "error"
            return MergeResult(success=False, task_id=task_id,
                             error_message="No worktree found")

        # ... existing merge logic ...

        # Example: Track checkout duration
        checkout_start = time.time()
        subprocess.run(["git", "checkout", self.main_branch], ...)
        git_metrics.checkout_duration.observe(time.time() - checkout_start)

        # Attempt merge
        result = subprocess.run(
            ["git", "merge", info.branch_name, "--no-ff", "-m", f"Merge {task_id}"],
            cwd=self.repo_path,
            capture_output=True
        )

        if result.returncode == 0:
            # SUCCESS
            metadata["result"] = "success"
            metadata["files_modified"] = len(info.files_modified)
            metadata["conflict_count"] = 0
            return MergeResult(success=True, task_id=task_id)
        else:
            # CONFLICT
            conflicted_files = self._get_conflicted_files()
            conflict_count = len(conflicted_files)

            metadata["result"] = "conflict"
            metadata["conflict_count"] = conflict_count
            git_metrics.conflicts_per_merge.observe(conflict_count)

            # Try LLM resolution
            if await _llm_resolve_conflict(self.repo_path, conflicted_files):
                metadata["result"] = "success"
                git_metrics.conflict_resolution_total.labels(
                    result="success",
                    method="llm"
                ).inc()
                return MergeResult(success=True, task_id=task_id, llm_resolved=True)
            else:
                git_metrics.conflict_resolution_total.labels(
                    result="failure",
                    method="llm"
                ).inc()
                return MergeResult(success=False, task_id=task_id, conflict=True)
```

### Example 2: Track LLM Conflict Resolution

```python
# In git_manager.py, update _llm_resolve_conflict:

from metrics import git_metrics
import time

async def _llm_resolve_conflict(repo_path: Path, conflicted_files: List[str]) -> bool:
    """Use LLM to resolve merge conflicts (with metrics)."""

    resolution_start = time.time()

    try:
        # ... existing LLM resolution logic ...

        for file_path in conflicted_files:
            # Resolve file...
            pass

        # Record success
        duration = time.time() - resolution_start
        git_metrics.conflict_resolution_duration.observe(duration)

        return True

    except Exception as e:
        duration = time.time() - resolution_start
        git_metrics.conflict_resolution_duration.observe(duration)
        logger.error(f"LLM conflict resolution failed: {e}")
        return False
```

### Example 3: Track Worktree Creation

```python
# In git_manager.py, update create_worktree:

def create_worktree(self, task_id: str, retry_number: int = 0) -> WorktreeInfo:
    """Create worktree (with metrics)."""

    start_time = time.time()

    try:
        # ... existing worktree creation logic ...

        subprocess.run(
            ["git", "worktree", "add", "--force", str(wt_path), branch_name],
            cwd=self.repo_path,
            check=True
        )

        # Record success
        git_metrics.worktree_creation_duration.observe(time.time() - start_time)
        git_metrics.worktree_operations_total.labels(
            operation="create",
            result="success"
        ).inc()

        return info

    except subprocess.CalledProcessError as e:
        # Record failure
        git_metrics.worktree_creation_duration.observe(time.time() - start_time)
        git_metrics.worktree_operations_total.labels(
            operation="create",
            result="error"
        ).inc()
        raise
```

## How to Add Metrics to worker.py

### Example: Track Task Execution Duration

```python
# In worker.py:

from metrics import task_metrics
import time

async def worker_node(state: Dict[str, Any], config: RunnableConfig = None):
    task_id = state.get("task_id")
    task_dict = next((t for t in state.get("tasks", []) if t["id"] == task_id), None)
    task = _dict_to_task(task_dict)

    profile = task.assigned_worker_profile
    phase = task.phase

    # Track execution duration
    execution_start = time.time()

    try:
        result = await handler(task, state, config)

        # Record duration
        duration = time.time() - execution_start
        task_metrics.execution_duration.labels(
            worker_profile=profile.value,
            phase=phase.value
        ).observe(duration)

        # Record completion
        status = "success" if result.status == "complete" else "failed"
        task_metrics.completion_total.labels(
            status=status,
            worker_profile=profile.value
        ).inc()

        # Track retry count
        if hasattr(task, 'retry_count') and task.retry_count:
            task_metrics.retry_count.observe(task.retry_count)

        return result

    except Exception as e:
        duration = time.time() - execution_start
        task_metrics.execution_duration.labels(
            worker_profile=profile.value,
            phase=phase.value
        ).observe(duration)

        task_metrics.completion_total.labels(
            status="error",
            worker_profile=profile.value
        ).inc()

        raise
```

## How to Add Metrics to dispatch.py

### Example: Track Dispatch Loop Performance

```python
# In dispatch.py, continuous_dispatch_loop:

from metrics import dispatch_metrics, task_metrics, update_task_state_gauges

async def continuous_dispatch_loop(run_id: str, ...) -> None:
    iteration = 0

    while iteration < max_iterations:
        iteration += 1
        cycle_start = time.time()

        # ... existing dispatch logic ...

        # Record cycle metrics
        cycle_duration = time.time() - cycle_start
        dispatch_metrics.loop_cycle_duration.observe(cycle_duration)
        dispatch_metrics.loop_iterations.labels(run_id=run_id).inc()

        # Update task state gauges
        update_task_state_gauges(state.get("tasks", []))

        # Track dispatches and completions
        dispatch_metrics.tasks_dispatched_per_cycle.observe(len(ready_tasks))
        dispatch_metrics.worker_completions_per_cycle.observe(len(completed))
```

## How to Add Metrics to llm_client.py

### Example: Track LLM API Calls

```python
# In llm_client.py or wherever you call the LLM:

from metrics import llm_metrics, estimate_llm_cost

async def invoke_llm(model_config, prompt):
    model_name = model_config.model_name
    provider = model_config.provider

    with llm_metrics.track_request(model=model_name, provider=provider) as metadata:
        try:
            response = await llm.ainvoke(prompt)

            # Extract token usage from response
            if hasattr(response, 'response_metadata'):
                usage = response.response_metadata.get('usage', {})
                prompt_tokens = usage.get('prompt_tokens', 0)
                completion_tokens = usage.get('completion_tokens', 0)

                metadata["prompt_tokens"] = prompt_tokens
                metadata["completion_tokens"] = completion_tokens

                # Estimate cost
                cost = estimate_llm_cost(model_name, prompt_tokens, completion_tokens)
                metadata["cost"] = cost

                metadata["result"] = "success"

            return response

        except RateLimitError as e:
            metadata["result"] = "rate_limit"
            llm_metrics.rate_limit_events.labels(
                model=model_name,
                provider=provider
            ).inc()
            raise

        except TimeoutError as e:
            metadata["result"] = "timeout"
            raise
```

## Testing the Metrics

### 1. Start your server:
```bash
python src/server.py
```

### 2. Check metrics endpoint:
```bash
curl http://localhost:8000/metrics
```

You should see output like:
```
# HELP git_merge_duration_seconds Time to merge a task branch to main
# TYPE git_merge_duration_seconds histogram
git_merge_duration_seconds_bucket{le="0.1"} 0.0
git_merge_duration_seconds_bucket{le="0.5"} 2.0
git_merge_duration_seconds_bucket{le="1.0"} 5.0
...

# HELP task_execution_duration_seconds Worker task execution time
# TYPE task_execution_duration_seconds histogram
task_execution_duration_seconds_bucket{phase="build",worker_profile="code_worker",le="1.0"} 0.0
task_execution_duration_seconds_bucket{phase="build",worker_profile="code_worker",le="5.0"} 1.0
...
```

### 3. Run a test task and check metrics:
```bash
# Run a task
curl -X POST http://localhost:8000/runs -d '{"objective": "Test task", ...}'

# Check metrics again
curl http://localhost:8000/metrics | grep git_merge
```

## Key Metrics to Watch

### Git Operations
- `git_merge_duration_seconds` - How long merges take
- `git_active_merges` - Current concurrent merges (should be 0 or 1 with locks)
- `git_merge_total{result="conflict"}` - Conflict rate
- `git_conflict_resolution_total{result="success"}` - LLM success rate

### Task Execution
- `task_execution_duration_seconds` - Worker performance
- `tasks_by_state{status="active"}` - Current workload
- `task_retry_count` - Reliability indicator

### LLM Costs
- `llm_cost_dollars_total` - Running cost tracker
- `llm_rate_limit_events_total` - Rate limit issues

## Next Steps

1. **Add metrics to git_manager.py** (focus on merge operations)
2. **Add metrics to worker.py** (track execution time)
3. **Test the /metrics endpoint**
4. **Set up Prometheus + Grafana** (see next guide)
