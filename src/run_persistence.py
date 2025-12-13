"""
Run Persistence Module
======================
Persistence for orchestrator runs - supports both SQLite and PostgreSQL.
Backend is selected via config.checkpoint_mode.
"""

import psycopg
from psycopg.rows import dict_row
import aiosqlite
import json
import os
import logging
from typing import Optional, Dict, Any, List
from datetime import datetime
from orchestrator_types import serialize_messages

logger = logging.getLogger(__name__)

from contextlib import asynccontextmanager

@asynccontextmanager
async def _sqlite_connection(db_path: str):
    """Open SQLite connection with WAL mode enabled for better concurrency."""
    async with aiosqlite.connect(db_path) as db:
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("PRAGMA busy_timeout=5000")
        yield db

# Get database configuration
def _get_db_config():
    """Get database configuration from config."""
    from config import OrchestratorConfig
    config = OrchestratorConfig()
    checkpoint_mode = config.checkpoint_mode.lower()
    
    if checkpoint_mode == "postgres":
        db_uri = config.postgres_uri or os.getenv("POSTGRES_URI")
        if not db_uri:
            raise ValueError("PostgreSQL mode requires POSTGRES_URI in config or environment")
        return "postgres", db_uri
    elif checkpoint_mode == "sqlite":
        db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "orchestrator.db")
        return "sqlite", db_path
    else:
        raise ValueError(f"Unknown checkpoint_mode: {checkpoint_mode}")

async def init_runs_table():
    """Create the runs table if it doesn't exist."""
    db_type, db_conn_info = _get_db_config()
    
    if db_type == "postgres":
        async with await psycopg.AsyncConnection.connect(
            db_conn_info, autocommit=True, row_factory=dict_row
        ) as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY,
                    thread_id TEXT,
                    objective TEXT,
                    status TEXT,
                    state_json TEXT,
                    created_at TEXT,
                    updated_at TEXT,
                    workspace_path TEXT,
                    task_counts_json TEXT
                )
            """)
            logger.info("✅ Runs table initialized (PostgreSQL)")
    else:  # sqlite
        async with _sqlite_connection(db_conn_info) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY,
                    thread_id TEXT,
                    objective TEXT,
                    status TEXT,
                    state_json TEXT,
                    created_at TEXT,
                    updated_at TEXT,
                    workspace_path TEXT,
                    task_counts_json TEXT
                )
            """)
            await db.commit()
            logger.info("✅ Runs table initialized (SQLite + WAL mode)")


