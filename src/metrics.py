"""
Agent Orchestrator — Metrics Collection
========================================
Prometheus metrics for observability.

Usage:
    from metrics import git_metrics, task_metrics

    # Record a merge duration
    with git_metrics.merge_duration.time():
        result = await merge_to_main(task_id)

    # Increment success counter
    git_metrics.merge_total.labels(result='success').inc()
"""

from prometheus_client import Counter, Histogram, Gauge, Summary, Info
import time
from contextlib import contextmanager
from typing import Optional


# =============================================================================
# GIT METRICS
# =============================================================================

class GitMetrics:
    """Metrics for git operations"""

    def __init__(self):
        # Duration metrics
        self.merge_duration = Histogram(
            'git_merge_duration_seconds',
            'Time to merge a task branch to main',
            buckets=[0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0, 120.0]
        )

        self.checkout_duration = Histogram(
            'git_checkout_duration_seconds',
            'Time to checkout main branch',
            buckets=[0.01, 0.05, 0.1, 0.5, 1.0, 2.0]
        )

        self.conflict_resolution_duration = Histogram(
            'git_conflict_resolution_duration_seconds',
            'Time for LLM to resolve merge conflicts',
            buckets=[1.0, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0]
        )

        self.worktree_creation_duration = Histogram(
            'git_worktree_creation_duration_seconds',
            'Time to create a new worktree',
            buckets=[0.1, 0.5, 1.0, 2.0, 5.0]
        )

        # Success/failure counters
        self.merge_total = Counter(
            'git_merge_total',
            'Total merge attempts',
            ['result']  # Labels: success, conflict, error
        )

        self.conflict_resolution_total = Counter(
            'git_conflict_resolution_total',
            'LLM conflict resolution attempts',
            ['result', 'method']  # result: success/failure, method: llm/auto/manual
        )

        self.worktree_operations_total = Counter(
            'git_worktree_operations_total',
            'Worktree operations',
            ['operation', 'result']  # operation: create/cleanup, result: success/error
        )

        # Concurrency metrics
        self.active_merges = Gauge(
            'git_active_merges',
            'Number of merges currently in progress'
        )

        self.merge_queue_depth = Gauge(
            'git_merge_queue_depth',
            'Number of tasks waiting to merge (0 if no queue)'
        )

        self.lock_wait_duration = Histogram(
            'git_lock_wait_duration_seconds',
            'Time spent waiting for merge lock',
            buckets=[0.01, 0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0]
        )

        # File/conflict stats
        self.files_modified_per_merge = Histogram(
            'git_files_modified_per_merge',
            'Number of files modified in a single merge',
            buckets=[1, 2, 5, 10, 20, 50, 100]
        )

        self.conflicts_per_merge = Histogram(
            'git_conflicts_per_merge',
            'Number of conflicted files in a merge',
            buckets=[0, 1, 2, 5, 10, 20]
        )

    @contextmanager
    def track_merge(self):
        """Context manager to track a merge operation"""
        self.active_merges.inc()
        start = time.time()
        result = "error"
        conflict_count = 0

        try:
            # Yield a dict to collect metadata
            metadata = {"result": "success", "conflict_count": 0, "files_modified": 0}
            yield metadata

            # Extract result from metadata
            result = metadata.get("result", "success")
            conflict_count = metadata.get("conflict_count", 0)
            files_modified = metadata.get("files_modified", 0)

            # Record file stats
            if files_modified > 0:
                self.files_modified_per_merge.observe(files_modified)
            if conflict_count >= 0:
                self.conflicts_per_merge.observe(conflict_count)

        finally:
            duration = time.time() - start
            self.merge_duration.observe(duration)
            self.merge_total.labels(result=result).inc()
            self.active_merges.dec()


# =============================================================================
# TASK METRICS
# =============================================================================

class TaskMetrics:
    """Metrics for task execution"""

    def __init__(self):
        # Duration metrics
        self.execution_duration = Histogram(
            'task_execution_duration_seconds',
            'Worker task execution time',
            ['worker_profile', 'phase'],
            buckets=[1.0, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0, 600.0]
        )

        self.director_cycle_duration = Histogram(
            'director_cycle_duration_seconds',
            'Time for one director iteration',
            buckets=[0.1, 0.5, 1.0, 2.0, 5.0, 10.0]
        )

        # Completion counters
        self.completion_total = Counter(
            'task_completion_total',
            'Task completions',
            ['status', 'worker_profile']  # status: success/failed/retry
        )

        self.retry_count = Histogram(
            'task_retry_count',
            'Number of retries before success/failure',
            buckets=[0, 1, 2, 3, 4, 5]
        )

        # State counters (current task states)
        self.tasks_by_state = Gauge(
            'tasks_by_state',
            'Current number of tasks in each state',
            ['status']  # planned, ready, active, complete, failed, etc.
        )

        self.active_workers = Gauge(
            'active_workers',
            'Number of workers currently executing',
            ['worker_profile']
        )

        # Phoenix protocol metrics
        self.phoenix_retry_total = Counter(
            'phoenix_retry_total',
            'Phoenix protocol retry attempts',
            ['phase', 'attempt']  # phase: plan/build/test, attempt: 1-4
        )

        self.hitl_escalation_total = Counter(
            'hitl_escalation_total',
            'Tasks escalated to human intervention',
            ['reason']  # max_retries, ambiguity, etc.
        )


