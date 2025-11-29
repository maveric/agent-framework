# Agent Orchestrator Architecture Specification
**Version 2.3 — November 2025**

---

## 1. Core Philosophy

### 1.1 Single-Project Runs
Each run focuses on **one objective** (project/feature):
- "Build a Todo Board web app"
- "Write a research report on topic X"
- "Validate micro-SaaS idea #17"

Each run has a single **Blackboard** = shared state for all agents.

### 1.2 Hub-and-Spoke with Central Blackboard
No deep parent/child tree of agents passing messages. All agents (Director, Workers, Strategist, Guardian) read/write from a shared state object containing:
- Tasks and their statuses
- Project spec and decisions
- Artifacts (via virtual filesystem references)
- Memories and insights

### 1.3 Pipelines Over Micro-Tasks
Tasks are **meaningful chunks** roughly like developer tickets—not atomic operations like "run a single search."

Examples:
- "Plan DB schema"
- "Implement API for todos"  
- "Draft report section"

Each component runs through phases: **PLAN → BUILD → TEST**

### 1.4 Strong Orchestration, Light Inner Loops
- **Orchestration** (Director, state machine, scheduling) = where design effort goes
- **Inner loops** (ReAct, tool calling, code execution) = delegate to proven libraries (LangGraph, deepagents, OpenAI Agents SDK)

### 1.5 Push-Based Task Assignment
The Director **dispatches tasks to specific Workers**; Workers do not self-select from a queue. This eliminates race conditions where multiple workers might grab the same task.

---

## 2. Roles / Nodes

### 2.1 The Director
**Role:** Project Manager & Logistician

The Director manages the queue and ensures structural plan validity. It does **not** do the work itself.

**Responsibilities:**
1. **Initial Decomposition:** Convert objective + spec into a DAG of tasks per component/phase. Creates BUILD tasks plus TEST placeholders (generic criteria, refined by Strategist after BUILD passes)
2. **Readiness Evaluation:** Classify PLANNED tasks into READY or BLOCKED (based on dependencies)
3. **Scheduling & Dispatch:** Choose which READY tasks to run next, assign to specific worker profiles
4. **Failure Handling:** Handle FAILED_QA tasks (Phoenix retries, escalation to humans)
5. **Re-planning:** Update task graph if Strategist signals "stagnating" or "plan is wrong"
6. **Suggested Task Review:** Approve or reject Worker-proposed scope changes (task splits, new subtasks)
7. **Escalation Handling:** Process worker escalations (spec mismatch, needs research, scope too large)
8. **Resume Waiting Tasks:** Re-dispatch tasks that were waiting for subtasks to complete

**Hybrid Logic:**
| Cognition (LLM) | Logic (Python) |
|-----------------|----------------|
| Initial breakdown: "Build App" → [Task A, B, C] | Graph traversal: checking dependencies |
| Review: Approving suggested tasks | Queue management: moving tasks between states |
| Re-planning: Inventing new path if stuck | Dispatch: generating Send() objects |
| Escalation resolution: deciding how to handle | Subtask completion: checking waiting_for_tasks |

### 2.2 Deep Workers
**Role:** Specialized Executors

Workers handle one stage of a pipeline for a given component. They are **task-scoped**, not persistent agents.

**Worker Types:**
| Worker | Phase | Responsibilities |
|--------|-------|------------------|
| `planner_worker` | PLAN | Design docs, architecture decisions |
| `code_worker` | BUILD | Implementation + **unit tests** (tests own code) |
| `test_worker` | TEST | **Acceptance/integration tests** (validates against criteria) |
| `research_worker` | Any | Investigation, recommendations |
| `writer_worker` | DOCUMENT | Technical documentation (README, API docs, guides) |

**Testing Division:**
- **Coder** writes unit tests — "Does my code work as I intended?"
- **Tester** writes acceptance tests — "Does this meet the acceptance criteria?"

This mirrors how good human teams work: coders test their own logic; testers validate the contract without implementation bias.

**Commit Flow:**
- Workers commit to task branch when declaring "done"
- Strategist reviews artifacts on that branch
- Merge to main only after Strategist approves

