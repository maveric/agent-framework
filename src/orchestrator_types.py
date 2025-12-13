"""
Agent Orchestrator — Type Definitions
=====================================
Version 2.3 — November 2025

Core data structures for the agent orchestration framework.
These types are designed for LangGraph compatibility.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Literal, Optional, Sequence, Union
from langchain_core.messages import BaseMessage


# =============================================================================
# ENUMS
# =============================================================================

class TaskStatus(str, Enum):
    """All possible states a task can be in."""
    PLANNED = "planned"           # Task exists, dependencies known, not yet evaluated
    READY = "ready"               # All prerequisites met, can be executed
    BLOCKED = "blocked"           # Cannot proceed (missing deps or external wait)
    ACTIVE = "active"             # Worker currently executing
    AWAITING_QA = "awaiting_qa"   # Artifact produced, waiting for Strategist
    FAILED_QA = "failed_qa"       # Strategist rejected, candidate for Phoenix
    FAILED = "failed"             # Task execution failed (error/exception)
    COMPLETE = "complete"         # Strategist approved, task done
    WAITING_HUMAN = "waiting_human"  # Needs human input (max retries or ambiguity)
    ABANDONED = "abandoned"       # Removed due to re-planning
    
    # Pending states (awaiting Director confirmation - eliminates race conditions)
    PENDING_AWAITING_QA = "pending_awaiting_qa"  # Worker done, awaiting director sync
    PENDING_COMPLETE = "pending_complete"         # QA passed, awaiting director sync
    PENDING_FAILED = "pending_failed"             # Task failed, awaiting director sync


class TaskPhase(str, Enum):
    """Pipeline phase for a task."""
    PLAN = "plan"           # Planning/design phase
    BUILD = "build"         # Implementation/execution phase
    TEST = "test"           # Testing/validation phase


class WorkerProfile(str, Enum):
    """Types of specialized workers."""
    PLANNER = "planner_worker"
    CODER = "code_worker"
    TESTER = "test_worker"
    RESEARCHER = "research_worker"
    WRITER = "writer_worker"
    MERGER = "merge_worker"  # Resolves git merge/rebase conflicts


class GuardianVerdict(str, Enum):
    """Guardian's assessment of task execution."""
    ON_TRACK = "on_track"     # Proceeding normally
    DRIFTING = "drifting"     # Going off-topic
    BLOCKED = "blocked"       # Stuck in circles
    STALLED = "stalled"       # No progress (potential hang/crash)
    UNSAFE = "unsafe"         # Attempting risky actions (future)


class GuardianTrajectory(str, Enum):
    """Direction of worker's alignment over time."""
    IMPROVING = "improving"   # Was off-topic but coming back
    STABLE = "stable"         # Consistent alignment (good or bad)
    WORSENING = "worsening"   # Drifting further off-course


class NudgeTone(str, Enum):
    """Tone of Guardian's intervention, scaled to severity."""
    GENTLE = "gentle"         # Alignment 50-69%: suggestive
    DIRECT = "direct"         # Alignment 25-49%: clear redirect
    FIRM = "firm"             # Alignment 0-24%: stop command


class StrategyStatus(str, Enum):
    """Overall project health assessment."""
    PROGRESSING = "progressing"   # Making forward progress
    STAGNATING = "stagnating"     # Stuck, may need re-planning
    BLOCKED = "blocked"           # Waiting on external input
    PAUSED_INFRA_ERROR = "paused_infra_error"      # Circuit breaker tripped
    PAUSED_HUMAN_REQUESTED = "paused_human_requested"  # Manual pause


class BlockedType(str, Enum):
    """Why a task is blocked."""
    DEPENDENCY = "dependency"           # Waiting on other tasks
    EXTERNAL = "external"               # Waiting on external input (human, API, etc.)
    RESOURCE = "resource"               # No available worker capacity
    DEPENDENCY_ABANDONED = "dependency_abandoned"  # A required dependency was abandoned
    WAITING_SUBTASK = "waiting_subtask"  # Waiting for spawned subtask to complete
    NEEDS_REPLANNING = "needs_replanning"  # Task escalated back to planning


class EscalationType(str, Enum):
    """Types of escalations a worker can raise."""
    NEEDS_RESEARCH = "needs_research"           # Spawn research subtask
    NEEDS_REPLANNING = "needs_replanning"       # Spec is wrong, go back to planning
    NEEDS_CLARIFICATION = "needs_clarification" # Ambiguity, might need human
    BLOCKED_EXTERNAL = "blocked_external"       # Waiting on something outside system
    SPEC_MISMATCH = "spec_mismatch"             # Inconsistency between specs/artifacts
    SCOPE_TOO_LARGE = "scope_too_large"         # Task should be split


# =============================================================================
# SUPPORTING DATA STRUCTURES
# =============================================================================