# =============================================================================
# LLM METRICS
# =============================================================================

class LLMMetrics:
    """Metrics for LLM API calls"""

    def __init__(self):
        # Request counters
        self.requests_total = Counter(
            'llm_requests_total',
            'Total LLM API calls',
            ['model', 'provider', 'result']  # result: success, rate_limit, error, timeout
        )

        # Token usage
        self.tokens_total = Counter(
            'llm_tokens_total',
            'Total tokens used',
            ['model', 'type']  # type: prompt, completion
        )

        # Cost tracking
        self.cost_dollars_total = Counter(
            'llm_cost_dollars_total',
            'Estimated LLM costs in USD',
            ['model', 'provider']
        )

        # Duration
        self.request_duration = Histogram(
            'llm_request_duration_seconds',
            'LLM API request duration',
            ['model', 'provider'],
            buckets=[0.5, 1.0, 2.0, 5.0, 10.0, 20.0, 30.0, 60.0]
        )

        # Rate limit tracking
        self.rate_limit_events = Counter(
            'llm_rate_limit_events_total',
            'Rate limit errors encountered',
            ['model', 'provider']
        )

        self.retry_attempts = Counter(
            'llm_retry_attempts_total',
            'Number of retries due to transient errors',
            ['model', 'provider', 'error_type']
        )

    @contextmanager
    def track_request(self, model: str, provider: str):
        """Context manager to track an LLM request"""
        start = time.time()
        result = "error"
        metadata = {
            "result": "success",
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "cost": 0.0
        }

        try:
            yield metadata
            result = metadata.get("result", "success")

            # Record token usage
            prompt_tokens = metadata.get("prompt_tokens", 0)
            completion_tokens = metadata.get("completion_tokens", 0)
            if prompt_tokens > 0:
                self.tokens_total.labels(model=model, type="prompt").inc(prompt_tokens)
            if completion_tokens > 0:
                self.tokens_total.labels(model=model, type="completion").inc(completion_tokens)

            # Record cost
            cost = metadata.get("cost", 0.0)
            if cost > 0:
                self.cost_dollars_total.labels(model=model, provider=provider).inc(cost)

        except Exception as e:
            result = "error"
            raise
        finally:
            duration = time.time() - start
            self.request_duration.labels(model=model, provider=provider).observe(duration)
            self.requests_total.labels(model=model, provider=provider, result=result).inc()


# =============================================================================
# DISPATCH METRICS
# =============================================================================

class DispatchMetrics:
    """Metrics for the dispatch loop"""

    def __init__(self):
        self.loop_iterations = Counter(
            'dispatch_loop_iterations_total',
            'Number of dispatch loop iterations',
            ['run_id']
        )

        self.loop_cycle_duration = Histogram(
            'dispatch_loop_cycle_duration_seconds',
            'Time for one dispatch loop cycle',
            buckets=[0.1, 0.5, 1.0, 2.0, 5.0, 10.0]
        )

        self.tasks_dispatched_per_cycle = Histogram(
            'dispatch_tasks_dispatched_per_cycle',
            'Number of tasks dispatched in one cycle',
            buckets=[0, 1, 2, 5, 10, 20]
        )

        self.worker_completions_per_cycle = Histogram(
            'dispatch_worker_completions_per_cycle',
            'Number of workers that completed in one cycle',
            buckets=[0, 1, 2, 5, 10, 20]
        )


# =============================================================================
# GLOBAL INSTANCES
# =============================================================================

git_metrics = GitMetrics()
task_metrics = TaskMetrics()
llm_metrics = LLMMetrics()
dispatch_metrics = DispatchMetrics()


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def update_task_state_gauges(tasks: list):
    """Update task state gauges based on current task list"""
    from collections import Counter

    # Count tasks by status
    status_counts = Counter(t.get("status") for t in tasks)

    # Update gauges
    for status in ["planned", "ready", "active", "awaiting_qa", "complete", "failed", "waiting_human", "blocked"]:
        count = status_counts.get(status, 0)
        task_metrics.tasks_by_state.labels(status=status).set(count)


def estimate_llm_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """
    Estimate cost based on current pricing (as of Nov 2024).
    This is approximate - update with actual pricing.
    """
    # Pricing per 1M tokens (input, output)
    pricing = {
        "gpt-4-turbo": (10.0, 30.0),
        "gpt-4": (30.0, 60.0),
        "gpt-3.5-turbo": (0.5, 1.5),
        "claude-3-opus": (15.0, 75.0),
        "claude-3-sonnet": (3.0, 15.0),
        "claude-3-haiku": (0.25, 1.25),
        "claude-sonnet-4": (3.0, 15.0),
    }

    # Default to reasonable estimate if model not found
    input_price, output_price = pricing.get(model, (5.0, 15.0))

    # Calculate cost
    input_cost = (prompt_tokens / 1_000_000) * input_price
    output_cost = (completion_tokens / 1_000_000) * output_price

    return input_cost + output_cost
