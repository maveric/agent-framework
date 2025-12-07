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

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Add src to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from langgraph_definition import create_orchestrator
from config import OrchestratorConfig
from state import OrchestratorState, tasks_reducer, task_memories_reducer, insights_reducer, design_log_reducer
from git_manager import WorktreeManager, initialize_git_repo
from orchestrator_types import worker_result_to_dict, task_to_dict, TaskStatus

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("server")

# Suppress noisy LangChain callback warnings about serialization
# These occur when our Pydantic models don't implement lc_serializable
# but don't affect functionality - purely cosmetic
logging.getLogger("langchain_core.callbacks.manager").setLevel(logging.ERROR)

# =============================================================================
# TYPES
# =============================================================================

class CreateRunRequest(BaseModel):
    objective: str
    spec: Optional[Dict[str, Any]] = None
    tags: Optional[List[str]] = None
    workspace: Optional[str] = None

class RunSummary(BaseModel):
    run_id: str
    objective: str
    status: str
    created_at: str
    updated_at: str
    task_counts: Dict[str, int]
    tags: List[str]
    workspace_path: Optional[str] = None

class HumanResolution(BaseModel):
    task_id: str
    action: str  # 'retry', 'abandon', or 'spawn_new_task'
    
    # For 'retry' action
    modified_description: Optional[str] = None
    modified_criteria: Optional[List[str]] = None
    
    # For 'spawn_new_task' action
    new_description: Optional[str] = None
    new_component: Optional[str] = None
    new_phase: Optional[str] = None
    new_worker_profile: Optional[str] = None
    new_criteria: Optional[List[str]] = None
    new_dependencies: Optional[List[str]] = None

# =============================================================================
# WEBSOCKET MANAGER
# =============================================================================

class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []
        self.subscriptions: Dict[str, List[WebSocket]] = {}  # run_id -> [websockets]

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"WebSocket connected. Total active: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        
        # Remove from subscriptions
        for run_id in list(self.subscriptions.keys()):
            if websocket in self.subscriptions[run_id]:
                self.subscriptions[run_id].remove(websocket)
                if not self.subscriptions[run_id]:
                    del self.subscriptions[run_id]
        logger.info(f"WebSocket disconnected. Total active: {len(self.active_connections)}")

    async def subscribe(self, websocket: WebSocket, run_id: str):
        if run_id not in self.subscriptions:
            self.subscriptions[run_id] = []
        if websocket not in self.subscriptions[run_id]:
            self.subscriptions[run_id].append(websocket)
            logger.info(f"Subscribed to {run_id}. Total subscribers: {len(self.subscriptions[run_id])}")
            
            # IMMEDIATELY send current state so client doesn't have to wait for next task update
            if run_id in runs_index:
                run_data = runs_index[run_id]
                try:
                    await websocket.send_json({
                        "type": "state_update",
                        "run_id": run_id,
                        "timestamp": datetime.now().isoformat(),
                        "payload": {
                            "status": run_data.get("status", "running"),
                            "task_counts": run_data.get("task_counts", {}),
                            "objective": run_data.get("objective", ""),
                        }
                    })
                except Exception as e:
                    logger.error(f"Error sending initial state: {e}")

    async def unsubscribe(self, websocket: WebSocket, run_id: str):
        if run_id in self.subscriptions and websocket in self.subscriptions[run_id]:
            self.subscriptions[run_id].remove(websocket)
            if not self.subscriptions[run_id]:
                del self.subscriptions[run_id]
            logger.info(f"Unsubscribed from {run_id}")

    async def broadcast(self, message: dict):
        # Inject timestamp if missing
        if "timestamp" not in message:
            message["timestamp"] = datetime.now().isoformat()
            
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception as e:
                logger.error(f"Error broadcasting message: {e}")

    async def broadcast_to_run(self, run_id: str, message: dict):
        # Inject run_id and timestamp if missing
        if "run_id" not in message:
            message["run_id"] = run_id
        if "timestamp" not in message:
            message["timestamp"] = datetime.now().isoformat()
            
        if run_id in self.subscriptions:
            for connection in self.subscriptions[run_id]:
                try:
                    await connection.send_json(message)
                except Exception as e:
                    logger.error(f"Error broadcasting to run {run_id}: {e}")

manager = ConnectionManager()

# =============================================================================
# APP SETUP
# =============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup - Initialize checkpointer
    global global_checkpointer
    
    try:
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
        import aiosqlite
        
        db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "orchestrator.db")
        logger.info(f"Initializing checkpointer with database: {db_path}")
        
        # Create async connection and checkpointer
        conn = await aiosqlite.connect(db_path)
        global_checkpointer = AsyncSqliteSaver(conn)
        
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

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("FRONTEND_URL", "*").split(",") if os.getenv("FRONTEND_URL") != "*" else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =============================================================================
# STATE MANAGEMENT
# =============================================================================

# In-memory storage for runs (in a real app, this would be a DB)
# We use the LangGraph checkpointing for the actual state, but we need an index
runs_index: Dict[str, Dict[str, Any]] = {}

# Track running background tasks for cancellation
running_tasks: Dict[str, Any] = {}  # run_id -> asyncio.Task

# Store full run states for restart capability
run_states: Dict[str, Dict[str, Any]] = {}  # run_id -> full state dict

# Global checkpointer (initialized at startup)
global_checkpointer = None

