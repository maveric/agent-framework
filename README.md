# 🤖 Agent Orchestrator Framework

A reliability-focused multi-agent LLM orchestration system designed for long-running software workflows with explicit state management, failure handling, and human-in-the-loop escalation.

![Status](https://img.shields.io/badge/status-active-green)
![Python](https://img.shields.io/badge/python-3.11+-blue)
![License](https://img.shields.io/badge/license-MIT-green)

> **Status**: Active development. Task lifecycle, retry protocol, and HITL escalation are functional. Supports 7 task states, configurable retries (default 4), and persistence via SQLite/PostgreSQL/MySQL.

---

## 🎯 What Makes This Different

Most agent frameworks optimize for impressive demos. This one optimizes for **systems that run unattended and fail gracefully**.

| Principle | Implementation |
|-----------|----------------|
| **Explicit state** | Blackboard architecture — state lives outside the model, in observable task objects |
| **Bounded authority** | LLMs propose actions; tools execute through validation layer with logging |
| **Failure as expected** | Phoenix retry protocol with accumulated context; escalates to human after max retries |
| **Human-in-the-loop** | HITL is a designed control path, not an exception handler — runs pause and wait for guidance |
| **Replayable runs** | Full task history persisted; conversation logs saved per task for debugging |
| **Isolation** | Git worktrees per task — parallel execution without merge conflicts |

For the philosophy behind these decisions, see [WHY.md](WHY.md).

---

## 📋 Table of Contents

- [Overview](#-overview)
- [Key Features](#-key-features)
- [Architecture](#-architecture)
- [Quick Start](#-quick-start)
- [Configuration](#-configuration)
- [Dashboard](#-dashboard)
- [API Reference](#-api-reference)
- [How It Works](#-how-it-works)
- [Project Structure](#-project-structure)
- [Development](#-development)
- [Contributing](#-contributing)

---

## 🌟 Overview

The Agent Orchestrator Framework coordinates **multi-step software workflows** — planning, building, testing, and integration — using specialized agents with explicit state management and controlled execution.

### Core Design

- **Explicit task lifecycle**: Tasks move through defined states (`planned` → `ready` → `active` → `awaiting_qa` → `complete`/`failed`)
- **Separation of reasoning and execution**: LLMs decide what to do; tools execute through a validation layer
- **Failure handling built-in**: Phoenix retry protocol accumulates context across attempts; escalates to human after configurable retries
- **Observable state**: All task state, agent logs, and decisions are persisted and queryable

**Implemented with**: LangGraph (state machines), FastAPI (REST/WebSocket), React (dashboard), Git worktrees (isolation)

### System Architecture

| Layer | Components | Purpose |
|-------|------------|---------|
| **Control Plane** | Director, Dispatch Loop, Phoenix Protocol, HITL | Orchestration, retry logic, human escalation |
| **Execution Plane** | Code Worker, Test Worker, Test Architect, Planner, Research Worker, Writer | Domain-specific task execution |
| **Integration Plane** | Merge Worker, Git Manager | Code integration, conflict resolution |
| **Safety Layer** | Guardian *(optional, WIP)*, Strategist (QA) | Drift detection, quality evaluation |

All agents operate on a shared **blackboard** — state lives outside the model in structured task objects.

---

## ✨ Key Features

### 🔀 Git Worktree Isolation
Each task executes in its own git worktree, enabling:
- **Parallel development** without merge conflicts
- **Clean rollback** on task failure
- **Automatic merge** to main on QA approval
- **LLM-assisted conflict resolution** for complex merges

### 🔄 Phoenix Protocol (Retry System)
Failed tasks don't just error out:
- Automatic retry with accumulated context
- Previous attempt history provided to next attempt
- Configurable max retries per task (default: 4)
- Human escalation for persistent failures

### 👤 Human-in-the-Loop (HITL)
When tasks exceed retry limits or are interrupted by human intervention:
- Task pauses and waits for human decision - other tasks continue if dependencies allow
- Options: **Retry** (with modifications), **Abandon**, **Spawn New Task**
- Real-time dashboard shows task status and agent logs
- Seamless resume after human intervention

### 📊 Real-Time Dashboard
React-based monitoring interface with:
- Live task graph visualization (DAG with dependency arrows)
- Agent conversation logs (full LLM chat history)
- WebSocket-based real-time updates
- Run management (start, stop, restart, cancel)
- Visual task dependency creation (click-to-connect/disconnect)

### 🧠 Task Memory Persistence
- Full agent conversation history saved per task
- Survives server restarts
- Multiple database backends: SQLite (default), PostgreSQL, MySQL
- Useful for debugging and post-mortem analysis

### 🚀 Concurrent Execution
- Configurable number of parallel workers (default: 5)
- Non-blocking dispatch loop for maximum parallelism
- Rate-limited API to prevent LLM quota exhaustion

---

## 🏗 Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          FastAPI Server (server.py)                      │
│  ┌──────────────┐   ┌──────────────┐   ┌───────────────────────────┐   │
│  │  REST API    │   │  WebSocket   │   │  Run Persistence (SQLite) │   │
│  │  /api/v1/*   │   │  Manager     │   │  Checkpointing            │   │
│  └──────────────┘   └──────────────┘   └───────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                    Continuous Dispatch Loop (api/dispatch.py)           │
│  ┌────────────┐    ┌───────────────┐    ┌───────────────────────┐     │
│  │  Director  │ →  │  Task Queue   │ →  │  Workers (Parallel)   │     │
│  │  Node      │    │  (Concurrent) │    │  code/test/plan/...   │     │
│  └────────────┘    └───────────────┘    └───────────────────────┘     │
│        │                                          │                    │
│        ▼                                          ▼                    │
│  ┌────────────────────────┐          ┌──────────────────────────┐     │
│  │  Phoenix Protocol      │ ←────────│  Strategist (QA Node)    │     │
│  │  (Retry & Escalation)  │          │  LLM-based evaluation    │     │
│  └────────────────────────┘          └──────────────────────────┘     │
└─────────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                      Git Worktree Manager (git_manager.py)              │
│  ┌───────────────┐  ┌───────────────┐  ┌───────────────┐              │
│  │  task_abc123  │  │  task_def456  │  │  task_ghi789  │  ...         │
│  │  (worktree)   │  │  (worktree)   │  │  (worktree)   │              │
│  └───────────────┘  └───────────────┘  └───────────────┘              │
│                               │                                        │
│                               ▼                                        │
│                        ┌─────────────┐                                │
│                        │    main     │  ← Merged on QA approval       │
│                        │  (branch)   │                                │
│                        └─────────────┘                                │
└─────────────────────────────────────────────────────────────────────────┘
```

### State Flow

1. **Director** decomposes objective → creates planner tasks
2. **Planner** creates worker tasks with dependencies
3. **Dispatch Loop** spawns workers for READY tasks (dependencies satisfied)
4. **Workers** execute in isolated worktrees using ReAct agent pattern
5. **Strategist** evaluates completed work against acceptance criteria
6. **Director** promotes successful tasks, retries failures (Phoenix protocol)
7. **Git Manager** merges approved work to main branch

---

## 🚀 Quick Start

### Prerequisites

- Python 3.11+
- Node.js 18+ (for dashboard)
- Git

### Installation

```bash
# Clone the repository
git clone https://github.com/maveric/agent-framework.git
cd agent-framework

# Create virtual environment
python -m venv .venv

# Activate (Windows)
.venv\Scripts\activate

# Activate (Unix/macOS)
source .venv/bin/activate

# Install Python dependencies
pip install -r requirements.txt

# Build the dashboard
cd orchestrator-dashboard
npm install
npm run build
cd ..
```

### Configuration

Create a `.env` file in the project root:

```env
# LLM Providers (at least one required)
OPENROUTER_API_KEY=sk-or-v1-xxxxxxxxxxxxx
ANTHROPIC_API_KEY=sk-ant-xxxxxxxxxxxxx
OPENAI_API_KEY=sk-xxxxxxxxxxxxx

# For local models (optional)
OLLAMA_BASE_URL=http://localhost:11434/v1

# Web search (for research worker)
TAVILY_API_KEY=tvly-xxxxxxxxxxxxx

# Optional: LangSmith tracing
LANGSMITH_API_KEY=your_key_here
LANGSMITH_PROJECT=agent-orchestrator
```

### Running

```bash
# Start the server (serves both API and dashboard)
python src/server.py

# Open dashboard at http://localhost:8085
```

### Creating Your First Run

1. Open the dashboard at `http://localhost:8085`
2. Click **"New Run"**
3. Enter an objective, e.g., *"Create a TODO list web app with FastAPI backend and vanilla JS frontend"*
4. Specify a workspace path (where code will be generated)
5. Click **"Start Run"**
6. Watch the agents work in real-time!

---

## ⚙️ Configuration

### Model Configuration

Edit `src/config.py` to customize which LLM models are used:

```python
@dataclass
class OrchestratorConfig:
    # Director uses smart model for planning
    director_model: ModelConfig = field(default_factory=lambda: ModelConfig(
        provider="openai",
        model_name="gpt-4.1",
        temperature=0.7
    ))
    
    # Default worker model (can be overridden per worker type)
    worker_model: ModelConfig = field(default_factory=lambda: ModelConfig(
        provider="glm",
        model_name="glm-4.6",
        temperature=0.5
    ))
    
    # Per-worker-type models (optional - falls back to worker_model)
    planner_model: Optional[ModelConfig] = None
    researcher_model: Optional[ModelConfig] = None
    coder_model: Optional[ModelConfig] = None
    tester_model: Optional[ModelConfig] = None
    
    # QA strategist
    strategist_model: ModelConfig = field(default_factory=lambda: ModelConfig(
        provider="openrouter",
        model_name="minimax/minimax-m2",
        temperature=0.3
    ))
    
    # Execution limits
    max_concurrent_workers: int = 5
    max_iterations_per_task: int = 10
    worker_timeout: int = 300  # seconds
```

### Database Backend

```python
# In config.py
checkpoint_mode: str = "sqlite"  # "sqlite", "postgres", "mysql", or "memory"

# PostgreSQL
postgres_uri: Optional[str] = None  # Falls back to POSTGRES_URI env var

# MySQL
mysql_uri: Optional[str] = None  # Falls back to MYSQL_URI env var
```

### Feature Flags

```python
enable_guardian: bool = False      # Drift detection during execution
enable_webhooks: bool = False      # External notifications - WIP
```

### Supported LLM Providers

| Provider | Config Value | Notes |
|----------|--------------|-------|
| OpenAI | `openai` | GPT-4, GPT-3.5 |
| Anthropic | `anthropic` | Claude 3.5, Claude 3 |
| OpenRouter | `openrouter` | Access to 100+ models |
| Google | `google` | Gemini models |
| GLM | `glm` | ZhipuAI models |
| Ollama | `local` | Local models via Ollama |

---

## 📊 Dashboard

The dashboard provides real-time visibility into agent operations:

### Views

| View | Description |
|------|-------------|
| **Dashboard** | List of all runs with status and progress |
| **Run Details** | Live task graph, agent logs, model config |
| **New Run** | Create new runs with objective and workspace config |
| **Human Queue** | Tasks waiting for HITL intervention |

### Task Graph

- **Nodes** = Tasks (color-coded by status)
- **Edges** = Dependencies (arrows show "depends on")
- **Click** = View task details and agent conversation
- **Link Mode** = Click-to-connect/disconnect for adding/removing dependencies

### Task Statuses

| Status | Color | Description |
|--------|-------|-------------|
| `planned` | Gray | Waiting for dependencies |
| `ready` | Slate | Dependencies satisfied, ready to run |
| `active` | Blue | Currently being executed |
| `awaiting_qa` | Orange | Waiting for QA evaluation |
| `complete` | Green | Successfully completed |
| `failed` | Red | Failed (will retry via Phoenix) |
| `waiting_human` | Yellow | Needs HITL intervention |
| `abandoned` | Dim | Manually abandoned |

---

## 🔌 API Reference

All endpoints are prefixed with `/api/v1/`.

### Runs

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/runs` | List all runs (paginated) |
| `POST` | `/runs` | Create new run |
| `GET` | `/runs/{id}` | Get run details + tasks |
| `POST` | `/runs/{id}/cancel` | Cancel a running task |
| `POST` | `/runs/{id}/restart` | Restart from last checkpoint |
| `POST` | `/runs/{id}/replan` | Trigger dependency rebuild |

### Tasks

| Method | Endpoint | Description |
|--------|----------|-------------|
| `PATCH` | `/runs/{id}/tasks/{task_id}` | Update task dependencies |
| `DELETE` | `/runs/{id}/tasks/{task_id}` | Abandon task + replan |

### HITL (Human-in-the-Loop)

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/runs/{id}/interrupts` | Check for pending interrupts |
| `POST` | `/runs/{id}/resolve` | Submit human resolution |
| `POST` | `/runs/{id}/tasks/{task_id}/interrupt` | Force interrupt a task |

### WebSocket

| Endpoint | Description |
|----------|-------------|
| `/ws` | Real-time updates (connect with run_id param) |

---

## 🔧 How It Works

### Task Lifecycle

```
PLANNED → READY → ACTIVE → AWAITING_QA → COMPLETE
             ↓                    ↓
          (blocked)            FAILED
                                 ↓
                          (Phoenix retry)
                                 ↓
                          WAITING_HUMAN
```

### Worker Execution (ReAct Pattern)

Each worker uses a ReAct (Reasoning + Acting) agent loop:

1. **Reason**: LLM analyzes the task and decides next action
2. **Act**: Execute a tool (write_file, run_shell, search, etc.)
3. **Observe**: See tool output
4. **Repeat** until task is complete

### Available Tools

Tools use a progressive disclosure system — workers request only what they need.

| Category | Tools |
|----------|-------|
| **Filesystem** | `read_file`, `write_file`, `append_file`, `list_directory`, `delete_file` |
| **Code Execution** | `run_shell`, `run_python` |
| **Git** | `git_status`, `git_commit`, `git_diff`, `git_log` |
| **Search** | `search_codebase`, `web_search` (Tavily) |
| **Framework** | `create_subtasks`, `post_insight`, `log_design_decision` |

---

## 📁 Project Structure

```
agent-framework/
├── src/
│   ├── server.py              # FastAPI app, lifespan, mounts (MAIN ENTRY)
│   ├── config.py              # Configuration dataclasses
│   ├── api/
│   │   ├── dispatch.py        # Continuous dispatch loop (core engine)
│   │   ├── state.py           # Shared API state
│   │   ├── types.py           # API type definitions
│   │   ├── websocket.py       # WebSocket connection manager
│   │   └── routes/
│   │       ├── runs.py        # Run CRUD endpoints
│   │       ├── tasks.py       # Task endpoints
│   │       ├── interrupts.py  # HITL endpoints
│   │       ├── metrics.py     # Prometheus metrics endpoint
│   │       └── ws.py          # WebSocket endpoint
│   ├── nodes/
│   │   ├── director_main.py   # Director orchestration logic
│   │   ├── director/          # Director helper modules
│   │   │   ├── decomposition.py
│   │   │   ├── integration.py
│   │   │   ├── readiness.py
│   │   │   ├── hitl.py
│   │   │   └── graph_utils.py
│   │   ├── worker.py          # Worker node entry point
│   │   ├── execution.py       # ReAct loop execution
│   │   ├── guardian.py        # Drift detection (optional)
│   │   ├── strategist.py      # QA evaluation node
│   │   ├── handlers/          # Worker profile handlers
│   │   │   ├── code_handler.py
│   │   │   ├── plan_handler.py
│   │   │   ├── test_handler.py
│   │   │   ├── test_architect_handler.py
│   │   │   ├── research_handler.py
│   │   │   ├── write_handler.py
│   │   │   └── merge_handler.py
│   │   └── tools_binding.py   # Tool wrappers for agents
│   ├── tools/                 # Tool implementations
│   │   ├── base.py            # Tool registry & definitions
│   │   ├── filesystem_async.py
│   │   ├── code_execution_async.py
│   │   ├── git_async.py
│   │   └── search_tools.py
│   ├── git_manager.py         # Worktree management
│   ├── llm_client.py          # Multi-provider LLM client
│   ├── state.py               # State definition and reducers
│   ├── orchestrator_types.py  # Core type definitions
│   ├── run_persistence.py     # Database state persistence
│   ├── task_queue.py          # Async task queue
│   ├── metrics.py             # Prometheus metrics
│   └── async_utils.py         # Async helper utilities
│
├── orchestrator-dashboard/    # React frontend
│   ├── src/
│   │   ├── pages/
│   │   │   ├── Dashboard.tsx
│   │   │   ├── RunDetails.tsx
│   │   │   ├── NewRun.tsx
│   │   │   └── HumanQueue.tsx
│   │   ├── components/
│   │   │   ├── TaskGraph.tsx  # DAG visualization
│   │   │   ├── InterruptModal.tsx
│   │   │   └── run-details/   # RunDetails subcomponents
│   │   └── api/
│   │       ├── client.ts
│   │       └── websocket.ts
│
├── Spec/                      # Design documentation
│   ├── agent_orchestrator_spec_v2.3.md
│   ├── dashboard_frontend_spec.md
│   └── future/                # Planned features
│
├── tests/
│   ├── unit/                  # Unit tests
│   └── test_task_memories.py  # Integration tests
│
├── docs/                      # Additional documentation
├── requirements.txt
└── README.md
```

---

## 🛠 Development

### Running Tests

```bash
# Run all tests
pytest tests/

# Run with coverage
pytest tests/ --cov=src --cov-report=html

# Run specific test file
pytest tests/unit/test_state_reducers.py -v
```

### Development Server

```bash
# Run backend with auto-reload
uvicorn src.server:app --reload --port 8085

# Run frontend dev server (separate terminal)
cd orchestrator-dashboard
npm run dev  # Runs on port 2999
```

### Code Quality

```bash
# Type checking (future)
mypy src/

# Linting (future)
ruff check src/
```

---

## 🤝 Contributing

This is an active research project. Key areas for contribution:

### High Priority
- [ ] Deep task cancellation (subprocess tracking)
- [ ] Improved conflict resolution strategies
- [ ] Multi-project workspace support
- [ ] Streaming LLM responses to UI

### Medium Priority
- [ ] Agent memory compression for long contexts
- [ ] Task cost estimation and budgeting
- [ ] Plugin system for custom tools
- [ ] Kubernetes deployment manifests

### Low Priority
- [ ] Alternative state backends (Redis, Postgres)
- [ ] Multi-user authentication
- [ ] Project templates/scaffolding

---

## ⚠️ Known Limitations

1. **Database Size**: `orchestrator.db` can grow large with many runs. Periodic cleanup recommended.

2. **LLM Costs**: Each agent iteration makes LLM calls. Monitor your API usage.

3. **Blocking Commands**: Agents occasionally run blocking commands (servers, watchers). Force-interrupt may be needed.

4. **Worktree Cleanup**: Old worktrees in `.worktrees/` can accumulate. Manual cleanup may be needed.

---

## 📄 License

MIT License - See [LICENSE](LICENSE) for details.

---

## 🙏 Acknowledgments

Built with:
- [LangChain](https://python.langchain.com/) & [LangGraph](https://langchain-ai.github.io/langgraph/)
- [FastAPI](https://fastapi.tiangolo.com/)
- [React](https://react.dev/) & [React Flow](https://reactflow.dev/)
- [Vite](https://vitejs.dev/)

---

*For questions or support, please open an issue on GitHub.*
