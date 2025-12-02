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

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Add src to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from langgraph_definition import create_orchestrator
from config import OrchestratorConfig
from state import OrchestratorState
from git_manager import WorktreeManager, initialize_git_repo
from orchestrator_types import worker_result_to_dict, task_to_dict

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("server")

# =============================================================================
# TYPES
# =============================================================================

class CreateRunRequest(BaseModel):
    objective: str
    spec: Optional[Dict[str, Any]] = None
    tags: Optional[List[str]] = None

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
    action: str
    feedback: Optional[str] = None
    modified_criteria: Optional[List[str]] = None
    modified_description: Optional[str] = None
    input_data: Optional[Dict[str, Any]] = None

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

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)
        for run_id in list(self.subscriptions.keys()):
            if websocket in self.subscriptions[run_id]:
                self.subscriptions[run_id].remove(websocket)

    async def subscribe(self, websocket: WebSocket, run_id: str):
        if run_id not in self.subscriptions:
            self.subscriptions[run_id] = []
        if websocket not in self.subscriptions[run_id]:
            self.subscriptions[run_id].append(websocket)
            logger.info(f"Subscribed to {run_id}")

    async def unsubscribe(self, websocket: WebSocket, run_id: str):
        if run_id in self.subscriptions and websocket in self.subscriptions[run_id]:
            self.subscriptions[run_id].remove(websocket)

    async def broadcast(self, message: dict):
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                pass

    async def broadcast_to_run(self, run_id: str, message: dict):
        if run_id in self.subscriptions:
            for connection in self.subscriptions[run_id]:
                try:
                    await connection.send_json(message)
                except Exception:
                    pass

manager = ConnectionManager()

# =============================================================================
# APP SETUP
# =============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Starting Orchestrator Server")
    yield
    # Shutdown
    logger.info("Shutting down Orchestrator Server")

app = FastAPI(title="Agent Orchestrator API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # For dev only
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

# Global DB connection for querying
db_conn = None
global_checkpointer = None

def get_orchestrator_graph():
    global db_conn, global_checkpointer
    
    # We use sqlite for persistence to allow dashboard to see history
    from langgraph.checkpoint.sqlite import SqliteSaver
    import sqlite3
    
    # Ensure .gemini directory exists for db
    db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "orchestrator.db")
    
    # Keep connection open
    if db_conn is None:
        db_conn = sqlite3.connect(db_path, check_same_thread=False)
        
    if global_checkpointer is None:
        global_checkpointer = SqliteSaver(db_conn)
    
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

@app.get("/api/runs", response_model=List[RunSummary])
async def list_runs():
    # Query the DB for all threads
    # LangGraph SqliteSaver uses a 'checkpoints' table with 'thread_id' column
    summaries = []
    
    try:
        # Ensure graph/checkpointer is initialized
        get_orchestrator_graph()
        
        cursor = db_conn.cursor()
        # Get distinct thread_ids
        cursor.execute("SELECT DISTINCT thread_id FROM checkpoints")
        thread_ids = [row[0] for row in cursor.fetchall()]
        
        for thread_id in thread_ids:
            # Get latest state for this thread
            config = {"configurable": {"thread_id": thread_id}}
            state_snapshot = global_checkpointer.get(config)
            
            if state_snapshot and "channel_values" in state_snapshot:
                state = state_snapshot["channel_values"]
                
                # Extract info
                run_id = state.get("run_id", thread_id)
                objective = state.get("objective", "Unknown")
                
                strat_status = state.get("strategy_status", "progressing")
                if strat_status == "complete":
                    status = "completed"
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
    
    # Start the run in background
    background_tasks.add_task(run_orchestrator, run_id, thread_id, request.objective, request.spec)
    
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
    try:
        get_orchestrator_graph()
        config = {"configurable": {"thread_id": run_data["thread_id"]}}
        state_snapshot = global_checkpointer.get(config)
        if state_snapshot and "channel_values" in state_snapshot:
            state = state_snapshot["channel_values"]
            
            # Serialize task memories
            task_memories = {}
            raw_memories = state.get("task_memories", {})
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
                "task_memories": task_memories
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
        
        # Set pending_reorg flag - director will handle blocking and waiting
        orchestrator.update_state(config, {"pending_reorg": True})
        
        logger.info(f"Pending reorg flag set for run {run_id}. Director will block new tasks and wait for active tasks to complete.")
        return {"status": "reorg_pending"}
        
    except Exception as e:
        logger.error(f"Failed to set pending_reorg flag: {e}")
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

async def run_orchestrator(run_id: str, thread_id: str, objective: str, spec: dict = None):
    """
    Execute the orchestrator graph.
    """
    logger.info(f"Starting run {run_id}")
    
    import uuid
    from pathlib import Path
    from git_manager import WorktreeManager, initialize_git_repo
    
    # Setup workspace
    workspace = "projects/workspace"
    workspace_path = Path(workspace).resolve()
    workspace_path.mkdir(parents=True, exist_ok=True)
    
    # Initialize git
    initialize_git_repo(workspace_path)
    
    # Create worktree manager
    worktree_base = workspace_path / ".worktrees"
    worktree_base.mkdir(exist_ok=True)
    
    wt_manager = WorktreeManager(
        repo_path=workspace_path,
        worktree_base=worktree_base
    )
    
    # Create config
    config = OrchestratorConfig(mock_mode=False)
    
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
    
    try:
        # Stream events from the graph
        async for event in orchestrator.astream_events(initial_state, config=run_config, version="v1"):
            kind = event["event"]
            
            if kind == "on_chain_end":
                # Check if it's the main graph end or a node end
                data = event["data"].get("output")
                if data and isinstance(data, dict) and "tasks" in data:
                    # Update state
                    runs_index[run_id].update({
                        "status": "running" if data.get("strategy_status") != "complete" else "completed",
                        "updated_at": datetime.now().isoformat(),
                        "task_counts": {
                            "planned": len([t for t in data.get("tasks", []) if t.status == "planned"]),
                            "completed": len([t for t in data.get("tasks", []) if t.status == "complete"]),
                        }
                    })
                    
                    # Broadcast update
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
                
    except Exception as e:
        logger.error(f"Run failed: {e}")
        import traceback
        traceback.print_exc()
        runs_index[run_id]["status"] = "failed"
        await manager.broadcast_to_run(run_id, {"type": "error", "payload": {"message": str(e)}})

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8085)