@dataclass
class BlockedReason:
    """Details about why a task is blocked."""
    type: BlockedType
    description: str
    waiting_on: List[str] = field(default_factory=list)  # Task IDs or external resource names
    since: datetime = field(default_factory=datetime.now)


@dataclass
class Insight:
    """
    Cross-task reusable knowledge.
    Freely posted by workers, immediately available to other tasks.
    """
    id: str
    topic: List[str]              # Tags for relevance filtering (e.g., ["api", "http"])
    summary: str                  # The actual insight
    source_task: str              # Task ID that discovered this
    created_at: datetime = field(default_factory=datetime.now)


@dataclass
class DesignDecision:
    """
    Append-only log entry for important design decisions.
    Persists across Phoenix retries.
    """
    id: str
    area: str                     # Domain area (db, api, ui, research, etc.)
    applies_to: List[str]         # Task IDs this decision affects
    summary: str                  # What was decided
    reason: str                   # Why this decision was made
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class SuggestedTask:
    """
    Worker-proposed task (scope split, new subtask).
    Requires Director approval before entering task graph.
    """
    suggested_id: str             # Proposed ID (Director may change)
    title: str                    # Task title (concise, commit-message style)
    component: str
    phase: TaskPhase
    description: str              # What this task should accomplish
    rationale: str                # Why this task is needed
    depends_on: List[str] = field(default_factory=list)
    acceptance_criteria: List[str] = field(default_factory=list)
    suggested_by_task: str = ""   # Task ID that proposed this
    priority: int = 5             # Suggested priority (1-10)
    dependency_queries: List[str] = field(default_factory=list)  # Natural language descriptions of external dependencies


@dataclass
class Escalation:
    """
    Worker escalation — signals that something is wrong and needs attention.
    
    Workers use this to communicate back to Director that:
    - The spec has issues (SPEC_MISMATCH, NEEDS_REPLANNING)
    - More information is needed (NEEDS_RESEARCH, NEEDS_CLARIFICATION)
    - The task is blocked on external factors (BLOCKED_EXTERNAL)
    - The scope is too large (SCOPE_TOO_LARGE)
    """
    type: EscalationType
    reason: str                             # Detailed explanation of why escalating
    affected_tasks: List[str] = field(default_factory=list)  # Task IDs that need attention
    suggested_action: str = ""              # What the worker thinks should happen
    context: Dict[str, Any] = field(default_factory=dict)  # Supporting details
    spawn_tasks: List["SuggestedTask"] = field(default_factory=list)  # Tasks to create
    blocking: bool = True                   # Does this block current task completion?


@dataclass
class WorkerCheckpoint:
    """
    Saved worker state for checkpoint-and-continue pattern.
    
    When a worker needs to pause (e.g., waiting for subtask), it saves
    its state here so it can resume later.
    """
    task_id: str
    checkpoint_id: str
    partial_work: Dict[str, Any]           # Worker-specific saved state
    files_in_progress: List[str]           # Paths being worked on
    resume_instructions: str               # What to do when resuming
    waiting_for: List[str] = field(default_factory=list)  # Task IDs to wait for
    created_at: datetime = field(default_factory=datetime.now)


# =============================================================================
# QA STRUCTURES
# =============================================================================

@dataclass
class CriterionResult:
    """Result of evaluating a single acceptance criterion."""
    criterion: str                # The criterion text
    passed: bool
    reasoning: str                # Why it passed or failed
    suggestions: Optional[str] = None  # How to fix if failed


@dataclass
class TestFailureAnalysis:
    """
    Analysis of a test failure during QA.
    Strategist investigates whether the test itself is correct.
    """
    test_name: str
    test_correct: bool            # Is the test testing the right thing?
    analysis: str                 # Explanation of why test is right or wrong


@dataclass
class QAVerdict:
    """
    Strategist's full evaluation of a task's artifact.
    Structured to support targeted Phoenix retries.
    
    For BUILD tasks, also includes refined criteria for the test placeholder.
    """
    passed: bool
    criterion_results: List[CriterionResult]
    overall_feedback: str         # Summary assessment
    suggested_focus: Optional[str] = None  # What to focus on if retrying
    
    # Test validity analysis (when test results are available)
    test_analysis: Optional[List[TestFailureAnalysis]] = None
    tests_needing_revision: List[str] = field(default_factory=list)  # Test names that are wrong
    
    # Test placeholder refinement (for BUILD tasks that pass QA)
    refined_test_criteria: Optional[List[str]] = None  # Specific criteria for test task


# =============================================================================
# GUARDIAN STRUCTURES
# =============================================================================

