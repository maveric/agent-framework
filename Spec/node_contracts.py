"""
Agent Orchestrator — Node Contracts
====================================
Version 1.0 — November 2025

Function signatures, input/output types, and state update patterns
for each LangGraph node in the orchestrator.

Depends on: 
- orchestrator_types.py
- git_filesystem_spec.py (for worktree operations)
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional, Sequence, TypedDict, Annotated
from langchain_core.messages import BaseMessage, SystemMessage
from langgraph.graph import StateGraph, Send

# Import our type definitions
from orchestrator_types import (
    Task, TaskStatus, TaskPhase, WorkerProfile,
    BlackboardState, BlackboardStateDict,
    WorkerResult, QAVerdict, GuardianNudge, GuardianVerdict, GuardianMetrics,
    GuardianTrajectory, NudgeTone,
    Insight, DesignDecision, SuggestedTask, AAR,
    BlockedReason, BlockedType, StrategyStatus,
    Escalation, EscalationType, WorkerCheckpoint,
    ModelConfig, DEFAULT_MODEL_CONFIGS,
    RetryConfig, WebhookConfig,
    CriterionResult, TestFailureAnalysis,
)


# =============================================================================
# STATE UPDATE PATTERN: REDUCERS
# =============================================================================
"""
We use LangGraph's reducer pattern for state updates. Each node returns
only the fields it wants to change. Reducers define how changes merge.

For lists (tasks, insights, design_log), we use custom reducers that support:
- Append: add new items
- Update: modify existing items by ID
- Remove: delete items by ID

