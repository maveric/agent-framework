"""
Agent Orchestrator — API Server
===============================
Version 1.0 — November 2025

FastAPI server for the orchestrator dashboard.
"""

import os
import sys
import json
import asyncio
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime
from contextlib import asynccontextmanager

from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Disable LangSmith tracing by default to prevent warnings
# User requested to turn this off. To enable, set LANGCHAIN_TRACING_V2=true AND ensure LANGCHAIN_API_KEY is valid.
# For now, we force it off to avoid "not authorized" errors.
os.environ["LANGCHAIN_TRACING_V2"] = "false"

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, BackgroundTasks, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

# Add src to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from langgraph_definition import create_orchestrator
from config import OrchestratorConfig
from state import OrchestratorState, tasks_reducer, task_memories_reducer, insights_reducer, design_log_reducer
from git_manager import WorktreeManager, initialize_git_repo
from orchestrator_types import worker_result_to_dict, task_to_dict, TaskStatus, serialize_messages

# Import API modules
from api.websocket import ConnectionManager
from api.types import CreateRunRequest, RunSummary, HumanResolution
from api.dispatch import run_orchestrator, continuous_dispatch_loop, broadcast_state_update
import api.state as api_state

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("server")

# Suppress noisy LangChain callback warnings about serialization
# These occur when our Pydantic models don't implement lc_serializable
# but don't affect functionality - purely cosmetic
logging.getLogger("langchain_core.callbacks.manager").setLevel(logging.ERROR)

# Initialize connection manager
manager = ConnectionManager()
# Set the global manager in api.state so dispatch module can use it
api_state.manager = manager

# =============================================================================
# APP SETUP
# =============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup - Initialize checkpointer
    try:
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
        import aiosqlite

        db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "orchestrator.db")
        logger.info(f"Initializing checkpointer with database: {db_path}")

        # Create async connection and checkpointer
        conn = await aiosqlite.connect(db_path)
        api_state.global_checkpointer = AsyncSqliteSaver(conn)

        logger.info("✅ AsyncSqliteSaver initialized successfully")
    except Exception as e:
        logger.error(f"❌ Failed to initialize checkpointer: {e}")
        import traceback
        traceback.print_exc()
        raise
    
    # Initialize our custom runs table
    from run_persistence import init_runs_table
    await init_runs_table()
    
    logger.info("Starting Orchestrator Server")
    
    # Register signal handlers for cleanup
    import signal
    import psutil
    
    def shutdown_handler():
        logger.info(f"Cleaning up child processes...")
        try:
            parent = psutil.Process(os.getpid())
            children = parent.children(recursive=True)
            for child in children:
                try:
                    logger.info(f"Killing child process {child.pid}")
                    child.terminate()
                except psutil.NoSuchProcess:
                    pass
            
            # Wait for termination
            _, alive = psutil.wait_procs(children, timeout=3)
            for p in alive:
                try:
                    logger.warning(f"Force killing process {p.pid}")
                    p.kill()
                except psutil.NoSuchProcess:
                    pass
                    
        except Exception as e:
            logger.error(f"Error during cleanup: {e}")
    
    yield
    
    # Shutdown logic (runs when FastAPI stops)
    logger.info("Shutting down Orchestrator Server")
    shutdown_handler()
    
    # Close DB connection
    if 'conn' in locals():
        await conn.close()
        logger.info("Database connection closed")

app = FastAPI(title="Agent Orchestrator API", lifespan=lifespan)

# Rate limiting setup
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("FRONTEND_URL", "*").split(",") if os.getenv("FRONTEND_URL") != "*" else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =============================================================================
# STATE MANAGEMENT (Using api.state module)
# =============================================================================

# Use state from api.state module
runs_index = api_state.runs_index
running_tasks = api_state.running_tasks
run_states = api_state.run_states
get_orchestrator_graph = api_state.get_orchestrator_graph

def _serialize_orch_config(config):
    """Serialize OrchestratorConfig to dict for API response."""
    if not config:
        return None
    
    try:
        return {
            "director_model": {
                "provider": config.director_model.provider,
                "model_name": config.director_model.model_name,
                "temperature": config.director_model.temperature
            },
            "worker_model": {
                "provider": config.worker_model.provider,
                "model_name": config.worker_model.model_name,
                "temperature": config.worker_model.temperature
            },
            "strategist_model": {
                "provider": config.strategist_model.provider,
                "model_name": config.strategist_model.model_name,
                "temperature": config.strategist_model.temperature
            }
        }
    except Exception as e:
        logger.error(f"Error serializing config: {e}")
        return None

# =============================================================================
# ENDPOINTS
# =============================================================================