def get_orchestrator_graph():
    """Get the orchestrator graph. Checkpointer is initialized at startup."""
    if global_checkpointer is None:
        raise RuntimeError("Checkpointer not initialized - server startup may have failed")
    
    return create_orchestrator(checkpointer=global_checkpointer)

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

@app.get("/api/runs", response_model=List[RunSummary])
async def list_runs():
    """List all runs from database and merge with in-memory active runs."""
    from run_persistence import list_all_runs
    
    logger.info("📊 /api/runs called - querying database...")
    
    # Get runs from our custom table
    db_runs = await list_all_runs()
    
    # Convert to RunSummary objects
    summaries = []
    seen_run_ids = set()
    
    for run_data in db_runs:
        run_id = run_data.get("run_id")
        seen_run_ids.add(run_id)
        
        summaries.append(RunSummary(
            run_id=run_id,
            objective=run_data.get("objective", ""),
            status=run_data.get("status", "unknown"),
            created_at=run_data.get("created_at", ""),
            updated_at=run_data.get("updated_at", ""),
            task_counts=run_data.get("task_counts", {}),
            tags=run_data.get("tags", []),
            workspace_path=run_data.get("workspace_path", "")
        ))
        
        # Update runs_index for other endpoints
        if run_id not in runs_index:
            runs_index[run_id] = run_data
    
    # CRITICAL: Include active runs from in-memory runs_index
    # These may not be in the database yet
    for run_id, run_data in runs_index.items():
        if run_id not in seen_run_ids:
            summaries.append(RunSummary(
                run_id=run_data.get("run_id", run_id),
                objective=run_data.get("objective", ""),
                status=run_data.get("status", "running"),
                created_at=run_data.get("created_at", ""),
                updated_at=run_data.get("updated_at", ""),
                task_counts=run_data.get("task_counts", {}),
                tags=run_data.get("tags", []),
                workspace_path=run_data.get("workspace_path", "")
            ))
    
    # Sort by created_at descending (most recent first)
    summaries.sort(key=lambda x: x.created_at, reverse=True)
        
    return summaries


@app.post("/api/runs")
async def create_run(request: CreateRunRequest, background_tasks: BackgroundTasks):
    import uuid
    from datetime import datetime
    
    run_id = f"run_{uuid.uuid4().hex[:8]}"
    thread_id = str(uuid.uuid4())
    
    # Initialize run record
    runs_index[run_id] = {
        "run_id": run_id,
        "thread_id": thread_id,
        "objective": request.objective,
        "status": "running",
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat(),
        "task_counts": {"planned": 0, "completed": 0},
        "tags": request.tags or []
    }
    
    # Broadcast new run to all clients
    await manager.broadcast({
        "type": "run_list_update",
        "payload": list(runs_index.values())
    })
    
    # Start the run in background and track the task
    import asyncio
    task = asyncio.create_task(run_orchestrator(run_id, thread_id, request.objective, request.spec, request.workspace))
    running_tasks[run_id] = task
    
    # Cleanup task when done
    def cleanup_task(t):
        running_tasks.pop(run_id, None)
        logger.info(f"Cleaned up task for run {run_id}")
    
    task.add_done_callback(cleanup_task)
    
    return {"run_id": run_id}

def _serialize_messages(messages: List[Any]) -> List[Dict[str, Any]]:
    """Serialize LangChain messages to dicts."""
    if not messages:
        return []
    
    serialized = []
    for msg in messages:
        # If already a dict (from database), return as-is
        if isinstance(msg, dict):
            serialized.append(msg)
            continue
            
        # Basic fields
        m_dict = {
            "type": msg.type,
            "content": msg.content,
        }
        
        # Add specific fields based on type
        if hasattr(msg, "tool_calls") and msg.tool_calls:
            m_dict["tool_calls"] = msg.tool_calls
            
        if hasattr(msg, "tool_call_id"):
            m_dict["tool_call_id"] = msg.tool_call_id
            
        if hasattr(msg, "name") and msg.name:
            m_dict["name"] = msg.name
            
        serialized.append(m_dict)
        
    return serialized