For dicts (task_memories, filesystem_index), we merge keys.
For scalars (strategy_status, updated_at), last write wins.
"""

def tasks_reducer(
    existing: List[Dict[str, Any]], 
    updates: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """
    Merge task updates into existing task list.
    - If update has matching ID, replace the task
    - If update has new ID, append
    - If update has {"_delete": True, "id": X}, remove task X
    """
    existing_by_id = {t["id"]: t for t in existing}
    
    for update in updates:
        task_id = update.get("id")
        if update.get("_delete"):
            existing_by_id.pop(task_id, None)
        else:
            existing_by_id[task_id] = update
    
    return list(existing_by_id.values())


def insights_reducer(
    existing: List[Dict[str, Any]], 
    updates: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """
    Append new insights. Insights are immutable once created.
    Duplicates (by ID) are ignored.
    """
    existing_ids = {i["id"] for i in existing}
    new_insights = [u for u in updates if u["id"] not in existing_ids]
    return existing + new_insights


def design_log_reducer(
    existing: List[Dict[str, Any]], 
    updates: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """
    Append new design decisions. Design log is append-only.
    """
    existing_ids = {d["id"] for d in existing}
    new_decisions = [u for u in updates if u["id"] not in existing_ids]
    return existing + new_decisions


def task_memories_reducer(
    existing: Dict[str, List[BaseMessage]], 
    updates: Dict[str, List[BaseMessage]]
) -> Dict[str, List[BaseMessage]]:
    """
    Merge task memories. 
    - New messages are appended to existing task memory
    - Special key {"_clear": task_id} wipes that task's memory (Phoenix)
    """
    result = dict(existing)
    
    for task_id, messages in updates.items():
        if task_id == "_clear":
            # messages is actually a list of task_ids to clear
            for tid in messages:
                result.pop(tid, None)
        elif task_id in result:
            result[task_id] = result[task_id] + messages
        else:
            result[task_id] = messages
    
    return result


# =============================================================================
# LANGGRAPH STATE SCHEMA WITH REDUCERS
# =============================================================================

class OrchestratorState(TypedDict, total=False):
    """
    LangGraph-compatible state with annotated reducers.
    This is the actual state schema used in the graph.
    """
    # Identity (no reducer - set once)
    run_id: str
    objective: str
    
    # Persistent context with reducers
    spec: Dict[str, Any]  # Last-write-wins (rarely changes)
    design_log: Annotated[List[Dict[str, Any]], design_log_reducer]
    insights: Annotated[List[Dict[str, Any]], insights_reducer]
    
    # Task management with reducer
    tasks: Annotated[List[Dict[str, Any]], tasks_reducer]
    
    # Ephemeral with reducer
    task_memories: Annotated[Dict[str, List[BaseMessage]], task_memories_reducer]
    
    # Filesystem (last-write-wins merge)
    filesystem_index: Dict[str, str]
    
    # Control
    guardian: Dict[str, Any]
    strategy_status: str
    
    # Metadata
    created_at: str
    updated_at: str


# =============================================================================
# NODE RETURN TYPES (DELTAS)
# =============================================================================

@dataclass
class DirectorUpdate:
    """What Director returns to update state."""
    tasks: List[Dict[str, Any]] = field(default_factory=list)  # New/updated tasks
    design_log: List[Dict[str, Any]] = field(default_factory=list)  # New decisions
    strategy_status: Optional[str] = None
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())
    
    # Routing instructions (not state, used by graph)
    send_to_worker: Optional[Send] = None  # Send() for dispatching to worker
    
    def to_state_update(self) -> Dict[str, Any]:
        """Convert to state delta dict."""
        update = {"updated_at": self.updated_at}
        if self.tasks:
            update["tasks"] = self.tasks
        if self.design_log:
            update["design_log"] = self.design_log
        if self.strategy_status:
            update["strategy_status"] = self.strategy_status
        return update


@dataclass
class WorkerUpdate:
    """What Worker returns to update state."""
    tasks: List[Dict[str, Any]] = field(default_factory=list)  # Updated task (status, result_path, etc.)
    task_memories: Dict[str, List[BaseMessage]] = field(default_factory=dict)  # New messages
    insights: List[Dict[str, Any]] = field(default_factory=list)  # New insights from AAR
    filesystem_index: Dict[str, str] = field(default_factory=dict)  # New/updated file mappings
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())
    
    # Routing - where to go next
    next_node: Literal["strategist", "guardian", "continue", "error"] = "strategist"
    
    def to_state_update(self) -> Dict[str, Any]:
        """Convert to state delta dict."""
        update = {"updated_at": self.updated_at}
        if self.tasks:
            update["tasks"] = self.tasks
        if self.task_memories:
            update["task_memories"] = self.task_memories
        if self.insights:
            update["insights"] = self.insights
        if self.filesystem_index:
            update["filesystem_index"] = self.filesystem_index
        return update


@dataclass
class StrategistUpdate:
    """What Strategist returns to update state."""
    tasks: List[Dict[str, Any]] = field(default_factory=list)  # Task with QA verdict
    design_log: List[Dict[str, Any]] = field(default_factory=list)  # Decisions from QA
    strategy_status: Optional[str] = None  # STAGNATING if too many failures
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())
    
    def to_state_update(self) -> Dict[str, Any]:
        update = {"updated_at": self.updated_at}
        if self.tasks:
            update["tasks"] = self.tasks
        if self.design_log:
            update["design_log"] = self.design_log
        if self.strategy_status:
            update["strategy_status"] = self.strategy_status
        return update


@dataclass
class GuardianUpdate:
    """What Guardian returns to update state."""
    task_memories: Dict[str, List[BaseMessage]] = field(default_factory=dict)  # Injected nudges
    guardian: Dict[str, Any] = field(default_factory=dict)  # Updated guardian state
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())
    
    # Routing
    verdict: GuardianVerdict = GuardianVerdict.ON_TRACK
    
    def to_state_update(self) -> Dict[str, Any]:
        update = {"updated_at": self.updated_at}
        if self.task_memories:
            update["task_memories"] = self.task_memories
        if self.guardian:
            update["guardian"] = self.guardian
        return update


# =============================================================================
# NODE FUNCTION SIGNATURES
# =============================================================================

# -----------------------------------------------------------------------------
# DIRECTOR NODE
# -----------------------------------------------------------------------------

def director_node(state: OrchestratorState) -> Dict[str, Any]:
    """
    Director: Project Manager & Logistician
    
    Responsibilities:
    1. Initial decomposition (on first run)
    2. Evaluate task readiness (PLANNED → READY or BLOCKED)
    3. Handle completed QA (COMPLETE or FAILED_QA tasks)
    4. Dispatch ready tasks to workers
    5. Handle re-planning if STAGNATING
    6. Review suggested tasks from workers
    7. Handle worker escalations (replanning, spec mismatch, etc.)
    8. Resume tasks waiting for subtasks
    
    Routing:
    - Returns Send() to dispatch tasks to worker_node
    - Returns to self if more tasks need evaluation
    - Ends if no more work to do
    
    State reads:
    - tasks (to evaluate status, check escalations)
    - objective, spec (for decomposition/planning)
    - strategy_status (to detect stagnation)
    - insights (to inform planning)
    
    State writes:
    - tasks (status changes, new tasks, escalation resolution)
    - design_log (planning decisions, escalation responses)
    - strategy_status (if changed)
    """
    # Implementation delegated to director_logic module
    pass


def director_initial_decomposition(
    objective: str,
    spec: Dict[str, Any],
    insights: List[Insight]
) -> List[Task]:
    """
    LLM call to decompose objective into initial task DAG.
    
    Returns list of Task objects with:
    - id, component, phase, description
    - depends_on relationships
    - acceptance_criteria
    - assigned_worker_profile
    - status = PLANNED
    """
    pass


def director_evaluate_readiness(
    task: Task,
    all_tasks: List[Task]
) -> TaskStatus:
    """
    Evaluate if a PLANNED task can become READY or should be BLOCKED.
    
    Pure Python logic (no LLM):
    - Check all depends_on tasks are COMPLETE
    - Check no external blockers
    
    Returns: READY, BLOCKED, or stays PLANNED
    """
    pass


def director_handle_failed_qa(
    task: Task,
    max_retries: int
) -> Task:
    """
    Handle a task that failed QA.
    
    Logic:
    - If retry_count >= max_retries: status = WAITING_HUMAN
    - Else: increment retry_count, apply Phoenix, status = READY
    """
    pass


def director_review_suggested_tasks(
    suggestions: List[SuggestedTask],
    existing_tasks: List[Task],
    objective: str,
    spec: Dict[str, Any]
) -> List[Task]:
    """
    LLM call to review worker-suggested tasks.
    
    For each suggestion:
    - Accept: create Task from suggestion
    - Reject: discard with reason
    - Modify: adjust and create Task
    
    Returns list of approved Tasks to add.
    """
    pass


def director_handle_escalation(
    escalation: Escalation,
    source_task: Task,
    all_tasks: List[Task],
    spec: Dict[str, Any],
    objective: str
) -> "EscalationResponse":
    """
    LLM call to handle a worker escalation.
    
    Escalation types and typical responses:
    
    NEEDS_RESEARCH:
        - Create research subtask
        - Set source_task to waiting_subtask status
        - Save checkpoint for resume
    
    NEEDS_REPLANNING:
        - Analyze what went wrong
        - Create new planning task(s)
        - May abandon/modify existing tasks
        - Record design decision explaining the change
    
    SPEC_MISMATCH:
        - Identify conflicting specs
        - Decide which is correct (or escalate to human)
        - Update affected tasks
        - May trigger replanning
    
    NEEDS_CLARIFICATION:
        - If resolvable: provide clarification, resume task
        - If not: escalate to WAITING_HUMAN
    
    BLOCKED_EXTERNAL:
        - Mark task as blocked
        - Record what it's waiting for
    
    SCOPE_TOO_LARGE:
        - Split task into smaller subtasks
        - Maintain dependencies correctly
    
    Returns EscalationResponse with actions to take.
    """
    pass


@dataclass
class EscalationResponse:
    """Director's response to a worker escalation."""
    
    # Tasks to create (already approved, no further review)
    create_tasks: List[Task] = field(default_factory=list)
    
    # Tasks to update (status changes, dependency updates)
    update_tasks: List[Dict[str, Any]] = field(default_factory=list)
    
    # Tasks to abandon (no longer needed)
    abandon_task_ids: List[str] = field(default_factory=list)
    
    # Design decisions to record
    design_decisions: List[DesignDecision] = field(default_factory=list)
    
    # Should source task resume? (If False, remains blocked)
    resume_source_task: bool = False
    
    # Checkpoint to restore when resuming (if any)
    restore_checkpoint: Optional[WorkerCheckpoint] = None
    
    # Escalate to human? (If True, source task → WAITING_HUMAN)
    escalate_to_human: bool = False
    human_prompt: Optional[str] = None  # What to ask the human