async def ensure_run_in_index(run_id: str) -> bool:
    """
    Ensure run is in runs_index by looking it up in database if needed.
    
    This allows API endpoints to work with CLI-initiated runs that aren't
    in the in-memory runs_index.
    
    Returns:
        True if run found (already in index or added from DB), False if not found.
    """
    # Already in index
    if run_id in runs_index:
        logger.debug(f"Run {run_id} already in index")
        return True
    
    # Try to find in database
    logger.info(f"🔍 Looking up run {run_id} in database (CLI-initiated run?)")
    try:
        get_orchestrator_graph()
        
        # Get async connection from checkpointer
        conn = global_checkpointer.conn
        cursor = await conn.cursor()
        await cursor.execute("SELECT DISTINCT thread_id FROM checkpoints")
        rows = await cursor.fetchall()
        thread_ids = [row[0] for row in rows]
        logger.info(f"   Found {len(thread_ids)} thread(s) in database")
        
        for thread_id in thread_ids:
            config = {"configurable": {"thread_id": thread_id}}
            state_snapshot = await global_checkpointer.aget(config)
            
            if state_snapshot and "channel_values" in state_snapshot:
                state = state_snapshot["channel_values"]
                found_run_id = state.get("run_id", thread_id)
                
                if found_run_id == run_id:
                    # Found it! Add to index
                    runs_index[run_id] = {
                        "run_id": run_id,
                        "thread_id": thread_id,
                        "objective": state.get("objective", ""),
                        "status": "running",
                        "created_at": state.get("created_at", ""),
                        "updated_at": state.get("updated_at", ""),
                        "task_counts": {},
                        "tags": state.get("tags", [])
                    }
                    logger.info(f"✅ Found and added run {run_id} (thread: {thread_id})")
                    return True
        
        logger.warning(f"❌ Run {run_id} not found in database")
        return False
            
    except Exception as e:
        logger.error(f"Error looking up run in database: {e}")
        return False

# =============================================================================
# ROUTE REGISTRATION
# =============================================================================

# Import route modules
from api.routes import runs_router, tasks_router, interrupts_router, ws_router

# Register routers
app.include_router(runs_router)
app.include_router(tasks_router)
app.include_router(interrupts_router)
app.include_router(ws_router)

# =============================================================================
# BACKGROUND WORKER
# =============================================================================