@app.get("/api/runs/{run_id}")
async def get_run(run_id: str):
    from run_persistence import load_run_state
    
    # Try to refresh from DB if not in memory
    if run_id not in runs_index:
        await list_runs()
        
    if run_id not in runs_index:
        raise HTTPException(status_code=404, detail="Run not found")
        
    run_data = runs_index[run_id]
    
    # First try in-memory state
    state = run_states.get(run_id)
    
    # Fallback to database
    if not state:
        state = await load_run_state(run_id)
    
    if state:
        # Serialize task memories
        task_memories = {}
        raw_memories = state.get("task_memories", {})
        logger.info(f"🔍 get_run found task_memories for: {list(raw_memories.keys())}")
        for task_id, messages in raw_memories.items():
            task_memories[task_id] = _serialize_messages(messages)
        
        # Check for interrupt data - prioritize persisted data from state
        interrupt_data = None
        tasks = state.get("tasks", [])  # Define early since both branches need it
        
        # FIRST: Check for persisted interrupt data (most accurate after server restart)
        if "_interrupt_data" in state:
            logger.info(f"🔍 Found persisted _interrupt_data in state")
            persisted = state["_interrupt_data"]
            
            # Build full interrupt_data from persisted data
            task_id = persisted.get("task_id")
            interrupt_data = {
                "task_id": task_id,
                "task_description": persisted.get("task_description", ""),
                "acceptance_criteria": persisted.get("acceptance_criteria", []),
                "failure_reason": persisted.get("failure_reason", ""),
                "retry_count": persisted.get("retry_count", 0),
                "max_retries": persisted.get("max_retries", 3),
                "tasks": [task_to_dict(task) if hasattr(task, "status") else task for task in tasks],
                "reason": "Task requires human intervention"
            }
        
        # FALLBACK: Search for waiting_human tasks (for backwards compatibility)
        if not interrupt_data:

            for t in tasks:
                status = t.get("status") if isinstance(t, dict) else getattr(t, "status", None)
                task_id = t.get("id") if isinstance(t, dict) else getattr(t, "id", None)
                
                if status == "waiting_human" or status == TaskStatus.WAITING_HUMAN:
                    logger.info(f"🔍 Found waiting_human task in get_run: {task_id}")
                    
                    # Extract task details for the modal
                    task_dict = t if isinstance(t, dict) else task_to_dict(t)
                    
                    # Get blocked_reason or escalation for failure reason
                    failure_reason = ""
                    if task_dict.get("blocked_reason"):
                        blocked = task_dict["blocked_reason"]
                        if isinstance(blocked, dict):
                            failure_reason = blocked.get("reason", "")
                        else:
                            failure_reason = str(blocked)
                    
                    if task_dict.get("escalation"):
                        escalation = task_dict["escalation"]
                        if isinstance(escalation, dict):
                            failure_reason = escalation.get("reason", failure_reason)
                    
                    interrupt_data = {
                        "task_id": task_id,
                        "task_description": task_dict.get("description", ""),
                        "acceptance_criteria": task_dict.get("acceptance_criteria", []),
                        "failure_reason": failure_reason,
                        "retry_count": task_dict.get("retry_count", 0),
                        "max_retries": task_dict.get("max_retries", 3),
                        "tasks": [task_to_dict(task) if hasattr(task, "status") else task for task in tasks],
                        "reason": "Task requires human intervention"
                    }
                    break

        
        if not interrupt_data:
            logger.info("ℹ️ No interrupt data found in get_run")
        else:
            run_data["interrupt_data"] = interrupt_data
            run_data["status"] = "interrupted"
        
        return {
            **run_data,
            "spec": state.get("spec", {}),
            "strategy_status": state.get("strategy_status", "active"),
            "tasks": [task_to_dict(t) if hasattr(t, "status") else t for t in tasks],
            "insights": state.get("insights", []),
            "design_log": state.get("design_log", []),
            "guardian": state.get("guardian", {}),
            "workspace_path": state.get("_workspace_path", run_data.get("workspace_path", "")),
            "model_config": _serialize_orch_config(state.get("orch_config")),
            "task_memories": task_memories,
            "interrupt_data": interrupt_data
        }
    
    # No state found - return minimal data
    logger.warning(f"⚠️ No state found for run {run_id}")
    return {
        **run_data,
        "spec": {},
        "strategy_status": "unknown",
        "tasks": [],
        "insights": [],
        "design_log": [],
        "guardian": {},
        "task_memories": {}
    }


@app.post("/api/runs/{run_id}/pause")
async def pause_run(run_id: str):
    if run_id not in runs_index:
        raise HTTPException(status_code=404, detail="Run not found")
    runs_index[run_id]["status"] = "paused"
    await manager.broadcast_to_run(run_id, {"type": "state_update", "payload": {"status": "paused"}})
    return {"status": "paused"}

@app.post("/api/runs/{run_id}/resume")
async def resume_run(run_id: str):
    if run_id not in runs_index:
        raise HTTPException(status_code=404, detail="Run not found")
    runs_index[run_id]["status"] = "running"
    await manager.broadcast_to_run(run_id, {"type": "state_update", "payload": {"status": "running"}})
    return {"status": "running"}

@app.post("/api/runs/{run_id}/replan")
async def replan_run(run_id: str):
    """Trigger a re-planning of pending tasks."""
    if run_id not in runs_index:
        raise HTTPException(status_code=404, detail="Run not found")
    
    try:
        orchestrator = get_orchestrator_graph()
        config = {"configurable": {"thread_id": runs_index[run_id]["thread_id"]}}
        
        # Set replan_requested flag - director will handle blocking and waiting
        # Must use async version since this is an async function
        await orchestrator.aupdate_state(config, {"replan_requested": True})
        
        logger.info(f"Replan requested for run {run_id}. Director will re-integrate pending tasks.")
        return {"status": "replan_requested"}
    except Exception as e:
        logger.error(f"Failed to set replan_requested flag: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/runs/{run_id}/tasks/{task_id}/interrupt")