def director_check_waiting_subtasks(
    tasks: List[Task]
) -> List[Task]:
    """
    Check if any tasks waiting for subtasks can now resume.
    
    For each task with status BLOCKED and waiting_for_tasks:
    - Check if all waited-for tasks are COMPLETE
    - If yes, mark task as READY to resume
    - Restore checkpoint if present
    
    Returns list of tasks ready to resume (with checkpoints restored).
    """
    tasks_to_resume = []
    
    for task in tasks:
        if task.get("status") != "blocked":
            continue
        
        waiting_for = task.get("waiting_for_tasks", [])
        if not waiting_for:
            continue
        
        # Check if all waited-for tasks are complete
        all_complete = True
        for waited_task_id in waiting_for:
            waited_task = next((t for t in tasks if t["id"] == waited_task_id), None)
            if not waited_task or waited_task.get("status") != "complete":
                all_complete = False
                break
        
        if all_complete:
            tasks_to_resume.append(task)
    
    return tasks_to_resume


# -----------------------------------------------------------------------------
# WORKER NODE (UNIFIED)
# -----------------------------------------------------------------------------

def worker_node(state: OrchestratorState, task_id: str) -> Dict[str, Any]:
    """
    Worker: Unified execution node that delegates to specialized handlers.
    
    This is a SINGLE LangGraph node that handles all worker types.
    The task's assigned_worker_profile determines which handler runs.
    
    Flow:
    1. Common pre-processing (load context, setup worktree)
    2. Check for checkpoint (resume if present)
    3. Type-specific execution (planner/coder/tester/researcher/writer)
    4. Guardian checkpoint (if needed)
    5. Handle result (complete, escalation, or waiting_subtask)
    6. Common post-processing (commit, package result)
    
    Args:
        state: Current blackboard state
        task_id: ID of task to execute (passed via Send())
    
    State reads:
    - tasks (to get assigned task, check for checkpoint)
    - task_memories (conversation history)
    - spec, design_log, insights (context for work)
    - filesystem_index (existing files)
    - guardian (for scheduling check)
    
    State writes:
    - tasks (status, result_path, aar, escalation, checkpoint)
    - task_memories (conversation history)
    - insights (from worker's AAR)
    - filesystem_index (new files)
    
    Escalation handling:
    - If worker returns escalation, task status → BLOCKED
    - Escalation stored on task for Director to process
    - If escalation.blocking=False, task can still complete
    
    Checkpoint handling:
    - If worker returns status="waiting_subtask", save checkpoint
    - Task status → BLOCKED, waiting_for_tasks populated
    - When subtasks complete, Director will resume this task
    """
    task = get_task_by_id(state, task_id)
    profile = task["assigned_worker_profile"]
    
    # === COMMON PRE-PROCESSING ===
    context = prepare_worker_context(state, task)
    worktree = setup_task_worktree(task)
    
    # === CHECK FOR CHECKPOINT (RESUME) ===
    checkpoint = task.get("checkpoint")
    if checkpoint:
        context = restore_worker_checkpoint(context, checkpoint)
    
    # === TYPE-SPECIFIC EXECUTION ===
    handler = get_worker_handler(profile)
    result = handler(context, task, worktree)
    
    # === HANDLE ESCALATION ===
    if result.escalation:
        return package_escalation_update(state, task, result)
    
    # === HANDLE WAITING FOR SUBTASK ===
    if result.status == "waiting_subtask":
        return package_checkpoint_update(state, task, result)
    
    # === COMMON POST-PROCESSING (normal completion) ===
    commit_task_worktree(task, worktree, result)
    return package_worker_update(state, task, result)