@dataclass
class GuardianMetrics:
    """Metrics passed to Guardian for stall/drift detection."""
    task_id: str
    time_since_last_message_seconds: float
    token_count_since_checkpoint: int
    tool_calls_since_checkpoint: int
    filesystem_writes_since_checkpoint: int
    time_since_last_fs_write_seconds: Optional[float]  # None if no writes yet


@dataclass
class GuardianNudge:
    """
    Guidance injected by Guardian into task's memory.
    
    Includes assessment data for tracking improvement over time.
    """
    task_id: str
    verdict: GuardianVerdict
    message: str                  # The actual guidance to inject
    detected_issue: str           # What triggered this nudge
    
    # Assessment data
    alignment_score: int = 100    # 0-100% alignment with objective
    trajectory: GuardianTrajectory = GuardianTrajectory.STABLE
    tone: Optional[NudgeTone] = None  # None if no nudge needed
    
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class GuardianState:
    """Guardian's tracking state."""
    last_reviewed_task: Optional[str] = None
    last_review_time: Optional[datetime] = None
    last_nudge_time: Optional[datetime] = None
    active_nudges: List[GuardianNudge] = field(default_factory=list)


# =============================================================================
# WORKER STRUCTURES
# =============================================================================

@dataclass
class AAR:
    """
    After Action Report — required from every worker on task completion.
    Summarizes what was done for context and debugging.
    """
    summary: str                  # What was accomplished
    approach: str                 # How it was approached
    challenges: List[str]         # Difficulties encountered
    decisions_made: List[str]     # Key decisions during execution
    files_modified: List[str]     # Paths that were created/changed
    time_spent_estimate: Optional[str] = None  # Rough time estimate


@dataclass
class WorkerResult:
    """
    What a worker returns upon task completion or pause.
    
    Status meanings:
    - "complete": Task finished successfully, ready for QA
    - "blocked": Cannot proceed, needs external resolution
    - "failed": Unrecoverable error occurred
    - "waiting_subtask": Paused, waiting for spawned subtask(s) to complete
    
    AAR is required for all statuses.
    """
    status: Literal["complete", "blocked", "failed", "waiting_subtask"]
    result_path: Optional[str]    # Primary artifact path for QA focus (None if failed/blocked)
    aar: AAR                      # Required: After Action Report
    
    # Optional enrichments
    insights: List[Insight] = field(default_factory=list)  # Reusable knowledge
    suggested_tasks: List[SuggestedTask] = field(default_factory=list)  # Scope changes (need approval)
    messages: List[BaseMessage] = field(default_factory=list)  # LLM conversation history
    
    # Escalation — signals issues that need Director attention
    escalation: Optional[Escalation] = None
    
    # Checkpoint for pause/resume pattern
    checkpoint: Optional[WorkerCheckpoint] = None  # Saved state if waiting_subtask
    
    # Legacy fields (use escalation instead for new code)
    blocked_reason: Optional[str] = None  # If status is "blocked"
    failure_reason: Optional[str] = None  # If status is "failed"


# =============================================================================
# TASK
# =============================================================================

@dataclass
class Task:
    """A single unit of work in the task graph."""
    # Identity
    id: str
    title: str                    # Concise task title (commit-message style)
    component: str                # Domain area (db, api, views, research, etc.)
    phase: TaskPhase
    description: str              # Human-readable description of what to do
    
    # State
    status: TaskStatus = TaskStatus.PLANNED
    
    # Dependencies & Scheduling
    depends_on: List[str] = field(default_factory=list)
    dependency_queries: List[str] = field(default_factory=list)  # Natural language queries for external dependencies
    priority: int = 5             # Higher = more important (1-10 scale)
    assigned_worker_profile: Optional[WorkerProfile] = None
    
    # Execution
    retry_count: int = 0
    max_retries: int = 3          # Before escalating to WAITING_HUMAN
    acceptance_criteria: List[str] = field(default_factory=list)
    
    # Results (populated during/after execution)
    result_path: Optional[str] = None
    qa_verdict: Optional[QAVerdict] = None
    aar: Optional[AAR] = None
    blocked_reason: Optional[BlockedReason] = None
    
    # Escalation — if worker raised an issue
    escalation: Optional[Escalation] = None
    
    # Checkpoint — for pause/resume pattern
    checkpoint: Optional[WorkerCheckpoint] = None
    waiting_for_tasks: List[str] = field(default_factory=list)  # Task IDs this is waiting on
    
    # Git integration
    branch_name: Optional[str] = None      # Git branch for this task's worktree
    worktree_path: Optional[str] = None    # Path to worktree directory
    
    # Timestamps
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    started_at: Optional[datetime] = None  # When became ACTIVE
    completed_at: Optional[datetime] = None


# =============================================================================
# BLACKBOARD STATE (LangGraph Compatible)
# =============================================================================

# For LangGraph, we use TypedDict for the state schema.
# However, we also want dataclass conveniences, so we provide both.