async def interrupt_task(run_id: str, task_id: str):
    """
    Force interrupt a specific task:
    1. Cancel the running orchestrator task
    2. Update the specific task status to WAITING_HUMAN
    3. Update run status to 'interrupted'
    """
    if run_id not in runs_index:
        raise HTTPException(status_code=404, detail="Run not found")
    
    # 1. Cancel the running task if it exists
    if run_id in running_tasks:
        logger.info(f"Force interrupting run {run_id} for task {task_id}")
        task = running_tasks[run_id]
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            logger.info(f"Run {run_id} cancelled successfully")
        except Exception as e:
            logger.error(f"Error cancelling run {run_id}: {e}")
            
    # 2. Update state to mark task as waiting_human
    try:
        orchestrator = get_orchestrator_graph()
        thread_id = runs_index[run_id]["thread_id"]
        config = {"configurable": {"thread_id": thread_id}}
        
        # Get current state
        current_state = await orchestrator.aget_state(config)
        if not current_state:
             raise HTTPException(status_code=404, detail="State not found")
             
        tasks = current_state.values.get("tasks", [])
        task_found = False
        
        # Modify the specific task
        updated_tasks = []
        for t in tasks:
            # Handle both object and dict representation
            t_id = t.id if hasattr(t, "id") else t.get("id")
            
            if t_id == task_id:
                logger.info(f"Marking task {task_id} as WAITING_HUMAN")
                task_found = True
                
                # Update status
                if hasattr(t, "status"):
                    t.status = TaskStatus.WAITING_HUMAN
                    t.updated_at = datetime.now()
                else:
                    t["status"] = "waiting_human"
                    t["updated_at"] = datetime.now().isoformat()
            
            updated_tasks.append(t)
            
        if not task_found:
            raise HTTPException(status_code=404, detail=f"Task {task_id} not found in state")
            
        # Persist the update
        # We update the 'tasks' key in the state
        # Note: We need to ensure we're passing the right format (dicts or objects) based on what the reducer expects.
        # The reducer expects a list of Task objects or dicts that it merges.
        # Since we are updating existing tasks, we should pass the modified list.
        
        # Convert all to dicts to be safe for the update
        tasks_payload = [task_to_dict(t) if hasattr(t, "status") else t for t in updated_tasks]
        
        await orchestrator.aupdate_state(config, {"tasks": tasks_payload})
        logger.info(f"State updated for run {run_id}")
        
        # 3. Build complete interrupt data matching server-initiated format
        # This needs to match what director.py line 370-381 creates
        interrupted_task_dict = next((t for t in tasks_payload if t.get("id") == task_id), None)
        if not interrupted_task_dict:
            raise HTTPException(status_code=500, detail="Task not found after update")
            
        interrupt_data = {
            "type": "manual_interrupt",
            "task_id": task_id,
            "task_description": interrupted_task_dict.get("description", ""),
            "component": interrupted_task_dict.get("component", ""),
            "phase": interrupted_task_dict.get("phase", "build"),
            "retry_count": interrupted_task_dict.get("retry_count", 0),
            "failure_reason": "Manually interrupted by user",
            "acceptance_criteria": interrupted_task_dict.get("acceptance_criteria", []),
            "assigned_worker_profile": interrupted_task_dict.get("assigned_worker_profile", "code_worker"),
            "depends_on": interrupted_task_dict.get("depends_on", [])
        }
        
        # Update run status and persist interrupt data
        runs_index[run_id]["status"] = "interrupted"
        runs_index[run_id]["interrupt_data"] = interrupt_data
        
        # Broadcast update - send BOTH state_update (for general UI) and interrupted (for modal)
        await manager.broadcast_to_run(run_id, {
            "type": "state_update", 
            "payload": {
                "status": "interrupted",
                "tasks": tasks_payload,
                "interrupt_data": interrupt_data
            }
        })
        
        await manager.broadcast_to_run(run_id, {
            "type": "interrupted", 
            "payload": {
                "status": "interrupted",
                "data": interrupt_data
            }
        })
        
        return {"status": "interrupted", "task_id": task_id}
        
    except Exception as e:
        logger.error(f"Error updating state for interrupt: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/runs/{run_id}/cancel")
async def cancel_run(run_id: str):
    """Cancel a running task."""
    from run_persistence import save_run_state
    
    if run_id not in runs_index:
        raise HTTPException(status_code=404, detail="Run not found")
    
    if run_id not in running_tasks:
        # Already completed or not running
        return {"status": runs_index[run_id].get("status", "unknown"), "message": "Run not active"}
    
    task = running_tasks[run_id]
    if task.done():
        return {"status": "already_completed"}
    
    # Cancel the task
    task.cancel()
    logger.warning(f"🛑 Cancelled run {run_id}")
    
    # Update status
    runs_index[run_id]["status"] = "cancelled"
    runs_index[run_id]["updated_at"] = datetime.now().isoformat()
    
    # Save cancelled state to database
    if run_id in run_states:
        await save_run_state(run_id, run_states[run_id], status="cancelled")
    
    # Broadcast cancellation
    await manager.broadcast_to_run(run_id, {
        "type": "cancelled",
        "payload": {"status": "cancelled", "message": "Run cancelled by user"}
    })
    
    # Broadcast run list update
    await manager.broadcast({
        "type": "run_list_update",
        "payload": list(runs_index.values())
    })
    
    return {"status": "cancelled", "run_id": run_id}