**Behavior:**
1. Receive task assignment from Director (push model)
2. Check for checkpoint (resume from saved state if present)
3. Read relevant spec/design/insights from Blackboard
4. Use tools and inner loops (search, code exec, web APIs) to produce artifact
5. Write artifact to virtual filesystem
6. Commit to task branch
7. Return structured result:
   - `result_path` — where artifact lives
   - `suggested_tasks` (optional) — scope changes requiring Director approval
   - `share_insight` (optional) — freely posted knowledge for other tasks
   - `escalation` (optional) — signal issues that need Director attention

**Escalation Types:**
Workers can escalate issues back to the Director instead of completing normally:

| Type | When to Use | Director Response |
|------|-------------|-------------------|
| `NEEDS_RESEARCH` | Need more information | Spawn research subtask, save checkpoint |
| `NEEDS_REPLANNING` | Spec is wrong or inconsistent | Create planning tasks, may abandon current |
| `SPEC_MISMATCH` | Conflicts between specs | Resolve conflict or escalate to human |
| `NEEDS_CLARIFICATION` | Ambiguity in requirements | Clarify or escalate to human |
| `BLOCKED_EXTERNAL` | Waiting on external resource | Mark blocked, record what it needs |
| `SCOPE_TOO_LARGE` | Task should be split | Split into subtasks, maintain deps |

**Checkpoint-and-Continue Pattern:**
When a worker needs to pause (e.g., waiting for research subtask):
1. Worker saves partial work to `checkpoint`
2. Returns `status="waiting_subtask"` with tasks to spawn
3. Director creates subtasks and marks worker's task BLOCKED
4. When subtasks complete, Director re-dispatches worker with checkpoint restored

### 2.3 The Strategist (QA)
**Role:** Quality Gatekeeper

Evaluates whether artifacts satisfy acceptance criteria and align with spec/design decisions.

**Reads:**
- `result_path` from filesystem
- Task's `acceptance_criteria`
- Relevant spec/design info
- Test results (if Tester has run)

**Produces:**
- PASS/FAIL verdict with per-criterion reasoning
- `qa_feedback` stored on the task
- Test validity analysis (when test failures exist)
- Refined test criteria (for BUILD tasks that pass)

**Test Validity Analysis:**

When test failures exist, Strategist investigates whether tests are correct before failing the build:
- **Test correct, code wrong** → FAIL QA, code needs fixing
- **Test wrong, code correct** → PASS QA, flag `tests_needing_revision`
- **Both need work** → FAIL QA, note both issues

Tests are not blindly authoritative — Strategist uses judgment.

**Test Placeholder Refinement:**

BUILD tasks have corresponding `test-{component}` placeholder tasks created during initial decomposition. When a BUILD task passes QA, Strategist refines the placeholder with specific, testable criteria based on what was actually built. This happens in the same LLM call to save tokens.

**Controls:**
- PASS → task status becomes `COMPLETE`
- FAIL → task status becomes `FAILED_QA`, Director decides next action

### 2.4 The Guardian
**Role:** Drift Detector & Co-Pilot

Periodically reviews a task's recent messages (`task_memories[task_id]`) plus objective/spec.

**Assessment Dimensions:**

1. **Alignment Score (0-100%)**
   | Score | Meaning |
   |-------|---------|
   | 90-100% | Fully on track |
   | 70-89% | Minor tangent but productive |
   | 50-69% | Noticeably off-topic but recoverable |
   | 25-49% | Significantly off-course |
   | 0-24% | Completely lost or stuck |

2. **Trajectory**
   - `IMPROVING` — Was off-topic but coming back (e.g., 50% → 75%)
   - `STABLE` — Consistent alignment (good or bad)
   - `WORSENING` — Drifting further off-course

**Verdict Categories:**
| Category | When Assigned |
|----------|---------------|
| ON_TRACK | Alignment ≥70% OR (alignment ≥50% AND trajectory=IMPROVING) |
| DRIFTING | Alignment 25-69% AND trajectory not IMPROVING |
| BLOCKED | Stuck in circles, repeating same failed approaches |
| STALLED | No progress, ignoring nudges, or potential crash |

