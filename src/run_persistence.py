"""
Run Persistence Module
======================
Simple SQLite persistence for orchestrator runs.
Stores full run state as JSON, independent of LangGraph checkpointing.
"""

import aiosqlite
import json
import os
import logging
from typing import Optional, Dict, Any, List
from datetime import datetime

logger = logging.getLogger(__name__)

# Database path (same as LangGraph checkpointer uses)
DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "orchestrator.db")

async def init_runs_table():
    """Create the runs table if it doesn't exist."""
    async with aiosqlite.connect(DB_PATH) as db:
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
        logger.info("✅ Runs table initialized")


async def save_run_state(run_id: str, state: Dict[str, Any], status: str = "running"):
    """
    Save or update a run's full state to the database.
    
    Args:
        run_id: Unique run identifier
        state: Full orchestrator state dict
        status: Current run status
    """
    try:
        # Serialize state to JSON (exclude non-serializable objects)
        state_copy = {}
        for key, value in state.items():
            # Skip internal/non-serializable objects
            if key.startswith('_') or key in ['orch_config']:
                continue
            try:
                # Test if serializable
                json.dumps(value)
                state_copy[key] = value
            except (TypeError, ValueError):
                logger.debug(f"Skipping non-serializable key: {key}")
        
        state_json = json.dumps(state_copy)
        
        # Get metadata
        objective = state.get("objective", "")
        thread_id = state.get("run_id", run_id)  # thread_id often equals run_id
        workspace_path = state.get("_workspace_path", "")
        created_at = state.get("created_at", datetime.now().isoformat())
        updated_at = datetime.now().isoformat()
        
        # Calculate task counts
        tasks = state.get("tasks", [])
        task_counts = {
            "planned": len([t for t in tasks if t.get("status") == "planned"]),
            "ready": len([t for t in tasks if t.get("status") == "ready"]),
            "active": len([t for t in tasks if t.get("status") == "active"]),
            "complete": len([t for t in tasks if t.get("status") == "complete"]),
            "failed": len([t for t in tasks if t.get("status") == "failed"]),
        }
        task_counts_json = json.dumps(task_counts)
        
        async with aiosqlite.connect(DB_PATH) as db:
            # Upsert (insert or replace)
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
    """
    Load a run's full state from the database.
    
    Returns:
        State dict or None if not found (includes _workspace_path if available)
    """
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute(
                "SELECT state_json, workspace_path FROM runs WHERE run_id = ?",
                (run_id,)
            )
            row = await cursor.fetchone()
            
            if row and row[0]:
                state = json.loads(row[0])
                # Restore _workspace_path from the separate column
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
        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute("""
                SELECT run_id, thread_id, objective, status, created_at, updated_at, workspace_path, task_counts_json
                FROM runs WHERE run_id = ?
            """, (run_id,))
            row = await cursor.fetchone()
            
            if row:
                return {
                    "run_id": row[0],
                    "thread_id": row[1],
                    "objective": row[2],
                    "status": row[3],
                    "created_at": row[4],
                    "updated_at": row[5],
                    "workspace_path": row[6],
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
        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute("""
                SELECT run_id, thread_id, objective, status, created_at, updated_at, workspace_path, task_counts_json
                FROM runs ORDER BY created_at DESC
            """)
            rows = await cursor.fetchall()
            
            return [{
                "run_id": row[0],
                "thread_id": row[1],
                "objective": row[2],
                "status": row[3],
                "created_at": row[4],
                "updated_at": row[5],
                "workspace_path": row[6],
                "task_counts": json.loads(row[7]) if row[7] else {},
                "tags": []
            } for row in rows]
            
    except Exception as e:
        logger.error(f"Failed to list runs: {e}")
        return []

async def delete_run(run_id: str) -> bool:
    """Delete a run from the database."""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("DELETE FROM runs WHERE run_id = ?", (run_id,))
            await db.commit()
            return True
    except Exception as e:
        logger.error(f"Failed to delete run: {e}")
        return False

async def update_run_status(run_id: str, status: str):
    """Quick update of just the run status."""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "UPDATE runs SET status = ?, updated_at = ? WHERE run_id = ?",
                (status, datetime.now().isoformat(), run_id)
            )
            await db.commit()
    except Exception as e:
        logger.error(f"Failed to update run status: {e}")
