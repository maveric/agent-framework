"""
Agent Orchestrator — LangGraph Graph Definition
================================================
Version 1.0 — November 2025

The actual StateGraph definition that wires together all nodes.
This is the entry point for running the orchestrator.

Depends on:
- orchestrator_types.py
- node_contracts.py
- git_filesystem_spec.py (for worktree/repo initialization)
"""

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional, Sequence, Annotated
from langgraph.graph import StateGraph, END, Send
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.checkpoint.memory import MemorySaver
from langchain_core.messages import BaseMessage

# Import our types and contracts
from orchestrator_types import (
    TaskStatus, TaskPhase, WorkerProfile, GuardianVerdict, StrategyStatus,
    EscalationType, ModelConfig,
)
from node_contracts import (
    OrchestratorState,
    OrchestratorConfig,
    tasks_reducer,
    insights_reducer,
    design_log_reducer,
    task_memories_reducer,
    director_node,
    worker_node,
    strategist_node,
    guardian_node,
)


# =============================================================================
# GRAPH TOPOLOGY
# =============================================================================
"""
Visual representation of the orchestrator graph:

                    ┌─────────────────────────────────────────────────────────┐
                    │                                                         │
                    ▼                                                         │
    ┌───────────────────────────────┐                                         │
    │          DIRECTOR             │                                         │
    │  - Initial decomposition      │                                         │
    │  - Evaluate readiness         │                                         │
    │  - Handle QA results          │                                         │
    │  - Review suggested tasks     │                                         │
    │  - Handle escalations ←───────┼─────────────────────────┐               │
    │  - Resume waiting tasks       │                         │               │
    │  - Apply Phoenix              │                         │               │
    └───────────────┬───────────────┘                         │               │
                    │                                         │               │
                    │ Send(worker, {task_id})                 │               │
                    │ (can dispatch multiple)                 │               │
                    ▼                                         │               │
    ┌───────────────────────────────┐                         │               │
    │           WORKER              │                         │               │
    │  - Unified entry point        │                         │               │
    │  - Check for checkpoint       │                         │               │
    │  - Type-specific handlers     │                         │               │
    │  - Guardian checkpoints       │◄────────────┐           │               │
    └───────────────┬───────────────┘             │           │               │
                    │                             │           │               │
                    ├─── escalation? ─────────────┼───────────┘               │
                    │    (BLOCKED + escalation)   │                           │
                    │                             │                           │
                    ├─── waiting_subtask? ────────┼───────────┐               │
                    │    (BLOCKED + checkpoint)   │           │               │
                    │                             │           │               │
                    │ should_run_guardian?        │           │               │
                    ├─────────────────────────────┤           │               │
                    │ No                          │ Yes       │               │
                    │                             ▼           │               │
                    │             ┌───────────────────────────────┐           │
                    │             │          GUARDIAN             │           │
                    │             │  - Compute metrics            │           │
                    │             │  - Detect drift/stall         │           │
                    │             │  - Inject nudge               │           │
                    │             └───────────────┬───────────────┘           │
                    │                             │                           │
                    │              ┌──────────────┴──────────────┐            │
                    │              │ ON_TRACK/DRIFTING/BLOCKED   │            │
                    │              │ (continue)                  │            │
                    │              ▼                             │            │
                    │         back to worker ────────────────────┘            │
                    │                                                         │
                    │              │ STALLED/UNSAFE                           │
                    │              │ (kill task)                              │
                    │              ▼                                          │
                    │         back to director ───────────────────────────────┤
                    │                                                         │
                    │ task complete (AWAITING_QA)                             │
                    ▼                                                         │
    ┌───────────────────────────────┐                                         │
    │         STRATEGIST            │                                         │
    │  - Load artifact              │                                         │
    │  - Evaluate criteria          │                                         │
    │  - PASS → COMPLETE            │                                         │
    │  - FAIL → FAILED_QA           │                                         │
    └───────────────┬───────────────┘                                         │
                    │                                                         │
                    │ always                                                  │
                    └─────────────────────────────────────────────────────────┘

ESCALATION FLOW:
    Worker detects issue → Returns escalation → Task BLOCKED
    Director receives → Handles escalation type:
      - NEEDS_RESEARCH: Create research subtask, original waits
      - NEEDS_REPLANNING: Create planning tasks, may abandon current
      - SPEC_MISMATCH: Resolve conflict or escalate to human
      - NEEDS_CLARIFICATION: Clarify or escalate to human
      - SCOPE_TOO_LARGE: Split into subtasks
      
CHECKPOINT/RESUME FLOW:
    Worker needs subtask → Returns waiting_subtask + checkpoint
    Task BLOCKED, waiting_for_tasks populated
    Subtask(s) execute and complete
    Director detects completion → Resumes original with checkpoint
                    
Terminal conditions (→ END):
    - All tasks COMPLETE/ABANDONED/WAITING_HUMAN
    - strategy_status == STAGNATING and no recovery possible
    - Human intervention required
"""