**Nudge Tone (scales with severity):**
| Alignment | Tone | Example |
|-----------|------|---------|
| 50-69% | Gentle | "Consider whether this is directly serving..." |
| 25-49% | Direct | "You've drifted. Stop X and return to Y." |
| 0-24% | Firm | "STOP. Immediately return to [objective]." |

**Stall Escalation Logic:**
- Mark STALLED only if: alignment <25% AND not improving, OR multiple nudges ignored, OR no activity
- Do NOT mark STALLED if worker is improving (even slowly) — give them time to recover

**Intervention:** Injects guidance via system messages into task's memory. Does NOT directly change task state—influences behavior indirectly.

**Metrics Tracked:**
- Time since last message in task_memories
- Token count consumed since last checkpoint
- Tool call count since last checkpoint
- Filesystem writes since last checkpoint

---

## 3. Blackboard & Memory Model

The Blackboard is a single state structure representing the entire run.

### 3.1 Schema

```
{
  "run_id": "uuid",
  "objective": "Build a Todo Board web app",
  
  // === PERSISTENT (survives Phoenix) ===
  
  "spec": {
    // Structured requirements
    "db": { "tables": [...], "constraints": [...] },
    "ui": { "layout": "3-column", "colors": {...} },
    "business_rules": [...]
  },
  
  "design_log": [
    // Append-only log of decisions
    {
      "id": "decision_1",
      "area": "api",
      "applies_to": ["task_api_plan"],
      "summary": "Use REST over GraphQL",
      "reason": "Simpler for MVP scope",
      "timestamp": "..."
    }
  ],
  
  "insights": [
    // Cross-task reusable knowledge (freely posted, no approval)
    {
      "id": "insight_1",
      "topic": ["api", "http"],
      "summary": "Prefer axios over fetch for auto JSON parsing",
      "source_task": "task_api_build"
    }
  ],
  
  // === EPHEMERAL (cleared by Phoenix) ===
  
  "task_memories": {
    // Per-task working memory: conversation history, partial drafts
    "task_api_build": [...messages...]
  },
  
  // === TASK MANAGEMENT ===
  
  "tasks": [...],  // See Task Model section
  
  // === FILESYSTEM ===
  
  "filesystem": {
    // Virtual FS index: paths → backend metadata
    // Actual implementation uses git worktrees
  },
  
  // === CONTROL ===
  
  "guardian": {
    "last_reviewed_task": "task_id",
    "last_nudge_time": "..."
  },
  "strategy_status": "PROGRESSING"  // or STAGNATING
}
```

### 3.2 Insights vs. Suggested Tasks

**Two distinct mechanisms:**

| | Insights | Suggested Tasks |
|-|----------|-----------------|
| **Purpose** | Knowledge sharing | Scope changes |
| **Example** | "This API has rate limits of 100/min" | "This task is too big, split into A and B" |
| **Approval** | None—freely posted | Requires Director review |
| **Availability** | Immediate | After approval |

---

## 4. Task Model & State Machine

### 4.1 Task Fields

```
{
  "id": "task_api_build",
  "component": "api",           // db, api, views, research, synthesis
  "phase": "build",             // plan, build, test
  "status": "READY",            // See states below
  "depends_on": ["task_api_plan", "task_db_build"],
  "priority": 10,
  "assigned_worker_profile": "code_worker",
  "retry_count": 0,
  "acceptance_criteria": [
    "Handles 404 errors gracefully",
    "Returns JSON responses",
    "Includes rate limiting"
  ],
  "result_path": null,          // Populated when artifact produced
  "qa_feedback": null,          // Populated on QA failure
  "blocked_reason": null,       // Populated when BLOCKED
  "created_at": "...",
  "updated_at": "...",
  "started_at": null            // Populated when ACTIVE (for timeout detection)
}
```

### 4.2 Task States

