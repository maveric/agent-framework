# Agent Orchestrator Spec — Implementation Gaps Checklist

**Purpose:** Track what needs to be defined before this spec is ready for Claude Code implementation.

**Status Key:**
- ⬜ Not started
- 🟡 In progress
- ✅ Complete

---

## Document Index

| Document | Description | Status |
|----------|-------------|--------|
| [Main Spec (v2.3)](agent_orchestrator_spec_v2.3.md) | Architecture overview, roles, state machine | ✅ Complete |
| [Type Definitions](orchestrator_types.py) | Python dataclasses, enums, serialization | ✅ Complete |
| [Node Contracts](node_contracts.py) | Function signatures, reducers, routing | ✅ Complete |
| [LangGraph Definition](langgraph_definition.py) | Graph topology, checkpointing, run management | ✅ Complete |
| [Git/Filesystem](git_filesystem_spec.py) | Worktree lifecycle, branch conventions, merge handling | ✅ Complete |
| [Prompt Templates](prompt_templates.py) | LLM prompts with formatters | ✅ Complete (14 prompts) |
| [Tool Definitions](tool_definitions.py) | Progressive disclosure tool registry | ✅ Complete |
| LangSmith (external) | Observability, tracing, debugging | ✅ Integration planned |
| Error Handling (inline) | RetryConfig, circuit breaker, escalation | ✅ In checklist + types |

---

## 1. Type Definitions

**Document:** [orchestrator_types.py](orchestrator_types.py)

Core data structures that all components depend on.

| Item | Status | Notes |
|------|--------|-------|
| `Task` dataclass | ✅ | All fields including escalation, checkpoint, waiting_for_tasks |
| `TaskStatus` enum | ✅ | 9 states defined |
| `BlackboardState` | ✅ | Both TypedDict and dataclass with serialization |
| `Spec` structure | ✅ | Freeform Dict[str, Any] — domain-specific |
| `DesignDecision` | ✅ | id, area, applies_to, summary, reason, timestamp |
| `Insight` | ✅ | id, topic, summary, source_task, created_at |
| `WorkerResult` | ✅ | status (incl. waiting_subtask), escalation, checkpoint |
| `SuggestedTask` | ✅ | Full schema for worker-proposed tasks |
| `QAVerdict` | ✅ | Structured with per-criterion CriterionResult, test_analysis, tests_needing_revision, refined_test_criteria |
| `GuardianNudge` | ✅ | task_id, verdict, message, detected_issue, alignment_score, trajectory, tone |
| `BlockedReason` | ✅ | type (enum), description, waiting_on, since |
| `Escalation` | ✅ | type, reason, affected_tasks, spawn_tasks, blocking |
| `WorkerCheckpoint` | ✅ | partial_work, files_in_progress, resume_instructions |
| `ModelConfig` | ✅ | Multi-provider model configuration |