# =============================================================================
# STATE SCHEMA (with reducers)
# =============================================================================

class OrchestratorStateWithReducers(OrchestratorState):
    """
    State schema with reducer annotations for LangGraph.
    
    This extends OrchestratorState with proper Annotated types
    that tell LangGraph how to merge partial updates.
    """
    # Override list/dict fields with reducer annotations
    tasks: Annotated[List[Dict[str, Any]], tasks_reducer]
    insights: Annotated[List[Dict[str, Any]], insights_reducer]
    design_log: Annotated[List[Dict[str, Any]], design_log_reducer]
    task_memories: Annotated[Dict[str, List[BaseMessage]], task_memories_reducer]


# =============================================================================
# ROUTING FUNCTIONS
# =============================================================================

def route_after_director(state: OrchestratorState, config: OrchestratorConfig) -> List[Send] | Literal["__end__", "wait"]:
    """
    Determine routing after Director node.
    
    Returns:
    - List[Send] to dispatch ready tasks to workers
    - "__end__" if all work is complete
    - "wait" if blocked waiting on external input
    """
    tasks = state.get("tasks", [])
    
    # Count tasks by status
    status_counts = {}
    for task in tasks:
        status = task.get("status", "planned")
        status_counts[status] = status_counts.get(status, 0) + 1
    
    # Check for active tasks (already dispatched)
    active_count = status_counts.get("active", 0)
    
    # Get ready tasks that can be dispatched
    ready_tasks = [t for t in tasks if t.get("status") == "ready"]
    
    # Check if we're done
    terminal_statuses = {"complete", "abandoned", "waiting_human"}
    all_terminal = all(
        task.get("status") in terminal_statuses
        for task in tasks
    )
    
    if all_terminal and tasks:
        return "__end__"
    
    # No tasks yet (shouldn't happen, but handle gracefully)
    if not tasks:
        return "__end__"
    
    # Respect concurrency limits
    available_slots = config.max_concurrent_workers - active_count
    
    if available_slots > 0 and ready_tasks:
        # Dispatch ready tasks up to available slots
        # Sort by priority (desc) then created_at (asc)
        ready_tasks.sort(
            key=lambda t: (-t.get("priority", 5), t.get("created_at", ""))
        )
        
        sends = []
        for task in ready_tasks[:available_slots]:
            sends.append(Send("worker", {"task_id": task["id"]}))
        
        return sends
    
    # If we have blocked/planned tasks but nothing ready, we're waiting
    if status_counts.get("blocked", 0) > 0 or status_counts.get("planned", 0) > 0:
        # Check if we're actually stuck (all non-terminal tasks are blocked)
        non_terminal = [t for t in tasks if t.get("status") not in terminal_statuses]
        all_blocked = all(t.get("status") == "blocked" for t in non_terminal)
        
        if all_blocked and non_terminal:
            # Truly stuck - might need human intervention
            # For now, return end and let Director handle escalation
            return "__end__"
    
    # Have active tasks running, or nothing to do
    if active_count > 0:
        return "wait"  # Wait for workers to finish
    
    return "__end__"