```
┌─────────┐
│ PLANNED │ ← Task definition exists, dependencies known
└────┬────┘
     │ Director evaluates readiness
     ▼
┌─────────┐    ┌─────────┐
│  READY  │◄───│ BLOCKED │ ← Prerequisites not met or external wait
└────┬────┘    └─────────┘
     │ Director dispatches
     ▼
┌─────────┐
│ ACTIVE  │ ← Worker executing
└────┬────┘
     │ Worker produces artifact
     ▼
┌─────────────┐
│ AWAITING_QA │ ← Strategist evaluating
└──────┬──────┘
       │
   ┌───┴───┐
   ▼       ▼
┌──────┐ ┌───────────┐
│COMPLETE│ │ FAILED_QA │ → Phoenix retry or escalate
└──────┘ └───────────┘

Extended states:
- WAITING_HUMAN: Needs human input (after max retries or ambiguity)
- ABANDONED: Task removed due to re-planning
```

### 4.3 State Transitions by Role

| Role | Transitions |
|------|-------------|
| **Director** | PLANNED → READY, PLANNED → BLOCKED, BLOCKED → READY, READY → ACTIVE, FAILED_QA → READY (Phoenix), FAILED_QA → WAITING_HUMAN, Any → ABANDONED |
| **Worker** | ACTIVE → AWAITING_QA |
| **Strategist** | AWAITING_QA → COMPLETE, AWAITING_QA → FAILED_QA |

### 4.4 Abandonment Semantics

**Two distinct operations:**

**Task Abandoned (surgical):**
- Single task removed from graph
- Reason: re-scoped, merged into another task, deemed unnecessary
- Dependents: re-evaluate; if they can proceed without this task's output, update `depends_on`; otherwise mark BLOCKED with `blocked_reason: "dependency_abandoned"`

**Branch Abandoned (scorched earth):**
- Task + all transitive dependents removed
- Reason: whole approach is wrong, pivot needed
- No re-evaluation—everything downstream is gone

```python
abandon_task(task_id)              # Surgical
abandon_branch(task_id)            # Cascade
```

---

## 5. Scheduling & Phoenix Protocol

### 5.1 Scheduling

**Director maintains:**
- **Ready Queue:** Tasks with `status = READY`, sorted by priority (desc), phase preference, created_at (FIFO tiebreak)
- **Blocked List:** Tasks with `status = BLOCKED` and their block reasons
- **Active Set:** Tasks currently `ACTIVE`, limited by global and per-worker-profile concurrency

**Scheduling Algorithm:**
1. Filter tasks: `status = READY` AND `assigned_worker_profile = target_profile`
2. Apply concurrency limits
3. Sort by priority desc, created_at asc
4. Pick top task, mark READY → ACTIVE, dispatch to worker

### 5.2 Phoenix Protocol

When Strategist returns FAIL:

1. **Strategist updates task:**
   - `status = FAILED_QA`
   - `qa_feedback = structured explanation`
   - `retry_count += 1`

2. **Director decides:**
   - If `retry_count > max_retries` → `WAITING_HUMAN` (or ABANDONED)
   - Else apply Phoenix:

3. **Phoenix Wipe:**
   - Reset `task_memories[task.id]` to minimal context:
     - One system message summarizing: task, failure, QA feedback
   - Keep `spec`, `design_log`, and `insights` intact
   - Set task back to `READY`

**Goal:** Fresh worker perspective with key lessons, avoiding repeated blind alleys.

---

## 6. Git Worktree Filesystem Model

### 6.1 Rationale

Using git worktrees solves multiple problems:
- **Isolation:** Each task operates in its own worktree
- **Versioning:** Every commit is an implicit checkpoint
- **Diffing:** Strategist can `git diff` to see changes
- **Merge semantics:** Built-in conflict detection
- **Rollback:** QA fails? `git reset`. No orphaned files.

### 6.2 Event-to-Git Mapping

