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
from state import OrchestratorState
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
    # Query the DB for all threads using async checkpointer
    summaries = []
    
    try:
        # Ensure graph/checkpointer is initialized
        orchestrator = get_orchestrator_graph()
        logger.info("📊 /api/runs called - querying database...")
        # Get async connection from checkpointer
        conn = global_checkpointer.conn
        cursor = await conn.cursor()
        
        # Get distinct thread_ids
        await cursor.execute("SELECT DISTINCT thread_id FROM checkpoints")
        rows = await cursor.fetchall()
        thread_ids = [row[0] for row in rows]
        
        for thread_id in thread_ids:
            # Get latest state for this thread
            config = {"configurable": {"thread_id": thread_id}}
            state_snapshot = await orchestrator.aget_state(config)
            
            if state_snapshot and state_snapshot.values:
                state = state_snapshot.values
                
                # Extract info
                run_id = state.get("run_id", thread_id)
                objective = state.get("objective", "Unknown")
                
                strat_status = state.get("strategy_status", "progressing")
                
                # Check for interrupts/pauses
                is_interrupted = False
                if state_snapshot.tasks and len(state_snapshot.tasks) > 0 and state_snapshot.tasks[0].interrupts:
                     is_interrupted = True
                     
                if strat_status == "complete":
                    status = "completed"
                elif is_interrupted:
                    status = "waiting_human" # Or "interrupted", but waiting_human is more descriptive for queue
                elif strat_status == "paused_human_requested":
                    status = "paused"
                elif strat_status == "paused_infra_error":
                    status = "failed"
                elif strat_status == "blocked":
                    status = "blocked"
                elif strat_status == "stagnating":
                    status = "stagnating"
                else:
                    status = "running"
                
                created_at = state.get("created_at", "")
                updated_at = state.get("updated_at", "")
                
                tasks = state.get("tasks", [])
                task_counts = {
                    "planned": len([t for t in tasks if getattr(t, "status", "") == "planned"]),
                    "completed": len([t for t in tasks if getattr(t, "status", "") == "complete"]),
                    "failed": len([t for t in tasks if getattr(t, "status", "") == "failed"]),
                    "active": len([t for t in tasks if getattr(t, "status", "") == "active"]),
                }
                
                summaries.append(RunSummary(
                    run_id=run_id,
                    objective=objective,
                    status=status,
                    created_at=created_at,
                    updated_at=updated_at,
                    task_counts=task_counts,
                    tags=state.get("tags", []),
                    workspace_path=state.get("_workspace_path", "")
                ))
                
                # Also update runs_index for other endpoints
                runs_index[run_id] = {
                    "run_id": run_id,
                    "thread_id": thread_id,
                    "objective": objective,
                    "status": status,
                    "created_at": created_at,
                    "updated_at": updated_at,
                    "task_counts": task_counts,
                    "tags": state.get("tags", [])
                }
                
    except Exception as e:
        logger.error(f"Error listing runs: {e}")
    
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
    # Try to refresh from DB if not in memory
    if run_id not in runs_index:
        await list_runs()
        
    if run_id not in runs_index:
        raise HTTPException(status_code=404, detail="Run not found")
        
    # Retrieve latest state from graph
    run_data = runs_index[run_id]
    
    # Get detailed state from checkpointer
    # Get detailed state from checkpointer
    try:
        orchestrator = get_orchestrator_graph()
        config = {"configurable": {"thread_id": run_data["thread_id"]}}
        
        # Use aget_state to get the full snapshot including interrupts
        state_snapshot = await orchestrator.aget_state(config)
        
        interrupt_data = None
        if state_snapshot.tasks:
            # Check for interrupts in the tasks
            for task in state_snapshot.tasks:
                if task.interrupts:
                    # We assume the first interrupt holds our data
                    interrupt_data = task.interrupts[0].value
                    logger.info(f"🔍 Found interrupt in get_run: {interrupt_data}")
                    break
        
        if not interrupt_data:
            # Fallback: Check for tasks manually marked as waiting_human
            # This handles cases where we manually updated state but didn't create a LangGraph interrupt
            if state_snapshot and state_snapshot.values:
                tasks = state_snapshot.values.get("tasks", [])
                for t in tasks:
                    # Handle both dict and object access
                    status = t.get("status") if isinstance(t, dict) else getattr(t, "status", None)
                    task_id = t.get("id") if isinstance(t, dict) else getattr(t, "id", None)
                    
                    if status == "waiting_human" or status == TaskStatus.WAITING_HUMAN:
                        logger.info(f"🔍 Found waiting_human task in get_run: {task_id}")
                        interrupt_data = {
                            "task_id": task_id,
                            "tasks": [task_to_dict(t) if hasattr(t, "status") else t for t in tasks],
                            "reason": "Restored from persisted state"
                        }
                        break
        
        if not interrupt_data:
            logger.info("ℹ️ No interrupt data found in get_run")
        else:
            # Ensure it's added to the response
            run_data["interrupt_data"] = interrupt_data
            run_data["status"] = "interrupted" # Force status to interrupted if we found data
        
        if state_snapshot and state_snapshot.values:
            state = state_snapshot.values
            
            # Serialize task memories
            task_memories = {}
            raw_memories = state.get("task_memories", {})
            logger.info(f"🔍 get_run found task_memories for: {list(raw_memories.keys())}")
            for task_id, messages in raw_memories.items():
                task_memories[task_id] = _serialize_messages(messages)
            
            return {
                **run_data,
                "spec": state.get("spec", {}),
                "strategy_status": state.get("strategy_status", "active"),
                "tasks": [task_to_dict(t) if hasattr(t, "status") else t for t in state.get("tasks", [])],
                "insights": state.get("insights", []),
                "design_log": state.get("design_log", []),
                "guardian": state.get("guardian", {}),
                "workspace_path": state.get("_workspace_path", ""),
                "model_config": _serialize_orch_config(state.get("orch_config")),
                "task_memories": task_memories,
                "interrupt_data": interrupt_data  # Include persistent interrupt data
            }
    except Exception as e:
        logger.error(f"Error getting run details: {e}")
        import traceback
        traceback.print_exc()

    return {
        **run_data,
        "spec": {},
        "strategy_status": "active",
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
        orchestrator.update_state(config, {"replan_requested": True})
        
        logger.info(f"Replan requested for run {run_id}. Director will re-integrate pending tasks.")
        return {"status": "replan_requested"}
    except Exception as e:
        logger.error(f"Failed to set replan_requested flag: {e}")
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
                if has_real_interrupt:
                    # Natural interrupt (from interrupt() call) - use Command(resume=...)
                    logger.info(f"   Resuming via Command(resume=...) - natural interrupt")
                    command = Command(resume=resolution.model_dump())
                    await _stream_and_broadcast(orchestrator, command, config, run_id)
                else:
                    # Manual interrupt - store resolution in state and invoke normally
                    logger.info(f"   Resuming via state update - manual interrupt")
                    
                    # Store the pending resolution in graph state for director to process
                    await orchestrator.aupdate_state(config, {
                        "pending_resolution": resolution.model_dump()
                    })
                    
                    # Invoke graph normally (no Command) - director will pick up pending_resolution
                    await _stream_and_broadcast(orchestrator, None, config, run_id)
                
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
                
                # Only broadcast if we actually have interrupt data
                if interrupt_data:
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
        
        await _stream_and_broadcast(orchestrator, initial_state, run_config, run_id)

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