async def save_run_state(run_id: str, state: Dict[str, Any], status: str = "running"):
    """Save or update a run's full state to the database."""
    try:
        db_type, db_conn_info = _get_db_config()
        
        # Serialize state to JSON (exclude non-serializable objects)
        state_copy = {}
        for key, value in state.items():
            if key.startswith('_') or key in ['orch_config']:
                continue
            if key == "task_memories":
                try:
                    state_copy[key] = {tid: serialize_messages(msgs) for tid, msgs in value.items()}
                except Exception as e:
                    logger.error(f"Failed to serialize task_memories: {e}")
                continue
            try:
                json.dumps(value)
                state_copy[key] = value
            except (TypeError, ValueError):
                logger.debug(f"Skipping non-serializable key: {key}")
        
        state_json = json.dumps(state_copy)
        objective = state.get("objective", "")
        thread_id = state.get("run_id", run_id)
        workspace_path = state.get("_workspace_path", "")
        created_at = state.get("created_at", datetime.now().isoformat())
        updated_at = datetime.now().isoformat()
        
        tasks = state.get("tasks", [])
        task_counts = {
            "planned": len([t for t in tasks if t.get("status") == "planned"]),
            "ready": len([t for t in tasks if t.get("status") == "ready"]),
            "active": len([t for t in tasks if t.get("status") == "active"]),
            "complete": len([t for t in tasks if t.get("status") == "complete"]),
            "failed": len([t for t in tasks if t.get("status") == "failed"]),
        }
        task_counts_json = json.dumps(task_counts)
        
        if db_type == "postgres":
            async with await psycopg.AsyncConnection.connect(
                db_conn_info, autocommit=True, row_factory=dict_row
            ) as conn:
                await conn.execute("""
                    INSERT INTO runs 
                    (run_id, thread_id, objective, status, state_json, created_at, updated_at, workspace_path, task_counts_json)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (run_id) DO UPDATE SET
                        thread_id = EXCLUDED.thread_id, objective = EXCLUDED.objective,
                        status = EXCLUDED.status, state_json = EXCLUDED.state_json,
                        updated_at = EXCLUDED.updated_at, workspace_path = EXCLUDED.workspace_path,
                        task_counts_json = EXCLUDED.task_counts_json
                """, (run_id, thread_id, objective, status, state_json, created_at, updated_at, workspace_path, task_counts_json))
        else:  # sqlite
            async with _sqlite_connection(db_conn_info) as db:
                await db.execute("""
                    INSERT OR REPLACE INTO runs 
                    (run_id, thread_id, objective, status, state_json, created_at, updated_at, workspace_path, task_counts_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (run_id, thread_id, objective, status, state_json, created_at, updated_at, workspace_path, task_counts_json))
                await db.commit()
            
        logger.debug(f"💾 Saved run state: {run_id} (status: {status})")
    except Exception as e:
        logger.error(f"Failed to save run state: {e}")

async def load_run_state(run_id: str) -> Optional[Dict[str, Any]]:
    """Load a run's full state from the database."""
    try:
        db_type, db_conn_info = _get_db_config()
        
        if db_type == "postgres":
            async with await psycopg.AsyncConnection.connect(
                db_conn_info, autocommit=True, row_factory=dict_row
            ) as conn:
                cursor = await conn.execute(
                    "SELECT state_json, workspace_path FROM runs WHERE run_id = %s", (run_id,)
                )
                row = await cursor.fetchone()
                if row and row["state_json"]:
                    state = json.loads(row["state_json"])
                    if row["workspace_path"]:
                        state["_workspace_path"] = row["workspace_path"]
                    return state
        else:  # sqlite
            async with _sqlite_connection(db_conn_info) as db:
                cursor = await db.execute(
                    "SELECT state_json, workspace_path FROM runs WHERE run_id = ?", (run_id,)
                )
                row = await cursor.fetchone()
                if row and row[0]:
                    state = json.loads(row[0])
                    if row[1]:
                        state["_workspace_path"] = row[1]
                    return state
        return None
    except Exception as e:
        logger.error(f"Failed to load run state: {e}")
        return None

async def load_run_summary(run_id: str) -> Optional[Dict[str, Any]]:
    """Load run summary (without full state) for list display."""
    try:
        db_type, db_conn_info = _get_db_config()
        
        if db_type == "postgres":
            async with await psycopg.AsyncConnection.connect(
                db_conn_info, autocommit=True, row_factory=dict_row
            ) as conn:
                cursor = await conn.execute("""
                    SELECT run_id, thread_id, objective, status, created_at, updated_at, workspace_path, task_counts_json
                    FROM runs WHERE run_id = %s
                """, (run_id,))
                row = await cursor.fetchone()
                if row:
                    return {
                        "run_id": row["run_id"], "thread_id": row["thread_id"],
                        "objective": row["objective"], "status": row["status"],
                        "created_at": row["created_at"], "updated_at": row["updated_at"],
                        "workspace_path": row["workspace_path"],
                        "task_counts": json.loads(row["task_counts_json"]) if row["task_counts_json"] else {},
                        "tags": []
                    }
        else:  # sqlite
            async with _sqlite_connection(db_conn_info) as db:
                cursor = await db.execute("""
                    SELECT run_id, thread_id, objective, status, created_at, updated_at, workspace_path, task_counts_json
                    FROM runs WHERE run_id = ?
                """, (run_id,))
                row = await cursor.fetchone()
                if row:
                    return {
                        "run_id": row[0], "thread_id": row[1], "objective": row[2], "status": row[3],
                        "created_at": row[4], "updated_at": row[5], "workspace_path": row[6],
                        "task_counts": json.loads(row[7]) if row[7] else {},
                        "tags": []
                    }
        return None
    except Exception as e:
        logger.error(f"Failed to load run summary: {e}")
        return None

async def list_all_runs() -> List[Dict[str, Any]]:
    """List all runs (summaries only, not full state)."""
    try:
        db_type, db_conn_info = _get_db_config()
        
        if db_type == "postgres":
            async with await psycopg.AsyncConnection.connect(
                db_conn_info, autocommit=True, row_factory=dict_row
            ) as conn:
                cursor = await conn.execute("""
                    SELECT run_id, thread_id, objective, status, created_at, updated_at, workspace_path, task_counts_json
                    FROM runs ORDER BY created_at DESC
                """)
                rows = await cursor.fetchall()
                return [{
                    "run_id": row["run_id"], "thread_id": row["thread_id"],
                    "objective": row["objective"], "status": row["status"],
                    "created_at": row["created_at"], "updated_at": row["updated_at"],
                    "workspace_path": row["workspace_path"],
                    "task_counts": json.loads(row["task_counts_json"]) if row["task_counts_json"] else {},
                    "tags": []
                } for row in rows]
        else:  # sqlite
            async with _sqlite_connection(db_conn_info) as db:
                cursor = await db.execute("""
                    SELECT run_id, thread_id, objective, status, created_at, updated_at, workspace_path, task_counts_json
                    FROM runs ORDER BY created_at DESC
                """)
                rows = await cursor.fetchall()
                return [{
                    "run_id": row[0], "thread_id": row[1], "objective": row[2], "status": row[3],
                    "created_at": row[4], "updated_at": row[5], "workspace_path": row[6],
                    "task_counts": json.loads(row[7]) if row[7] else {},
                    "tags": []
                } for row in rows]
    except Exception as e:
        logger.error(f"Failed to list runs: {e}")
        return []

async def delete_run(run_id: str) -> bool:
    """Delete a run from the database."""
    try:
        db_type, db_conn_info = _get_db_config()
        
        if db_type == "postgres":
            async with await psycopg.AsyncConnection.connect(
                db_conn_info, autocommit=True, row_factory=dict_row
            ) as conn:
                await conn.execute("DELETE FROM runs WHERE run_id = %s", (run_id,))
        else:  # sqlite
            async with _sqlite_connection(db_conn_info) as db:
                await db.execute("DELETE FROM runs WHERE run_id = ?", (run_id,))
                await db.commit()
        return True
    except Exception as e:
        logger.error(f"Failed to delete run: {e}")
        return False

async def update_run_status(run_id: str, status: str):
    """Quick update of just the run status."""
    try:
        db_type, db_conn_info = _get_db_config()
        updated_at = datetime.now().isoformat()
        
        if db_type == "postgres":
            async with await psycopg.AsyncConnection.connect(
                db_conn_info, autocommit=True, row_factory=dict_row
            ) as conn:
                await conn.execute(
                    "UPDATE runs SET status = %s, updated_at = %s WHERE run_id = %s",
                    (status, updated_at, run_id)
                )
        else:  # sqlite
            async with _sqlite_connection(db_conn_info) as db:
                await db.execute(
                    "UPDATE runs SET status = ?, updated_at = ? WHERE run_id = ?",
                    (status, updated_at, run_id)
                )
                await db.commit()
    except Exception as e:
        logger.error(f"Failed to update run status: {e}")