def route_after_worker(state: OrchestratorState, task_id: str) -> Literal["strategist", "director", "guardian"]:
    """
    Determine routing after Worker completes an iteration.
    
    Called after each worker step to check if:
    - Task is complete → strategist (for QA)
    - Task has escalation → director (to handle escalation)
    - Task is waiting_subtask → director (to spawn subtasks)
    - Task needs Guardian check → guardian
    - Task hit an issue → director
    
    Escalation routing:
    - Worker sets task status to BLOCKED and attaches escalation
    - Route to director to process escalation type
    - Director may create tasks, resolve conflicts, or escalate to human
    """
    task = None
    for t in state.get("tasks", []):
        if t["id"] == task_id:
            task = t
            break
    
    if not task:
        return "director"  # Task not found, error handling
    
    status = task.get("status")
    
    # Check for escalation (always route to director)
    if task.get("escalation"):
        return "director"
    
    if status == "awaiting_qa":
        return "strategist"
    elif status in ("blocked", "failed"):
        return "director"
    else:
        # Still active - this shouldn't happen in normal flow
        # as worker should set status before returning
        return "director"


def route_after_guardian(state: OrchestratorState, task_id: str) -> Literal["worker", "director"]:
    """
    Determine routing after Guardian check.
    
    Returns:
    - "worker" to continue execution (nudge injected if needed)
    - "director" if task should be killed (STALLED/UNSAFE)
    """
    guardian_state = state.get("guardian", {})
    last_verdict = guardian_state.get("last_verdict", "on_track")
    
    if last_verdict in ("stalled", "unsafe"):
        return "director"
    else:
        return "worker"


def route_after_strategist(state: OrchestratorState) -> Literal["director"]:
    """
    After Strategist, always return to Director.
    
    Director will:
    - Unblock dependent tasks if COMPLETE
    - Apply Phoenix if FAILED_QA
    - Escalate if max retries exceeded
    """
    return "director"


# =============================================================================
# CHECKPOINTING STRATEGY
# =============================================================================
"""
CHECKPOINTING STRATEGY

We use LangGraph's built-in checkpointing for:
1. Crash recovery - resume from last stable state
2. Human-in-the-loop - pause at WAITING_HUMAN, resume when input provided
3. Debugging - replay execution from any checkpoint

Checkpoint frequency:
- After every node execution (automatic with LangGraph)
- This means we checkpoint after every:
  - Director decision
  - Worker iteration
  - Guardian check
  - Strategist evaluation

Storage options:
- Development: MemorySaver (in-memory, lost on restart)
- Production: SqliteSaver (persistent, survives restart)
- Distributed: PostgresSaver (multi-instance, production scale)

Thread/Run management:
- Each run gets a unique thread_id (same as run_id)
- Multiple runs can execute concurrently with different thread_ids
- Resume a run by providing its thread_id

Checkpoint data includes:
- Full OrchestratorState
- Graph position (which node was last executed)
- Channel versions (for reducer consistency)
"""

def create_checkpointer(
    mode: Literal["memory", "sqlite", "postgres"] = "sqlite",
    db_path: str = "./orchestrator_checkpoints.db"
):
    """
    Create appropriate checkpointer based on deployment mode.
    
    Args:
        mode: "memory" for dev, "sqlite" for single-instance, "postgres" for distributed
        db_path: Path to SQLite database (only used for sqlite mode)
    
    Returns:
        LangGraph checkpointer instance
    """
    if mode == "memory":
        return MemorySaver()
    elif mode == "sqlite":
        return SqliteSaver.from_conn_string(f"sqlite:///{db_path}")
    elif mode == "postgres":
        # Requires: pip install langgraph-checkpoint-postgres
        from langgraph.checkpoint.postgres import PostgresSaver
        # Connection string from environment
        import os
        conn_string = os.environ.get("POSTGRES_CONNECTION_STRING")
        return PostgresSaver.from_conn_string(conn_string)
    else:
        raise ValueError(f"Unknown checkpointer mode: {mode}")