def restore_worker_checkpoint(
    context: "WorkerContext", 
    checkpoint: WorkerCheckpoint
) -> "WorkerContext":
    """
    Restore worker context from a checkpoint.
    
    Merges checkpoint's partial_work into context and
    adds resume_instructions to guide continued execution.
    """
    # Add checkpoint data to context
    context.checkpoint_data = checkpoint.partial_work
    context.resume_instructions = checkpoint.resume_instructions
    context.files_in_progress = checkpoint.files_in_progress
    return context


def package_escalation_update(
    state: OrchestratorState,
    task: Dict[str, Any],
    result: WorkerResult
) -> Dict[str, Any]:
    """
    Package state update when worker raises an escalation.
    
    If escalation.blocking:
        - Task status → BLOCKED
        - Escalation stored on task
    Else:
        - Task can still complete (escalation is informational)
        - Escalation stored for Director to review
    """
    escalation = result.escalation
    
    if escalation.blocking:
        updated_task = {
            **task,
            "status": "blocked",
            "escalation": result.escalation,
            "aar": result.aar,
            "updated_at": datetime.now().isoformat(),
        }
    else:
        # Non-blocking escalation - task continues to completion
        updated_task = {
            **task,
            "status": "awaiting_qa" if result.status == "complete" else task["status"],
            "result_path": result.result_path,
            "escalation": result.escalation,  # Still recorded
            "aar": result.aar,
            "updated_at": datetime.now().isoformat(),
        }
    
    return {
        "tasks": [updated_task],
        "insights": [i.__dict__ for i in result.insights] if result.insights else [],
        "updated_at": datetime.now().isoformat(),
    }


def package_checkpoint_update(
    state: OrchestratorState,
    task: Dict[str, Any],
    result: WorkerResult
) -> Dict[str, Any]:
    """
    Package state update when worker pauses for subtask.
    
    - Task status → BLOCKED
    - Checkpoint saved for later resume
    - waiting_for_tasks populated from escalation.spawn_tasks
    """
    # Get task IDs to wait for (from spawn_tasks in escalation if present)
    waiting_for = []
    if result.escalation and result.escalation.spawn_tasks:
        waiting_for = [st.suggested_id for st in result.escalation.spawn_tasks]
    elif result.checkpoint:
        waiting_for = result.checkpoint.waiting_for
    
    updated_task = {
        **task,
        "status": "blocked",
        "blocked_reason": {
            "type": "waiting_subtask",
            "description": "Waiting for subtask(s) to complete",
            "waiting_on": waiting_for,
            "since": datetime.now().isoformat(),
        },
        "checkpoint": result.checkpoint,
        "waiting_for_tasks": waiting_for,
        "aar": result.aar,
        "updated_at": datetime.now().isoformat(),
    }
    
    return {
        "tasks": [updated_task],
        "insights": [i.__dict__ for i in result.insights] if result.insights else [],
        "updated_at": datetime.now().isoformat(),
    }