**Additional types defined:**
- `TaskPhase` enum (PLAN, BUILD, TEST)
- `WorkerProfile` enum (5 worker types)
- `GuardianVerdict` enum (ON_TRACK, DRIFTING, BLOCKED, STALLED, UNSAFE)
- `GuardianTrajectory` enum (IMPROVING, STABLE, WORSENING)
- `NudgeTone` enum (GENTLE, DIRECT, FIRM)
- `StrategyStatus` enum (PROGRESSING, STAGNATING, BLOCKED, PAUSED_INFRA_ERROR, PAUSED_HUMAN_REQUESTED)
- `BlockedType` enum (6 types including WAITING_SUBTASK, NEEDS_REPLANNING)
- `EscalationType` enum (6 escalation types)
- `GuardianMetrics` dataclass (for stall detection)
- `GuardianNudge` dataclass (with alignment_score, trajectory, tone)
- `GuardianState` dataclass
- `AAR` dataclass (After Action Report)
- `CriterionResult` dataclass (for structured QA)
- `TestFailureAnalysis` dataclass (Strategist's analysis of test validity)
- `RetryConfig` dataclass (tool retries, circuit breaker)
- `WebhookConfig` dataclass (stubbed for future)
- `DEFAULT_MODEL_CONFIGS` dict (default models per role)
- Full serialization helpers for LangGraph compatibility

---

## 2. Node Contracts (Function Signatures)

**Document:** [node_contracts.py](node_contracts.py)

Input/output specifications for each LangGraph node.

| Item | Status | Notes |
|------|--------|-------|
| `director_node()` signature | ✅ | Decomposition, readiness, dispatch, Phoenix, escalation handling |
| `worker_node()` signature | ✅ | Unified node with escalation/checkpoint support |
| `strategist_node()` signature | ✅ | QA evaluation, test validity analysis, test placeholder refinement, stagnation detection |
| `guardian_node()` signature | ✅ | Alignment score (0-100%), trajectory tracking, tone-scaled nudges |
| State update pattern | ✅ | Delta returns with reducers for lists/dicts |
| Inter-node communication | ✅ | Send() for dispatch, routing functions defined |
| Escalation handling | ✅ | `director_handle_escalation()`, `EscalationResponse` |
| Checkpoint/resume | ✅ | `restore_worker_checkpoint()`, `package_checkpoint_update()` |

**Additional items defined:**
- `OrchestratorState` TypedDict with annotated reducers
- Reducer functions for tasks, insights, design_log, task_memories
- Update dataclasses: `DirectorUpdate`, `WorkerUpdate`, `StrategistUpdate`, `GuardianUpdate`
- `WorkerContext` with checkpoint/resume fields
- Type-specific handler signatures (planner, coder, tester, researcher, writer)
- `WorkerIterationState` and `should_run_guardian()` for Guardian scheduling
- Routing functions for all node transitions
- `OrchestratorConfig` dataclass with multi-provider `ModelConfig` support
- `apply_phoenix()` implementation
- `package_escalation_update()` and `package_checkpoint_update()`
- `director_check_waiting_subtasks()` for resuming paused tasks

---

## 3. LangGraph Integration

**Document:** [langgraph_definition.py](langgraph_definition.py)

Specifics of how this maps to LangGraph primitives.

| Item | Status | Notes |
|------|--------|-------|
| Graph topology diagram | ✅ | ASCII diagram in docstring showing full flow |
| Conditional routing functions | ✅ | `route_after_director`, `route_after_worker`, etc. |
| State schema with reducers | ✅ | `OrchestratorStateWithReducers` TypedDict |
| Checkpointing strategy | ✅ | Memory/SQLite/Postgres options with `create_checkpointer()` |
| Interrupt mechanism | ✅ | Guardian checkpoints + human-in-the-loop support |
| Subgraph for Workers | ✅ | Single node with type-specific handlers |

**Additional items defined:**
- `build_orchestrator_graph()` — constructs the StateGraph
- `create_orchestrator()` — compiles graph with checkpointer
- `start_run()` / `resume_run()` / `stream_run()` — execution entry points
- Human-in-the-loop: `get_waiting_tasks()`, `provide_human_input()`
- Debugging: `get_run_history()`, `rollback_to_checkpoint()`
- Full usage example with Todo Board spec

---

## 4. Git/Filesystem Abstraction

**Document:** [git_filesystem_spec.py](git_filesystem_spec.py)

How file operations actually work.

| Item | Status | Notes |
|------|--------|-------|
| Directory structure | ✅ | `./project/` (repo) + `./worktrees/` (task worktrees) |
| Branch naming convention | ✅ | `task/{id}`, `task/{id}/retry-{n}` for Phoenix |
| Worktree lifecycle | ✅ | `WorktreeManager` with create/commit/merge/cleanup |
| Commit triggers | ✅ | On task completion via `commit_task_work()` |
| Commit message format | ✅ | `[{task_id}] {phase}: {summary}` template |
| Filesystem abstraction API | ✅ | `FilesystemIndex` for tracking, worktree paths for access |
| Worker file access | ✅ | Workers work directly in worktree_path |
| Merge conflict policy | ✅ | First-to-merge wins, second retries from updated main |

**Additional items defined:**
- `GitConfig` dataclass with all paths and settings
- `WorktreeInfo` and `WorktreeStatus` for tracking
- `WorktreeManager` class with full lifecycle operations
- `MergeResult` for conflict detection
- Phoenix retry support with failed branch reference (`get_phoenix_context()`)
- `ConflictResolutionStrategy` for handling merge conflicts
- `initialize_git_repo()` for run bootstrap
- Cleanup with user confirmation requirement

---

## 5. Guardian Scheduling & Injection

**Document:** Covered in [node_contracts.py](node_contracts.py) and [prompt_templates.py](prompt_templates.py)

How the Guardian actually operates.

| Item | Status | Notes |
|------|--------|-------|
| Trigger mechanism | ✅ | Hybrid: iteration-based + time-based fallback |
| Scheduling interval/threshold | ✅ | 15 iterations OR 60 seconds (configurable) |
| Async vs. sync execution | ✅ | Sync: runs at checkpoints in worker loop |
| Injection mechanism | ✅ | `guardian_create_nudge()` → SystemMessage with tone |
| Worker awareness | ✅ | Worker loop checks `should_run_guardian()` |
| Verdict logic | ✅ | Alignment (0-100%) + trajectory → ON_TRACK/DRIFTING/BLOCKED/STALLED |
| Tone scaling | ✅ | GENTLE (50-69%), DIRECT (25-49%), FIRM (0-24%) |
| Stall conditions | ✅ | <25% AND not improving, OR ignoring nudges, OR no activity |

---

## 6. Prompt Templates

**Document:** [prompt_templates.py](prompt_templates.py)

The actual prompts for each LLM invocation.

| Item | Status | Notes |
|------|--------|-------|
| Director: Initial decomposition | ✅ | Objective + markdown spec → task DAG with test placeholders |
| Director: Readiness evaluation | — | Pure Python logic, no LLM needed |
| Director: Suggested task review | ✅ | Accept/reject/merge/defer worker proposals |
| Director: Re-planning | ✅ | Stagnation recovery with analysis |
| Director: Task assignment | ✅ | Context briefing for workers |
| Director: Handle escalation | ✅ | Resolve worker escalations |
| Worker: Planner | ✅ | Design docs + decisions; opinionated; file r/w + web search |
| Worker: Coder | ✅ | Implementation + unit tests; commits to task branch |
| Worker: Tester | ✅ | Acceptance/integration tests; validates against criteria; reports per-criterion results |
| Worker: Researcher | ✅ | Research doc + insights + recommendation; web search + light code execution |
| Worker: Writer | ✅ | Technical docs (README, API, guides); file r/w + web search |
| Strategist: QA evaluation | ✅ | Criteria assessment + test validity analysis + test placeholder refinement |
| Guardian: Drift detection | ✅ | Alignment score (0-100%) + trajectory; tone scales with severity; considers improvement |
| Phoenix: Context summary | ✅ | Summarizes failure, provides suggested focus, references failed branch |

---

## 7. Tool Definitions

**Document:** [tool_definitions.py](tool_definitions.py)

What tools workers can use. Uses progressive disclosure pattern from Anthropic's MCP blog post.

| Item | Status | Notes |
|------|--------|-------|
| Tool schema format | ✅ | Custom ToolDefinition with to_full_schema() for OpenAI-style output |
| Tool registry design | ✅ | ToolRegistry with progressive disclosure via search_tools |
| Filesystem tools | ✅ | read_file, write_file, append_file, list_directory, file_exists, delete_file |
| Git tools | ✅ | commit, diff, status, add, log, merge |
| Web tools | ✅ | search, fetch, fetch_structured |
| Code execution tools | ✅ | run_python, run_shell, run_tests |
| Sandbox model | ✅ | Noted in tool docs; implementation deferred to runtime |
| Progressive disclosure | ✅ | TOOLS_INDEX.md, category TOOL.md files, search_tools meta-tool |
| Detail levels | ✅ | name_only, name_desc, full_schema |
| Worker defaults | ✅ | get_tools_for_worker() maps worker profiles to default categories |

---

## 8. Bootstrap & Initialization

**Document:** [langgraph_definition.py](langgraph_definition.py), [git_filesystem_spec.py](git_filesystem_spec.py), and [prompt_templates.py](prompt_templates.py)

How a run starts.

| Item | Status | Notes |
|------|--------|-------|
| `start_run()` signature | ✅ | `start_run(orchestrator, objective, spec, run_id)` |
| Minimum viable input | ✅ | Objective + markdown spec (user writes prose, not JSON) |
| Spec derivation | ✅ | Director extracts structure in initial decomposition prompt |
| Initial task generation | ✅ | `DIRECTOR_INITIAL_DECOMPOSITION` prompt in prompt_templates.py |
| Blackboard initialization | ✅ | Defined in `start_run()` with all defaults |
| Git repo initialization | ✅ | `initialize_git_repo()` in git_filesystem_spec.py |

---

## 9. Concurrency Model

**Document:** Covered in [node_contracts.py](node_contracts.py) and [langgraph_definition.py](langgraph_definition.py)

How parallel execution works.

| Item | Status | Notes |
|------|--------|-------|
| Execution model | ✅ | LangGraph's model: Send() for parallel dispatch |
| Max concurrent workers | ✅ | `ConcurrencyConfig.max_global_active` (default 5) |
| Per-profile concurrency | ✅ | `ConcurrencyConfig.max_per_profile` dict |
| Blackboard synchronization | ✅ | Reducer pattern handles merging |
| LangGraph concurrency | ✅ | Using Send() for parallel worker dispatch |

---

## 10. Error Handling

**Document:** Inline below (will be added to node_contracts.py)

Recovery from non-QA failures.

| Item | Status | Notes |
|------|--------|-------|
| LLM API errors | ✅ | Server errors → pause run; context overflow → split or summarize |
| Git operation failures | ✅ | Infra errors → pause run, wait for human |
| Tool execution exceptions | ✅ | Retry N times (default 3), then fail task |
| Worker crash mid-task | ✅ | Guardian detects (no context updates), Phoenix restart |
| Network failures | ✅ | Treated as LLM/tool errors per above |
| Retry policies | ✅ | Exponential backoff with limit; circuit breaker |
| Error escalation path | ✅ | Task → WAITING_HUMAN; Run-level → pause for human |

### Error Categories

**1. LLM API Errors**

| Error Type | Response |
|------------|----------|
| Server error (500, 502, 503) | Pause entire run, wait for human |
| Connection error / timeout | Pause entire run, wait for human |
| Rate limit (429) | Use fallback model if configured; else pause run |
| Context overflow at task start | Escalation: Director splits task |
| Context overflow mid-execution | Worker self-summarizes and continues (deepagents feature) |
| Invalid response / parse error | Retry with backoff, then fail task |

**Rate Limit Fallback Chain:**
```python
# Each ModelConfig can specify a fallback
primary = ModelConfig(provider="anthropic", model="claude-sonnet-4-20250514",
    fallback=ModelConfig(provider="openai", model="gpt-4o")
)

# On 429 from primary → automatically try fallback
# If fallback also 429 (or no fallback configured) → pause run
```

**2. Git Operation Failures**

| Error Type | Response |
|------------|----------|
| Merge conflict | Handled: retry task from updated main |
| Disk full / permissions | Pause entire run, wait for human |
| Corrupted repo | Pause entire run, wait for human |
| Worktree creation fails | Pause entire run, wait for human |

No remote integration — push/pull to GitHub is manual.

**3. Tool Execution Errors**

| Error Type | Response |
|------------|----------|
| Tool raises exception | Retry up to `max_tool_retries` (default: 3) |
| Tool timeout | Retry up to `max_tool_retries` |
| All retries exhausted | Task fails → Phoenix retry |

Tools are trusted to raise exceptions on bad state. No output schema validation.

**4. Worker Crash / Orphaned Tasks**

Detection: Guardian sees no updates to `task_memories` for extended period (STALLED verdict).

Recovery: Phoenix-style clean restart. Crashed worker's partial work is abandoned; new worker starts fresh with context from failed attempt for reference.

### Retry Configuration

```python
@dataclass
class RetryConfig:
    """Retry settings for infrastructure errors."""
    
    # Tool-level retries (within a task)
    max_tool_retries: int = 3
    tool_retry_backoff_base: float = 1.0  # seconds
    tool_retry_backoff_max: float = 30.0  # cap
    
    # Task-level retries (Phoenix)
    max_task_retries: int = 3  # Already in OrchestratorConfig
    
    # Circuit breaker
    circuit_breaker_threshold: int = 3  # consecutive infra failures
    circuit_breaker_pause: bool = True  # pause run when tripped
```

**Exponential Backoff Formula:**
```python
delay = min(base * (2 ** attempt) + random_jitter, max_delay)
```

### Circuit Breaker

If `circuit_breaker_threshold` consecutive tasks fail due to infrastructure errors (not QA failures):
1. Set `run_status` to `PAUSED_INFRA_ERROR`
2. Log the pattern (which errors, which tasks)
3. Wait for human intervention
4. Human can: fix issue and resume, or abort run

### Run-Level Status Extension

Add to `StrategyStatus` enum:
```python
class StrategyStatus(str, Enum):
    PROGRESSING = "progressing"
    STAGNATING = "stagnating"
    BLOCKED = "blocked"
    PAUSED_INFRA_ERROR = "paused_infra_error"  # Circuit breaker tripped
    PAUSED_HUMAN_REQUESTED = "paused_human_requested"  # Manual pause
```

### Webhooks (Stubbed)

```python
@dataclass
class WebhookConfig:
    """Future: webhook notifications for run events."""
    enabled: bool = False
    url: Optional[str] = None
    events: List[str] = field(default_factory=list)  # e.g., ["run_paused", "run_complete"]
    
    # Not implemented in v1 — stub for future use
```

---

## 11. Configuration Schema

**Document:** [node_contracts.py](node_contracts.py) — `OrchestratorConfig` and [orchestrator_types.py](orchestrator_types.py) — `ModelConfig`

All tunable parameters.

| Item | Status | Notes |
|------|--------|-------|
| `max_retries` | ✅ | `max_task_retries` in OrchestratorConfig (default: 3) |
| `guardian_interval` | ✅ | `guardian_iteration_interval` (15) + `guardian_time_interval` (60s) |
| `task_timeout_seconds` | ✅ | Added to OrchestratorConfig (default: 600) |
| `concurrency_limits` | ✅ | `max_concurrent_workers` (default: 3) |
| `model` settings | ✅ | Multi-provider via `ModelConfig` with `get_model()`, `set_provider_for_role()` |
| `temperature` settings | ✅ | Per-role via `ModelConfig.temperature` (default: 0.7) |
| `max_tokens` settings | ✅ | Per-role via `ModelConfig.max_tokens` (default: 4096) |
| Git/filesystem paths | ✅ | `worktree_base_path`, `main_branch` |
| Full config dataclass | ✅ | `OrchestratorConfig` with `ModelConfig` dict |
| Multi-provider support | ✅ | anthropic, openai, google, glm, ollama, azure, bedrock |

---

## 12. Persistence & Recovery

**Document:** Covered in [langgraph_definition.py](langgraph_definition.py)

How state survives crashes.

| Item | Status | Notes |
|------|--------|-------|
| Persistence backend | ✅ | Memory/SQLite/Postgres via `create_checkpointer()` |
| Checkpoint frequency | ✅ | After every node execution (LangGraph automatic) |
| State serialization format | ✅ | LangGraph handles via checkpointer |
| Recovery procedure | ✅ | `resume_run()` function defined |
| Partial failure recovery | ✅ | Checkpoint includes graph position |
| Run history retention | ✅ | Deployment decision — checkpointer supports TTL configuration |

---

## 13. Observability & Logging

**Document:** LangSmith integration (external service)

Debugging and monitoring via LangSmith.

| Item | Status | Notes |
|------|--------|-------|
| Log format | ✅ | LangSmith structured traces |
| Log destination | ✅ | LangSmith cloud (or self-hosted) |
| Event taxonomy | ✅ | LangGraph nodes auto-traced; custom spans for git ops |
| Event payload schemas | ✅ | LangSmith captures inputs/outputs automatically |
| Trace correlation | ✅ | Automatic run trees; tag with `task_id`, `run_id` |
| Metrics to track | ✅ | Token usage, latency per-node automatic; business metrics in state |
| Debug replay capability | ✅ | LangSmith trace viewer + playground |

**LangSmith handles automatically:**
- All LLM calls with inputs/outputs/tokens/latency
- LangGraph node execution traces
- Run trees showing full execution flow
- Trace viewer for debugging
- Playground for prompt iteration

**Custom additions needed:**
- Tag runs with metadata: `task_id`, `run_id`, `worker_profile`
- Wrap git operations in custom spans: `with langsmith.trace("git_commit")`
- Business metrics (QA pass rate, retry rate) tracked in BlackboardState
- Cost aggregation: map tokens → $ by model if needed

---

## Priority Order (Suggested)

Dependencies flow downward—complete higher items first.

1. ~~**Type Definitions**~~ ✅ — Everything depends on these
2. ~~**Node Contracts**~~ ✅ — Defines component boundaries  
3. ~~**LangGraph Integration**~~ ✅ — Architecture skeleton
4. ~~**Git/Filesystem Abstraction**~~ ✅ — Workers need this to operate
5. ~~**Prompt Templates**~~ ✅ — Director + Workers + Strategist + Guardian + Phoenix complete
6. ~~**Tool Definitions**~~ ✅ — Progressive disclosure pattern with search_tools
7. ~~**Bootstrap & Initialization**~~ ✅ — Complete (spec derivation handled in Director initial decomposition)
8. ~~**Configuration Schema**~~ ✅ — Complete with multi-provider support
9. ~~**Guardian Scheduling**~~ ✅ — Complete with verdict logic and tone scaling
10. ~~**Concurrency Model**~~ ✅ — Complete
11. ~~**Error Handling**~~ ✅ — RetryConfig, circuit breaker, escalation paths
12. ~~**Persistence & Recovery**~~ ✅ — Complete via LangGraph checkpointing
13. ~~**Observability & Logging**~~ ✅ — LangSmith integration

---

## Session Log

Track what we work on and when.

| Date | Items Addressed | Notes |
|------|-----------------|-------|
| 2025-11-28 | Type Definitions (Section 1) | All 11 items complete. Created orchestrator_types.py |
| 2025-11-28 | Node Contracts (Section 2) | All 6 items complete. Created node_contracts.py |
| 2025-11-28 | LangGraph Integration (Section 3) | All 6 items complete. Created langgraph_definition.py |
| 2025-11-28 | Escalation System | Added EscalationType, Escalation, WorkerCheckpoint types. Updated Director/Worker handling |
| 2025-11-28 | Multi-Provider Models | Added ModelConfig, updated OrchestratorConfig with provider support |
| 2025-11-28 | Configuration Schema (Section 11) | All items complete with ModelConfig |
| 2025-11-28 | Git/Filesystem (Section 4) | All 8 items complete. Created git_filesystem_spec.py |
| 2025-11-28 | Observability (Section 13) | LangSmith integration. Updated spec and langgraph_definition.py |
| 2025-11-28 | Error Handling (Section 10) | All 7 items complete. Added RetryConfig, WebhookConfig, circuit breaker |
| 2025-11-28 | Prompt Templates (Section 6) | All 14 prompts complete. Created prompt_templates.py |
| 2025-11-28 | Documentation Sync | Updated spec/types/contracts for: test validity analysis, test placeholder refinement, coder unit tests vs tester acceptance tests, commit flow |
| 2025-11-28 | Guardian Types | Added GuardianTrajectory, NudgeTone enums. Updated GuardianNudge with alignment_score, trajectory, tone |
| 2025-11-28 | Phoenix Prompt | Context summary for retry: failure details, suggested focus, failed branch reference |
| 2025-11-29 | Tool Definitions (Section 7) | Progressive disclosure pattern from Anthropic MCP blog. Created tool_definitions.py |
| 2025-11-29 | Final Audit | Standardized TaskPhase (IMPLEMENT→BUILD), aligned CriterionResult fields, updated apply_phoenix to use format_phoenix_context, added __all__ exports |

---

## 🎉 SPECIFICATION COMPLETE

All 13 sections are now complete. The orchestrator specification is ready for implementation.

### Files for `/specs` folder:
1. `agent_orchestrator_spec_v2.3.md` — Main architecture spec
2. `orchestrator_types.py` — Type definitions  
3. `node_contracts.py` — Function signatures
4. `langgraph_definition.py` — Graph topology
5. `git_filesystem_spec.py` — Git worktree integration
6. `prompt_templates.py` — LLM prompts (14 total)
7. `tool_definitions.py` — Progressive disclosure tools

---

*Last updated: November 2025*