# =============================================================================
# GRAPH BUILDER
# =============================================================================

def build_orchestrator_graph(config: OrchestratorConfig) -> StateGraph:
    """
    Build the orchestrator StateGraph.
    
    This creates the graph structure but doesn't compile it.
    Call .compile() with a checkpointer to get a runnable graph.
    
    Args:
        config: Orchestrator configuration
    
    Returns:
        StateGraph ready for compilation
    """
    
    # Create graph with state schema
    graph = StateGraph(OrchestratorStateWithReducers)
    
    # -------------------------------------------------------------------------
    # ADD NODES
    # -------------------------------------------------------------------------
    
    # Director node - entry point and orchestration hub
    graph.add_node("director", director_node)
    
    # Worker node - unified worker that delegates to type-specific handlers
    # Receives task_id via Send()
    graph.add_node("worker", worker_node)
    
    # Strategist node - QA evaluation
    # Receives task_id from worker completion
    graph.add_node("strategist", strategist_node)
    
    # Guardian node - drift detection
    # Receives task_id when checkpoint triggers
    graph.add_node("guardian", guardian_node)
    
    # -------------------------------------------------------------------------
    # ADD EDGES
    # -------------------------------------------------------------------------
    
    # Entry point
    graph.set_entry_point("director")
    
    # Director routing (conditional - can dispatch multiple workers)
    graph.add_conditional_edges(
        "director",
        lambda state: route_after_director(state, config),
        {
            "__end__": END,
            "wait": "director",  # Loop back, waiting for workers
            # Send() targets handled automatically
        }
    )
    
    # Worker routing (after completion)
    # Note: This is simplified - actual implementation needs task_id context
    graph.add_conditional_edges(
        "worker",
        lambda state: route_after_worker_simple(state),
        {
            "strategist": "strategist",
            "guardian": "guardian",
            "director": "director",
        }
    )
    
    # Guardian routing
    graph.add_conditional_edges(
        "guardian",
        lambda state: route_after_guardian_simple(state),
        {
            "worker": "worker",
            "director": "director",
        }
    )
    
    # Strategist always returns to Director
    graph.add_edge("strategist", "director")
    
    return graph


def route_after_worker_simple(state: OrchestratorState) -> Literal["strategist", "director", "guardian"]:
    """Simplified routing that checks most recently updated task."""
    # Find the most recently active task
    tasks = state.get("tasks", [])
    active_or_awaiting = [
        t for t in tasks 
        if t.get("status") in ("awaiting_qa", "active")
    ]
    
    if not active_or_awaiting:
        return "director"
    
    # Sort by updated_at to find most recent
    active_or_awaiting.sort(key=lambda t: t.get("updated_at", ""), reverse=True)
    task = active_or_awaiting[0]
    
    if task.get("status") == "awaiting_qa":
        return "strategist"
    
    # Check if Guardian should run (based on iteration count in task metadata)
    task_meta = task.get("_worker_meta", {})
    if task_meta.get("needs_guardian_check", False):
        return "guardian"
    
    return "director"


def route_after_guardian_simple(state: OrchestratorState) -> Literal["worker", "director"]:
    """Simplified Guardian routing."""
    guardian_state = state.get("guardian", {})
    last_verdict = guardian_state.get("last_verdict", "on_track")
    
    if last_verdict in ("stalled", "unsafe"):
        return "director"
    return "worker"