@dataclass
class WorkerContext:
    """Context prepared for worker execution."""
    task: Task
    objective: str
    spec: Dict[str, Any]
    relevant_spec_sections: Dict[str, Any]  # Filtered to task's component
    relevant_insights: List[Insight]  # Filtered to task's topics
    relevant_decisions: List[DesignDecision]  # Filtered to task
    memories: List[BaseMessage]  # This task's conversation history
    dependent_artifacts: Dict[str, str]  # Paths to artifacts from dependencies
    worktree_path: str
    
    # Checkpoint/resume fields (populated when resuming from checkpoint)
    checkpoint_data: Optional[Dict[str, Any]] = None  # Partial work from checkpoint
    resume_instructions: Optional[str] = None  # Instructions for resuming
    files_in_progress: List[str] = field(default_factory=list)  # Files being worked on
    
    # Results from subtasks (populated when resuming after subtask completion)
    subtask_results: Dict[str, Any] = field(default_factory=dict)  # task_id -> result


def prepare_worker_context(state: OrchestratorState, task: Dict[str, Any]) -> WorkerContext:
    """
    Extract and filter relevant context for a worker.
    
    This reduces token usage by only including:
    - Spec sections relevant to task's component
    - Insights relevant to task's topics
    - Design decisions that apply to this task
    - Artifacts from completed dependencies
    """
    pass


def get_worker_handler(profile: str):
    """Return the handler function for a worker profile."""
    handlers = {
        "planner_worker": run_planner_worker,
        "code_worker": run_coder_worker,
        "test_worker": run_tester_worker,
        "research_worker": run_researcher_worker,
        "writer_worker": run_writer_worker,
    }
    return handlers[profile]


# -----------------------------------------------------------------------------
# TYPE-SPECIFIC WORKER HANDLERS
# -----------------------------------------------------------------------------

def run_planner_worker(
    context: WorkerContext,
    task: Dict[str, Any],
    worktree_path: str
) -> WorkerResult:
    """
    Planner worker: Creates plans and designs.
    
    Tools: search (optional), diagramming (optional), file write
    Output: Design document, schema, or plan artifact
    
    Typical flow:
    1. Analyze requirements from spec
    2. Consider constraints and dependencies
    3. Generate plan/design document
    4. Write to artifact file
    """
    pass


def run_coder_worker(
    context: WorkerContext,
    task: Dict[str, Any],
    worktree_path: str
) -> WorkerResult:
    """
    Coder worker: Implements code.
    
    Tools: file read/write, code execution, linting, package management
    Output: Source code files
    
    Typical flow:
    1. Read plan from dependency artifacts
    2. Implement code
    3. Run linter, fix issues
    4. Optionally run quick tests
    5. Write final code to files
    """
    pass


def run_tester_worker(
    context: WorkerContext,
    task: Dict[str, Any],
    worktree_path: str
) -> WorkerResult:
    """
    Tester worker: Validates implementations.
    
    Tools: code execution, test runners, file read
    Output: Test files and/or test results report
    
    Typical flow:
    1. Read implementation from dependency artifacts
    2. Generate test cases from acceptance criteria
    3. Run tests
    4. Report results
    """
    pass


def run_researcher_worker(
    context: WorkerContext,
    task: Dict[str, Any],
    worktree_path: str
) -> WorkerResult:
    """
    Researcher worker: Gathers and synthesizes information.
    
    Tools: web search, web fetch, file write
    Output: Research notes, summaries, source documents
    
    Typical flow:
    1. Generate search queries from task description
    2. Search and fetch relevant sources
    3. Synthesize findings
    4. Write research artifact
    """
    pass


def run_writer_worker(
    context: WorkerContext,
    task: Dict[str, Any],
    worktree_path: str
) -> WorkerResult:
    """
    Writer worker: Produces prose documents.
    
    Tools: file read/write, optional search
    Output: Documents, reports, copy
    
    Typical flow:
    1. Read inputs (research, outline, style guide)
    2. Draft content
    3. Self-review and refine
    4. Write final artifact
    """
    pass


# -----------------------------------------------------------------------------
# WORKER ITERATION & GUARDIAN CHECKPOINT
# -----------------------------------------------------------------------------

@dataclass 
class WorkerIterationState:
    """Tracks worker's progress for Guardian scheduling."""
    task_id: str
    iteration_count: int = 0
    last_guardian_check: Optional[datetime] = None
    token_count: int = 0
    tool_calls: int = 0
    fs_writes: int = 0


def should_run_guardian(
    iteration_state: WorkerIterationState,
    config: "OrchestratorConfig"
) -> bool:
    """
    Determine if Guardian should run.
    
    Triggers:
    - iteration_count >= config.guardian_iteration_interval (default: 15)
    - OR time since last check >= config.guardian_time_interval (default: 60s)
    """
    if iteration_state.iteration_count >= config.guardian_iteration_interval:
        return True
    
    if iteration_state.last_guardian_check:
        elapsed = (datetime.now() - iteration_state.last_guardian_check).total_seconds()
        if elapsed >= config.guardian_time_interval:
            return True
    
    return False


# -----------------------------------------------------------------------------
# STRATEGIST NODE
# -----------------------------------------------------------------------------

