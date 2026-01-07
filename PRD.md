# Product Requirements Document (PRD)
# Agent Orchestrator Framework v2.0

**Version:** 2.0
**Date:** January 2026
**Status:** Production
**Branch:** improved-pre-tdd

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [System Architecture Overview](#2-system-architecture-overview)
3. [Core Components](#3-core-components)
4. [State Management](#4-state-management)
5. [Agent Nodes](#5-agent-nodes)
6. [Tool System](#6-tool-system)
7. [Git Worktree Management](#7-git-worktree-management)
8. [API Layer](#8-api-layer)
9. [Frontend Dashboard](#9-frontend-dashboard)
10. [Persistence Layer](#10-persistence-layer)
11. [Configuration](#11-configuration)
12. [Metrics & Observability](#12-metrics--observability)
13. [Implementation Guide](#13-implementation-guide)
14. [Technology Stack](#14-technology-stack)
15. [File Structure](#15-file-structure)

---

## 1. Executive Summary

### 1.1 Product Overview

The **Agent Orchestrator Framework** is a LangGraph-based multi-agent system designed to collaboratively solve complex software engineering tasks. It orchestrates specialized worker agents through a blackboard pattern, enabling autonomous code generation, testing, and deployment with human-in-the-loop (HITL) intervention capabilities.

### 1.2 Key Capabilities

- **Multi-Agent Orchestration**: Director, Worker, Strategist, and Guardian agents collaborate via shared state
- **Task Decomposition**: Automatic breakdown of objectives into parallel executable tasks
- **Git Worktree Isolation**: Each task operates in an isolated git worktree preventing conflicts
- **Progressive Tool Disclosure**: Tools loaded on-demand to minimize LLM token consumption
- **Human-in-the-Loop (HITL)**: Automatic escalation when tasks exceed retry limits
- **Real-time Monitoring**: WebSocket-based dashboard with task graph visualization
- **Multi-Database Support**: SQLite, PostgreSQL, and MySQL for state persistence
- **Phoenix Retry Protocol**: Automatic retry with fresh context on task failures

### 1.3 Target Use Cases

1. **Autonomous Code Generation**: Generate complete features from natural language specifications
2. **Test-Driven Development**: Automated test creation and validation
3. **Codebase Refactoring**: Large-scale refactoring with verification
4. **Documentation Generation**: Auto-generate docs from code analysis
5. **Research & Analysis**: Web research with synthesized reports

---

## 2. System Architecture Overview

### 2.1 High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           ORCHESTRATOR DASHBOARD                             │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐      │
│  │Dashboard │  │ NewRun   │  │RunDetails│  │HumanQueue│  │TaskGraph │      │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘      │
│       └──────────────┴──────────────┴──────────────┴──────────────┘          │
│                                    │                                          │
│                              WebSocket + REST API                             │
└────────────────────────────────────┬────────────────────────────────────────┘
                                     │
┌────────────────────────────────────┴────────────────────────────────────────┐
│                              FASTAPI SERVER                                  │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐        │
│  │ /api/runs   │  │ /api/tasks  │  │/api/interrupts│ │    /ws     │        │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘        │
│         └────────────────┴─────────────────┴────────────────┘               │
│                                    │                                         │
│                        CONTINUOUS DISPATCH LOOP                              │
└────────────────────────────────────┬────────────────────────────────────────┘
                                     │
┌────────────────────────────────────┴────────────────────────────────────────┐
│                           LANGGRAPH STATE MACHINE                            │
│                                                                              │
│    ┌──────────┐     ┌──────────┐     ┌───────────┐     ┌──────────┐        │
│    │ DIRECTOR │────▶│  WORKER  │────▶│STRATEGIST │────▶│ DIRECTOR │        │
│    └──────────┘     └──────────┘     └───────────┘     └──────────┘        │
│         │                │                 │                                 │
│         │          ┌─────┴─────┐          │                                 │
│         │          │  HANDLERS │          │                                 │
│         │          ├───────────┤          │                                 │
│         │          │• Planner  │          │                                 │
│         │          │• Coder    │          │                                 │
│         │          │• Tester   │          │                                 │
│         │          │• Research │          │                                 │
│         │          │• Writer   │          │                                 │
│         │          │• Merger   │          │                                 │
│         │          │• QA       │          │                                 │
│         │          └───────────┘          │                                 │
│         │                                 │                                 │
│         └────────────────┬────────────────┘                                 │
│                          ▼                                                   │
│                  ┌───────────────┐                                          │
│                  │OrchestratorState│                                         │
│                  │  (Blackboard)  │                                          │
│                  └───────────────┘                                          │
└────────────────────────────────────┬────────────────────────────────────────┘
                                     │
┌────────────────────────────────────┴────────────────────────────────────────┐
│                              INFRASTRUCTURE                                  │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐    │
│  │WorktreeManager│  │  LLM Client  │  │  Tool System │  │  Persistence │    │
│  │  (Git Ops)   │  │(Multi-Provider)│ │(Progressive) │  │(SQL/MySQL)   │    │
│  └──────────────┘  └──────────────┘  └──────────────┘  └──────────────┘    │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 2.2 Graph Execution Flow

```
Entry ─▶ DIRECTOR ─┬─▶ WORKER ─┬─▶ STRATEGIST ─▶ DIRECTOR
                   │           │       (QA)
                   │           │
                   │           └─▶ DIRECTOR (skip QA for PLAN/BUILD)
                   │
                   └─▶ END (all tasks complete)
```

### 2.3 Core Design Patterns

| Pattern | Purpose | Implementation |
|---------|---------|----------------|
| **Blackboard** | Shared state coordination | OrchestratorState TypedDict |
| **State Machine** | Workflow orchestration | LangGraph StateGraph |
| **Reducer** | Concurrent state merging | Custom reducer functions |
| **Progressive Disclosure** | Token optimization | On-demand tool loading |
| **Worktree Isolation** | Conflict prevention | Per-task git worktrees |
| **Phoenix Retry** | Fault tolerance | Auto-retry with fresh context |
| **HITL** | Human oversight | LangGraph interrupt() |

---

## 3. Core Components

### 3.1 Entry Points

#### 3.1.1 CLI Entry (`src/main.py`)

**Purpose**: Command-line interface for standalone runs

**Signature**:
```bash
python -m src.main --objective "Build a REST API" --workspace ./project [--provider openai] [--model gpt-4]
```

**Arguments**:
| Argument | Required | Default | Description |
|----------|----------|---------|-------------|
| `--objective` | Yes | - | High-level task description |
| `--workspace` | No | `../workspace` | Project directory |
| `--provider` | No | Config default | LLM provider (anthropic, openai, google, glm, openrouter, local) |
| `--model` | No | Config default | Model name |
| `--mock-run` | No | False | Enable mock mode for testing |

**Behavior**:
1. Parse CLI arguments
2. Load `.env` environment variables
3. Create SQLite checkpointer at `orchestrator.db`
4. Initialize logging to `{workspace}/logs/run_{timestamp}.log`
5. Call `start_run()` with configuration
6. Report completion status

#### 3.1.2 Server Entry (`src/server.py`)

**Purpose**: FastAPI server for dashboard and API access

**Startup Sequence**:
1. Initialize checkpointer (SQLite/PostgreSQL/MySQL based on config)
2. Create database tables (idempotent)
3. Mount API routers
4. Initialize WebSocket ConnectionManager
5. Serve static dashboard files (if built)
6. Start Uvicorn server

**Configuration**:
```python
# Default: SQLite
checkpoint_mode = "sqlite"  # or "postgres", "mysql"

# Environment Variables
POSTGRES_URI = "postgresql://user:pass@host:5432/db"
MYSQL_URI = "mysql://user:pass@host:3306/db"
FRONTEND_URL = "*"  # CORS origins
```

### 3.2 Graph Definition (`src/langgraph_definition.py`)

**Purpose**: Assemble LangGraph StateGraph with nodes and edges

**Function**: `create_orchestrator(config, checkpoint_mode, checkpointer) -> CompiledGraph`

**Graph Structure**:
```python
graph = StateGraph(OrchestratorState)

# Add Nodes
graph.add_node("director", director_node)
graph.add_node("worker", worker_node)
graph.add_node("strategist", strategist_node)

# Set Entry Point
graph.set_entry_point("director")

# Conditional Routing
graph.add_conditional_edges("director", route_after_director)
  # Routes to: "worker" or END

graph.add_conditional_edges("worker", route_after_worker)
  # TEST phase → "strategist"
  # PLAN/BUILD phase → "director"

graph.add_edge("strategist", "director")

# Compile with checkpointer
return graph.compile(checkpointer=checkpointer)
```

**Function**: `start_run(objective, workspace, spec, config, checkpointer) -> Dict`

**Initial State**:
```python
{
    "run_id": f"run_{uuid.hex[:8]}",
    "objective": objective,
    "spec": spec or {},
    "tasks": [],
    "insights": [],
    "design_log": [],
    "task_memories": {},
    "filesystem_index": {},
    "guardian": {},
    "strategy_status": "progressing",
    "created_at": iso_timestamp,
    "updated_at": iso_timestamp,
    "mock_mode": config.mock_mode,
    "_wt_manager": WorktreeManager,
    "_workspace_path": workspace_path,
    "_worktree_base_path": worktree_base,
    "_logs_base_path": logs_base_path,
    "orch_config": config,
}
```

**Invocation**:
```python
result = await orchestrator.ainvoke(
    initial_state,
    config={
        "recursion_limit": 150,
        "configurable": {
            "thread_id": thread_id,
            "mock_mode": mock_mode
        }
    }
)
```

---

## 4. State Management

### 4.1 OrchestratorState Schema (`src/state.py`)

```python
class OrchestratorState(TypedDict, total=False):
    # Identity (set once)
    run_id: str
    objective: str

    # Persistent context (uses reducers)
    spec: Dict[str, Any]                                          # Last-write-wins
    design_log: Annotated[List[Dict], design_log_reducer]         # Append-only
    insights: Annotated[List[Dict], insights_reducer]             # Append-only
    tasks: Annotated[List[Dict], tasks_reducer]                   # Merge by ID
    task_memories: Annotated[Dict[str, List[BaseMessage]], task_memories_reducer]

    # Control flags
    pending_resolution: Dict[str, Any]   # HITL resolution data
    filesystem_index: Dict[str, str]     # File ownership tracking
    guardian: Dict[str, Any]             # Guardian state
    replan_requested: bool               # Manual replan trigger
    pending_reorg: bool                  # Smart replan flag
    strategy_status: str                 # Overall status

    # Internal state (not serialized)
    _wt_manager: Any                     # WorktreeManager instance
    _workspace_path: str                 # Workspace root
    _worktree_base_path: str             # Worktree directory
    _logs_base_path: str                 # Logs directory
    orch_config: Any                     # OrchestratorConfig
    _interrupt_data: Dict[str, Any]      # HITL pause data

    # Metadata
    created_at: str                      # ISO timestamp
    updated_at: str                      # ISO timestamp
    mock_mode: bool                      # Test mode flag
```

### 4.2 State Reducers

#### 4.2.1 tasks_reducer
```python
def tasks_reducer(existing: List[Dict], updates: List[Dict]) -> List[Dict]:
    """
    Merge task updates into existing task list.
    - If update has matching ID: replace the task
    - If update has new ID: append
    - If update has {"_delete": True, "id": X}: remove task X
    """
    existing_by_id = {t["id"]: t for t in existing}
    for update in updates:
        if update.get("_delete"):
            existing_by_id.pop(update["id"], None)
        else:
            existing_by_id[update["id"]] = update
    return list(existing_by_id.values())
```

#### 4.2.2 insights_reducer
```python
def insights_reducer(existing: List[Dict], updates: List[Dict]) -> List[Dict]:
    """
    Append new insights (immutable once created).
    Duplicates (by ID) are ignored.
    """
    existing_ids = {i["id"] for i in existing}
    new_insights = [u for u in updates if u["id"] not in existing_ids]
    return existing + new_insights
```

#### 4.2.3 design_log_reducer
```python
def design_log_reducer(existing: List[Dict], updates: List[Dict]) -> List[Dict]:
    """
    Append-only design decisions.
    New decisions only (duplicates ignored).
    """
    existing_ids = {d["id"] for d in existing}
    new_decisions = [u for u in updates if u["id"] not in existing_ids]
    return existing + new_decisions
```

#### 4.2.4 task_memories_reducer
```python
def task_memories_reducer(
    existing: Dict[str, List[BaseMessage]],
    updates: Dict[str, List[BaseMessage]]
) -> Dict[str, List[BaseMessage]]:
    """
    Merge task memories (LLM conversation histories).
    - New messages appended to existing task memory
    - Special key "_clear" with list of task_ids wipes those memories
    """
    result = dict(existing)

    if "_clear" in updates:
        for task_id in updates["_clear"]:
            result.pop(task_id, None)
        return result

    for task_id, messages in updates.items():
        if task_id in result:
            result[task_id] = result[task_id] + messages
        else:
            result[task_id] = messages

    return result
```

### 4.3 Type Definitions (`src/orchestrator_types.py`)

#### 4.3.1 Task Status Enum
```python
class TaskStatus(str, Enum):
    PLANNED = "planned"                    # Exists, dependencies known
    READY = "ready"                        # Prerequisites met
    BLOCKED = "blocked"                    # Cannot proceed
    ACTIVE = "active"                      # Worker executing
    AWAITING_QA = "awaiting_qa"            # Artifact produced
    FAILED_QA = "failed_qa"                # Strategist rejected
    FAILED = "failed"                      # Execution error
    COMPLETE = "complete"                  # Strategist approved
    WAITING_HUMAN = "waiting_human"        # Needs manual input
    ABANDONED = "abandoned"                # Removed during replan
    PENDING_AWAITING_QA = "pending_awaiting_qa"  # Director sync needed
    PENDING_COMPLETE = "pending_complete"        # QA done, sync needed
    PENDING_FAILED = "pending_failed"            # Failed, sync needed
```

#### 4.3.2 Task Phase Enum
```python
class TaskPhase(str, Enum):
    PLAN = "plan"       # Planning/design
    BUILD = "build"     # Implementation
    TEST = "test"       # Testing/validation
```

#### 4.3.3 Worker Profile Enum
```python
class WorkerProfile(str, Enum):
    PLANNER = "planner_worker"
    CODER = "code_worker"
    TESTER = "test_worker"
    RESEARCHER = "research_worker"
    WRITER = "writer_worker"
    MERGER = "merge_worker"
    QA = "qa_worker"
```

#### 4.3.4 Task Dataclass
```python
@dataclass
class Task:
    id: str
    title: str
    component: str
    phase: TaskPhase
    description: str
    status: TaskStatus = TaskStatus.PLANNED
    depends_on: List[str] = field(default_factory=list)
    dependency_queries: List[str] = field(default_factory=list)
    priority: int = 5
    assigned_worker_profile: Optional[WorkerProfile] = None
    retry_count: int = 0
    max_retries: int = 3
    acceptance_criteria: List[str] = field(default_factory=list)
    result_path: Optional[str] = None
    qa_verdict: Optional[QAVerdict] = None
    aar: Optional[AAR] = None
    blocked_reason: Optional[BlockedReason] = None
    escalation: Optional[Escalation] = None
    checkpoint: Optional[WorkerCheckpoint] = None
    waiting_for_tasks: List[str] = field(default_factory=list)
    branch_name: Optional[str] = None
    worktree_path: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
```

#### 4.3.5 WorkerResult Dataclass
```python
@dataclass
class WorkerResult:
    status: Literal["complete", "blocked", "failed", "waiting_subtask"]
    result_path: Optional[str]
    aar: AAR
    insights: List[Insight] = field(default_factory=list)
    suggested_tasks: List[SuggestedTask] = field(default_factory=list)
    messages: List[BaseMessage] = field(default_factory=list)
    escalation: Optional[Escalation] = None
    checkpoint: Optional[WorkerCheckpoint] = None
```

#### 4.3.6 AAR (After Action Report) Dataclass
```python
@dataclass
class AAR:
    summary: str
    approach: str
    challenges: List[str]
    decisions_made: List[str]
    files_modified: List[str]
    time_spent_estimate: Optional[str] = None
```

#### 4.3.7 QAVerdict Dataclass
```python
@dataclass
class QAVerdict:
    passed: bool
    criterion_results: List[CriterionResult]
    overall_feedback: str
    suggested_focus: Optional[str] = None
    test_analysis: Optional[List[TestFailureAnalysis]] = None
    tests_needing_revision: List[str] = field(default_factory=list)
    refined_test_criteria: Optional[List[str]] = None
```

---

## 5. Agent Nodes

### 5.1 Director Node (`src/nodes/director_main.py`)

**Purpose**: Task decomposition, integration, readiness evaluation, state management

**Signature**:
```python
async def director_node(state: OrchestratorState, config: RunnableConfig = None) -> Dict[str, Any]
```

**Responsibilities**:

1. **Phase 0: State Promotion** - Confirm pending states
   - `PENDING_AWAITING_QA` → `AWAITING_QA`
   - `PENDING_COMPLETE` → `COMPLETE`
   - `PENDING_FAILED` → `FAILED`

2. **Initial Decomposition** (if no tasks exist)
   - Explore existing project structure
   - Create `design_spec.md` via LLM
   - Decompose into 1-5 planner tasks

3. **Phoenix Retry Protocol** (retry_count < 4)
   - `FAILED` → `PLANNED` (retry)
   - TEST failed QA → Spawn BUILD task to fix code

4. **Readiness Evaluation**
   - `PLANNED` → `READY` when all dependencies are `COMPLETE`

5. **Plan Integration** (after all planners complete)
   - Collect `suggested_tasks` from completed tasks
   - PASS 1: Deduplication & scope validation (LLM)
   - PASS 1.5: Feature-to-foundation linking (deterministic)
   - PASS 2: Dependency query resolution (LLM)
   - PASS 3: Transitive reduction (optional)

6. **Human-in-the-Loop** (max retries exceeded)
   - Set `status = WAITING_HUMAN`
   - Call `interrupt()` with task context

**Submodules**:
- `director/decomposition.py` - Objective breakdown
- `director/integration.py` - Plan integration
- `director/readiness.py` - Task readiness evaluation
- `director/hitl.py` - Human resolution processing
- `director/graph_utils.py` - Cycle detection

### 5.2 Worker Node (`src/nodes/worker.py`)

**Purpose**: Execute tasks using profile-specific handlers

**Signature**:
```python
async def worker_node(state: Dict[str, Any], config: RunnableConfig = None) -> Dict[str, Any]
```

**Execution Flow**:
1. Find task to execute (from `task_id` in state)
2. Get/create worktree for task
3. Select handler based on `assigned_worker_profile`
4. Execute ReAct agent with bound tools
5. Commit changes to worktree
6. Return `WorkerResult` with status, AAR, suggested_tasks

**Handler Selection**:
```python
handlers = {
    WorkerProfile.PLANNER: _plan_handler,
    WorkerProfile.CODER: _code_handler,
    WorkerProfile.TESTER: _test_handler,
    WorkerProfile.RESEARCHER: _research_handler,
    WorkerProfile.WRITER: _write_handler,
    WorkerProfile.MERGER: _merge_handler,
}
```

### 5.3 Strategist Node (`src/nodes/strategist.py`)

**Purpose**: QA evaluation and merge coordination

**Signature**:
```python
async def strategist_node(state: Dict[str, Any], config: RunnableConfig = None) -> Dict[str, Any]
```

**Workflow**:
1. Find tasks with `status = AWAITING_QA`
2. For PLAN tasks: Auto-pass
3. For BUILD/TEST tasks: Run QA agent verification
4. Parse QA verdict (PASS/FAIL)
5. If PASS: Rebase on main, then merge
6. If CONFLICT: Spawn merge task, rewire dependencies
7. Set final status (`PENDING_COMPLETE` or `PENDING_FAILED`)

**Merge Task Creation** (on conflict):
```python
{
    "title": f"Resolve merge conflicts from {original_task}",
    "phase": "build",
    "status": "ready",
    "assigned_worker_profile": "merger",
    "depends_on": [original_task_id],
    "_use_worktree_task_id": original_task_id,
    "_merge_context": {
        "original_task_id": str,
        "conflict_files": List[str],
        "error_message": str
    }
}
```

### 5.4 Routing Functions (`src/nodes/routing.py`)

#### 5.4.1 route_after_director
```python
def route_after_director(state) -> Literal["__end__", "director"] | List[Send]:
    """
    1. No tasks → END
    2. All terminal (COMPLETE|ABANDONED|WAITING_HUMAN) → END
    3. PLANNED but no READY → "director" (re-evaluate)
    4. READY tasks exist → [Send("worker", {task_id}), ...]
    """
```

#### 5.4.2 route_after_worker
```python
def route_after_worker(state) -> Literal["director"] | List[Send]:
    """
    1. For AWAITING_QA tasks:
       - TEST phase → dispatch to "strategist"
       - PLAN/BUILD → mark COMPLETE (skip QA)
    2. If test tasks exist → [Send("strategist", ...)]
    3. Else → "director"
    """
```

### 5.5 Worker Handlers

#### 5.5.1 Plan Handler (`handlers/plan_handler.py`)

**Tools**: `read_file`, `write_file`, `list_directory`, `file_exists`, `create_subtasks`

**Component-Aware Roles**:
1. **Foundation Architect** (component = "foundation"/"infrastructure")
   - Creates ONE massive scaffold task
   - Installs ALL dependencies
   - No dependency_queries (root of tree)

2. **Feature Architect** (normal component)
   - Builds vertical slices (Model + API + UI + Test)
   - Uses dependency_queries for cross-feature dependencies
   - Forbidden: No scaffolding, no configs

3. **Testing Architect** (component = "verification"/"testing")
   - Runs AFTER all features complete
   - First task MUST have `dependency_queries: ["All feature implementations complete"]`

**MANDATORY**: Must call `create_subtasks` with at least ONE test task

#### 5.5.2 Code Handler (`handlers/code_handler.py`)

**Tools**: `read_file`, `write_file`, `delete_file`, `list_directory`, `file_exists`, `run_python`, `run_shell`, `report_existing_implementation`

**Key Constraints**:
- NEVER HTML-escape code
- ALWAYS use `file_exists` before `write_file`
- Use shared venv (NEVER global pip install)
- No blocking commands (Flask run, npm start)
- Verify code works before completion
- Delete temporary test files

#### 5.5.3 Test Handler (`handlers/test_handler.py`)

**Tools**: `read_file`, `write_file`, `list_directory`, `run_python`, `run_shell`, `create_subtasks`

**MANDATORY OUTPUT**: Create `agents-work/test-results/test-{component}.md`

**File Contents**:
```markdown
# Test Results: {component}

## Command Run
`python -m pytest tests/test_api.py -v`

## Output
```
(actual test output)
```

## Summary
✅ All tests passed (N/M) OR ❌ X tests failed
```

**Task FAILS automatically if file doesn't exist**

#### 5.5.4 QA Handler (`handlers/qa_handler.py`)

**Tools (READ-ONLY)**: `read_file`, `list_directory`, `file_exists`, `run_python`, `run_shell`

**Verdict Format**:
```
QA_VERDICT: PASS
QA_FEEDBACK: [Evidence]
```
OR
```
QA_VERDICT: FAIL
QA_FEEDBACK: [What's missing]
QA_SUGGESTIONS: [Improvements]
```

#### 5.5.5 Research Handler (`handlers/research_handler.py`)

**Tools**: `read_file`, `write_file`, `list_directory`, `tavily_search_tool`

**Output**: `research-results/report.md` with:
- Executive summary
- Findings
- Analysis
- Recommendations
- Sources

#### 5.5.6 Write Handler (`handlers/write_handler.py`)

**Tools**: `read_file`, `write_file`, `list_directory`

**Purpose**: Technical documentation, commit messages

#### 5.5.7 Merge Handler (`handlers/merge_handler.py`)

**Tools**: `read_file`, `write_file`, `list_directory`, `file_exists`, `run_shell`

**Workflow**:
1. `git rebase main` (shows conflicts)
2. Examine conflicts with `git status`, `git diff`
3. Resolve by merging BOTH changes (don't pick sides)
4. `git add <file>` after each resolution
5. `git rebase --continue`
6. Verify merged code works

---

## 6. Tool System

### 6.1 Tool Architecture

**Pattern**: Progressive disclosure - tools loaded on-demand per task

**Tool Categories**:
```python
class ToolCategory(str, Enum):
    FILESYSTEM = "filesystem"
    GIT = "git"
    WEB = "web"
    CODE_EXECUTION = "code_execution"
    DATABASE = "database"
    COMMUNICATION = "communication"
```

### 6.2 Tool Definition Structure

```python
@dataclass
class ToolDefinition:
    name: str
    category: ToolCategory
    description: str
    detailed_docs: str
    parameters: List[ToolParameter]
    returns: str
    examples: List[str] = field(default_factory=list)
    requires_confirmation: bool = False
    is_destructive: bool = False
    estimated_latency: str = "fast"  # fast, medium, slow
```

### 6.3 Filesystem Tools (`src/tools/filesystem_async.py`)

| Tool | Signature | Description |
|------|-----------|-------------|
| `read_file_async` | `(path, encoding="utf-8", root=None) -> str` | Read file contents |
| `write_file_async` | `(path, content, encoding="utf-8", root=None) -> str` | Create/overwrite file |
| `append_file_async` | `(path, content, encoding="utf-8", root=None) -> str` | Append to file |
| `list_directory_async` | `(path=".", recursive=False, pattern="*", max_depth=3, max_results=500) -> List[str]` | List directory |
| `file_exists_async` | `(path, root=None) -> bool` | Check existence |
| `delete_file_async` | `(path, confirm, root=None) -> str` | Delete file (requires confirm=True) |

**Path Security**:
```python
def _is_safe_path(path: str, root: Path, additional_roots: List[Path]) -> bool:
    """Ensure path is within workspace or allowed directories"""
```

**Auto-Excluded Directories**: `node_modules`, `venv`, `__pycache__`, `.git`, `.svn`, `dist`, `build`, `.tox`

### 6.4 Git Tools (`src/tools/git_async.py`)

| Tool | Signature | Description |
|------|-----------|-------------|
| `git_commit_async` | `(message, add_all=False) -> str` | Commit staged changes |
| `git_status_async` | `() -> str` | Show working tree status |
| `git_diff_async` | `(target="HEAD", path=None) -> str` | Show changes |
| `git_add_async` | `(paths: List[str]) -> str` | Stage files |
| `git_log_async` | `(count=10) -> str` | Show commit history |

### 6.5 Code Execution Tools (`src/tools/code_execution_async.py`)

| Tool | Signature | Description |
|------|-----------|-------------|
| `run_python_async` | `(code, timeout=30, cwd=None, workspace_path=None) -> str` | Execute Python |
| `run_shell_async` | `(command, timeout=30, cwd=None, workspace_path=None) -> str` | Execute shell |

**Features**:
- Uses workspace `.venv` if available
- Process group handling for timeout cleanup
- Windows: `CREATE_NEW_PROCESS_GROUP` + `taskkill /T`
- Unix: `os.setsid()` + `killpg()`

### 6.6 Search Tools (`src/tools/search_tools.py`)

```python
def get_tavily_search_tool(max_results=5) -> TavilySearch
async def web_search(query: str, max_results=5) -> List[Dict]
```

**Requires**: `TAVILY_API_KEY` environment variable

### 6.7 Tool Binding (`src/nodes/tools_binding.py`)

**Purpose**: Bind tools to worktree context with safety constraints

```python
def _bind_tools(tools: List[Callable], state: Dict, profile: WorkerProfile) -> List[Callable]:
    """
    - Bind worktree path as root
    - Add main workspace and merge source as additional_roots
    - Enforce read-before-write for existing files
    """
```

**Read-Before-Write Enforcement**:
```python
def _create_write_file_wrapper(tool, worktree_path, workspace_path, source_worktree_path, files_read):
    """
    If file exists and NOT in files_read → REJECT write
    Agent must read_file first to prevent overwriting
    """
```

### 6.8 Shared Tools (`src/nodes/shared_tools.py`)

#### create_subtasks
```python
def create_subtasks(subtasks: List[SubtaskDefinition]) -> str:
    """
    Create commit-level subtasks (atomic, reviewable changes)

    Validation:
    - Max 15 subtasks per call
    - Each must have title and description
    - Phase must be "plan", "build", or "test"
    """
```

#### report_existing_implementation
```python
def report_existing_implementation(file_path, implementation_summary, verification_details) -> str:
    """
    Signal that existing code already implements required feature
    ONLY for pre-existing code, NOT for code just created
    """
```

---

## 7. Git Worktree Management

### 7.1 WorktreeManager (`src/git_manager.py`)

**Purpose**: Per-task git worktree isolation

**Configuration**:
```python
@dataclass
class AsyncWorktreeManager:
    repo_path: Path
    worktree_base: Path
    main_branch: str = "main"
    worktrees: Dict[str, WorktreeInfo] = field(default_factory=dict)
    _merge_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
```

### 7.2 WorktreeInfo Structure

```python
@dataclass
class WorktreeInfo:
    task_id: str
    branch_name: str
    worktree_path: Path
    status: WorktreeStatus
    created_at: datetime
    merged_at: Optional[datetime] = None
    deleted_at: Optional[datetime] = None
    retry_number: int = 0
    previous_branch: Optional[str] = None
    commits: List[str] = field(default_factory=list)
    files_modified: List[str] = field(default_factory=list)
```

### 7.3 Worktree Lifecycle

```
1. CREATE: git worktree add --force {worktree_base}/{task_id} -b task/{task_id} main
           ↓
2. WORK:   Agent writes files to worktree_path
           Files isolated from other tasks
           ↓
3. COMMIT: git add -A; git commit -m "Task {id} complete"
           ↓
4. REBASE: git fetch . main:main; git rebase main
           ↓ (conflict → spawn merge task)
5. MERGE:  git merge task/{id} --no-ff
           CRITICAL: Uses asyncio.Lock to serialize merges
           ↓
6. CLEANUP: git worktree remove task/{id}
```

### 7.4 Key Methods

```python
async def create_worktree(task_id: str, retry_number: int = 0) -> WorktreeInfo
async def commit_changes(task_id: str, message: str) -> str
async def rebase_on_main(task_id: str) -> MergeResult
async def merge_to_main(task_id: str) -> MergeResult  # Uses _merge_lock
async def cleanup_worktree(task_id: str) -> None
async def recover_worktrees(task_ids: List[str]) -> int
```

### 7.5 MergeResult Structure

```python
@dataclass
class MergeResult:
    success: bool
    task_id: str
    conflict: bool = False
    conflicting_files: List[str] = field(default_factory=list)
    error_message: str = ""
    llm_resolved: bool = False
```

### 7.6 Phoenix Retry Pattern

On task failure:
1. Create `task/{id}/retry-{n}` branch from failed branch
2. Task gets fresh worktree with read-only reference to failed attempt
3. Failed branch preserved for debugging

---

## 8. API Layer

### 8.1 API Routes Overview

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/v1/runs` | GET | List all runs (paginated) |
| `/api/v1/runs` | POST | Create and start new run |
| `/api/v1/runs/{run_id}` | GET | Get full run details |
| `/api/v1/runs/{run_id}/pause` | POST | Pause run |
| `/api/v1/runs/{run_id}/resume` | POST | Resume paused run |
| `/api/v1/runs/{run_id}/replan` | POST | Trigger task replanning |
| `/api/v1/runs/{run_id}/cancel` | POST | Cancel running run |
| `/api/v1/runs/{run_id}/restart` | POST | Restart from checkpoint |
| `/api/v1/runs/{run_id}/tasks/{task_id}` | PATCH | Update task dependencies |
| `/api/v1/runs/{run_id}/tasks/{task_id}` | DELETE | Abandon task |
| `/api/v1/runs/{run_id}/tasks/{task_id}/memories` | GET | Get task conversation history |
| `/api/v1/runs/{run_id}/tasks/{task_id}/interrupt` | POST | Force interrupt task |
| `/api/v1/runs/{run_id}/interrupts` | GET | Check for pending interrupts |
| `/api/v1/runs/{run_id}/resolve` | POST | Resolve HITL intervention |
| `/ws` | WebSocket | Real-time state updates |
| `/metrics` | GET | Prometheus metrics |

### 8.2 Request/Response Types (`src/api/types.py`)

#### CreateRunRequest
```python
class CreateRunRequest(BaseModel):
    objective: str                      # Required
    spec: Optional[Dict[str, Any]]
    tags: Optional[List[str]]
    workspace: Optional[str]
```

#### RunSummary
```python
class RunSummary(BaseModel):
    run_id: str
    objective: str
    status: str
    created_at: str
    updated_at: str
    task_counts: Dict[str, int]
    tags: List[str]
    workspace_path: Optional[str]
```

#### HumanResolution
```python
class HumanResolution(BaseModel):
    task_id: str
    action: str                         # 'retry', 'abandon', 'spawn_new_task'

    # For 'retry':
    modified_description: Optional[str]
    modified_criteria: Optional[List[str]]

    # For 'spawn_new_task':
    new_description: Optional[str]
    new_component: Optional[str]
    new_phase: Optional[str]
    new_worker_profile: Optional[str]
    new_criteria: Optional[List[str]]
    new_dependencies: Optional[List[str]]
```

### 8.3 WebSocket Protocol (`src/api/websocket.py`)

#### ConnectionManager
```python
class ConnectionManager:
    async connect(websocket: WebSocket)
    disconnect(websocket: WebSocket)
    async subscribe(websocket: WebSocket, run_id: str, runs_index: Dict)
    async unsubscribe(websocket: WebSocket, run_id: str)
    async broadcast(message: dict)
    async broadcast_to_run(run_id: str, message: dict)
```

#### Message Types
```python
WSMessageType = Literal[
    'state_update',      # Run status/task updates
    'task_update',       # Specific task changes
    'log_message',       # Real-time logs
    'human_needed',      # HITL required
    'run_complete',      # Run finished
    'error',
    'heartbeat',
    'subscribe',
    'unsubscribe',
    'subscribed',
    'unsubscribed',
    'run_list_update',   # Dashboard refresh
    'interrupted',       # Run interrupted
    'task_interrupted',  # Task interrupted
    'status'             # Initialization messages
]
```

#### Message Format
```python
{
    "type": str,
    "run_id": str,           # Auto-injected
    "timestamp": str,        # Auto-injected (ISO format)
    "payload": Any
}
```

### 8.4 Dispatch Loop (`src/api/dispatch.py`)

**Function**: `continuous_dispatch_loop(run_id, state, run_config)`

**6-Phase Execution Loop**:

```
PHASE 1: Collect Completed Workers
├── Poll task_queue.collect_completed()
├── Merge task_memories FIRST
├── Merge updated tasks into state
├── Save checkpoint
└── Broadcast state_update

PHASE 2: Run Director
├── Call director_node(state, run_config)
├── Merge results via reducers
├── Save checkpoint
└── Broadcast state_update

PHASE 3: Dispatch Ready Tasks
├── Find tasks with status="ready"
├── Up to task_queue.available_slots
├── Mark as "active", set started_at
├── Create worktree if needed
├── Spawn worker_node as background task
└── Broadcast state_update

PHASE 4: Run Strategist for QA
├── Find tasks with status="awaiting_qa"
├── Call strategist_node(state, run_config)
├── Merge results
├── Save checkpoint
└── Broadcast state_update

PHASE 5: Check Completion
├── All terminal → EXIT "completed"
├── waiting_human + no work → EXIT "interrupted"
└── 10 iterations no progress → EXIT "deadlock"

PHASE 6: Wait for Completions
├── If has_work: await task_queue.wait_for_any(timeout=1.0)
└── Else: await asyncio.sleep(0.1)
```

---

## 9. Frontend Dashboard

### 9.1 Technology Stack

- **React 18.3.1** - UI framework
- **React Router DOM 7.0.1** - Routing
- **@tanstack/react-query 5.62.0** - Server state
- **zustand 5.0.1** - WebSocket state
- **reactflow 11.11.4** - Task graph visualization
- **dagre 0.8.5** - Graph layout
- **Tailwind CSS 3.4.15** - Styling
- **Vite 6.0.1** - Build tool

### 9.2 Application Structure

```
orchestrator-dashboard/
├── src/
│   ├── main.tsx              # Entry point
│   ├── App.tsx               # Routes + QueryClient
│   ├── api/
│   │   ├── client.ts         # HTTP API client
│   │   └── websocket.ts      # Zustand WebSocket store
│   ├── types/
│   │   └── run.ts            # Type definitions
│   ├── components/
│   │   ├── layout/
│   │   │   └── Layout.tsx    # App shell with navigation
│   │   ├── TaskGraph.tsx     # ReactFlow task DAG
│   │   ├── LogPanel.tsx      # Real-time logs
│   │   ├── InterruptModal.tsx # HITL resolution
│   │   ├── CancelRunButton.tsx
│   │   ├── RestartRunButton.tsx
│   │   ├── ShutdownButton.tsx
│   │   ├── TaskDetailsContent.tsx
│   │   └── run-details/
│   │       ├── TaskCard.tsx
│   │       ├── TaskInspector.tsx
│   │       ├── RunHeader.tsx
│   │       ├── ModelConfig.tsx
│   │       ├── InsightsPanel.tsx
│   │       ├── DesignLogPanel.tsx
│   │       └── DirectorLogsModal.tsx
│   └── pages/
│       ├── Dashboard.tsx     # Run list
│       ├── NewRun.tsx        # Create run form
│       ├── RunDetails.tsx    # Run monitoring
│       └── HumanQueue.tsx    # HITL queue
├── package.json
├── vite.config.ts
├── tailwind.config.js
└── index.html
```

### 9.3 Routes

| Path | Component | Purpose |
|------|-----------|---------|
| `/` | Dashboard | List all runs with stats |
| `/new` | NewRun | Create new run form |
| `/runs/:runId` | RunDetails | Run monitoring + task graph |
| `/queue` | HumanQueue | Tasks needing intervention |

### 9.4 Key Components

#### TaskGraph
- Interactive DAG visualization with ReactFlow
- Dagre layout algorithm (top-to-bottom)
- Hover highlighting of connected nodes/edges
- Link mode for manual dependency editing
- Status-based node coloring

#### RunDetails
- Dual view modes (list/graph)
- On-demand task memory loading (prevents OOM)
- Real-time WebSocket updates
- Interrupt modal for HITL
- Initialization progress messages

#### InterruptModal
- Three resolution options:
  1. **Retry**: Edit description/criteria, retry task
  2. **Create New Task**: Define new task to replace
  3. **Abandon**: Mark task as abandoned

### 9.5 WebSocket Store (Zustand)

```typescript
interface WebSocketStore {
    socket: WebSocket | null;
    connected: boolean;
    subscribedRuns: Set<string>;
    messages: WSMessage[];  // Last 100 for debugging

    connect(): void;
    disconnect(): void;
    subscribe(runId: string): void;
    unsubscribe(runId: string): void;
    addMessageHandler(type: WSMessageType, handler: (msg) => void): () => void;
}
```

---

## 10. Persistence Layer

### 10.1 Database Support (`src/run_persistence.py`)

| Database | Configuration | Features |
|----------|--------------|----------|
| SQLite | `checkpoint_mode = "sqlite"` | WAL mode, busy timeout 5s |
| PostgreSQL | `POSTGRES_URI` env var | Production-ready |
| MySQL | `MYSQL_URI` env var | Connection pooling (10 max) |

### 10.2 Schema

```sql
CREATE TABLE runs (
    run_id TEXT PRIMARY KEY,
    thread_id TEXT,
    objective TEXT,
    status TEXT,
    state_json TEXT,           -- Full state (LONGTEXT for MySQL)
    created_at TEXT,
    updated_at TEXT,
    workspace_path TEXT,
    task_counts_json TEXT
);
```

### 10.3 Key Functions

```python
async def init_runs_table()
async def save_run_state(run_id: str, state: Dict, status: str = "running")
async def load_run_state(run_id: str) -> Optional[Dict]
async def load_run_summary(run_id: str) -> Optional[Dict]
async def list_all_runs() -> List[Dict]
async def delete_run(run_id: str) -> bool
async def update_run_status(run_id: str, status: str)
```

### 10.4 Task Queue (`src/task_queue.py`)

**Purpose**: Background task execution for non-blocking dispatch

```python
class TaskCompletionQueue:
    def __init__(self, max_concurrent: int = 5):
        self._running: Dict[str, asyncio.Task] = {}
        self._completed: List[CompletedTask] = []
        self._max_concurrent = max_concurrent
        self._lock = asyncio.Lock()

    def spawn(task_id: str, coro) -> bool
    def collect_completed() -> List[CompletedTask]
    async def wait_for_any(timeout: float = 0.5)
    async def cancel_task(task_id: str) -> bool
    async def cancel_all()

    @property
    def active_count() -> int
    @property
    def available_slots() -> int
    @property
    def has_work() -> bool
```

---

## 11. Configuration

### 11.1 OrchestratorConfig (`src/config.py`)

```python
@dataclass
class OrchestratorConfig:
    # Model configurations (per agent role)
    director_model: ModelConfig
    worker_model: ModelConfig
    planner_model: ModelConfig
    researcher_model: ModelConfig
    strategist_model: ModelConfig
    coder_model: Optional[ModelConfig] = None
    tester_model: Optional[ModelConfig] = None
    writer_model: Optional[ModelConfig] = None
    merger_model: Optional[ModelConfig] = None

    # Execution limits
    max_concurrent_workers: int = 5
    max_iterations_per_task: int = 10
    max_total_iterations: int = 100
    worker_timeout: int = 300
    director_timeout: int = 60

    # Feature flags
    enable_guardian: bool = False
    enable_git_worktrees: bool = False
    enable_webhooks: bool = False
    enable_transitive_reduction: bool = False

    # Persistence
    checkpoint_dir: str = "./checkpoints"
    checkpoint_mode: str = "mysql"  # sqlite, postgres, mysql, memory

    # MySQL settings
    mysql_host: str = "localhost"
    mysql_port: int = 3306
    mysql_user: str = "root"
    mysql_password: str = ""
    mysql_database: str = "orchestrator"

    # Path management
    run_data_base_path: Optional[str] = "F:/coding/agent-stuff/run-data"

    # Methods
    def get_run_data_path(run_id: str) -> Path
    def get_worktree_base(run_id: str) -> Path
    def get_llm_logs_path(run_id: str) -> Path
    def get_run_logs_path(run_id: str) -> Path
```

### 11.2 ModelConfig

```python
@dataclass
class ModelConfig:
    provider: str          # anthropic, openai, google, glm, openrouter, local
    model_name: str        # e.g., "gpt-4o", "claude-3-5-sonnet-20241022"
    temperature: float = 0.7
    max_tokens: Optional[int] = None
```

### 11.3 LLM Client (`src/llm_client.py`)

**Supported Providers**:

| Provider | Key Environment Variable | Base URL |
|----------|-------------------------|----------|
| anthropic | `ANTHROPIC_API_KEY` | (default) |
| openai | `OPENAI_API_KEY` | (default) |
| google | `GOOGLE_API_KEY` | (default) |
| glm | `GLM_API_KEY` | https://api.z.ai/api/coding/paas/v4 |
| openrouter | `OPENROUTER_API_KEY` | https://openrouter.ai/api/v1 |
| local (Ollama) | `OLLAMA_BASE_URL` | http://localhost:11434 |

**Retry Configuration**: 5 retries with exponential backoff (1s, 2s, 4s, 8s, 16s)

---

## 12. Metrics & Observability

### 12.1 Prometheus Metrics (`src/metrics.py`)

#### GitMetrics
```python
merge_duration         # Histogram (seconds)
checkout_duration      # Histogram (seconds)
merge_total            # Counter (labels: result)
active_merges          # Gauge
conflicts_per_merge    # Histogram
```

#### TaskMetrics
```python
execution_duration     # Histogram (labels: worker_profile, phase)
completion_total       # Counter (labels: status, worker_profile)
retry_count            # Histogram
tasks_by_state         # Gauge (label: status)
active_workers         # Gauge (label: worker_profile)
phoenix_retry_total    # Counter (labels: phase, attempt)
hitl_escalation_total  # Counter (label: reason)
```

#### LLMMetrics
```python
requests_total         # Counter (labels: model, provider, result)
tokens_total           # Counter (labels: model, type)
cost_dollars_total     # Counter (labels: model, provider)
request_duration       # Histogram (labels: model, provider)
rate_limit_events      # Counter (labels: model, provider)
```

#### DispatchMetrics
```python
loop_iterations        # Counter (label: run_id)
loop_cycle_duration    # Histogram
tasks_dispatched_per_cycle    # Histogram
worker_completions_per_cycle  # Histogram
```

### 12.2 LLM Request Logging (`src/llm_logger.py`)

```python
def log_llm_request(task_id, messages, tools, config, workspace_path, logs_base_path) -> Dict
def log_llm_response(task_id, result, files_modified, status, workspace_path, logs_base_path) -> str
def validate_request_size(stats: Dict, max_chars: int = 100000)
```

**Log Format**: `{logs_base_path}/{task_id}/request_{timestamp}.json`

---

## 13. Implementation Guide

### 13.1 Project Setup

```bash
# Clone repository
git clone <repo-url>
cd agent-framework

# Create Python virtual environment
python -m venv .venv
source .venv/bin/activate  # or .venv\Scripts\activate on Windows

# Install dependencies
pip install -r requirements.txt

# Setup environment variables
cp .env.example .env
# Edit .env with API keys:
# - ANTHROPIC_API_KEY
# - OPENAI_API_KEY
# - TAVILY_API_KEY (for web search)
```

### 13.2 Database Setup

#### SQLite (Default)
```python
# No setup required - auto-created at orchestrator.db
```

#### MySQL
```bash
# Create database
mysql -u root -p -e "CREATE DATABASE orchestrator;"

# Configure in .env or config.py
MYSQL_URI="mysql://user:password@localhost:3306/orchestrator"
```

#### PostgreSQL
```bash
# Create database
createdb orchestrator

# Configure in .env
POSTGRES_URI="postgresql://user:password@localhost:5432/orchestrator"
```

### 13.3 Running the Server

```bash
# Start API server
python -m uvicorn src.server:app --host 0.0.0.0 --port 8085

# Or with auto-reload for development
python -m uvicorn src.server:app --reload --port 8085
```

### 13.4 Running the Dashboard

```bash
cd orchestrator-dashboard

# Install dependencies
npm install

# Start development server
npm run dev
# Dashboard available at http://localhost:2999
```

### 13.5 CLI Usage

```bash
# Run with default settings
python -m src.main --objective "Build a REST API with user authentication" --workspace ./my-project

# Run with specific model
python -m src.main --objective "Create a CLI tool" --provider openai --model gpt-4o

# Mock run for testing
python -m src.main --objective "Test objective" --mock-run
```

---

## 14. Technology Stack

### 14.1 Backend

| Component | Technology | Version |
|-----------|------------|---------|
| Language | Python | 3.9+ |
| Framework | FastAPI | Latest |
| State Machine | LangGraph | Latest |
| LLM Integration | LangChain | Latest |
| Async Runtime | asyncio | Standard |
| Database | SQLite/PostgreSQL/MySQL | Various |
| Task Queue | asyncio.Task | Standard |

### 14.2 Frontend

| Component | Technology | Version |
|-----------|------------|---------|
| Framework | React | 18.3.1 |
| Routing | React Router DOM | 7.0.1 |
| State | Zustand, React Query | 5.0.1, 5.62.0 |
| Graph Visualization | ReactFlow | 11.11.4 |
| Graph Layout | Dagre | 0.8.5 |
| Styling | Tailwind CSS | 3.4.15 |
| Build Tool | Vite | 6.0.1 |
| Icons | Lucide React | 0.462.0 |

### 14.3 External Services

| Service | Purpose | Required |
|---------|---------|----------|
| Anthropic API | LLM (Claude) | Optional |
| OpenAI API | LLM (GPT) | Optional |
| Google AI | LLM (Gemini) | Optional |
| Tavily | Web Search | Optional |
| Ollama | Local LLM | Optional |

---

## 15. File Structure

```
agent-framework/
├── src/
│   ├── main.py                    # CLI entry point
│   ├── server.py                  # FastAPI server
│   ├── langgraph_definition.py    # Graph definition
│   ├── config.py                  # Configuration
│   ├── state.py                   # State schema + reducers
│   ├── orchestrator_types.py      # Type definitions
│   ├── git_manager.py             # Worktree management
│   ├── llm_client.py              # Multi-provider LLM client
│   ├── llm_logger.py              # LLM request logging
│   ├── task_queue.py              # Background task queue
│   ├── run_persistence.py         # Database persistence
│   ├── metrics.py                 # Prometheus metrics
│   ├── async_utils.py             # Async utilities
│   ├── nodes/
│   │   ├── __init__.py
│   │   ├── director_main.py       # Director node
│   │   ├── worker.py              # Worker node
│   │   ├── strategist.py          # Strategist node
│   │   ├── guardian.py            # Guardian node (stub)
│   │   ├── routing.py             # Routing functions
│   │   ├── execution.py           # ReAct execution
│   │   ├── tools_binding.py       # Tool binding
│   │   ├── shared_tools.py        # Shared tools
│   │   ├── utils.py               # Node utilities
│   │   ├── director/
│   │   │   ├── __init__.py
│   │   │   ├── decomposition.py   # Objective breakdown
│   │   │   ├── integration.py     # Plan integration
│   │   │   ├── readiness.py       # Dependency checking
│   │   │   ├── hitl.py            # Human resolution
│   │   │   └── graph_utils.py     # Cycle detection
│   │   └── handlers/
│   │       ├── __init__.py
│   │       ├── code_handler.py    # Coder worker
│   │       ├── plan_handler.py    # Planner worker
│   │       ├── test_handler.py    # Tester worker
│   │       ├── qa_handler.py      # QA verification
│   │       ├── research_handler.py# Research worker
│   │       ├── write_handler.py   # Writer worker
│   │       └── merge_handler.py   # Merge conflict resolution
│   ├── tools/
│   │   ├── __init__.py
│   │   ├── base.py                # Tool definitions
│   │   ├── filesystem_async.py    # File operations
│   │   ├── git_async.py           # Git operations
│   │   ├── code_execution_async.py# Code execution
│   │   └── search_tools.py        # Web search
│   └── api/
│       ├── __init__.py
│       ├── dispatch.py            # Dispatch loop
│       ├── types.py               # Request/response types
│       ├── websocket.py           # WebSocket manager
│       ├── state.py               # Global state
│       └── routes/
│           ├── __init__.py
│           ├── runs.py            # Run endpoints
│           ├── tasks.py           # Task endpoints
│           ├── interrupts.py      # HITL endpoints
│           ├── ws.py              # WebSocket endpoint
│           └── metrics.py         # Metrics endpoint
├── orchestrator-dashboard/        # React frontend
│   ├── src/
│   │   ├── main.tsx
│   │   ├── App.tsx
│   │   ├── api/
│   │   ├── types/
│   │   ├── components/
│   │   └── pages/
│   ├── package.json
│   ├── vite.config.ts
│   └── tailwind.config.js
├── Spec/                          # Specifications
│   ├── agent_orchestrator_spec_v2.3.md
│   ├── dashboard_spec.py
│   ├── dashboard_frontend_spec.md
│   ├── langgraph_definition.py
│   ├── orchestrator_types.py
│   ├── prompt_templates.py
│   ├── tool_definitions.py
│   ├── node_contracts.py
│   ├── git_filesystem_spec.py
│   └── future/
│       ├── chunked-execution-with-guardian.md
│       ├── continuous-dispatch-optimization.md
│       ├── deep_task_cancellation.md
│       └── performance-instrumentation.md
├── docs/                          # Documentation
│   ├── observability-setup-guide.md
│   ├── llm-throttling-design.md
│   ├── metrics-instrumentation-example.md
│   └── concurrent-git-strategies.md
├── tests/                         # Test suite
│   ├── __init__.py
│   ├── test_task_memories.py
│   └── unit/
│       ├── __init__.py
│       ├── test_state_reducers.py
│       ├── test_task_serialization.py
│       ├── test_graph_utils.py
│       └── test_task_readiness.py
├── observability/                 # Prometheus/Grafana configs
│   ├── prometheus.yml
│   ├── README.md
│   └── grafana/
├── requirements.txt
├── docker-compose.observability.yml
├── DATABASE_CONFIG.md
├── REFACTORING_SUMMARY.md
├── README.md
└── PRD.md                         # This document
```

---

## Appendix A: Task State Transitions

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         TASK STATE MACHINE                               │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│   PLANNED ──────────┬─────────────────────────────────────────────────▶ READY
│      │              │ (dependencies satisfied)                           │
│      │              │                                                    │
│      ▼              │                                                    ▼
│   BLOCKED           │                                                 ACTIVE
│      │              │                                                    │
│      │              │                                                    │
│      └──────────────┘                              ┌─────────────────────┤
│                                                    │                     │
│                                     ┌──────────────┤                     │
│                                     │              │                     │
│                                     ▼              ▼                     ▼
│                              PENDING_FAILED  PENDING_AWAITING_QA  PENDING_COMPLETE
│                                     │              │                     │
│                                     ▼              ▼                     ▼
│                                  FAILED      AWAITING_QA            COMPLETE
│                                     │              │
│                                     │              ▼
│                                     │         FAILED_QA
│                                     │              │
│                                     ▼              │
│                              WAITING_HUMAN ◀──────┘
│                                     │
│                                     ▼
│                                ABANDONED
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘

Legend:
─────▶  Normal transition
- - -▶  Phoenix retry (back to PLANNED)
```

---

## Appendix B: Agent Communication Flow

```
┌──────────────────────────────────────────────────────────────────────────┐
│                      ORCHESTRATOR EXECUTION FLOW                          │
├──────────────────────────────────────────────────────────────────────────┤
│                                                                           │
│  1. User provides objective                                               │
│     │                                                                     │
│     ▼                                                                     │
│  2. DIRECTOR: Decompose objective into design_spec.md                     │
│     │         Create 1-5 planner tasks                                    │
│     │                                                                     │
│     ▼                                                                     │
│  3. WORKER (Planner): Execute planner tasks                               │
│     │                 Call create_subtasks() to define work               │
│     │                                                                     │
│     ▼                                                                     │
│  4. DIRECTOR: Integrate plans from all planners                           │
│     │         - PASS 1: Deduplication & scope validation                  │
│     │         - PASS 1.5: Feature-to-foundation linking                   │
│     │         - PASS 2: Dependency query resolution                       │
│     │         - PASS 3: Transitive reduction                              │
│     │                                                                     │
│     ▼                                                                     │
│  5. DIRECTOR: Evaluate readiness (PLANNED → READY)                        │
│     │                                                                     │
│     ▼                                                                     │
│  6. WORKER (Coder/Tester): Execute BUILD/TEST tasks                       │
│     │                      Write code, run tests                          │
│     │                                                                     │
│     ▼                                                                     │
│  7. STRATEGIST: QA verification                                           │
│     │           - PASS → Rebase + Merge to main                           │
│     │           - FAIL → Task returns to DIRECTOR (Phoenix retry)         │
│     │           - CONFLICT → Spawn merge task                             │
│     │                                                                     │
│     ▼                                                                     │
│  8. DIRECTOR: Confirm pending states                                      │
│     │         Evaluate new readiness                                      │
│     │         Handle Phoenix retries                                      │
│     │                                                                     │
│     ▼                                                                     │
│  9. Repeat 5-8 until all tasks COMPLETE or WAITING_HUMAN                  │
│     │                                                                     │
│     ▼                                                                     │
│ 10. If WAITING_HUMAN: Interrupt for human decision                        │
│     │                 - Retry with modifications                          │
│     │                 - Create new task                                   │
│     │                 - Abandon task                                      │
│     │                                                                     │
│     ▼                                                                     │
│ 11. Run completes when all tasks are terminal (COMPLETE/ABANDONED)        │
│                                                                           │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## Appendix C: Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `ANTHROPIC_API_KEY` | If using Anthropic | - | Anthropic API key |
| `OPENAI_API_KEY` | If using OpenAI | - | OpenAI API key |
| `GOOGLE_API_KEY` | If using Google | - | Google AI API key |
| `GLM_API_KEY` | If using GLM | - | Zhipu AI API key |
| `OPENROUTER_API_KEY` | If using OpenRouter | - | OpenRouter API key |
| `TAVILY_API_KEY` | For web search | - | Tavily search API key |
| `OLLAMA_BASE_URL` | If using Ollama | `http://localhost:11434` | Ollama server URL |
| `POSTGRES_URI` | If using PostgreSQL | - | PostgreSQL connection string |
| `MYSQL_URI` | If using MySQL | - | MySQL connection string |
| `FRONTEND_URL` | No | `*` | CORS allowed origins |
| `VITE_API_URL` | No | `http://localhost:8085` | API URL for dashboard |
| `VITE_WS_URL` | No | `ws://127.0.0.1:8085/ws` | WebSocket URL |

---

## Revision History

| Version | Date | Changes |
|---------|------|---------|
| 2.0 | January 2026 | Initial comprehensive PRD from improved-pre-tdd branch |

---

*This PRD was auto-generated from comprehensive codebase analysis. For the most current implementation details, refer to the source code and inline documentation.*