| Event | Git Operation |
|-------|---------------|
| Task becomes ACTIVE | Create worktree from main (or parent task's branch) |
| Worker writes artifact | Commit to task's branch |
| Task → AWAITING_QA | Branch frozen for Strategist review |
| QA PASS | Merge branch to main, delete worktree |
| QA FAIL (Phoenix) | Reset branch to pre-attempt, or create fresh worktree |
| Task ABANDONED | Delete branch and worktree, no merge |

### 6.3 Conflict Handling

When parallel tasks touch the same files:
- Sequential merges by completion order
- Conflicts trigger re-work for the later task
- Director notified of conflict, can adjust dependencies

---

## 7. Example: Todo Board Project

### 7.1 Objective
Build a simple Todo Board where users can:
- Create, view, update, delete todos
- Each todo has: title, description, status (todo/in_progress/done), due date
- Overdue todos are visually highlighted

### 7.2 Spec (excerpt)
```
spec.db.tables.todos = {
  columns: [id, title, description, status, due_date, created_at],
  constraints: [status IN ('todo','in_progress','done')]
}

spec.ui = {
  layout: "3-column-kanban",
  colors: { overdue: "#ef4444", ... }
}

spec.business_rules = [
  "status defaults to 'todo'",
  "delete requires confirmation",
  "overdue = due_date < today AND status != 'done'"
]
```

### 7.3 Task Graph

```
db_plan ──────► db_build ──────► db_test
    │                │
    ▼                ▼
api_plan ─────► api_build
    │                │
    ▼                ▼
views_plan ───► views_build
```

### 7.4 Task Lifecycle Example (views_build)

1. Created as PLANNED with dependencies: `[api_build, views_plan]`
2. Dependencies incomplete → stays PLANNED
3. Director evaluates → BLOCKED (waiting on deps)
4. Deps complete → BLOCKED → READY
5. Director schedules → READY → ACTIVE
6. Worker generates code, saves to `/artifacts/frontend/todo_board.jsx`
7. Worker returns `result_path` → ACTIVE → AWAITING_QA
8. Strategist inspects vs criteria:
   - PASS → COMPLETE
   - FAIL → FAILED_QA, Phoenix retry

---

## 8. Generalizing Beyond Coding

The architecture is **domain-agnostic**. What changes by domain:
- Components & phases
- Worker profiles and tools
- Acceptance criteria and QA prompts

### 8.1 Research + Report

**Components:** research, synthesis, outline, draft, edit, citations

**Phases per component:**
- PLAN (define research questions)
- EXECUTE (gather sources, synthesize, draft)
- QA (check coverage, factuality, coherence)

**Workers:** research_worker, writer_worker, editor_worker

**Blackboard:** `spec.research` (scope, audience, depth), filesystem for notes/sources/report

### 8.2 Future: Micro-SaaS Factory (North Star)

A Meta-Director (CEO) sits one level above, managing multiple project runs:
- Project-level statuses: IDEA → RESEARCHING → VALIDATING → BUILDING → LAUNCHING → OPERATING
- Allocates resources across projects
- Kills stale projects, promotes promising ones

**Key insight:** Same pattern reused at project granularity. Not in scope for current implementation.

---

## 9. Implementation Direction

### 9.1 Stack

| Layer | Technology | Purpose |
|-------|------------|---------|
| Orchestration | LangGraph | Nodes, state management, Send/routing |
| Workers | deepagents or OpenAI Agents SDK | Inner loops, tool calling, REPL |
| Filesystem | Git worktrees | Isolation, versioning, rollback |
| Tools | Code-first directory of skills | Following Anthropic's MCP context management |
| Persistence | LangGraph checkpointers | SQLite/Postgres for state recovery |
| Observability | LangSmith | Tracing, debugging, metrics, replay |

### 9.2 Tool Layer (Code-First)

Rather than dumping hundreds of tool schemas into context:
- Organize tools as code libraries by domain (research, code, marketing, ops)
- Workers can call pre-exposed tools OR write code that imports these libraries
- MCP servers wrapped as libraries—LLM interacts via code, not raw schemas
- Avoids context bloat per Anthropic's recommendations

---

## 10. Configuration

### 10.1 Multi-Provider Model Support

The orchestrator supports using different LLM providers for different roles. This allows:
- Cost optimization (use cheaper models for simpler tasks)
- Capability matching (use specialized models for specific tasks)
- Vendor diversification (don't rely on single provider)

**Supported Providers:**
- `anthropic` — Claude models
- `openai` — GPT models
- `google` — Gemini models
- `glm` — GLM models (Zhipu AI)
- `ollama` — Local models
- `azure` — Azure OpenAI
- `bedrock` — AWS Bedrock

**Configurable Roles:**
| Role | Default Model | Notes |
|------|---------------|-------|
| `director` | Claude Sonnet | Planning and orchestration |
| `strategist` | Claude Sonnet | QA evaluation |
| `guardian` | Claude Haiku | Lightweight drift detection |
| `planner_worker` | Claude Sonnet | Design and planning |
| `code_worker` | Claude Sonnet | Code implementation |
| `test_worker` | Claude Sonnet | Test generation |
| `research_worker` | Claude Sonnet | Information gathering |
| `writer_worker` | Claude Sonnet | Prose drafting |

**Example Configuration:**
```python
config = OrchestratorConfig()
config.set_provider_for_role("code_worker", "glm", "glm-4-plus")
config.set_provider_for_role("guardian", "openai", "gpt-4o-mini")
config.set_provider_for_role("research_worker", "openai", "gpt-4o")
```

**Rate Limit Fallback:**
```python
# Each model can specify a fallback for 429 errors
from orchestrator_types import ModelConfig

config.models["director"] = ModelConfig(
    provider="anthropic", 
    model="claude-sonnet-4-20250514",
    fallback=ModelConfig(provider="openai", model="gpt-4o")
)
# If Anthropic rate limits → automatically switch to OpenAI
```

### 10.2 Key Configuration Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `max_task_retries` | 3 | Retries before escalating to human |
| `max_concurrent_workers` | 3 | Parallel worker limit |
| `guardian_iteration_interval` | 15 | Tool calls between Guardian checks |
| `guardian_time_interval` | 60s | Max seconds between Guardian checks |
| `stagnation_threshold` | 3 | Failures before STAGNATING status |
| `task_timeout_seconds` | 600 | Per-task execution limit |
| `worktree_base_path` | `./worktrees` | Git worktree location |

---

## 11. Open Items & Decisions

### 11.1 Resolved

| Issue | Resolution |
|-------|------------|
| Guardian race conditions | Accepted risk—QA is the backstop |
| Timeout detection | Guardian's responsibility (STALLED category) |
| Task assignment model | Push-based (Director assigns, Workers don't self-select) |
| Insights vs. suggested tasks | Insights = free post; Suggestions = require approval |
| Meta-Director scope | North star only, not in current spec |
| Tool layer approach | Follow Anthropic MCP context management |

### 11.2 Deferred (Post-MVP)

- Cost/budget tracking per task and run
- Richer QA outcomes (PASS_WITH_NOTES, PARTIAL)
- Adaptive Guardian scheduling based on task risk
- Checkpoint/snapshot for catastrophic recovery

---

## 12. Next Steps

1. **Implement minimal vertical slice:**
   - `db` component: PLAN + IMPLEMENT + TEST for Todo Board

2. **Wire core nodes in LangGraph:**
   - Director, one Worker profile, Strategist
   - Single `BlackboardState` object

3. **Validate with slice:**
   - Task state transitions
   - Phoenix logic
   - Guardian nudges
   - Git worktree integration
   - Ergonomics of LangGraph + deep workers

---

## 13. Implementation Documents

Detailed implementation specifications:

| Document | Description |
|----------|-------------|
| [orchestrator_types.py](orchestrator_types.py) | All Python dataclasses, enums, and serialization helpers |
| [node_contracts.py](node_contracts.py) | Function signatures, reducers, state update patterns |
| [langgraph_definition.py](langgraph_definition.py) | Graph topology, checkpointing, run management |
| [git_filesystem_spec.py](git_filesystem_spec.py) | Git worktree management, branch conventions, merge handling |
| [agent_orchestrator_gaps_checklist.md](agent_orchestrator_gaps_checklist.md) | Implementation progress tracker |

---

*Document maintained collaboratively. Last updated: November 2025.*