from typing import TypedDict


class BlackboardStateDict(TypedDict, total=False):
    """
    LangGraph-compatible state schema.
    This is the actual type used in the graph.
    """
    # Run identity
    run_id: str
    objective: str
    
    # Persistent context (survives Phoenix)
    spec: Dict[str, Any]                    # Freeform requirements
    design_log: List[Dict[str, Any]]        # DesignDecision as dicts
    insights: List[Dict[str, Any]]          # Insight as dicts
    
    # Task management
    tasks: List[Dict[str, Any]]             # Task as dicts
    
    # Ephemeral (cleared by Phoenix per-task)
    task_memories: Dict[str, List[BaseMessage]]  # task_id -> message history
    
    # Filesystem (metadata only - actual files in git)
    filesystem_index: Dict[str, str]        # path -> branch that owns it
    
    # Control
    guardian: Dict[str, Any]                # GuardianState as dict
    strategy_status: str                    # StrategyStatus value
    
    # Metadata
    created_at: str                         # ISO format
    updated_at: str                         # ISO format


@dataclass
class BlackboardState:
    """
    Convenience dataclass wrapper around BlackboardStateDict.
    Use this for type-safe manipulation, convert to/from dict for LangGraph.
    """
    # Run identity
    run_id: str
    objective: str
    
    # Persistent context (survives Phoenix)
    spec: Dict[str, Any] = field(default_factory=dict)
    design_log: List[DesignDecision] = field(default_factory=list)
    insights: List[Insight] = field(default_factory=list)
    
    # Task management
    tasks: List[Task] = field(default_factory=list)
    
    # Ephemeral (cleared by Phoenix per-task)
    task_memories: Dict[str, List[BaseMessage]] = field(default_factory=dict)
    
    # Filesystem (metadata only - actual files in git)
    filesystem_index: Dict[str, str] = field(default_factory=dict)  # path -> branch
    
    # Control
    guardian: GuardianState = field(default_factory=GuardianState)
    strategy_status: StrategyStatus = StrategyStatus.PROGRESSING
    
    # Metadata
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    
    def to_dict(self) -> BlackboardStateDict:
        """Convert to LangGraph-compatible dict."""
        return {
            "run_id": self.run_id,
            "objective": self.objective,
            "spec": self.spec,
            "design_log": [_design_decision_to_dict(d) for d in self.design_log],
            "insights": [_insight_to_dict(i) for i in self.insights],
            "tasks": [task_to_dict(t) for t in self.tasks],
            "task_memories": self.task_memories,  # BaseMessage is already serializable
            "filesystem_index": self.filesystem_index,
            "guardian": _guardian_state_to_dict(self.guardian),
            "strategy_status": self.strategy_status.value,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }
    
    @classmethod
    def from_dict(cls, data: BlackboardStateDict) -> "BlackboardState":
        """Create from LangGraph dict."""
        return cls(
            run_id=data.get("run_id", ""),
            objective=data.get("objective", ""),
            spec=data.get("spec", {}),
            design_log=[_dict_to_design_decision(d) for d in data.get("design_log", [])],
            insights=[_dict_to_insight(i) for i in data.get("insights", [])],
            tasks=[_dict_to_task(t) for t in data.get("tasks", [])],
            task_memories=data.get("task_memories", {}),
            filesystem_index=data.get("filesystem_index", {}),
            guardian=_dict_to_guardian_state(data.get("guardian", {})),
            strategy_status=StrategyStatus(data.get("strategy_status", "progressing")),
            created_at=datetime.fromisoformat(data["created_at"]) if data.get("created_at") else datetime.now(),
            updated_at=datetime.fromisoformat(data["updated_at"]) if data.get("updated_at") else datetime.now(),
        )


# =============================================================================
# SERIALIZATION HELPERS
# =============================================================================

def _design_decision_to_dict(d: DesignDecision) -> Dict[str, Any]:
    return {
        "id": d.id,
        "area": d.area,
        "applies_to": d.applies_to,
        "summary": d.summary,
        "reason": d.reason,
        "timestamp": d.timestamp.isoformat(),
    }

def _dict_to_design_decision(data: Dict[str, Any]) -> DesignDecision:
    return DesignDecision(
        id=data["id"],
        area=data["area"],
        applies_to=data.get("applies_to", []),
        summary=data["summary"],
        reason=data["reason"],
        timestamp=datetime.fromisoformat(data["timestamp"]) if data.get("timestamp") else datetime.now(),
    )

def _insight_to_dict(i: Insight) -> Dict[str, Any]:
    return {
        "id": i.id,
        "topic": i.topic,
        "summary": i.summary,
        "source_task": i.source_task,
        "created_at": i.created_at.isoformat(),
    }

