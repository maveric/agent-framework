# Agent Orchestrator Framework

A multi-agent LLM orchestration system that coordinates AI agents to build software projects autonomously, with human-in-the-loop (HITL) intervention for quality control and course correction.

## What It Is

This framework enables **autonomous software development** by coordinating multiple specialized AI agents:

- **Director**: Plans tasks, manages dependencies, orchestrates the overall workflow
- **Code Workers**: Write implementation code (backend, frontend, APIs)
- **Test Workers**: Create and run tests, validate implementations
- **Planner Workers**: Break down complex tasks into subtasks
- **Strategist (QA)**: Evaluates completed work against acceptance criteria

All agents operate on a shared **blackboard** state, communicating through structured task objects rather than direct agent-to-agent messaging.

## Key Features

### 🔀 Git Worktree Isolation
Each task executes in its own git worktree, enabling:
- Parallel development without merge conflicts
- Clean rollback on task failure
- Automatic merge to main on QA approval
- LLM-assisted conflict resolution

### 🔄 Phoenix Protocol (Retry System)
Failed tasks don't just error out:
- Automatic retry with accumulated context
- Previous attempt history provided to next attempt
- Configurable max retries per task
- Human escalation for persistent failures

### 👤 Human-in-the-Loop (HITL)
When tasks exceed retry limits:
- Run pauses and waits for human decision
- Options: Retry (with modifications), Abandon, Spawn New Task
- Real-time dashboard shows task status and agent logs
- Seamless resume after human intervention

### 📊 Real-Time Dashboard
React-based monitoring interface:
- Live task graph visualization
- Agent conversation logs
- WebSocket-based real-time updates
- Run management (start, stop, restart, interrupt)

### 🧠 Task Memory Persistence
- Full agent conversation history saved per task
- Survives server restarts
- Useful for debugging and post-mortem analysis

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    FastAPI Server (server.py)               │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐  │
│  │  REST API   │  │  WebSocket  │  │  Run Persistence    │  │
│  │  Endpoints  │  │  Manager    │  │  (SQLite)           │  │
│  └─────────────┘  └─────────────┘  └─────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│               Continuous Dispatch Loop                       │
│  ┌─────────┐  ┌─────────────┐  ┌─────────────┐             │
│  │Director │→ │Task Queue   │→ │ Workers     │              │
│  │ Node    │  │(Concurrent) │  │ (Parallel)  │              │
│  └─────────┘  └─────────────┘  └─────────────┘              │
│       │                              │                       │
│       ▼                              ▼                       │
│  ┌─────────────┐            ┌─────────────────┐             │
│  │ Strategist  │←───────────│ QA Evaluation   │             │
│  │ (QA Node)   │            │ (LLM-based)     │             │
│  └─────────────┘            └─────────────────┘             │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                   Git Worktree Manager                       │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐    │
│  │ task_001 │  │ task_002 │  │ task_003 │  │   main   │    │
│  │ worktree │  │ worktree │  │ worktree │  │ (merged) │    │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘    │
└─────────────────────────────────────────────────────────────┘
```

## Project Structure

```
agent-framework/
├── src/
│   ├── server.py              # FastAPI server, REST API, WebSocket
│   ├── nodes/
│   │   ├── director.py        # Task planning and orchestration
│   │   ├── worker.py          # Agent execution (code, test, plan)
│   │   ├── strategist.py      # QA evaluation
│   │   └── routing.py         # Graph routing logic
│   ├── git_manager.py         # Worktree management, merge, conflict resolution
│   ├── llm_client.py          # Multi-provider LLM abstraction
│   ├── config.py              # Model configuration
│   ├── state.py               # Blackboard state definition
│   ├── orchestrator_types.py  # Task, Worker, Status types
│   ├── run_persistence.py     # SQLite state persistence
│   └── tools/                 # Agent tools (filesystem, git, shell)
├── orchestrator-dashboard/    # React frontend
│   ├── src/
│   │   ├── pages/RunDetails.tsx
│   │   ├── components/
│   │   │   ├── TaskGraph.tsx
│   │   │   ├── InterruptModal.tsx
│   │   │   └── TaskDetailsContent.tsx
│   │   └── services/websocket.ts
├── spec/                      # Design documentation
│   ├── architecture.md
│   ├── future/               # Planned enhancements
│   └── ...
└── requirements.txt
```

## Getting Started

### Prerequisites
- Python 3.11+
- Node.js 18+ (for dashboard)
- Git

### Installation

```bash
# Clone and setup
cd agent-framework
python -m venv .venv
.venv\Scripts\activate  # Windows
source .venv/bin/activate  # Unix

pip install -r requirements.txt

# Setup dashboard
cd orchestrator-dashboard
npm install
npm run build
cd ..
```

### Configuration

Create `.env` file:
```env
# LLM Providers (choose one or more)
OPENROUTER_API_KEY=your_key_here
# ANTHROPIC_API_KEY=...
# OPENAI_API_KEY=...

# Search APIs (for research worker)
TAVILY_API_KEY=tvly-xxxxxxxxxxxxxxxxxxxxx
SERPAPI_KEY=your_serpapi_key_here

# Optional: Ollama for local models
# OLLAMA_BASE_URL=http://localhost:11434/v1
```

### Running

```bash
# Start server (serves both API and dashboard)
python src/server.py

# Open dashboard
# http://localhost:8085
```

## Current Challenges & Known Issues

### 🔧 Active Development Areas

1. **Task Memory Loss After QA**
   - Investigating: Worker conversation logs sometimes only show QA messages
   - Debug logging added to trace the issue

2. **Long-Running Commands**
   - Agents occasionally run blocking commands (servers, watchers)
   - Interrupt doesn't kill spawned subprocesses
   - Spec written for future deep cancellation feature

3. **Git State Edge Cases**
   - Multiple failed merges can leave repo in inconsistent state
   - Added auto-recovery for common scenarios
   - Merge abort before checkout to handle mid-merge states

4. **Test Result Detection**
   - QA relies on agents writing results to specific paths
   - Proactive search added to find expected test files

### ⚠️ Operational Notes

- **Database Size**: `orchestrator.db` can grow large with many runs
- **LLM Costs**: Each agent iteration makes LLM calls; monitor usage
- **Worktree Cleanup**: Old worktrees in `.worktrees/` can accumulate

## Configuration Options

Edit `src/config.py` to customize:

```python
OrchestratorConfig(
    worker_model=ModelConfig(provider="openrouter", model="..."),
    coder_model=ModelConfig(...),  # Separate model for code tasks
    max_workers=5,                 # Concurrent task limit
    max_retries=4,                 # Phoenix retries before HITL
)
```

## Contributing

This is an active research project. Key areas for contribution:

- [ ] Deep task cancellation (subprocess tracking)
- [ ] Improved conflict resolution strategies
- [ ] Task dependency graph optimization
- [ ] Agent memory/context compression
- [ ] Multi-project workspace support

## License

[To be determined]

---

*Built with LangChain, LangGraph, FastAPI, React, and a lot of debugging sessions.*