async def _stream_and_broadcast(orchestrator, input_data, run_config, run_id):
    """Stream events from the graph and broadcast updates to the frontend."""
    try:
        logger.info(f"📡 Starting event stream for run {run_id}")
        event_count = 0
        
        # CRITICAL: Ensure recursion_limit is set to prevent default 25 limit
        if "recursion_limit" not in run_config:
            run_config["recursion_limit"] = 150
        
        async for event in orchestrator.astream_events(input_data, config=run_config, version="v1"):
            kind = event["event"]
            name = event.get("name", "")
            event_count += 1
            
            # Log node execution
            if kind == "on_chain_start" and name in ["director", "worker", "strategist"]:
                logger.info(f"  ▶️  Node '{name}' starting")
                # Broadcast log to frontend
                await manager.broadcast_to_run(run_id, {
                    "type": "log_message",
                    "payload": {
                        "message": f"Node '{name}' starting",
                        "level": "info",
                        "node": name,
                        "timestamp": datetime.now().isoformat()
                    }
                })
            
            if kind == "on_chain_end":
                # Log node completion
                if name in ["director", "worker", "strategist"]:
                    data = event["data"].get("output")
                    if data and isinstance(data, dict) and "tasks" in data:
                        logger.info(f"  ✅ Node '{name}' completed")
                        # Broadcast log to frontend
                        await manager.broadcast_to_run(run_id, {
                            "type": "log_message",
                            "payload": {
                                "message": f"Node '{name}' completed",
                                "level": "success",
                                "node": name,
                                    "timestamp": datetime.now().isoformat()
                            }
                        })
                
                # Check if it's the main graph end or a node end
                data = event["data"].get("output")
                if data and isinstance(data, dict) and "tasks" in data:
                    # Log task status changes
                    for task in data.get("tasks", []):
                        if isinstance(task, dict):
                            task_id = task.get("id", "")[:12]
                            status = task.get("status", "")
                            retry_count = task.get("retry_count", 0)
                            if status in ["active", "failed", "waiting_human", "complete"]:
                                logger.info(f"     Task {task_id}: {status} (retries: {retry_count})")
                    
                    # Update state
                    runs_index[run_id].update({
                        "status": "running" if data.get("strategy_status") != "complete" else "completed",
                        "updated_at": datetime.now().isoformat(),
                        "task_counts": {
                            "planned": len([t for t in data.get("tasks", []) if (isinstance(t, dict) and t.get("status") == "planned") or (not isinstance(t, dict) and getattr(t, "status", "") == "planned")]),
                            "completed": len([t for t in data.get("tasks", []) if (isinstance(t, dict) and t.get("status") == "complete") or (not isinstance(t, dict) and getattr(t, "status", "") == "complete")]),
                        }
                    })
                    
                    # Broadcast FULL state update (same as polling API)
                    # We fetch the latest state from the graph to ensure we send the complete list
                    # CRITICAL: We merge the event data (which is freshest) into the snapshot (which might be slightly stale)
                    try:
                        snapshot = await orchestrator.aget_state(run_config)
                        full_tasks = []
                        if snapshot and snapshot.values:
                            full_tasks = snapshot.values.get("tasks", [])
                        
                        # Create a map of existing tasks
                        task_map = {t.id if hasattr(t, "id") else t.get("id"): t for t in full_tasks}
                        
                        # Merge in the FRESH updates from the event
                        fresh_tasks = data.get("tasks", [])
                        for t in fresh_tasks:
                            t_id = t.get("id")
                            if t_id:
                                # If it's a dict, use it directly. If existing was object, replace it.
                                # The event data 't' is always a dict here because it comes from the event output
                                task_map[t_id] = t
                        
                        # Convert back to list
                        merged_tasks = list(task_map.values())
                        
                        # Convert to dicts if needed for serialization
                        serialized_tasks = [task_to_dict(t) if hasattr(t, "status") else t for t in merged_tasks]
                        
                        # Serialize task_memories (LLM conversations)
                        task_memories = {}
                        raw_memories = snapshot.values.get("task_memories", {})
                        for task_id, messages in raw_memories.items():
                            task_memories[task_id] = _serialize_messages(messages)
                        
                        await manager.broadcast_to_run(run_id, {
                            "type": "state_update",
                            "payload": {
                                "tasks": serialized_tasks,
                                "status": runs_index[run_id]["status"],
                                "task_counts": runs_index[run_id]["task_counts"],
                                "task_memories": task_memories
                            }
                        })
                    except Exception as e:
                        logger.error(f"Failed to broadcast full state: {e}")
                        # Fallback to partial update if fetch fails
                        await manager.broadcast_to_run(run_id, {
                            "type": "state_update",
                            "payload": {
                                "tasks": [worker_result_to_dict(t) if hasattr(t, "status") else t for t in data.get("tasks", [])],
                                "status": runs_index[run_id]["status"]
                            }
                        })
            
            elif kind == "on_chat_model_stream":
                # Optional: Stream tokens for logs
                pass
        
        logger.info(f"📡 Event stream ended ({event_count} events)")
                
    except Exception as e:
        logger.error(f"Run failed: {e}")
        import traceback
        traceback.print_exc()
        runs_index[run_id]["status"] = "failed"
        await manager.broadcast_to_run(run_id, {"type": "error", "payload": {"message": str(e)}})
    
    finally:
        # CRITICAL: Check if run is paused after stream ends
        # This detects interrupts that occur during execution
        try:
            snapshot = await orchestrator.aget_state(run_config)
            
            if snapshot.next:  # Graph is paused/interrupted
                runs_index[run_id]["status"] = "interrupted"
                logger.info(f"Run {run_id} paused for HITL intervention")
                
                # Extract interrupt data
                interrupt_data = {}
                if snapshot.tasks and len(snapshot.tasks) > 0 and snapshot.tasks[0].interrupts:
                    interrupt_data = snapshot.tasks[0].interrupts[0].value
                
                # CRITICAL: Persist interrupt data to state for server restart recovery
                if interrupt_data:
                    # Get current state and add interrupt data
                    current_state = snapshot.values.copy() if snapshot.values else {}
                    current_state["_interrupt_data"] = interrupt_data
                    
                    # Save to database with interrupt status
                    from run_persistence import save_run_state
                    await save_run_state(run_id, current_state, status="interrupted")
                    
                    # Also save to in-memory state
                    run_states[run_id] = current_state
                    
                    # Broadcast interrupt notification to frontend
                    await manager.broadcast_to_run(run_id, {
                        "type": "interrupted",
                        "payload": {
                            "status": "interrupted",
                            "data": interrupt_data
                        }
                    })
                else:
                    logger.warning(f"Run {run_id} paused but no interrupt data found. Snapshot next: {snapshot.next}")
                
                # Broadcast run list update
                await manager.broadcast({
                    "type": "run_list_update",
                    "payload": list(runs_index.values())
                })

            else:
                # Run actually completed
                logger.info(f"Run {run_id} completed successfully")
                
                # Broadcast run list update  
                await manager.broadcast({
                    "type": "run_list_update",
                    "payload": list(runs_index.values())
                })
                
        except Exception as e:
            logger.error(f"Error checking final state: {e}")

# Mount static files for production deployment (Option A)
# Only mount if the dist directory exists
import os as _os
from pathlib import Path as _Path

dist_path = _Path(__file__).parent.parent / "orchestrator-dashboard" / "dist"
if dist_path.exists():
    from fastapi.staticfiles import StaticFiles
    
    # Mount static files for all routes except /api and /ws
    app.mount("/", StaticFiles(directory=str(dist_path), html=True), name="static")
    logger.info(f"📦 Serving static files from {dist_path}")
else:
    logger.info("📦 No static files found. Run 'npm run build' in orchestrator-dashboard/ for production deployment.")

if __name__ == "__main__":
    import uvicorn
    
    # Allow configuration via environment variables
    host = _os.getenv("SERVER_HOST", "0.0.0.0")
    port = int(_os.getenv("SERVER_PORT", "8085"))
    
    logger.info(f"🚀 Starting server on {host}:{port}")
    uvicorn.run(app, host=host, port=port)