def _dict_to_insight(data: Dict[str, Any]) -> Insight:
    return Insight(
        id=data["id"],
        topic=data.get("topic", []),
        summary=data["summary"],
        source_task=data["source_task"],
        created_at=datetime.fromisoformat(data["created_at"]) if data.get("created_at") else datetime.now(),
    )

def _blocked_reason_to_dict(b: BlockedReason) -> Dict[str, Any]:
    return {
        "type": b.type.value,
        "description": b.description,
        "waiting_on": b.waiting_on,
        "since": b.since.isoformat(),
    }

def _dict_to_blocked_reason(data: Dict[str, Any]) -> BlockedReason:
    return BlockedReason(
        type=BlockedType(data["type"]),
        description=data["description"],
        waiting_on=data.get("waiting_on", []),
        since=datetime.fromisoformat(data["since"]) if data.get("since") else datetime.now(),
    )

def _criterion_result_to_dict(c: CriterionResult) -> Dict[str, Any]:
    return {
        "criterion": c.criterion,
        "passed": c.passed,
        "reasoning": c.reasoning,
        "suggestions": c.suggestions,
    }

def _dict_to_criterion_result(data: Dict[str, Any]) -> CriterionResult:
    return CriterionResult(
        criterion=data["criterion"],
        passed=data["passed"],
        reasoning=data["reasoning"],
        suggestions=data.get("suggestions"),
    )

def _qa_verdict_to_dict(q: QAVerdict) -> Dict[str, Any]:
    return {
        "passed": q.passed,
        "criterion_results": [_criterion_result_to_dict(c) for c in q.criterion_results],
        "overall_feedback": q.overall_feedback,
        "suggested_focus": q.suggested_focus,
    }

def _dict_to_qa_verdict(data: Dict[str, Any]) -> QAVerdict:
    # Support simplified format from LLM-based evaluation: {passed, feedback, suggestions}
    if "overall_feedback" not in data and "feedback" in data:
        return QAVerdict(
            passed=data["passed"],
            criterion_results=[],
            overall_feedback=data.get("feedback", "No feedback provided"),
            suggested_focus=", ".join(data.get("suggestions", [])) if data.get("suggestions") else None,
        )
    
    # Original detailed format
    return QAVerdict(
        passed=data["passed"],
        criterion_results=[_dict_to_criterion_result(c) for c in data.get("criterion_results", [])],
        overall_feedback=data["overall_feedback"],
        suggested_focus=data.get("suggested_focus"),
    )

def _aar_to_dict(a: AAR) -> Dict[str, Any]:
    return {
        "summary": a.summary,
        "approach": a.approach,
        "challenges": a.challenges,
        "decisions_made": a.decisions_made,
        "files_modified": a.files_modified,
        "time_spent_estimate": a.time_spent_estimate,
    }

def _dict_to_aar(data: Dict[str, Any]) -> AAR:
    return AAR(
        summary=data["summary"],
        approach=data["approach"],
        challenges=data.get("challenges", []),
        decisions_made=data.get("decisions_made", []),
        files_modified=data.get("files_modified", []),
        time_spent_estimate=data.get("time_spent_estimate"),
    )

def task_to_dict(t: Task) -> Dict[str, Any]:
    return {
        "id": t.id,
        "title": t.title,
        "component": t.component,
        "phase": t.phase.value,
        "description": t.description,
        "status": t.status.value,
        "depends_on": t.depends_on,
        "dependency_queries": t.dependency_queries,
        "priority": t.priority,
        "assigned_worker_profile": t.assigned_worker_profile.value if t.assigned_worker_profile else None,
        "retry_count": t.retry_count,
        "max_retries": t.max_retries,
        "acceptance_criteria": t.acceptance_criteria,
        "result_path": t.result_path,
        "qa_verdict": _qa_verdict_to_dict(t.qa_verdict) if t.qa_verdict else None,
        "aar": _aar_to_dict(t.aar) if t.aar else None,
        "blocked_reason": _blocked_reason_to_dict(t.blocked_reason) if t.blocked_reason else None,
        "escalation": _escalation_to_dict(t.escalation) if t.escalation else None,
        "checkpoint": _worker_checkpoint_to_dict(t.checkpoint) if t.checkpoint else None,
        "waiting_for_tasks": t.waiting_for_tasks,
        "branch_name": t.branch_name,
        "worktree_path": t.worktree_path,
        "created_at": t.created_at.isoformat(),
        "updated_at": t.updated_at.isoformat(),
        "started_at": t.started_at.isoformat() if t.started_at else None,
        "completed_at": t.completed_at.isoformat() if t.completed_at else None,
    }