# =============================================================================
# LANGSMITH OBSERVABILITY
# =============================================================================
"""
LangSmith Integration
---------------------

LangSmith provides automatic tracing for all LangGraph runs. To enable:

1. Set environment variables:
   export LANGCHAIN_TRACING_V2=true
   export LANGCHAIN_API_KEY=<your-api-key>
   export LANGCHAIN_PROJECT="agent-orchestrator"  # Optional project name

2. All LLM calls, node executions, and state transitions are automatically traced.

3. For custom spans (git operations, business events):

   from langsmith import traceable
   
   @traceable(name="git_commit")
   def commit_task_work(...):
       ...

4. Add run metadata for filtering in LangSmith UI:

   orchestrator.invoke(
       initial_state,
       config={
           "configurable": {"thread_id": run_id},
           "metadata": {
               "run_id": run_id,
               "objective": objective[:100],
           },
           "tags": ["orchestrator", "v1"],
       }
   )

5. Tag individual tasks by adding metadata in worker_node:

   from langsmith import get_current_run_tree
   
   run_tree = get_current_run_tree()
   if run_tree:
       run_tree.metadata["task_id"] = task_id
       run_tree.metadata["worker_profile"] = profile

Key traces to look for in LangSmith:
- director_node: Task decomposition and dispatch decisions
- worker_node: Individual task execution
- strategist_node: QA evaluation
- guardian_node: Drift/stall detection

Business metrics (QA pass rate, retry counts) are tracked in BlackboardState
and can be queried from final state or aggregated across runs externally.
"""


# =============================================================================
# COMPILED GRAPH & RUN FUNCTIONS
# =============================================================================

def create_orchestrator(
    config: Optional[OrchestratorConfig] = None,
    checkpoint_mode: Literal["memory", "sqlite", "postgres"] = "sqlite",
    db_path: str = "./orchestrator_checkpoints.db"
):
    """
    Create a compiled, runnable orchestrator.
    
    Args:
        config: Orchestrator configuration (uses defaults if None)
        checkpoint_mode: Checkpointing backend
        db_path: Path for SQLite checkpoints
    
    Returns:
        Compiled LangGraph that can be invoked or streamed
    """
    if config is None:
        config = OrchestratorConfig()
    
    graph = build_orchestrator_graph(config)
    checkpointer = create_checkpointer(checkpoint_mode, db_path)
    
    return graph.compile(checkpointer=checkpointer)