def strategist_node(state: OrchestratorState, task_id: str) -> Dict[str, Any]:
    """
    Strategist: Quality Assurance.
    
    Evaluates artifacts against acceptance criteria.
    
    Flow:
    1. Load task and its artifact from filesystem
    2. Load acceptance criteria and relevant spec
    3. Evaluate each criterion
    4. If test results available, analyze test validity (don't blindly trust failures)
    5. Produce QAVerdict
    6. If BUILD task passes, refine the corresponding test placeholder criteria
    7. Update task status (COMPLETE or FAILED_QA)
    
    Test Validity Analysis:
    - When tests fail, Strategist investigates whether tests are correct
    - "Test correct, code wrong" → FAIL QA
    - "Test wrong, code correct" → PASS QA, flag tests_needing_revision
    - "Both need work" → FAIL QA, note both issues
    
    Test Placeholder Refinement:
    - BUILD tasks have corresponding test-{component} placeholders
    - When BUILD passes QA, Strategist updates placeholder with specific criteria
    - This happens in the same LLM call to save tokens
    
    State reads:
    - tasks (to get task under review, test placeholder if BUILD)
    - spec (for context)
    - filesystem_index (to locate artifact)
    - (reads actual file from worktree)
    
    State writes:
    - tasks (status, qa_verdict, refined test placeholder criteria)
    - strategy_status (if detecting pattern of failures)
    - design_log (if QA reveals important decisions)
    """
    pass


def strategist_evaluate_artifact(
    artifact_content: str,
    artifact_path: str,
    acceptance_criteria: List[str],
    spec: Dict[str, Any],
    task_description: str,
    test_results: Optional[Dict[str, Any]] = None,
    test_placeholder: Optional[Dict[str, Any]] = None
) -> QAVerdict:
    """
    LLM call to evaluate artifact against criteria.
    
    Args:
        artifact_content: The actual artifact to review
        artifact_path: Path to the artifact
        acceptance_criteria: List of criteria to evaluate against
        spec: Project specification for context
        task_description: What the task was supposed to do
        test_results: Tester's report if available (for test validity analysis)
        test_placeholder: Test task to refine if this is a BUILD task
    
    Returns structured QAVerdict with:
    - passed: bool
    - criterion_results: List[CriterionResult]
    - overall_feedback: str
    - suggested_focus: Optional[str] (for retry)
    - test_analysis: List[TestFailureAnalysis] (if test results provided)
    - tests_needing_revision: List[str] (test names that are wrong)
    - refined_test_criteria: List[str] (if BUILD task passes)
    """
    pass


def strategist_check_stagnation(
    tasks: List[Dict[str, Any]],
    threshold: int = 3
) -> bool:
    """
    Detect if project is stagnating.
    
    Indicators:
    - Same task has failed QA threshold times
    - Multiple tasks stuck in FAILED_QA
    - Circular dependency pattern
    
    Returns True if strategy_status should become STAGNATING.
    """
    pass


# -----------------------------------------------------------------------------
# GUARDIAN NODE
# -----------------------------------------------------------------------------

def guardian_node(state: OrchestratorState, task_id: str) -> Dict[str, Any]:
    """
    Guardian: Drift Detection & Course Correction.
    
    Reviews task's recent activity and injects guidance if needed.
    
    Flow:
    1. Load task's recent memories
    2. Compute metrics (time, tokens, tool calls, fs writes)
    3. Evaluate alignment (0-100%) and trajectory (improving/stable/worsening)
    4. Determine verdict based on alignment + trajectory
    5. If intervention needed, generate nudge with appropriate tone
    6. Update guardian state with assessment history
    
    Verdict Logic:
    - ON_TRACK: alignment ≥70% OR (alignment ≥50% AND trajectory=IMPROVING)
    - DRIFTING: alignment 25-69% AND trajectory not IMPROVING
    - BLOCKED: stuck in circles, repeating failed approaches
    - STALLED: alignment <25% AND not improving, OR ignoring nudges, OR no activity
    
    Nudge Tone (scales with severity):
    - GENTLE (50-69%): "Consider whether..."
    - DIRECT (25-49%): "You've drifted. Stop X and return to Y."
    - FIRM (0-24%): "STOP. Immediately return to..."
    
    Key behavior: Workers who are IMPROVING don't get marked STALLED — they get time to recover.
    
    State reads:
    - tasks (current task)
    - task_memories (recent conversation)
    - objective (to check alignment)
    - guardian (last check times, previous nudges)
    
    State writes:
    - task_memories (inject nudge if needed)
    - guardian (update check times, store assessment)
    """
    pass


def guardian_compute_metrics(
    task_id: str,
    task_memories: List[BaseMessage],
    guardian_state: Dict[str, Any]
) -> GuardianMetrics:
    """
    Compute metrics for drift/stall detection.
    
    Returns GuardianMetrics with:
    - time_since_last_message_seconds
    - token_count_since_checkpoint
    - tool_calls_since_checkpoint
    - filesystem_writes_since_checkpoint
    """
    pass