def _dict_to_task(data: Dict[str, Any]) -> Task:
    return Task(
        id=data["id"],
        title=data.get("title", "Untitled"),  # Default for backwards compatibility
        component=data["component"],
        phase=TaskPhase(data["phase"]),
        description=data["description"],
        status=TaskStatus(data.get("status", "planned")),
        depends_on=data.get("depends_on", []),
        dependency_queries=data.get("dependency_queries", []),
        priority=data.get("priority", 5),
        assigned_worker_profile=WorkerProfile(data["assigned_worker_profile"]) if data.get("assigned_worker_profile") else None,
        retry_count=data.get("retry_count", 0),
        max_retries=data.get("max_retries", 3),
        acceptance_criteria=data.get("acceptance_criteria", []),
        result_path=data.get("result_path"),
        qa_verdict=_dict_to_qa_verdict(data["qa_verdict"]) if data.get("qa_verdict") else None,
        aar=_dict_to_aar(data["aar"]) if data.get("aar") else None,
        blocked_reason=_dict_to_blocked_reason(data["blocked_reason"]) if data.get("blocked_reason") else None,
        escalation=_dict_to_escalation(data["escalation"]) if data.get("escalation") else None,
        checkpoint=_dict_to_worker_checkpoint(data["checkpoint"]) if data.get("checkpoint") else None,
        waiting_for_tasks=data.get("waiting_for_tasks", []),
        branch_name=data.get("branch_name"),
        worktree_path=data.get("worktree_path"),
        created_at=datetime.fromisoformat(data["created_at"]) if data.get("created_at") else datetime.now(),
        updated_at=datetime.fromisoformat(data["updated_at"]) if data.get("updated_at") else datetime.now(),
        started_at=datetime.fromisoformat(data["started_at"]) if data.get("started_at") else None,
        completed_at=datetime.fromisoformat(data["completed_at"]) if data.get("completed_at") else None,
    )

def _guardian_state_to_dict(g: GuardianState) -> Dict[str, Any]:
    return {
        "last_reviewed_task": g.last_reviewed_task,
        "last_review_time": g.last_review_time.isoformat() if g.last_review_time else None,
        "last_nudge_time": g.last_nudge_time.isoformat() if g.last_nudge_time else None,
        "active_nudges": [_guardian_nudge_to_dict(n) for n in g.active_nudges],
    }

def _dict_to_guardian_state(data: Dict[str, Any]) -> GuardianState:
    return GuardianState(
        last_reviewed_task=data.get("last_reviewed_task"),
        last_review_time=datetime.fromisoformat(data["last_review_time"]) if data.get("last_review_time") else None,
        last_nudge_time=datetime.fromisoformat(data["last_nudge_time"]) if data.get("last_nudge_time") else None,
        active_nudges=[_dict_to_guardian_nudge(n) for n in data.get("active_nudges", [])],
    )

def _guardian_nudge_to_dict(n: GuardianNudge) -> Dict[str, Any]:
    return {
        "task_id": n.task_id,
        "verdict": n.verdict.value,
        "message": n.message,
        "detected_issue": n.detected_issue,
        "timestamp": n.timestamp.isoformat(),
    }

def _dict_to_guardian_nudge(data: Dict[str, Any]) -> GuardianNudge:
    return GuardianNudge(
        task_id=data["task_id"],
        verdict=GuardianVerdict(data["verdict"]),
        message=data["message"],
        detected_issue=data["detected_issue"],
        timestamp=datetime.fromisoformat(data["timestamp"]) if data.get("timestamp") else datetime.now(),
    )


# =============================================================================
# ESCALATION & CHECKPOINT SERIALIZATION
# =============================================================================

def _escalation_to_dict(e: Escalation) -> Dict[str, Any]:
    return {
        "type": e.type.value,
        "reason": e.reason,
        "affected_tasks": e.affected_tasks,
        "suggested_action": e.suggested_action,
        "context": e.context,
        "spawn_tasks": [_suggested_task_to_dict(s) for s in e.spawn_tasks],
        "blocking": e.blocking,
    }

def _dict_to_escalation(data: Dict[str, Any]) -> Escalation:
    return Escalation(
        type=EscalationType(data["type"]),
        reason=data["reason"],
        affected_tasks=data.get("affected_tasks", []),
        suggested_action=data.get("suggested_action", ""),
        context=data.get("context", {}),
        spawn_tasks=[_dict_to_suggested_task(s) for s in data.get("spawn_tasks", [])],
        blocking=data.get("blocking", True),
    )

def _worker_checkpoint_to_dict(c: WorkerCheckpoint) -> Dict[str, Any]:
    return {
        "task_id": c.task_id,
        "checkpoint_id": c.checkpoint_id,
        "partial_work": c.partial_work,
        "files_in_progress": c.files_in_progress,
        "resume_instructions": c.resume_instructions,
        "waiting_for": c.waiting_for,
        "created_at": c.created_at.isoformat(),
    }