@app.post("/api/runs/{run_id}/restart")
async def restart_run(run_id: str):
    """Restart a stopped/crashed/cancelled run from its last state."""
    from run_persistence import load_run_state
    
    state = None
    
    # Try in-memory first
    if run_id in run_states:
        state = run_states[run_id]
    else:
        # Try database
        state = await load_run_state(run_id)
    
    if not state:
        if run_id not in runs_index:
            raise HTTPException(status_code=404, detail="Run not found - no state available to restart")
        return {"status": "error", "message": "No saved state available for restart. Run data exists but full state was lost."}
    
    # Check if already running
    if run_id in running_tasks and not running_tasks[run_id].done():
        return {"status": "already_running", "message": "Run is already active"}

    
    # Get workspace and thread info from state
    workspace_path = state.get("_workspace_path", "")
    thread_id = runs_index.get(run_id, {}).get("thread_id", f"thread_{run_id}")
    
    # Rebuild run_config
    run_config = {
        "configurable": {
            "thread_id": thread_id,
            "mock_mode": state.get("mock_mode", False)
        }
    }
    
    # Reset any 'active' tasks back to 'ready' so they get re-dispatched
    tasks = state.get("tasks", [])
    for task in tasks:
        if task.get("status") == "active":
            task["status"] = "ready"
            logger.info(f"  Reset active task {task.get('id')} to ready for restart")
    
    # Update status
    runs_index[run_id]["status"] = "running"
    runs_index[run_id]["updated_at"] = datetime.now().isoformat()
    
    logger.info(f"🔄 Restarting run {run_id}")
    
    # Create new background task for the dispatch loop
    task = asyncio.create_task(_continuous_dispatch_loop(run_id, state, run_config))
    running_tasks[run_id] = task
    
    # Cleanup when done
    def cleanup(t):
        logger.info(f"Cleaned up task for run {run_id}")
        if run_id in running_tasks:
            del running_tasks[run_id]
    
    task.add_done_callback(cleanup)
    
    # Broadcast update
    await manager.broadcast({
        "type": "run_list_update",
        "payload": list(runs_index.values())
    })
    
    return {"status": "restarted", "run_id": run_id, "message": "Run restarted from saved state"}

@app.get("/api/runs/{run_id}/interrupts")
async def get_interrupts(run_id: str):
    """Check if run is paused waiting for human input."""
    # Ensure run is in index (may be CLI-initiated)
    if not await ensure_run_in_index(run_id):
        raise HTTPException(status_code=404, detail="Run not found")
    
    try:
        orchestrator = get_orchestrator_graph()
        thread_id = runs_index[run_id]["thread_id"]
        config = {"configurable": {"thread_id": thread_id}}
        
        # Get current state snapshot (correct LangGraph API)
        snapshot = await orchestrator.aget_state(config)
        
        # Check if graph is paused (snapshot.next is non-empty when waiting)
        if snapshot.next:
            logger.info(f"⏸️  Run {run_id} is PAUSED (snapshot.next = {snapshot.next})")
            # Check for dynamic interrupt - this is where LangGraph stores interrupt() payloads
            # Based on user research and LangGraph docs
            if snapshot.tasks and len(snapshot.tasks) > 0 and snapshot.tasks[0].interrupts:
                # Extract the interrupt data we passed to interrupt()
                interrupt_data = snapshot.tasks[0].interrupts[0].value
                logger.info(f"   Found interrupt: task_id={interrupt_data.get('task_id')}, type={interrupt_data.get('type')}")
                return {
                    "interrupted": True,
                    "data": interrupt_data
                }
        
        return {"interrupted": False}
        
    except Exception as e:
        logger.error(f"Error checking interrupts: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/runs/{run_id}/resolve")