def guardian_evaluate(
    metrics: GuardianMetrics,
    recent_messages: List[BaseMessage],
    objective: str,
    task_description: str,
    acceptance_criteria: List[str],
    previous_nudges: List[GuardianNudge]
) -> GuardianNudge:
    """
    LLM call to evaluate task alignment and generate intervention if needed.
    
    Args:
        metrics: Activity metrics (time, tool calls, fs writes)
        recent_messages: Last N messages from task_memories
        objective: Project objective
        task_description: What this task should accomplish
        acceptance_criteria: Task's acceptance criteria
        previous_nudges: Previous nudges for this task (to assess trajectory)
    
    Returns GuardianNudge with:
    - verdict: ON_TRACK, DRIFTING, BLOCKED, or STALLED
    - alignment_score: 0-100% alignment with objective
    - trajectory: IMPROVING, STABLE, or WORSENING
    - tone: GENTLE, DIRECT, or FIRM (if nudge needed)
    - message: Guidance to inject (if not ON_TRACK)
    - detected_issue: What triggered intervention
    """
    pass


def guardian_create_nudge(nudge: GuardianNudge) -> SystemMessage:
    """
    Create a SystemMessage to inject into task's memory.
    
    Tone adapts to severity level:
    - GENTLE: Suggestive, questioning
    - DIRECT: Clear redirect  
    - FIRM: Stop command
    
    Format:
    [GUARDIAN - {tone}]: {verdict}
    Alignment: {score}% | Trajectory: {trajectory}
    
    {message}
    
    Focus: {detected_issue}
    """
    pass


# =============================================================================
# GRAPH ROUTING FUNCTIONS
# =============================================================================

def route_after_director(state: OrchestratorState) -> List[Send] | str:
    """
    Determine where to go after Director.
    
    Returns:
    - List[Send] to dispatch tasks to workers (can dispatch multiple)
    - "end" if no more work
    - "director" to loop back for more processing
    """
    active_tasks = [t for t in state["tasks"] if t["status"] == "active"]
    ready_tasks = [t for t in state["tasks"] if t["status"] == "ready"]
    
    if active_tasks:
        # Tasks already running, wait for them
        return "wait"
    
    if ready_tasks:
        # Dispatch ready tasks (respecting concurrency limits)
        sends = []
        for task in ready_tasks[:MAX_CONCURRENT_WORKERS]:
            sends.append(Send("worker", {"task_id": task["id"]}))
        return sends
    
    # Check if we're done
    all_complete = all(
        t["status"] in ("complete", "abandoned", "waiting_human")
        for t in state["tasks"]
    )
    if all_complete:
        return "end"
    
    # Still have blocked tasks, wait
    return "wait"


def route_after_worker(state: OrchestratorState, task_id: str) -> str:
    """
    Determine where to go after Worker completes.
    
    Returns:
    - "strategist" to evaluate artifact (normal completion)
    - "guardian" if Guardian check is due
    - "director" if worker reported blocked/failed
    """
    task = get_task_by_id(state, task_id)
    
    if task["status"] == "awaiting_qa":
        return "strategist"
    elif task["status"] == "blocked":
        return "director"
    else:
        return "director"


def route_after_strategist(state: OrchestratorState) -> str:
    """
    Determine where to go after Strategist.
    
    Always returns to Director to:
    - Handle COMPLETE (unblock dependents)
    - Handle FAILED_QA (Phoenix or escalate)
    - Check for more ready tasks
    """
    return "director"


def route_after_guardian(state: OrchestratorState, task_id: str) -> str:
    """
    Determine where to go after Guardian.
    
    Returns:
    - "worker" to continue execution (with nudge injected if needed)
    - "director" if Guardian determined task should be killed
    """
    guardian_state = state.get("guardian", {})
    last_verdict = guardian_state.get("last_verdict", "on_track")
    
    if last_verdict in ("stalled", "unsafe"):
        # Kill the task, return to Director
        return "director"
    else:
        # Continue worker execution
        return "worker"


# =============================================================================
# CONFIGURATION
# =============================================================================