def _dict_to_worker_checkpoint(data: Dict[str, Any]) -> WorkerCheckpoint:
    return WorkerCheckpoint(
        task_id=data["task_id"],
        checkpoint_id=data["checkpoint_id"],
        partial_work=data.get("partial_work", {}),
        files_in_progress=data.get("files_in_progress", []),
        resume_instructions=data["resume_instructions"],
        waiting_for=data.get("waiting_for", []),
        created_at=datetime.fromisoformat(data["created_at"]) if data.get("created_at") else datetime.now(),
    )


# =============================================================================
# WORKER RESULT SERIALIZATION
# =============================================================================

def worker_result_to_dict(w: WorkerResult) -> Dict[str, Any]:
    return {
        "status": w.status,
        "result_path": w.result_path,
        "aar": _aar_to_dict(w.aar),
        "insights": [_insight_to_dict(i) for i in w.insights],
        "suggested_tasks": [_suggested_task_to_dict(s) for s in w.suggested_tasks],
        "escalation": _escalation_to_dict(w.escalation) if w.escalation else None,
        "checkpoint": _worker_checkpoint_to_dict(w.checkpoint) if w.checkpoint else None,
        "blocked_reason": w.blocked_reason,
        "failure_reason": w.failure_reason,
        "messages": w.messages,
    }

def _suggested_task_to_dict(s: SuggestedTask) -> Dict[str, Any]:
    return {
        "suggested_id": s.suggested_id,
        "title": s.title,
        "component": s.component,
        "phase": s.phase.value,
        "description": s.description,
        "rationale": s.rationale,
        "depends_on": s.depends_on,
        "dependency_queries": s.dependency_queries,  # Cross-component dependencies
        "acceptance_criteria": s.acceptance_criteria,
        "suggested_by_task": s.suggested_by_task,
        "priority": s.priority,
    }

def dict_to_worker_result(data: Dict[str, Any]) -> WorkerResult:
    return WorkerResult(
        status=data["status"],
        result_path=data.get("result_path"),
        aar=_dict_to_aar(data["aar"]),
        insights=[_dict_to_insight(i) for i in data.get("insights", [])],
        suggested_tasks=[_dict_to_suggested_task(s) for s in data.get("suggested_tasks", [])],
        escalation=_dict_to_escalation(data["escalation"]) if data.get("escalation") else None,
        checkpoint=_dict_to_worker_checkpoint(data["checkpoint"]) if data.get("checkpoint") else None,
        blocked_reason=data.get("blocked_reason"),
        failure_reason=data.get("failure_reason"),
        messages=data.get("messages", []),
    )

def serialize_messages(messages: List[Any]) -> List[Dict[str, Any]]:
    """Serialize LangChain messages to dicts for persistence."""
    if not messages:
        return []
    
    serialized = []
    for msg in messages:
        # If already a dict (from database), return as-is
        if isinstance(msg, dict):
            serialized.append(msg)
            continue
            
        # Basic fields
        m_dict = {
            "type": msg.type,
            "content": msg.content,
        }
        
        # Add specific fields based on type
        if hasattr(msg, "tool_calls") and msg.tool_calls:
            m_dict["tool_calls"] = msg.tool_calls
            
        if hasattr(msg, "tool_call_id") and msg.tool_call_id:
            m_dict["tool_call_id"] = msg.tool_call_id
            
        if hasattr(msg, "name") and msg.name:
            m_dict["name"] = msg.name
            
        serialized.append(m_dict)
        
    return serialized

def _dict_to_suggested_task(data: Dict[str, Any]) -> SuggestedTask:
    return SuggestedTask(
        suggested_id=data["suggested_id"],
        title=data.get("title", "Untitled"),
        component=data["component"],
        phase=TaskPhase(data["phase"]),
        description=data["description"],
        rationale=data["rationale"],
        depends_on=data.get("depends_on", []),
        dependency_queries=data.get("dependency_queries", []),  # Cross-component dependencies
        acceptance_criteria=data.get("acceptance_criteria", []),
        suggested_by_task=data.get("suggested_by_task", ""),
        priority=data.get("priority", 5),
    )


# =============================================================================
# MODEL CONFIGURATION
# =============================================================================