async def resolve_interrupt(run_id: str, resolution: HumanResolution, background_tasks: BackgroundTasks):
    """Resume execution with human decision."""
    # Ensure run is in index (may be CLI-initiated)
    if not await ensure_run_in_index(run_id):
        raise HTTPException(status_code=404, detail="Run not found")
    
    try:
        from langgraph.types import Command
        
        orchestrator = get_orchestrator_graph()
        thread_id = runs_index[run_id]["thread_id"]
        config = {"configurable": {"thread_id": thread_id}}
        
        # Check if there's a real interrupt in the graph (from interrupt() call)
        snapshot = await orchestrator.aget_state(config)
        has_real_interrupt = (
            snapshot and 
            snapshot.tasks and 
            len(snapshot.tasks) > 0 and 
            snapshot.tasks[0].interrupts
        )
        
        logger.info(f"▶️  Resuming run {run_id} with action '{resolution.action}'")
        logger.info(f"   Has real interrupt: {has_real_interrupt}")
        if resolution.action == "retry" and resolution.modified_description:
            logger.info(f"   Modified description: {resolution.modified_description[:100]}...")
        
        async def resume_execution():
            try:
                # CRITICAL: Always use continuous dispatch loop, not super-step mode
                # Load current state from database to continue where we left off
                from run_persistence import load_run_state
                
                state = await load_run_state(run_id)
                if not state:
                    logger.error(f"   No saved state found for run {run_id}")
                    return
                
                # Apply the resolution directly to state
                # The director will process it via pending_resolution
                state["pending_resolution"] = resolution.model_dump()
                
                logger.info(f"   Continuing dispatch loop with {len(state.get('tasks', []))} tasks")
                
                # Resume the continuous dispatch loop (not super-step mode!)
                await _continuous_dispatch_loop(run_id, state, config)
                
                logger.info(f"✅ Successfully resumed run {run_id} with action: {resolution.action}")

            except Exception as e:
                logger.error(f"❌ Error during resume execution: {e}")
                import traceback
                traceback.print_exc()
        
        background_tasks.add_task(resume_execution)
        
        return {"status": "resuming", "action": resolution.action}
        
    except Exception as e:
        logger.error(f"Error resuming run: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))




@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_json()
            if data.get("type") == "subscribe":
                await manager.subscribe(websocket, data.get("run_id"))
            elif data.get("type") == "unsubscribe":
                await manager.unsubscribe(websocket, data.get("run_id"))
    except WebSocketDisconnect:
        manager.disconnect(websocket)

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

# =============================================================================
# CONTINUOUS DISPATCH EXECUTION (Non-blocking worker dispatch)
# =============================================================================

async def _continuous_dispatch_loop(run_id: str, state: dict, run_config: dict):
    """
    Run the orchestrator with continuous task dispatch.
    
    Unlike LangGraph's superstep model which blocks until ALL workers complete,
    this loop dispatches workers as background tasks and immediately continues
    to check for newly-ready tasks.
    
    Flow:
        Director → spawn(workers) → poll completions → Director → spawn more...
    """
    from task_queue import TaskCompletionQueue
    from nodes.director import director_node
    from nodes.worker import worker_node
    from nodes.strategist import strategist_node
    from orchestrator_types import task_to_dict
    
    
    # Get max concurrent workers from config
    orch_config = state.get("orch_config")
    max_concurrent = getattr(orch_config, "max_concurrent_workers", 5) if orch_config else 5
    task_queue = TaskCompletionQueue(max_concurrent=max_concurrent)
    iteration = 0
    max_iterations = 500  # Safety limit
    
    logger.info(f"🚀 Starting continuous dispatch loop for run {run_id}")
    
    try:
        while iteration < max_iterations:
            # Reset activity flag for this cycle
            activity_occurred = False
            
            # ========== PHASE 1: Process completed workers ==========
            completed = task_queue.collect_completed()
            for c in completed:
                logger.info(f"  📥 Processing completed task: {c.task_id[:12]}")
                
                for task in state.get("tasks", []):
                    if task.get("id") == c.task_id:
                        if c.error:
                            task["status"] = "failed"
                            task["error"] = str(c.error)
                            logger.error(f"  ❌ Task {c.task_id[:12]} failed: {c.error}")
                        else:
                            # Worker returns state updates with modified task
                            if c.result and isinstance(c.result, dict):
                                # Find the updated task in the result
                                result_tasks = c.result.get("tasks", [])
                                for rt in result_tasks:
                                    if rt.get("id") == c.task_id:
                                        # Merge updates
                                        task.update(rt)
                                        break
                            # Merge tool outputs/messages to task_memories (for chat log in UI)
                                if "task_memories" in c.result:
                                    worker_memories = c.result["task_memories"]
                                    if worker_memories:
                                        # Apply reducer to preserve existing memories
                                        state["task_memories"] = task_memories_reducer(
                                            state.get("task_memories", {}), 
                                            worker_memories
                                        )

                                
                                logger.info(f"  ✅ Task {c.task_id[:12]} → {task.get('status')}")
                                
                                # Log files modified if any
                                if task.get("aar") and task["aar"].get("files_modified"):
                                    files = task["aar"]["files_modified"]
                                    logger.info(f"     📂 Modified {len(files)} file(s): {', '.join(files)}")
                                
                                # Activity occurred
                                activity_occurred = True
                        break
                
                # Save checkpoint to database after worker updates
                # TODO: Fix persistence - aupdate_state triggers old graph execution
                # if completed:
                #     try:
                #         orchestrator = get_orchestrator_graph()
                #         await orchestrator.aupdate_state(run_config, state, as_node="worker")
                #     except Exception as e:
                #         logger.error(f"Failed to save checkpoint: {e}")
                
                # Broadcast state update
                await _broadcast_state_update(run_id, state)
            
            # ========== PHASE 2: Run Director (evaluates readiness, creates tasks) ==========
            # Director modifies state directly
            director_result = await director_node(state, run_config)
            if director_result:
                # Only count as activity if meaningful state changed (ignore internal counters)
                meaningful_keys = ["tasks", "insights", "design_log", "replan_requested"]
                if any(key in director_result for key in meaningful_keys):
                    activity_occurred = True
                
                # Merge director updates into state (applying reducers)
                for key, value in director_result.items():
                    if key == "tasks":
                        state["tasks"] = tasks_reducer(state.get("tasks", []), value)
                    elif key == "task_memories":
                        state["task_memories"] = task_memories_reducer(state.get("task_memories", {}), value)
                    elif key == "insights":
                        state["insights"] = insights_reducer(state.get("insights", []), value)
                    elif key == "design_log":
                        state["design_log"] = design_log_reducer(state.get("design_log", []), value)
                    elif key != "_wt_manager":  # Don't overwrite internal objects
                        state[key] = value
                
                # TODO: Fix persistence - aupdate_state triggers old graph execution
                # try:
                #     orchestrator = get_orchestrator_graph()
                #     await orchestrator.aupdate_state(run_config, state, as_node="director")
                # except Exception as e:
                #     logger.error(f"Failed to save checkpoint: {e}")
            
            # ========== PHASE 3: Find and dispatch ready tasks ==========
            ready_tasks = [t for t in state.get("tasks", []) if t.get("status") == "ready"]
            
            # Dispatch ready tasks (up to available slots)
            dispatched = 0
            for task in ready_tasks[:task_queue.available_slots]:
                task_id = task.get("id")
                if task_queue.is_running(task_id):
                    continue  # Already running
                
                # Mark as active
                task["status"] = "active"
                task["started_at"] = datetime.now().isoformat()
                
                # Create worktree if needed
                wt_manager = state.get("_wt_manager")
                if wt_manager and not state.get("mock_mode", False):
                    try:
                        wt_manager.create_worktree(task_id)
                    except Exception as e:
                        logger.warning(f"Failed to create worktree: {e}")
                
                # Spawn worker as background task
                worker_state = {**state, "task_id": task_id}
                task_queue.spawn(task_id, worker_node(worker_state, run_config))
                dispatched += 1
                activity_occurred = True
                
                logger.info(f"  🚀 Dispatched: {task_id[:12]} ({task.get('assigned_worker_profile', 'unknown')})")
            
            if dispatched > 0:
                await _broadcast_state_update(run_id, state)
            
            # ========== PHASE 4: Run Strategist for QA (Test tasks or Awaiting QA) ==========
            # We need to run Strategist if:
            # 1. Task is explicitly AWAITING_QA (any phase)
            # 2. Task is TEST phase and COMPLETE but missing verdict (legacy check)
            tasks_requiring_qa = [t for t in state.get("tasks", []) 
                               if t.get("status") == "awaiting_qa" 
                               or (t.get("status") == "complete" and t.get("phase") == "test" and not t.get("qa_verdict"))]
            
            for task in tasks_requiring_qa:
                logger.info(f"  🔍 QA evaluating: {task.get('id', '')[:12]}")
                strategist_result = await strategist_node({**state, "task_id": task.get("id")}, run_config)
                if strategist_result:
                    activity_occurred = True
                    for key, value in strategist_result.items():
                        if key == "tasks":
                            # Update the specific task
                            for rt in value:
                                for t in state["tasks"]:
                                    if t.get("id") == rt.get("id"):
                                        t.update(rt)
                        elif key != "_wt_manager":
                            state[key] = value
                await _broadcast_state_update(run_id, state)
            
            # ========== PHASE 5: Check completion ==========
            all_tasks = state.get("tasks", [])
            
            # Exit conditions
            terminal_statuses = {"complete", "abandoned", "waiting_human"}
            all_terminal = all(t.get("status") in terminal_statuses for t in all_tasks) if all_tasks else False
            
            if all_terminal and not task_queue.has_work:
                logger.info(f"✅ All tasks complete! Ending run {run_id}")
                runs_index[run_id]["status"] = "completed"
                
                # Save completed state to database
                from run_persistence import save_run_state
                await save_run_state(run_id, state, status="completed")
                
                await _broadcast_state_update(run_id, state)
                break
            
            # Check for HITL interrupts
            waiting_human = [t for t in all_tasks if t.get("status") == "waiting_human"]
            if waiting_human and not task_queue.has_work:
                logger.info(f"⏸️  Run paused for human intervention")
                runs_index[run_id]["status"] = "interrupted"
                
                # Save interrupted state to database
                from run_persistence import save_run_state
                await save_run_state(run_id, state, status="interrupted")
                break
            
            # No work and no ready tasks? Check if we're stuck
            if not task_queue.has_work and not ready_tasks and not tasks_requiring_qa:
                # Check for planned tasks that might become ready
                planned = [t for t in all_tasks if t.get("status") == "planned"]
                
                # Also check for completed planners with suggestions that need integration
                # These are awaiting_qa but have suggested_tasks that Director needs to process
                awaiting_planners = [t for t in all_tasks 
                                    if t.get("status") == "awaiting_qa" 
                                    and t.get("assigned_worker_profile") == "planner_worker"
                                    and t.get("suggested_tasks")]
                
                if not planned and not awaiting_planners:
                    logger.warning(f"⚠️  No more work to do, but not all tasks complete")
                    break
                elif awaiting_planners:
                    logger.info(f"  📋 {len(awaiting_planners)} planners have suggestions pending integration")
                # Otherwise director will evaluate readiness on next cycle
            
            # ========== PHASE 6: Wait for completions ==========
            if task_queue.has_work:
                # Wait a bit for workers to complete
                await task_queue.wait_for_any(timeout=1.0)
            else:
                # Small delay to prevent tight loop
                await asyncio.sleep(0.1)
            
            # Only increment iteration if something actually happened
            # This prevents 500 max_iterations from being reached just by idling
            if activity_occurred:
                iteration += 1
            
            # Update run status
            runs_index[run_id].update({
                "status": "running",
                "updated_at": datetime.now().isoformat(),
                "task_counts": {
                    "planned": len([t for t in all_tasks if t.get("status") == "planned"]),
                    "active": len([t for t in all_tasks if t.get("status") == "active"]),
                    "completed": len([t for t in all_tasks if t.get("status") == "complete"]),
                    "failed": len([t for t in all_tasks if t.get("status") == "failed"]),
                }
            })
            
            # Save full state for restart capability (both in-memory and database)
            run_states[run_id] = state.copy()
            
            # Persist to database
            from run_persistence import save_run_state
            await save_run_state(run_id, state, status="running")
        
        if iteration >= max_iterations:
            logger.error(f"❌ Max iterations ({max_iterations}) reached for run {run_id}")
            runs_index[run_id]["status"] = "failed"
            
            # Save failed state to database
            from run_persistence import save_run_state
            await save_run_state(run_id, state, status="failed")
    
    except Exception as e:
        logger.error(f"❌ Continuous dispatch error: {e}")
        import traceback
        traceback.print_exc()
        runs_index[run_id]["status"] = "failed"
        
        # Save error state to database
        try:
            from run_persistence import save_run_state
            await save_run_state(run_id, state, status="failed")
        except Exception as e2:
            logger.error(f"Failed to save error checkpoint: {e2}")
        
        await manager.broadcast_to_run(run_id, {"type": "error", "payload": {"message": str(e)}})
    
    finally:
        # Cancel any remaining workers
        await task_queue.cancel_all()
        
        # Final broadcast
        await manager.broadcast({"type": "run_list_update", "payload": list(runs_index.values())})
        logger.info(f"🏁 Run {run_id} finished after {iteration} iterations")


async def _broadcast_state_update(run_id: str, state: dict):
    """Broadcast state update to connected clients."""
    try:
        serialized_tasks = [task_to_dict(t) if hasattr(t, "status") else t for t in state.get("tasks", [])]
        
        # Serialize task_memories (LLM conversations)
        task_memories = {}
        raw_memories = state.get("task_memories", {})
        for task_id, messages in raw_memories.items():
            task_memories[task_id] = _serialize_messages(messages)

        await manager.broadcast_to_run(run_id, {
            "type": "state_update",
            "payload": {
                "tasks": serialized_tasks,
                "status": runs_index[run_id].get("status", "running"),
                "task_counts": runs_index[run_id].get("task_counts", {}),
                "task_memories": task_memories
            }
        })
    except Exception as e:
        logger.error(f"Failed to broadcast state: {e}")


async def _execute_run_logic(run_id: str, thread_id: str, objective: str, spec: dict, workspace_path: Any):
    """Core execution logic for the run."""
    from pathlib import Path
    from git_manager import WorktreeManager, initialize_git_repo
    import subprocess
    import platform
    
    try:
        # Initialize git
        initialize_git_repo(workspace_path)
        
        # Create SHARED venv at workspace root (all worktrees will use this)
        venv_path = workspace_path / ".venv"
        if not venv_path.exists():
            logger.info(f"Creating shared venv at {venv_path}...")
            try:
                subprocess.run(
                    ["python", "-m", "venv", str(venv_path)],
                    cwd=str(workspace_path),
                    check=True,
                    capture_output=True,
                    timeout=120  # 2 minute timeout
                )
                logger.info(f"✅ Shared venv created at {venv_path}")
                
                # Install basic packages (requests for test harness pattern)
                pip_exe = venv_path / "Scripts" / "pip.exe" if platform.system() == "Windows" else venv_path / "bin" / "pip"
                if pip_exe.exists():
                    subprocess.run(
                        [str(pip_exe), "install", "requests"],
                        cwd=str(workspace_path),
                        capture_output=True,
                        timeout=120
                    )
                    logger.info(f"✅ Installed 'requests' in shared venv")
            except subprocess.TimeoutExpired:
                logger.warning(f"Venv creation timed out - agents may need to create manually")
            except subprocess.CalledProcessError as e:
                logger.warning(f"Venv creation failed: {e} - agents may need to create manually")
        else:
            logger.info(f"Shared venv already exists at {venv_path}")
    
        # Create config
        config = OrchestratorConfig(mock_mode=False)
        
        # Create worktree manager (Always enabled to match main.py behavior)
        worktree_base = workspace_path / ".worktrees"
        worktree_base.mkdir(exist_ok=True)
        
        wt_manager = WorktreeManager(
            repo_path=workspace_path,
            worktree_base=worktree_base
        )
        
        # Create graph
        orchestrator = get_orchestrator_graph()
        
        # Initial state
        initial_state = {
            "run_id": run_id,
            "objective": objective,
            "spec": spec or {},
            "tasks": [],
            "insights": [],
            "design_log": [],
            "task_memories": {},
            "filesystem_index": {},
            "guardian": {},
            "strategy_status": "progressing",
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
            "mock_mode": False,
            "_wt_manager": wt_manager,
            "_workspace_path": str(workspace_path),
            "orch_config": config,
        }
        
        run_config = {
            "configurable": {
                "thread_id": thread_id,
                "mock_mode": False
            }
        }
        
        # Use continuous dispatch (non-blocking worker execution)
        # instead of LangGraph's blocking superstep model
        await _continuous_dispatch_loop(run_id, initial_state, run_config)

    except Exception as e:
        logger.error(f"Critical error in run execution logic: {e}")
        import traceback
        traceback.print_exc()


async def run_orchestrator(run_id: str, thread_id: str, objective: str, spec: dict = None, workspace: str = None):
    """
    Execute the orchestrator graph.
    """
    logger.info(f"Starting run {run_id}")
    
    import uuid
    from pathlib import Path
    from git_manager import WorktreeManager, initialize_git_repo
    
    # Setup workspace
    if not workspace:
        workspace = "projects/workspace"
    
    workspace_path = Path(workspace).resolve()
    workspace_path.mkdir(parents=True, exist_ok=True)
    
    # Setup file logging for this run
    # This mimics main.py's logging behavior
    log_dir = workspace_path / "logs"
    log_dir.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = log_dir / f"run_{timestamp}.log"
    
    # Add file handler to root logger
    file_handler = logging.FileHandler(log_file, encoding='utf-8')
    file_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
    root_logger = logging.getLogger()
    root_logger.addHandler(file_handler)
    logger.info(f"📝 Logging run to: {log_file}")
    
    try:
        await _execute_run_logic(run_id, thread_id, objective, spec, workspace_path)
    finally:
        # Clean up file handler
        root_logger.removeHandler(file_handler)
        file_handler.close()
        logger.info(f"📝 Closed log file: {log_file}")

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
