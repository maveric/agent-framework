# Database Configuration Guide

## Overview

The orchestrator now supports **both SQLite and PostgreSQL** for checkpointing and run persistence.

Database backend is selected via `config.checkpoint_mode` in `src/config.py`.

---

## Configuration Options

### Option 1: SQLite (Default)

**Best for**: Local development, single-machine deployments

```python
# In src/config.py
checkpoint_mode: str = "sqlite"
```

- No additional setup required
- Database file: `orchestrator.db`
- Works immediately out of the box

### Option 2: PostgreSQL

**Best for**: Production, remote hosting, multi-user deployments

```python
# In src/config.py
checkpoint_mode: str = "postgres"
postgres_uri: Optional[str] = "postgresql://user:pass@host:5432/dbname"  # Or use env var
```

**OR** set via environment variable:
```env
# In .env
POSTGRES_URI=postgresql://user:pass@host:5432/orchestrator_db
```

Config setting takes precedence over environment variable.

---

## Switching Backends

### To use SQLite:
1. Set `checkpoint_mode = "sqlite"` in `config.py`
2. Restart server
3. Database stored in `orchestrator.db`

### To use PostgreSQL:
1. Set `checkpoint_mode = "postgres"` in `config.py`
2. Set `postgres_uri` in config OR `POSTGRES_URI` in `.env`
3. Ensure PostgreSQL database exists
4. Restart server - tables auto-created

### To switch from SQLite → PostgreSQL:
- Old SQLite data remains in `orchestrator.db` (archived)
- New runs use PostgreSQL (fresh start)
- No migration tool - data starts fresh

### To switch from PostgreSQL → SQLite:
- PostgreSQL data remains on server (archived)
- New runs use local SQLite
- Fresh start

---

## What Gets Stored Where

Both backends store:
- **LangGraph checkpoints** (agent state, conversation history)
- **Custom runs table** (run metadata, task counts, state snapshots)

**Tables created:**
- `checkpoints` - LangGraph state (auto-created by AsyncPostgresSaver/AsyncSqliteSaver)
- `runs` - Custom run persistence (created by run_persistence.py)

---

## Current Settings

Check your current mode:
```python
from config import OrchestratorConfig
config = OrchestratorConfig()
print(f"Checkpoint mode: {config.checkpoint_mode}")
print(f"Postgres URI: {config.postgres_uri or os.getenv('POSTGRES_URI') or 'Not set'}")
```

Server logs on startup show:
```
Initializing checkpointer (mode: sqlite)
✅ AsyncSqliteSaver initialized successfully
✅ Runs table initialized (SQLite)
```

or

```
Initializing checkpointer (mode: postgres)
✅ AsyncPostgresSaver initialized successfully
✅ Runs table initialized (PostgreSQL)
```

---

## Troubleshooting

**Error: "Unknown checkpoint_mode"**
- Valid values: "sqlite" or "postgres"
- Check spelling in config.py

**Error: "PostgreSQL mode requires POSTGRES_URI"**
- Set `postgres_uri` in config.py OR `POSTGRES_URI` in .env
- Format: `postgresql://user:password@host:port/database`

**Error: "database does not exist"**
- Create database on PostgreSQL server first:
  ```sql
  CREATE DATABASE orchestrator_db;
  ```

**Run not showing up after backend switch**
- Each backend has separate data
- Switch back to see old runs
- Or export/import manually if needed