@dataclass
class ModelConfig:
    """
    Configuration for a single LLM model.
    
    Supports multiple providers: anthropic, openai, google, glm, ollama, azure, bedrock.
    API keys are expected from environment variables, not stored here.
    """
    provider: Literal["anthropic", "openai", "google", "glm", "ollama", "azure", "bedrock"]
    model: str                          # Model identifier (provider-specific)
    temperature: float = 0.7
    max_tokens: int = 4096
    timeout_seconds: int = 120
    # Provider-specific options
    extra: Dict[str, Any] = field(default_factory=dict)
    # Rate limit fallback — different provider/model to use when rate limited
    fallback: Optional["ModelConfig"] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "timeout_seconds": self.timeout_seconds,
            "extra": self.extra,
            "fallback": self.fallback.to_dict() if self.fallback else None,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ModelConfig":
        fallback_data = data.get("fallback")
        return cls(
            provider=data["provider"],
            model=data["model"],
            temperature=data.get("temperature", 0.7),
            max_tokens=data.get("max_tokens", 4096),
            timeout_seconds=data.get("timeout_seconds", 120),
            extra=data.get("extra", {}),
            fallback=cls.from_dict(fallback_data) if fallback_data else None,
        )


# Default model configurations by role
DEFAULT_MODEL_CONFIGS: Dict[str, ModelConfig] = {
    # Orchestration roles
    "director": ModelConfig(provider="anthropic", model="claude-sonnet-4-20250514"),
    "strategist": ModelConfig(provider="anthropic", model="claude-sonnet-4-20250514"),
    "guardian": ModelConfig(provider="anthropic", model="claude-haiku-3-5-20241022", max_tokens=1024),

    # Worker types
    "planner_worker": ModelConfig(provider="anthropic", model="claude-sonnet-4-20250514"),
    "code_worker": ModelConfig(provider="anthropic", model="claude-sonnet-4-20250514"),
    "test_worker": ModelConfig(provider="anthropic", model="claude-sonnet-4-20250514"),
    "research_worker": ModelConfig(provider="anthropic", model="claude-sonnet-4-20250514"),
    "writer_worker": ModelConfig(provider="anthropic", model="claude-sonnet-4-20250514"),
    "merge_worker": ModelConfig(provider="anthropic", model="claude-sonnet-4-20250514"),  # Conflict resolution
}


# =============================================================================
# ERROR HANDLING CONFIGURATION
# =============================================================================

@dataclass
class RetryConfig:
    """
    Retry settings for infrastructure errors.
    
    Separate from task-level Phoenix retries (which handle QA failures).
    These handle transient infrastructure issues like tool timeouts.
    """
    # Tool-level retries (within a single task execution)
    max_tool_retries: int = 3
    tool_retry_backoff_base: float = 1.0    # seconds
    tool_retry_backoff_max: float = 30.0    # cap on backoff
    tool_retry_jitter: float = 0.5          # random jitter factor (0-1)
    
    # Circuit breaker — pauses run on repeated infra failures
    circuit_breaker_threshold: int = 3      # consecutive infra failures to trip
    circuit_breaker_enabled: bool = True    # pause run when tripped
    
    def calculate_backoff(self, attempt: int) -> float:
        """Calculate delay with exponential backoff and jitter."""
        import random
        base_delay = min(
            self.tool_retry_backoff_base * (2 ** attempt),
            self.tool_retry_backoff_max
        )
        jitter = base_delay * self.tool_retry_jitter * random.random()
        return base_delay + jitter


@dataclass
class WebhookConfig:
    """
    Webhook notifications for run events.
    
    Stubbed for future use — not implemented in v1.
    """
    enabled: bool = False
    url: Optional[str] = None
    secret: Optional[str] = None            # For signature verification
    events: List[str] = field(default_factory=list)
    # Supported events (future):
    # - "run_started"
    # - "run_complete"
    # - "run_paused"
    # - "task_complete"
    # - "task_failed"
    # - "human_input_needed"
    timeout_seconds: int = 30
    retry_count: int = 3


# =============================================================================
# EXPORTS
# =============================================================================

__all__ = [
    # Enums
    "TaskStatus",
    "TaskPhase",
    "WorkerProfile",
    "GuardianVerdict",
    "GuardianTrajectory",
    "NudgeTone",
    "StrategyStatus",
    "BlockedType",
    "EscalationType",
    # Core Dataclasses
    "Task",
    "Insight",
    "DesignDecision",
    "SuggestedTask",
    "AAR",
    "WorkerResult",
    # QA Types
    "CriterionResult",
    "TestFailureAnalysis",
    "QAVerdict",
    # Guardian Types
    "GuardianMetrics",
    "GuardianNudge",
    "GuardianState",
    # Blocked/Escalation Types
    "BlockedReason",
    "Escalation",
    "WorkerCheckpoint",
    # State Types
    "BlackboardState",
    "BlackboardStateDict",
    # Config Types
    "ModelConfig",
    "OrchestratorConfig",
    "RetryConfig",
    "WebhookConfig",
    # Default Configs
    "DEFAULT_MODEL_CONFIGS",
    # Serialization Helpers
    "task_to_dict",
    "dict_to_task",
    "qa_verdict_to_dict",
    "dict_to_qa_verdict",
    "blackboard_to_dict",
    "dict_to_blackboard",
    "serialize_messages",
]