def start_run(
    orchestrator,
    objective: str,
    spec: Dict[str, Any],
    run_id: Optional[str] = None,
    tags: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    Start a new orchestrator run.
    
    Args:
        orchestrator: Compiled orchestrator graph
        objective: What to accomplish
        spec: Project specification (freeform dict)
        run_id: Optional run ID (generated if not provided)
        tags: Optional tags for LangSmith filtering
    
    Returns:
        Final state after run completes
    """
    import uuid
    
    if run_id is None:
        run_id = str(uuid.uuid4())
    
    initial_state = {
        "run_id": run_id,
        "objective": objective,
        "spec": spec,
        "design_log": [],
        "insights": [],
        "tasks": [],  # Director will populate via initial decomposition
        "task_memories": {},
        "filesystem_index": {},
        "guardian": {},
        "strategy_status": "progressing",
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat(),
    }
    
    # Run config with checkpointing and LangSmith metadata
    config = {
        "configurable": {"thread_id": run_id},
        # LangSmith metadata for observability
        "metadata": {
            "run_id": run_id,
            "objective": objective[:100],  # Truncate for display
        },
        "tags": tags or ["orchestrator"],
    }
    
    result = orchestrator.invoke(initial_state, config)
    return result


def resume_run(
    orchestrator,
    run_id: str,
    human_input: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Resume a paused or crashed run.
    
    Args:
        orchestrator: Compiled orchestrator graph
        run_id: ID of run to resume
        human_input: Optional input for WAITING_HUMAN tasks
    
    Returns:
        Final state after run completes
    """
    config = {"configurable": {"thread_id": run_id}}
    
    # If human input provided, inject it into state
    if human_input:
        # Get current state from checkpoint
        current_state = orchestrator.get_state(config)
        
        # Update tasks that were waiting for human input
        updated_tasks = []
        for task in current_state.values.get("tasks", []):
            if task.get("status") == "waiting_human":
                task_input = human_input.get(task["id"])
                if task_input:
                    task["status"] = "ready"  # Re-queue for execution
                    task["human_input"] = task_input
                    updated_tasks.append(task)
        
        if updated_tasks:
            # Update state with human input
            orchestrator.update_state(
                config,
                {"tasks": updated_tasks}
            )
    
    # Resume execution
    result = orchestrator.invoke(None, config)
    return result


def stream_run(
    orchestrator,
    objective: str,
    spec: Dict[str, Any],
    run_id: Optional[str] = None
):
    """
    Stream a run, yielding state after each node execution.
    
    Useful for:
    - Progress monitoring
    - Real-time UI updates
    - Debugging
    
    Yields:
        (node_name, state_update) tuples
    """
    import uuid
    
    if run_id is None:
        run_id = str(uuid.uuid4())
    
    initial_state = {
        "run_id": run_id,
        "objective": objective,
        "spec": spec,
        "design_log": [],
        "insights": [],
        "tasks": [],
        "task_memories": {},
        "filesystem_index": {},
        "guardian": {},
        "strategy_status": "progressing",
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat(),
    }
    
    config = {"configurable": {"thread_id": run_id}}
    
    for event in orchestrator.stream(initial_state, config, stream_mode="updates"):
        yield event


# =============================================================================
# HUMAN-IN-THE-LOOP SUPPORT
# =============================================================================

def get_waiting_tasks(orchestrator, run_id: str) -> List[Dict[str, Any]]:
    """
    Get tasks waiting for human input.
    
    Args:
        orchestrator: Compiled orchestrator graph
        run_id: ID of run to check
    
    Returns:
        List of tasks with status WAITING_HUMAN
    """
    config = {"configurable": {"thread_id": run_id}}
    state = orchestrator.get_state(config)
    
    if state is None:
        return []
    
    tasks = state.values.get("tasks", [])
    return [t for t in tasks if t.get("status") == "waiting_human"]


def provide_human_input(
    orchestrator,
    run_id: str,
    task_id: str,
    input_type: Literal["feedback", "decision", "artifact", "approval"],
    content: Any
) -> None:
    """
    Provide human input for a waiting task.
    
    Args:
        orchestrator: Compiled orchestrator graph
        run_id: ID of run
        task_id: ID of task waiting for input
        input_type: Type of input being provided
        content: The actual input
    """
    config = {"configurable": {"thread_id": run_id}}
    
    human_input = {
        "type": input_type,
        "content": content,
        "provided_at": datetime.now().isoformat(),
    }
    
    # Update the specific task
    orchestrator.update_state(
        config,
        {
            "tasks": [{
                "id": task_id,
                "status": "ready",
                "human_input": human_input,
                "updated_at": datetime.now().isoformat(),
            }]
        }
    )


# =============================================================================
# DEBUGGING & INSPECTION
# =============================================================================

def get_run_history(orchestrator, run_id: str) -> List[Dict[str, Any]]:
    """
    Get the full checkpoint history for a run.
    
    Useful for debugging and understanding execution flow.
    """
    config = {"configurable": {"thread_id": run_id}}
    history = []
    
    for state in orchestrator.get_state_history(config):
        history.append({
            "checkpoint_id": state.config.get("checkpoint_id"),
            "node": state.next,  # Next node to execute
            "task_count": len(state.values.get("tasks", [])),
            "status_summary": summarize_task_statuses(state.values.get("tasks", [])),
            "created_at": state.created_at,
        })
    
    return history


def summarize_task_statuses(tasks: List[Dict[str, Any]]) -> Dict[str, int]:
    """Count tasks by status."""
    summary = {}
    for task in tasks:
        status = task.get("status", "unknown")
        summary[status] = summary.get(status, 0) + 1
    return summary


def rollback_to_checkpoint(orchestrator, run_id: str, checkpoint_id: str) -> None:
    """
    Rollback a run to a specific checkpoint.
    
    WARNING: This discards all progress after the checkpoint.
    """
    config = {
        "configurable": {
            "thread_id": run_id,
            "checkpoint_id": checkpoint_id,
        }
    }
    
    # Get state at checkpoint
    state = orchestrator.get_state(config)
    
    # Update to that state (this effectively rolls back)
    orchestrator.update_state(
        {"configurable": {"thread_id": run_id}},
        state.values
    )


# =============================================================================
# USAGE EXAMPLE
# =============================================================================

if __name__ == "__main__":
    # Example usage
    
    # -------------------------------------------------------------------------
    # Option A: Default configuration (all Anthropic)
    # -------------------------------------------------------------------------
    orchestrator = create_orchestrator(
        checkpoint_mode="sqlite",
        db_path="./my_project_checkpoints.db"
    )
    
    # -------------------------------------------------------------------------
    # Option B: Multi-provider configuration
    # -------------------------------------------------------------------------
    from orchestrator_types import ModelConfig
    
    config = OrchestratorConfig()
    
    # Use different providers for different roles
    config.set_provider_for_role("director", "anthropic", "claude-sonnet-4-20250514")
    config.set_provider_for_role("strategist", "anthropic", "claude-sonnet-4-20250514")
    config.set_provider_for_role("guardian", "openai", "gpt-4o-mini", max_tokens=1024)
    
    # Use GLM for coding tasks
    config.set_provider_for_role("code_worker", "glm", "glm-4-plus")
    config.set_provider_for_role("test_worker", "glm", "glm-4-plus")
    
    # Use OpenAI for research (good at web search synthesis)
    config.set_provider_for_role("research_worker", "openai", "gpt-4o")
    
    # Keep Anthropic for planning and writing
    config.set_provider_for_role("planner_worker", "anthropic", "claude-sonnet-4-20250514")
    config.set_provider_for_role("writer_worker", "anthropic", "claude-sonnet-4-20250514")
    
    orchestrator = create_orchestrator(
        config=config,
        checkpoint_mode="sqlite",
        db_path="./my_project_checkpoints.db"
    )
    
    # -------------------------------------------------------------------------
    # Define project
    # -------------------------------------------------------------------------
    objective = "Build a Todo Board web app"
    spec = {
        "db": {
            "tables": {
                "todos": {
                    "columns": ["id", "title", "description", "status", "due_date"],
                    "constraints": ["status IN ('todo', 'in_progress', 'done')"]
                }
            }
        },
        "ui": {
            "layout": "3-column-kanban",
            "colors": {"overdue": "#ef4444"}
        },
        "business_rules": [
            "status defaults to 'todo'",
            "delete requires confirmation",
            "overdue = due_date < today AND status != 'done'"
        ]
    }
    
    # -------------------------------------------------------------------------
    # Run options
    # -------------------------------------------------------------------------
    
    # Option 1: Run to completion
    # final_state = start_run(orchestrator, objective, spec)
    
    # Option 2: Stream for progress updates
    # for node, update in stream_run(orchestrator, objective, spec):
    #     print(f"[{node}] Updated: {list(update.keys())}")
    
    # Option 3: Run with human-in-the-loop
    # run_id = "my-run-123"
    # start_run(orchestrator, objective, spec, run_id)
    # ... later ...
    # waiting = get_waiting_tasks(orchestrator, run_id)
    # if waiting:
    #     provide_human_input(orchestrator, run_id, waiting[0]["id"], "approval", True)
    #     resume_run(orchestrator, run_id)
    
    print("Orchestrator ready!")
    print(f"Models configured: {list(config.models.keys())}")