@dataclass
class OrchestratorConfig:
    """
    Configuration for the orchestrator.
    
    Supports multi-provider model configuration - each role can use a different
    provider (anthropic, openai, google, glm, ollama, azure, bedrock).
    """
    
    # Retry limits
    max_task_retries: int = 3
    
    # Concurrency
    max_concurrent_workers: int = 3
    
    # Guardian scheduling
    guardian_iteration_interval: int = 15  # Every N tool calls
    guardian_time_interval: int = 60  # Or every N seconds
    
    # Stagnation detection
    stagnation_threshold: int = 3  # Failures before STAGNATING
    
    # Task timeout
    task_timeout_seconds: int = 600  # 10 minutes default
    
    # Models (per role) - use ModelConfig for full control
    models: Dict[str, ModelConfig] = field(default_factory=lambda: dict(DEFAULT_MODEL_CONFIGS))
    
    # Git
    worktree_base_path: str = "./worktrees"
    main_branch: str = "main"
    
    # Error handling
    retry: RetryConfig = field(default_factory=RetryConfig)
    
    # Webhooks (stubbed for future)
    webhooks: WebhookConfig = field(default_factory=WebhookConfig)
    
    def get_model(self, role: str) -> ModelConfig:
        """
        Get model config for a role, with fallback chain.
        
        Args:
            role: Role name (director, strategist, guardian, planner_worker, etc.)
        
        Returns:
            ModelConfig for the role
        """
        if role in self.models:
            return self.models[role]
        
        # Fallback chain for workers
        if role.endswith("_worker"):
            # Try generic worker config
            if "worker" in self.models:
                return self.models["worker"]
            # Fall back to director
            return self.models.get("director", DEFAULT_MODEL_CONFIGS["director"])
        
        # Ultimate fallback
        return self.models.get("director", DEFAULT_MODEL_CONFIGS["director"])
    
    def set_model(self, role: str, config: ModelConfig) -> None:
        """Set model config for a specific role."""
        self.models[role] = config
    
    def set_provider_for_role(
        self, 
        role: str, 
        provider: str, 
        model: str,
        **kwargs
    ) -> None:
        """
        Convenience method to set provider/model for a role.
        
        Example:
            config.set_provider_for_role("code_worker", "glm", "glm-4-plus")
            config.set_provider_for_role("guardian", "openai", "gpt-4o-mini")
        """
        self.models[role] = ModelConfig(
            provider=provider,
            model=model,
            temperature=kwargs.get("temperature", 0.7),
            max_tokens=kwargs.get("max_tokens", 4096),
            timeout_seconds=kwargs.get("timeout_seconds", 120),
            extra=kwargs.get("extra", {}),
        )


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def get_task_by_id(state: OrchestratorState, task_id: str) -> Dict[str, Any]:
    """Get a task by ID from state."""
    for task in state.get("tasks", []):
        if task["id"] == task_id:
            return task
    raise ValueError(f"Task not found: {task_id}")


def setup_task_worktree(task: Dict[str, Any]) -> str:
    """
    Create git worktree for a task.
    
    Returns path to worktree directory.
    """
    pass


def commit_task_worktree(
    task: Dict[str, Any],
    worktree_path: str,
    result: WorkerResult
) -> str:
    """
    Commit changes in task's worktree.
    
    Commit message format:
    [{task_id}] {phase}: {summary from AAR}
    
    Files: {list of modified files}
    
    Returns commit hash.
    """
    pass


def package_worker_update(
    state: OrchestratorState,
    task: Dict[str, Any],
    result: WorkerResult
) -> Dict[str, Any]:
    """
    Convert WorkerResult into state update dict.
    """
    pass


# =============================================================================
# PHOENIX PROTOCOL
# =============================================================================

def apply_phoenix(
    task: Dict[str, Any],
    qa_verdict: QAVerdict,
    task_memories: List[BaseMessage],
    failed_branch: str,
    design_decisions: List[Dict[str, Any]],
    insights: List[Dict[str, Any]],
    max_retries: int = 3
) -> tuple[Dict[str, Any], Dict[str, List[BaseMessage]]]:
    """
    Apply Phoenix Protocol to a failed task.
    
    1. Clear task_memories[task_id]
    2. Create comprehensive context message using format_phoenix_context
    3. Reset task status to READY
    4. Increment retry_count
    
    Note: Use format_phoenix_context from prompt_templates.py to generate
    the context message. That function provides:
    - Detailed failure analysis
    - Reference to failed branch for examination
    - Relevant design decisions and insights
    - Guidance on what to do differently
    
    Returns:
    - Updated task dict
    - task_memories update (with _clear instruction)
    """
    # Import here to avoid circular dependency
    from prompt_templates import format_phoenix_context
    
    phoenix_context_text = format_phoenix_context(
        task=task,
        qa_verdict={
            "criterion_results": [
                {"criterion": cr.criterion, "passed": cr.passed, 
                 "reasoning": cr.reasoning, "suggestions": cr.suggestions}
                for cr in qa_verdict.criterion_results
            ],
            "overall_feedback": qa_verdict.overall_feedback,
            "suggested_focus": qa_verdict.suggested_focus,
        },
        failed_branch=failed_branch,
        design_decisions=design_decisions,
        insights=insights,
        max_retries=max_retries,
    )
    
    phoenix_message = SystemMessage(content=phoenix_context_text)
    
    updated_task = {
        **task,
        "status": "ready",
        "retry_count": task["retry_count"] + 1,
        "qa_verdict": None,  # Clear previous verdict
        "started_at": None,
    }
    
    memories_update = {
        "_clear": [task["id"]],  # Clear old memories
        task["id"]: [phoenix_message],  # Seed with Phoenix context
    }
    
    return updated_task, memories_update
