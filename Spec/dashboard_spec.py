"""
Orchestrator Dashboard — API & Frontend Specification
======================================================
Version 1.0 — November 2025

A production-ready dashboard for monitoring orchestrator runs,
viewing task progress, and handling human-in-the-loop interactions.

Architecture:
- Backend: FastAPI + LangServe + WebSocket
- Frontend: React + TypeScript + TanStack Query + ReactFlow
- Persistence: SQLite (dev) / PostgreSQL (prod)

This document contains:
1. Backend API specification (FastAPI)
2. WebSocket streaming protocol
3. Frontend component structure
4. TypeScript interfaces
5. Human-in-the-loop workflows
"""

# =============================================================================
# PART 1: BACKEND API
# =============================================================================

"""
File Structure:
---------------
backend/
├── main.py                 # FastAPI app entry point
├── api/
│   ├── __init__.py
│   ├── runs.py            # Run management endpoints
│   ├── tasks.py           # Task endpoints
│   ├── hitl.py            # Human-in-the-loop endpoints
│   └── websocket.py       # WebSocket streaming
├── services/
│   ├── __init__.py
│   ├── orchestrator.py    # Orchestrator wrapper
│   └── state.py           # State queries
├── models/
│   ├── __init__.py
│   ├── requests.py        # Pydantic request models
│   └── responses.py       # Pydantic response models
└── config.py              # Configuration
"""

# -----------------------------------------------------------------------------
# backend/config.py
# -----------------------------------------------------------------------------

CONFIG_PY = '''
"""Application configuration."""
from pydantic_settings import BaseSettings
from typing import Literal
from functools import lru_cache


class Settings(BaseSettings):
    """App settings from environment variables."""
    
    # API
    app_name: str = "Orchestrator Dashboard"
    debug: bool = False
    api_prefix: str = "/api/v1"
    
    # CORS
    cors_origins: list[str] = ["http://localhost:3000", "http://localhost:5173"]
    
    # Database
    database_mode: Literal["sqlite", "postgres"] = "sqlite"
    database_url: str = "sqlite:///./orchestrator.db"
    
    # Orchestrator
    max_concurrent_workers: int = 3
    default_max_retries: int = 3
    
    # WebSocket
    ws_heartbeat_interval: int = 30  # seconds
    
    class Config:
        env_file = ".env"


@lru_cache()
def get_settings() -> Settings:
    return Settings()
'''

# -----------------------------------------------------------------------------
# backend/models/responses.py
# -----------------------------------------------------------------------------

RESPONSES_PY = '''
"""Pydantic models for API responses."""
from pydantic import BaseModel, Field
from typing import Any, Optional
from datetime import datetime
from enum import Enum


# === Enums (mirror orchestrator_types) ===

class TaskStatus(str, Enum):
    PLANNED = "planned"
    READY = "ready"
    BLOCKED = "blocked"
    ACTIVE = "active"
    AWAITING_QA = "awaiting_qa"
    FAILED_QA = "failed_qa"
    COMPLETE = "complete"
    WAITING_HUMAN = "waiting_human"
    ABANDONED = "abandoned"


class TaskPhase(str, Enum):
    PLAN = "plan"
    BUILD = "build"
    TEST = "test"


class StrategyStatus(str, Enum):
    PROGRESSING = "progressing"
    STAGNATING = "stagnating"
    BLOCKED = "blocked"
    PAUSED_INFRA_ERROR = "paused_infra_error"
    PAUSED_HUMAN_REQUESTED = "paused_human_requested"


# === Response Models ===

class TaskSummary(BaseModel):
    """Lightweight task for list views."""
    id: str
    component: str
    phase: TaskPhase
    status: TaskStatus
    description: str
    priority: int = 5
    retry_count: int = 0
    assigned_worker_profile: Optional[str] = None
    depends_on: list[str] = []
    
    
class TaskDetail(TaskSummary):
    """Full task details."""
    acceptance_criteria: list[str] = []
    result_path: Optional[str] = None
    qa_verdict: Optional[dict[str, Any]] = None
    aar: Optional[dict[str, Any]] = None
    escalation: Optional[dict[str, Any]] = None
    human_feedback: Optional[str] = None
    created_at: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None


class CriterionResultResponse(BaseModel):
    """Single criterion evaluation."""
    criterion: str
    passed: bool
    reasoning: str
    suggestions: Optional[str] = None


class QAVerdictResponse(BaseModel):
    """QA evaluation result."""
    passed: bool
    criterion_results: list[CriterionResultResponse] = []
    overall_feedback: str
    suggested_focus: Optional[str] = None
    tests_needing_revision: list[str] = []


class RunSummary(BaseModel):
    """Lightweight run for list views."""
    run_id: str
    objective: str
    status: StrategyStatus
    created_at: str
    updated_at: str
    task_counts: dict[str, int]  # status -> count


class RunDetail(BaseModel):
    """Full run state."""
    run_id: str
    objective: str
    spec: dict[str, Any]
    status: StrategyStatus
    tasks: list[TaskDetail]
    insights: list[dict[str, Any]] = []
    design_log: list[dict[str, Any]] = []
    created_at: str
    updated_at: str


class HumanQueueItem(BaseModel):
    """Task requiring human input."""
    run_id: str
    task: TaskDetail
    reason: str  # Why it needs human input
    options: list[str]  # Available actions
    context: dict[str, Any] = {}  # Additional context


class RunListResponse(BaseModel):
    """Paginated run list."""
    runs: list[RunSummary]
    total: int
    page: int
    page_size: int


class TaskGraphNode(BaseModel):
    """Node for DAG visualization."""
    id: str
    label: str
    status: TaskStatus
    phase: TaskPhase
    component: str


class TaskGraphEdge(BaseModel):
    """Edge for DAG visualization."""
    source: str
    target: str


class TaskGraphResponse(BaseModel):
    """Full graph for visualization."""
    nodes: list[TaskGraphNode]
    edges: list[TaskGraphEdge]


# === WebSocket Event Models ===

class WSEvent(BaseModel):
    """WebSocket event envelope."""
    event_type: str
    run_id: str
    timestamp: str
    data: dict[str, Any]


class TaskUpdateEvent(BaseModel):
    """Task status changed."""
    task_id: str
    old_status: Optional[TaskStatus]
    new_status: TaskStatus
    task: TaskSummary


class LogEvent(BaseModel):
    """Log message from node execution."""
    node: str  # director, worker, strategist, guardian
    level: str  # debug, info, warn, error
    message: str
    task_id: Optional[str] = None
'''

# -----------------------------------------------------------------------------
# backend/models/requests.py
# -----------------------------------------------------------------------------

REQUESTS_PY = '''
"""Pydantic models for API requests."""
from pydantic import BaseModel, Field
from typing import Any, Optional, Literal


class CreateRunRequest(BaseModel):
    """Start a new orchestrator run."""
    objective: str = Field(..., min_length=1, max_length=1000)
    spec: dict[str, Any] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)


class HumanResolutionRequest(BaseModel):
    """Human resolves a WAITING_HUMAN task."""
    action: Literal["approve", "reject", "modify", "retry", "abandon"]
    feedback: Optional[str] = None
    modified_criteria: Optional[list[str]] = None
    modified_description: Optional[str] = None
    additional_context: Optional[dict[str, Any]] = None


class PauseRunRequest(BaseModel):
    """Pause a running orchestrator."""
    reason: Optional[str] = None


class ResumeRunRequest(BaseModel):
    """Resume a paused orchestrator."""
    pass


class RetryTaskRequest(BaseModel):
    """Manually retry a failed task."""
    clear_memories: bool = True
    modified_criteria: Optional[list[str]] = None


class AddTaskRequest(BaseModel):
    """Manually add a task to a run."""
    component: str
    phase: Literal["plan", "build", "test"]
    description: str
    depends_on: list[str] = []
    acceptance_criteria: list[str] = []
    assigned_worker_profile: str = "code_worker"
    priority: int = 5


class UpdateTaskRequest(BaseModel):
    """Modify a task (only allowed for PLANNED/BLOCKED tasks)."""
    description: Optional[str] = None
    acceptance_criteria: Optional[list[str]] = None
    priority: Optional[int] = None
'''

# -----------------------------------------------------------------------------
# backend/services/orchestrator.py
# -----------------------------------------------------------------------------

ORCHESTRATOR_SERVICE_PY = '''
"""Orchestrator service wrapper."""
from typing import Any, AsyncIterator, Optional
from datetime import datetime
import asyncio
import uuid

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.checkpoint.postgres import PostgresSaver
from langchain_core.runnables import RunnableConfig

# Import from your orchestrator specs
from orchestrator_types import TaskStatus, StrategyStatus
from langgraph_definition import create_orchestrator, OrchestratorConfig

from config import get_settings


class OrchestratorService:
    """
    Singleton service managing the orchestrator instance.
    
    Handles:
    - Creating/resuming runs
    - State queries
    - Human-in-the-loop updates
    - Event streaming
    """
    
    _instance: Optional["OrchestratorService"] = None
    
    def __init__(self):
        settings = get_settings()
        
        # Create checkpointer based on config
        if settings.database_mode == "sqlite":
            self.checkpointer = SqliteSaver.from_conn_string(settings.database_url)
        else:
            self.checkpointer = PostgresSaver.from_conn_string(settings.database_url)
        
        # Create orchestrator config
        self.config = OrchestratorConfig(
            max_concurrent_workers=settings.max_concurrent_workers,
            default_max_retries=settings.default_max_retries,
        )
        
        # Compile orchestrator
        self.orchestrator = create_orchestrator(
            config=self.config,
            checkpoint_mode=settings.database_mode,
        )
        
        # Active run subscriptions (run_id -> set of queues)
        self._subscriptions: dict[str, set[asyncio.Queue]] = {}
    
    @classmethod
    def get_instance(cls) -> "OrchestratorService":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    # === RUN MANAGEMENT ===
    
    async def create_run(
        self,
        objective: str,
        spec: dict[str, Any],
        tags: list[str] = None
    ) -> str:
        """Start a new orchestrator run."""
        run_id = str(uuid.uuid4())
        
        initial_state = {
            "run_id": run_id,
            "objective": objective,
            "spec": spec,
            "design_log": [],
            "insights": [],
            "tasks": [],
            "task_memories": {},
            "filesystem_index": {},
            "guardian": {},
            "strategy_status": "progressing",
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
        }
        
        config = self._get_config(run_id, tags)
        
        # Start run in background
        asyncio.create_task(self._run_orchestrator(run_id, initial_state, config))
        
        return run_id
    
    async def _run_orchestrator(
        self,
        run_id: str,
        initial_state: dict[str, Any],
        config: RunnableConfig
    ):
        """Execute orchestrator and broadcast events."""
        try:
            async for event in self.orchestrator.astream_events(
                initial_state, config, version="v2"
            ):
                await self._broadcast_event(run_id, event)
        except Exception as e:
            await self._broadcast_event(run_id, {
                "event": "error",
                "data": {"error": str(e)}
            })
    
    async def resume_run(self, run_id: str) -> None:
        """Resume a paused run."""
        config = self._get_config(run_id)
        
        # Update status
        state = self.orchestrator.get_state(config)
        if state.values.get("strategy_status") in ["paused_human_requested", "paused_infra_error"]:
            self.orchestrator.update_state(config, {"strategy_status": "progressing"})
        
        # Resume in background
        asyncio.create_task(self._resume_orchestrator(run_id, config))
    
    async def _resume_orchestrator(self, run_id: str, config: RunnableConfig):
        """Continue orchestrator from checkpoint."""
        try:
            async for event in self.orchestrator.astream_events(None, config, version="v2"):
                await self._broadcast_event(run_id, event)
        except Exception as e:
            await self._broadcast_event(run_id, {
                "event": "error",
                "data": {"error": str(e)}
            })
    
    async def pause_run(self, run_id: str, reason: str = None) -> None:
        """Pause a running orchestrator."""
        config = self._get_config(run_id)
        update = {"strategy_status": "paused_human_requested"}
        if reason:
            update["pause_reason"] = reason
        self.orchestrator.update_state(config, update)
    
    # === STATE QUERIES ===
    
    def get_run_state(self, run_id: str) -> dict[str, Any]:
        """Get full state of a run."""
        config = self._get_config(run_id)
        state = self.orchestrator.get_state(config)
        return state.values if state else None
    
    def get_tasks(self, run_id: str) -> list[dict[str, Any]]:
        """Get tasks for a run."""
        state = self.get_run_state(run_id)
        return state.get("tasks", []) if state else []
    
    def get_task(self, run_id: str, task_id: str) -> Optional[dict[str, Any]]:
        """Get a specific task."""
        tasks = self.get_tasks(run_id)
        for task in tasks:
            if task["id"] == task_id:
                return task
        return None
    
    def get_waiting_human_tasks(self, run_id: str) -> list[dict[str, Any]]:
        """Get tasks needing human input."""
        tasks = self.get_tasks(run_id)
        return [t for t in tasks if t.get("status") == "waiting_human"]
    
    def list_runs(
        self,
        page: int = 1,
        page_size: int = 20,
        status_filter: str = None
    ) -> tuple[list[dict[str, Any]], int]:
        """
        List all runs with pagination.
        
        Returns: (runs, total_count)
        """
        # Query checkpointer for all thread configs
        # This is implementation-specific based on checkpointer
        # For SQLite, we'd query the checkpoints table
        
        # Simplified version - in production, query the DB directly
        all_runs = []
        
        # Get unique thread_ids from checkpointer
        # This would need to be implemented based on your checkpointer
        thread_ids = self._get_all_thread_ids()
        
        for thread_id in thread_ids:
            state = self.get_run_state(thread_id)
            if state:
                # Apply status filter
                if status_filter and state.get("strategy_status") != status_filter:
                    continue
                
                # Build summary
                tasks = state.get("tasks", [])
                task_counts = {}
                for task in tasks:
                    status = task.get("status", "planned")
                    task_counts[status] = task_counts.get(status, 0) + 1
                
                all_runs.append({
                    "run_id": thread_id,
                    "objective": state.get("objective", ""),
                    "status": state.get("strategy_status", "progressing"),
                    "created_at": state.get("created_at", ""),
                    "updated_at": state.get("updated_at", ""),
                    "task_counts": task_counts,
                })
        
        # Sort by updated_at desc
        all_runs.sort(key=lambda r: r["updated_at"], reverse=True)
        
        # Paginate
        total = len(all_runs)
        start = (page - 1) * page_size
        end = start + page_size
        
        return all_runs[start:end], total
    
    def _get_all_thread_ids(self) -> list[str]:
        """Get all thread IDs from checkpointer. Implementation-specific."""
        # For SQLite:
        # cursor.execute("SELECT DISTINCT thread_id FROM checkpoints")
        # return [row[0] for row in cursor.fetchall()]
        
        # Placeholder - implement based on your checkpointer
        return []
    
    # === HUMAN IN THE LOOP ===
    
    async def resolve_human_task(
        self,
        run_id: str,
        task_id: str,
        action: str,
        feedback: str = None,
        modified_criteria: list[str] = None,
        additional_context: dict = None
    ) -> dict[str, Any]:
        """
        Resolve a WAITING_HUMAN task.
        
        Actions:
        - approve: Mark ready, continue execution
        - reject: Abandon task
        - modify: Update criteria/description, mark ready
        - retry: Reset to ready with fresh context
        - abandon: Mark abandoned
        """
        config = self._get_config(run_id)
        state = self.orchestrator.get_state(config)
        tasks = state.values.get("tasks", [])
        
        task = None
        for t in tasks:
            if t["id"] == task_id:
                task = t
                break
        
        if not task:
            raise ValueError(f"Task {task_id} not found")
        
        if task["status"] != "waiting_human":
            raise ValueError(f"Task {task_id} is not waiting for human input")
        
        # Apply resolution
        if action == "approve":
            task["status"] = "ready"
            task["human_feedback"] = feedback
            
        elif action == "reject" or action == "abandon":
            task["status"] = "abandoned"
            task["abandon_reason"] = feedback or "Rejected by human"
            
        elif action == "modify":
            task["status"] = "ready"
            if modified_criteria:
                task["acceptance_criteria"] = modified_criteria
            if feedback:
                task["human_feedback"] = feedback
            if additional_context:
                task["human_context"] = additional_context
                
        elif action == "retry":
            task["status"] = "ready"
            task["retry_count"] = 0  # Reset retries
            task["human_feedback"] = feedback
            # Clear task memories for fresh start
            task_memories = state.values.get("task_memories", {})
            if task_id in task_memories:
                del task_memories[task_id]
        
        # Update state
        self.orchestrator.update_state(config, {"tasks": tasks})
        
        # Resume execution
        await self.resume_run(run_id)
        
        return task
    
    # === EVENT STREAMING ===
    
    async def subscribe(self, run_id: str) -> AsyncIterator[dict[str, Any]]:
        """Subscribe to events for a run."""
        queue: asyncio.Queue = asyncio.Queue()
        
        if run_id not in self._subscriptions:
            self._subscriptions[run_id] = set()
        self._subscriptions[run_id].add(queue)
        
        try:
            while True:
                event = await queue.get()
                yield event
        finally:
            self._subscriptions[run_id].discard(queue)
            if not self._subscriptions[run_id]:
                del self._subscriptions[run_id]
    
    async def _broadcast_event(self, run_id: str, event: dict[str, Any]):
        """Broadcast event to all subscribers."""
        if run_id not in self._subscriptions:
            return
        
        formatted_event = {
            "event_type": event.get("event", "unknown"),
            "run_id": run_id,
            "timestamp": datetime.now().isoformat(),
            "data": event.get("data", {}),
        }
        
        for queue in self._subscriptions[run_id]:
            await queue.put(formatted_event)
    
    # === HELPERS ===
    
    def _get_config(self, run_id: str, tags: list[str] = None) -> RunnableConfig:
        """Build LangGraph config for a run."""
        return {
            "configurable": {"thread_id": run_id},
            "metadata": {"run_id": run_id},
            "tags": tags or ["orchestrator"],
        }
'''

# -----------------------------------------------------------------------------
# backend/api/runs.py
# -----------------------------------------------------------------------------

RUNS_API_PY = '''
"""Run management endpoints."""
from fastapi import APIRouter, HTTPException, Query
from typing import Optional

from models.requests import CreateRunRequest, PauseRunRequest
from models.responses import (
    RunSummary, RunDetail, RunListResponse,
    TaskGraphResponse, TaskGraphNode, TaskGraphEdge
)
from services.orchestrator import OrchestratorService

router = APIRouter(prefix="/runs", tags=["runs"])


@router.get("", response_model=RunListResponse)
async def list_runs(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: Optional[str] = None
):
    """List all orchestrator runs."""
    service = OrchestratorService.get_instance()
    runs, total = service.list_runs(page, page_size, status)
    
    return RunListResponse(
        runs=[RunSummary(**r) for r in runs],
        total=total,
        page=page,
        page_size=page_size
    )


@router.post("", response_model=dict)
async def create_run(request: CreateRunRequest):
    """Start a new orchestrator run."""
    service = OrchestratorService.get_instance()
    run_id = await service.create_run(
        objective=request.objective,
        spec=request.spec,
        tags=request.tags
    )
    return {"run_id": run_id, "status": "started"}


@router.get("/{run_id}", response_model=RunDetail)
async def get_run(run_id: str):
    """Get full details of a run."""
    service = OrchestratorService.get_instance()
    state = service.get_run_state(run_id)
    
    if not state:
        raise HTTPException(status_code=404, detail="Run not found")
    
    return RunDetail(
        run_id=run_id,
        objective=state.get("objective", ""),
        spec=state.get("spec", {}),
        status=state.get("strategy_status", "progressing"),
        tasks=state.get("tasks", []),
        insights=state.get("insights", []),
        design_log=state.get("design_log", []),
        created_at=state.get("created_at", ""),
        updated_at=state.get("updated_at", ""),
    )


@router.post("/{run_id}/pause")
async def pause_run(run_id: str, request: PauseRunRequest = None):
    """Pause a running orchestrator."""
    service = OrchestratorService.get_instance()
    
    state = service.get_run_state(run_id)
    if not state:
        raise HTTPException(status_code=404, detail="Run not found")
    
    reason = request.reason if request else None
    await service.pause_run(run_id, reason)
    
    return {"status": "paused", "run_id": run_id}


@router.post("/{run_id}/resume")
async def resume_run(run_id: str):
    """Resume a paused orchestrator."""
    service = OrchestratorService.get_instance()
    
    state = service.get_run_state(run_id)
    if not state:
        raise HTTPException(status_code=404, detail="Run not found")
    
    await service.resume_run(run_id)
    
    return {"status": "resumed", "run_id": run_id}


@router.get("/{run_id}/graph", response_model=TaskGraphResponse)
async def get_task_graph(run_id: str):
    """Get task DAG for visualization."""
    service = OrchestratorService.get_instance()
    tasks = service.get_tasks(run_id)
    
    if not tasks:
        raise HTTPException(status_code=404, detail="Run not found")
    
    nodes = []
    edges = []
    
    for task in tasks:
        nodes.append(TaskGraphNode(
            id=task["id"],
            label=task.get("description", task["id"])[:50],
            status=task.get("status", "planned"),
            phase=task.get("phase", "build"),
            component=task.get("component", "unknown"),
        ))
        
        for dep in task.get("depends_on", []):
            edges.append(TaskGraphEdge(source=dep, target=task["id"]))
    
    return TaskGraphResponse(nodes=nodes, edges=edges)
'''

# -----------------------------------------------------------------------------
# backend/api/tasks.py
# -----------------------------------------------------------------------------

TASKS_API_PY = '''
"""Task endpoints."""
from fastapi import APIRouter, HTTPException
from typing import Optional

from models.requests import AddTaskRequest, UpdateTaskRequest, RetryTaskRequest
from models.responses import TaskSummary, TaskDetail
from services.orchestrator import OrchestratorService

router = APIRouter(prefix="/runs/{run_id}/tasks", tags=["tasks"])


@router.get("", response_model=list[TaskSummary])
async def list_tasks(run_id: str, status: Optional[str] = None):
    """List tasks for a run."""
    service = OrchestratorService.get_instance()
    tasks = service.get_tasks(run_id)
    
    if status:
        tasks = [t for t in tasks if t.get("status") == status]
    
    return [TaskSummary(**t) for t in tasks]


@router.get("/{task_id}", response_model=TaskDetail)
async def get_task(run_id: str, task_id: str):
    """Get task details."""
    service = OrchestratorService.get_instance()
    task = service.get_task(run_id, task_id)
    
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    
    return TaskDetail(**task)


@router.post("/{task_id}/retry")
async def retry_task(run_id: str, task_id: str, request: RetryTaskRequest = None):
    """Manually retry a failed task."""
    service = OrchestratorService.get_instance()
    task = service.get_task(run_id, task_id)
    
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    
    if task["status"] not in ["failed_qa", "abandoned"]:
        raise HTTPException(
            status_code=400, 
            detail=f"Cannot retry task in status {task['status']}"
        )
    
    # Reset task
    clear_memories = request.clear_memories if request else True
    await service.resolve_human_task(
        run_id=run_id,
        task_id=task_id,
        action="retry",
        modified_criteria=request.modified_criteria if request else None
    )
    
    return {"status": "retrying", "task_id": task_id}


@router.get("/{task_id}/logs")
async def get_task_logs(run_id: str, task_id: str):
    """Get execution logs for a task."""
    service = OrchestratorService.get_instance()
    state = service.get_run_state(run_id)
    
    if not state:
        raise HTTPException(status_code=404, detail="Run not found")
    
    # Get task memories (conversation history)
    memories = state.get("task_memories", {}).get(task_id, [])
    
    # Format as log entries
    logs = []
    for msg in memories:
        logs.append({
            "role": msg.type if hasattr(msg, "type") else "unknown",
            "content": msg.content if hasattr(msg, "content") else str(msg),
            "timestamp": getattr(msg, "timestamp", None),
        })
    
    return {"task_id": task_id, "logs": logs}


@router.get("/{task_id}/artifact")
async def get_task_artifact(run_id: str, task_id: str):
    """Get the artifact produced by a task."""
    service = OrchestratorService.get_instance()
    task = service.get_task(run_id, task_id)
    
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    
    result_path = task.get("result_path")
    if not result_path:
        raise HTTPException(status_code=404, detail="No artifact for this task")
    
    # Read artifact content
    try:
        with open(result_path, "r") as f:
            content = f.read()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read artifact: {e}")
    
    return {
        "task_id": task_id,
        "path": result_path,
        "content": content,
    }
'''

# -----------------------------------------------------------------------------
# backend/api/hitl.py
# -----------------------------------------------------------------------------

HITL_API_PY = '''
"""Human-in-the-loop endpoints."""
from fastapi import APIRouter, HTTPException

from models.requests import HumanResolutionRequest
from models.responses import HumanQueueItem, TaskDetail
from services.orchestrator import OrchestratorService

router = APIRouter(prefix="/hitl", tags=["human-in-the-loop"])


@router.get("/queue", response_model=list[HumanQueueItem])
async def get_human_queue():
    """Get all tasks across all runs needing human input."""
    service = OrchestratorService.get_instance()
    
    queue = []
    runs, _ = service.list_runs(page=1, page_size=1000)
    
    for run in runs:
        waiting_tasks = service.get_waiting_human_tasks(run["run_id"])
        
        for task in waiting_tasks:
            # Determine why it needs human input
            reason = "Unknown"
            options = ["approve", "reject", "modify"]
            
            if task.get("retry_count", 0) >= 3:
                reason = "Max retries exceeded"
                options = ["retry", "modify", "abandon"]
            elif task.get("escalation"):
                esc = task["escalation"]
                reason = f"Escalation: {esc.get('type', 'unknown')}"
                options = ["approve", "modify", "abandon"]
            elif task.get("status") == "waiting_human":
                reason = "Requires human decision"
            
            queue.append(HumanQueueItem(
                run_id=run["run_id"],
                task=TaskDetail(**task),
                reason=reason,
                options=options,
                context={
                    "objective": run.get("objective", ""),
                    "qa_verdict": task.get("qa_verdict"),
                    "aar": task.get("aar"),
                }
            ))
    
    return queue


@router.get("/queue/{run_id}", response_model=list[HumanQueueItem])
async def get_run_human_queue(run_id: str):
    """Get tasks needing human input for a specific run."""
    service = OrchestratorService.get_instance()
    
    state = service.get_run_state(run_id)
    if not state:
        raise HTTPException(status_code=404, detail="Run not found")
    
    waiting_tasks = service.get_waiting_human_tasks(run_id)
    
    queue = []
    for task in waiting_tasks:
        reason = "Unknown"
        options = ["approve", "reject", "modify"]
        
        if task.get("retry_count", 0) >= 3:
            reason = "Max retries exceeded"
            options = ["retry", "modify", "abandon"]
        elif task.get("escalation"):
            esc = task["escalation"]
            reason = f"Escalation: {esc.get('type', 'unknown')}"
        
        queue.append(HumanQueueItem(
            run_id=run_id,
            task=TaskDetail(**task),
            reason=reason,
            options=options,
            context={
                "objective": state.get("objective", ""),
                "qa_verdict": task.get("qa_verdict"),
            }
        ))
    
    return queue


@router.post("/resolve/{run_id}/{task_id}")
async def resolve_task(
    run_id: str,
    task_id: str,
    request: HumanResolutionRequest
):
    """Resolve a task waiting for human input."""
    service = OrchestratorService.get_instance()
    
    try:
        task = await service.resolve_human_task(
            run_id=run_id,
            task_id=task_id,
            action=request.action,
            feedback=request.feedback,
            modified_criteria=request.modified_criteria,
            additional_context=request.additional_context,
        )
        
        return {
            "status": "resolved",
            "action": request.action,
            "task": TaskDetail(**task),
        }
        
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
'''

# -----------------------------------------------------------------------------
# backend/api/websocket.py
# -----------------------------------------------------------------------------

WEBSOCKET_API_PY = '''
"""WebSocket streaming endpoints."""
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
import asyncio
import json

from services.orchestrator import OrchestratorService

router = APIRouter(tags=["websocket"])


@router.websocket("/ws/runs/{run_id}")
async def run_stream(websocket: WebSocket, run_id: str):
    """
    WebSocket endpoint for real-time run updates.
    
    Events:
    - task_update: Task status changed
    - node_start: Node began execution
    - node_end: Node finished execution
    - log: Log message from execution
    - error: Error occurred
    - heartbeat: Keep-alive ping
    """
    await websocket.accept()
    
    service = OrchestratorService.get_instance()
    
    # Verify run exists
    state = service.get_run_state(run_id)
    if not state:
        await websocket.close(code=4004, reason="Run not found")
        return
    
    # Send initial state
    await websocket.send_json({
        "event_type": "initial_state",
        "run_id": run_id,
        "data": {
            "status": state.get("strategy_status"),
            "tasks": state.get("tasks", []),
        }
    })
    
    # Start heartbeat task
    heartbeat_task = asyncio.create_task(heartbeat(websocket))
    
    try:
        # Subscribe to events
        async for event in service.subscribe(run_id):
            await websocket.send_json(event)
            
    except WebSocketDisconnect:
        pass
    finally:
        heartbeat_task.cancel()


async def heartbeat(websocket: WebSocket, interval: int = 30):
    """Send periodic heartbeat to keep connection alive."""
    while True:
        await asyncio.sleep(interval)
        try:
            await websocket.send_json({"event_type": "heartbeat"})
        except:
            break


@router.websocket("/ws/hitl")
async def hitl_stream(websocket: WebSocket):
    """
    WebSocket for human-in-the-loop notifications.
    
    Broadcasts when any task across any run needs human input.
    """
    await websocket.accept()
    
    service = OrchestratorService.get_instance()
    
    # Create a queue for this connection
    queue = asyncio.Queue()
    
    # Register for HITL events
    # This would need a separate subscription mechanism
    # For now, poll periodically
    
    heartbeat_task = asyncio.create_task(heartbeat(websocket))
    
    try:
        last_queue = []
        while True:
            # Poll for waiting tasks (in production, use event-driven)
            runs, _ = service.list_runs(page=1, page_size=1000)
            current_queue = []
            
            for run in runs:
                waiting = service.get_waiting_human_tasks(run["run_id"])
                for task in waiting:
                    current_queue.append({
                        "run_id": run["run_id"],
                        "task_id": task["id"],
                    })
            
            # Send new items
            new_items = [q for q in current_queue if q not in last_queue]
            if new_items:
                await websocket.send_json({
                    "event_type": "new_hitl_items",
                    "items": new_items,
                })
            
            last_queue = current_queue
            await asyncio.sleep(5)  # Poll every 5 seconds
            
    except WebSocketDisconnect:
        pass
    finally:
        heartbeat_task.cancel()
'''

# -----------------------------------------------------------------------------
# backend/main.py
# -----------------------------------------------------------------------------

MAIN_PY = '''
"""FastAPI application entry point."""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from config import get_settings
from api import runs, tasks, hitl, websocket
from services.orchestrator import OrchestratorService


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize services on startup."""
    # Initialize orchestrator service
    OrchestratorService.get_instance()
    yield
    # Cleanup on shutdown (if needed)


def create_app() -> FastAPI:
    settings = get_settings()
    
    app = FastAPI(
        title=settings.app_name,
        debug=settings.debug,
        lifespan=lifespan,
    )
    
    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    # Include routers
    app.include_router(runs.router, prefix=settings.api_prefix)
    app.include_router(tasks.router, prefix=settings.api_prefix)
    app.include_router(hitl.router, prefix=settings.api_prefix)
    app.include_router(websocket.router)
    
    @app.get("/health")
    async def health():
        return {"status": "healthy"}
    
    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
'''


# =============================================================================
# PART 2: FRONTEND SPECIFICATION
# =============================================================================

"""
Frontend File Structure:
------------------------
frontend/
├── src/
│   ├── api/
│   │   ├── client.ts          # Axios/fetch wrapper
│   │   ├── runs.ts            # Run API calls
│   │   ├── tasks.ts           # Task API calls
│   │   ├── hitl.ts            # HITL API calls
│   │   └── websocket.ts       # WebSocket manager
│   ├── components/
│   │   ├── layout/
│   │   │   ├── Sidebar.tsx
│   │   │   ├── Header.tsx
│   │   │   └── Layout.tsx
│   │   ├── runs/
│   │   │   ├── RunList.tsx
│   │   │   ├── RunCard.tsx
│   │   │   └── CreateRunModal.tsx
│   │   ├── tasks/
│   │   │   ├── TaskGraph.tsx      # DAG visualization
│   │   │   ├── TaskList.tsx
│   │   │   ├── TaskDetail.tsx
│   │   │   ├── TaskStatusBadge.tsx
│   │   │   └── ArtifactViewer.tsx
│   │   ├── hitl/
│   │   │   ├── HumanQueue.tsx
│   │   │   ├── ResolutionModal.tsx
│   │   │   └── QueueNotification.tsx
│   │   └── common/
│   │       ├── LogStream.tsx
│   │       ├── JsonViewer.tsx
│   │       └── LoadingSpinner.tsx
│   ├── hooks/
│   │   ├── useRuns.ts
│   │   ├── useTasks.ts
│   │   ├── useWebSocket.ts
│   │   └── useHitl.ts
│   ├── pages/
│   │   ├── Dashboard.tsx
│   │   ├── RunDetail.tsx
│   │   ├── HumanQueue.tsx
│   │   └── Settings.tsx
│   ├── types/
│   │   └── index.ts           # TypeScript interfaces
│   ├── utils/
│   │   └── formatters.ts
│   ├── App.tsx
│   └── main.tsx
├── package.json
└── vite.config.ts
"""

# -----------------------------------------------------------------------------
# frontend/src/types/index.ts
# -----------------------------------------------------------------------------

TYPES_TS = '''
// === Enums ===

export type TaskStatus =
  | "planned"
  | "ready"
  | "blocked"
  | "active"
  | "awaiting_qa"
  | "failed_qa"
  | "complete"
  | "waiting_human"
  | "abandoned";

export type TaskPhase = "plan" | "build" | "test";

export type StrategyStatus =
  | "progressing"
  | "stagnating"
  | "blocked"
  | "paused_infra_error"
  | "paused_human_requested";

export type HitlAction = "approve" | "reject" | "modify" | "retry" | "abandon";


// === Task Types ===

export interface TaskSummary {
  id: string;
  component: string;
  phase: TaskPhase;
  status: TaskStatus;
  description: string;
  priority: number;
  retry_count: number;
  assigned_worker_profile?: string;
  depends_on: string[];
}

export interface CriterionResult {
  criterion: string;
  passed: boolean;
  reasoning: string;
  suggestions?: string;
}

export interface QAVerdict {
  passed: boolean;
  criterion_results: CriterionResult[];
  overall_feedback: string;
  suggested_focus?: string;
  tests_needing_revision: string[];
}

export interface AAR {
  summary: string;
  approach: string;
  challenges: string[];
  decisions_made: string[];
  files_modified: string[];
  time_spent_estimate: string;
}

export interface TaskDetail extends TaskSummary {
  acceptance_criteria: string[];
  result_path?: string;
  qa_verdict?: QAVerdict;
  aar?: AAR;
  escalation?: {
    type: string;
    description: string;
    blocking: boolean;
  };
  human_feedback?: string;
  created_at?: string;
  started_at?: string;
  completed_at?: string;
}


// === Run Types ===

export interface TaskCounts {
  [status: string]: number;
}

export interface RunSummary {
  run_id: string;
  objective: string;
  status: StrategyStatus;
  created_at: string;
  updated_at: string;
  task_counts: TaskCounts;
}

export interface RunDetail {
  run_id: string;
  objective: string;
  spec: Record<string, unknown>;
  status: StrategyStatus;
  tasks: TaskDetail[];
  insights: Array<{ topic: string[]; summary: string }>;
  design_log: Array<{ area: string; summary: string; reason: string }>;
  created_at: string;
  updated_at: string;
}


// === Graph Types ===

export interface TaskGraphNode {
  id: string;
  label: string;
  status: TaskStatus;
  phase: TaskPhase;
  component: string;
}

export interface TaskGraphEdge {
  source: string;
  target: string;
}

export interface TaskGraph {
  nodes: TaskGraphNode[];
  edges: TaskGraphEdge[];
}


// === HITL Types ===

export interface HumanQueueItem {
  run_id: string;
  task: TaskDetail;
  reason: string;
  options: HitlAction[];
  context: {
    objective?: string;
    qa_verdict?: QAVerdict;
    aar?: AAR;
  };
}

export interface HumanResolutionRequest {
  action: HitlAction;
  feedback?: string;
  modified_criteria?: string[];
  modified_description?: string;
  additional_context?: Record<string, unknown>;
}


// === WebSocket Types ===

export interface WSEvent {
  event_type: string;
  run_id: string;
  timestamp: string;
  data: Record<string, unknown>;
}

export interface TaskUpdateEvent {
  task_id: string;
  old_status?: TaskStatus;
  new_status: TaskStatus;
  task: TaskSummary;
}
'''

# -----------------------------------------------------------------------------
# frontend/src/api/client.ts
# -----------------------------------------------------------------------------

API_CLIENT_TS = '''
import axios from "axios";

const API_BASE = import.meta.env.VITE_API_URL || "http://localhost:8000/api/v1";

export const apiClient = axios.create({
  baseURL: API_BASE,
  headers: {
    "Content-Type": "application/json",
  },
});

// Request interceptor for auth (if needed later)
apiClient.interceptors.request.use((config) => {
  // Add auth token if available
  // const token = localStorage.getItem("token");
  // if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

// Response interceptor for error handling
apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    console.error("API Error:", error.response?.data || error.message);
    return Promise.reject(error);
  }
);
'''

# -----------------------------------------------------------------------------
# frontend/src/api/runs.ts
# -----------------------------------------------------------------------------

RUNS_API_TS = '''
import { apiClient } from "./client";
import type { RunSummary, RunDetail, TaskGraph } from "../types";

export interface RunListResponse {
  runs: RunSummary[];
  total: number;
  page: number;
  page_size: number;
}

export interface CreateRunRequest {
  objective: string;
  spec?: Record<string, unknown>;
  tags?: string[];
}

export const runsApi = {
  list: async (page = 1, pageSize = 20, status?: string): Promise<RunListResponse> => {
    const params = new URLSearchParams({ page: String(page), page_size: String(pageSize) });
    if (status) params.append("status", status);
    const { data } = await apiClient.get(`/runs?${params}`);
    return data;
  },

  get: async (runId: string): Promise<RunDetail> => {
    const { data } = await apiClient.get(`/runs/${runId}`);
    return data;
  },

  create: async (request: CreateRunRequest): Promise<{ run_id: string }> => {
    const { data } = await apiClient.post("/runs", request);
    return data;
  },

  pause: async (runId: string, reason?: string): Promise<void> => {
    await apiClient.post(`/runs/${runId}/pause`, { reason });
  },

  resume: async (runId: string): Promise<void> => {
    await apiClient.post(`/runs/${runId}/resume`);
  },

  getGraph: async (runId: string): Promise<TaskGraph> => {
    const { data } = await apiClient.get(`/runs/${runId}/graph`);
    return data;
  },
};
'''

# -----------------------------------------------------------------------------
# frontend/src/api/hitl.ts
# -----------------------------------------------------------------------------

HITL_API_TS = '''
import { apiClient } from "./client";
import type { HumanQueueItem, HumanResolutionRequest, TaskDetail } from "../types";

export const hitlApi = {
  getQueue: async (): Promise<HumanQueueItem[]> => {
    const { data } = await apiClient.get("/hitl/queue");
    return data;
  },

  getRunQueue: async (runId: string): Promise<HumanQueueItem[]> => {
    const { data } = await apiClient.get(`/hitl/queue/${runId}`);
    return data;
  },

  resolve: async (
    runId: string,
    taskId: string,
    request: HumanResolutionRequest
  ): Promise<{ status: string; action: string; task: TaskDetail }> => {
    const { data } = await apiClient.post(`/hitl/resolve/${runId}/${taskId}`, request);
    return data;
  },
};
'''

# -----------------------------------------------------------------------------
# frontend/src/api/websocket.ts
# -----------------------------------------------------------------------------

WEBSOCKET_TS = '''
import { WSEvent } from "../types";

const WS_BASE = import.meta.env.VITE_WS_URL || "ws://localhost:8000";

type EventHandler = (event: WSEvent) => void;

export class WebSocketManager {
  private ws: WebSocket | null = null;
  private handlers: Set<EventHandler> = new Set();
  private reconnectAttempts = 0;
  private maxReconnectAttempts = 5;
  private reconnectDelay = 1000;
  private runId: string | null = null;

  connect(runId: string): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.disconnect();
    }

    this.runId = runId;
    this.ws = new WebSocket(`${WS_BASE}/ws/runs/${runId}`);

    this.ws.onopen = () => {
      console.log("WebSocket connected");
      this.reconnectAttempts = 0;
    };

    this.ws.onmessage = (event) => {
      const data: WSEvent = JSON.parse(event.data);
      this.handlers.forEach((handler) => handler(data));
    };

    this.ws.onclose = () => {
      console.log("WebSocket disconnected");
      this.attemptReconnect();
    };

    this.ws.onerror = (error) => {
      console.error("WebSocket error:", error);
    };
  }

  disconnect(): void {
    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }
    this.runId = null;
  }

  subscribe(handler: EventHandler): () => void {
    this.handlers.add(handler);
    return () => this.handlers.delete(handler);
  }

  private attemptReconnect(): void {
    if (this.reconnectAttempts >= this.maxReconnectAttempts || !this.runId) {
      return;
    }

    this.reconnectAttempts++;
    const delay = this.reconnectDelay * Math.pow(2, this.reconnectAttempts - 1);

    console.log(`Reconnecting in ${delay}ms (attempt ${this.reconnectAttempts})`);

    setTimeout(() => {
      if (this.runId) {
        this.connect(this.runId);
      }
    }, delay);
  }
}

export const wsManager = new WebSocketManager();
'''

# -----------------------------------------------------------------------------
# frontend/src/hooks/useWebSocket.ts
# -----------------------------------------------------------------------------

USE_WEBSOCKET_TS = '''
import { useEffect, useState, useCallback } from "react";
import { wsManager } from "../api/websocket";
import type { WSEvent, TaskSummary } from "../types";

interface UseWebSocketResult {
  connected: boolean;
  lastEvent: WSEvent | null;
  tasks: TaskSummary[];
}

export function useWebSocket(runId: string | null): UseWebSocketResult {
  const [connected, setConnected] = useState(false);
  const [lastEvent, setLastEvent] = useState<WSEvent | null>(null);
  const [tasks, setTasks] = useState<TaskSummary[]>([]);

  useEffect(() => {
    if (!runId) return;

    wsManager.connect(runId);

    const unsubscribe = wsManager.subscribe((event) => {
      setLastEvent(event);

      switch (event.event_type) {
        case "initial_state":
          setConnected(true);
          if (event.data.tasks) {
            setTasks(event.data.tasks as TaskSummary[]);
          }
          break;

        case "task_update":
          const update = event.data as { task: TaskSummary };
          setTasks((prev) =>
            prev.map((t) => (t.id === update.task.id ? update.task : t))
          );
          break;

        case "heartbeat":
          // Keep-alive, no action needed
          break;

        default:
          console.log("Unknown event:", event.event_type);
      }
    });

    return () => {
      unsubscribe();
      wsManager.disconnect();
      setConnected(false);
    };
  }, [runId]);

  return { connected, lastEvent, tasks };
}
'''

# -----------------------------------------------------------------------------
# frontend/src/components/tasks/TaskGraph.tsx
# -----------------------------------------------------------------------------

TASK_GRAPH_TSX = '''
import { useCallback, useMemo } from "react";
import ReactFlow, {
  Node,
  Edge,
  Background,
  Controls,
  MiniMap,
  useNodesState,
  useEdgesState,
} from "reactflow";
import dagre from "dagre";
import "reactflow/dist/style.css";

import type { TaskGraph as TaskGraphType, TaskStatus, TaskPhase } from "../../types";

// Status -> color mapping
const statusColors: Record<TaskStatus, string> = {
  planned: "#9CA3AF",      // gray
  ready: "#3B82F6",        // blue
  blocked: "#F59E0B",      // amber
  active: "#8B5CF6",       // purple
  awaiting_qa: "#F97316",  // orange
  failed_qa: "#EF4444",    // red
  complete: "#10B981",     // green
  waiting_human: "#EC4899", // pink
  abandoned: "#6B7280",    // gray-500
};

// Phase -> shape mapping (for visual distinction)
const phaseStyles: Record<TaskPhase, React.CSSProperties> = {
  plan: { borderRadius: "50%" },      // circle
  build: { borderRadius: "4px" },     // square
  test: { borderRadius: "4px", transform: "rotate(45deg)" }, // diamond-ish
};

interface TaskGraphProps {
  graph: TaskGraphType;
  onNodeClick?: (taskId: string) => void;
}

export function TaskGraph({ graph, onNodeClick }: TaskGraphProps) {
  // Layout using dagre
  const { nodes: layoutNodes, edges: layoutEdges } = useMemo(() => {
    const dagreGraph = new dagre.graphlib.Graph();
    dagreGraph.setDefaultEdgeLabel(() => ({}));
    dagreGraph.setGraph({ rankdir: "LR", nodesep: 50, ranksep: 100 });

    // Add nodes
    graph.nodes.forEach((node) => {
      dagreGraph.setNode(node.id, { width: 180, height: 60 });
    });

    // Add edges
    graph.edges.forEach((edge) => {
      dagreGraph.setEdge(edge.source, edge.target);
    });

    // Calculate layout
    dagre.layout(dagreGraph);

    // Convert to ReactFlow format
    const nodes: Node[] = graph.nodes.map((node) => {
      const position = dagreGraph.node(node.id);
      return {
        id: node.id,
        position: { x: position.x - 90, y: position.y - 30 },
        data: {
          label: node.label,
          status: node.status,
          phase: node.phase,
          component: node.component,
        },
        style: {
          backgroundColor: statusColors[node.status],
          color: "white",
          padding: "8px 12px",
          fontSize: "12px",
          fontWeight: 500,
          minWidth: "160px",
          textAlign: "center" as const,
          border: "2px solid white",
          boxShadow: "0 2px 4px rgba(0,0,0,0.2)",
          ...phaseStyles[node.phase],
        },
      };
    });

    const edges: Edge[] = graph.edges.map((edge, i) => ({
      id: `e-${i}`,
      source: edge.source,
      target: edge.target,
      animated: false,
      style: { stroke: "#9CA3AF" },
    }));

    return { nodes, edges };
  }, [graph]);

  const [nodes, , onNodesChange] = useNodesState(layoutNodes);
  const [edges, , onEdgesChange] = useEdgesState(layoutEdges);

  const handleNodeClick = useCallback(
    (_: React.MouseEvent, node: Node) => {
      onNodeClick?.(node.id);
    },
    [onNodeClick]
  );

  return (
    <div style={{ width: "100%", height: "500px" }}>
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onNodeClick={handleNodeClick}
        fitView
        attributionPosition="bottom-left"
      >
        <Background />
        <Controls />
        <MiniMap
          nodeColor={(node) => statusColors[node.data.status as TaskStatus]}
          maskColor="rgba(0, 0, 0, 0.1)"
        />
      </ReactFlow>
    </div>
  );
}
'''

# -----------------------------------------------------------------------------
# frontend/src/components/hitl/HumanQueue.tsx
# -----------------------------------------------------------------------------

HUMAN_QUEUE_TSX = '''
import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { hitlApi } from "../../api/hitl";
import type { HumanQueueItem, HitlAction, HumanResolutionRequest } from "../../types";
import { TaskStatusBadge } from "../tasks/TaskStatusBadge";
import { ResolutionModal } from "./ResolutionModal";

export function HumanQueue() {
  const queryClient = useQueryClient();
  const [selectedItem, setSelectedItem] = useState<HumanQueueItem | null>(null);

  const { data: queue = [], isLoading } = useQuery({
    queryKey: ["hitl-queue"],
    queryFn: () => hitlApi.getQueue(),
    refetchInterval: 10000, // Poll every 10s
  });

  const resolveMutation = useMutation({
    mutationFn: ({
      runId,
      taskId,
      request,
    }: {
      runId: string;
      taskId: string;
      request: HumanResolutionRequest;
    }) => hitlApi.resolve(runId, taskId, request),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["hitl-queue"] });
      setSelectedItem(null);
    },
  });

  const handleResolve = (action: HitlAction, feedback?: string, modifiedCriteria?: string[]) => {
    if (!selectedItem) return;

    resolveMutation.mutate({
      runId: selectedItem.run_id,
      taskId: selectedItem.task.id,
      request: {
        action,
        feedback,
        modified_criteria: modifiedCriteria,
      },
    });
  };

  if (isLoading) {
    return <div className="p-4">Loading queue...</div>;
  }

  if (queue.length === 0) {
    return (
      <div className="p-8 text-center text-gray-500">
        <div className="text-4xl mb-2">✓</div>
        <div>No tasks requiring human input</div>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <h2 className="text-xl font-semibold">Human Input Required ({queue.length})</h2>

      <div className="space-y-3">
        {queue.map((item) => (
          <div
            key={`${item.run_id}-${item.task.id}`}
            className="border rounded-lg p-4 bg-white shadow-sm hover:shadow-md transition-shadow cursor-pointer"
            onClick={() => setSelectedItem(item)}
          >
            <div className="flex items-start justify-between">
              <div className="flex-1">
                <div className="flex items-center gap-2 mb-1">
                  <span className="font-medium">{item.task.id}</span>
                  <TaskStatusBadge status={item.task.status} />
                </div>
                <p className="text-sm text-gray-600 mb-2">{item.task.description}</p>
                <div className="text-sm">
                  <span className="text-amber-600 font-medium">{item.reason}</span>
                </div>
              </div>
              <div className="flex gap-2">
                {item.options.map((action) => (
                  <button
                    key={action}
                    className={`px-3 py-1 rounded text-sm font-medium ${
                      action === "approve"
                        ? "bg-green-100 text-green-700 hover:bg-green-200"
                        : action === "reject" || action === "abandon"
                        ? "bg-red-100 text-red-700 hover:bg-red-200"
                        : "bg-blue-100 text-blue-700 hover:bg-blue-200"
                    }`}
                    onClick={(e) => {
                      e.stopPropagation();
                      if (action === "approve") {
                        handleResolve(action);
                      } else {
                        setSelectedItem(item);
                      }
                    }}
                  >
                    {action.charAt(0).toUpperCase() + action.slice(1)}
                  </button>
                ))}
              </div>
            </div>
          </div>
        ))}
      </div>

      {selectedItem && (
        <ResolutionModal
          item={selectedItem}
          onClose={() => setSelectedItem(null)}
          onResolve={handleResolve}
          isLoading={resolveMutation.isPending}
        />
      )}
    </div>
  );
}
'''

# -----------------------------------------------------------------------------
# frontend/src/components/hitl/ResolutionModal.tsx
# -----------------------------------------------------------------------------

RESOLUTION_MODAL_TSX = '''
import { useState } from "react";
import type { HumanQueueItem, HitlAction } from "../../types";

interface ResolutionModalProps {
  item: HumanQueueItem;
  onClose: () => void;
  onResolve: (action: HitlAction, feedback?: string, modifiedCriteria?: string[]) => void;
  isLoading: boolean;
}

export function ResolutionModal({ item, onClose, onResolve, isLoading }: ResolutionModalProps) {
  const [action, setAction] = useState<HitlAction>(item.options[0]);
  const [feedback, setFeedback] = useState("");
  const [criteria, setCriteria] = useState(item.task.acceptance_criteria.join("\\n"));

  const handleSubmit = () => {
    const modifiedCriteria = action === "modify" ? criteria.split("\\n").filter(Boolean) : undefined;
    onResolve(action, feedback || undefined, modifiedCriteria);
  };

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-white rounded-lg shadow-xl max-w-2xl w-full mx-4 max-h-[90vh] overflow-y-auto">
        {/* Header */}
        <div className="p-4 border-b">
          <h3 className="text-lg font-semibold">Resolve: {item.task.id}</h3>
          <p className="text-sm text-gray-500">{item.task.description}</p>
        </div>

        {/* Context */}
        <div className="p-4 bg-gray-50 border-b">
          <div className="text-sm">
            <div className="font-medium text-amber-600 mb-2">{item.reason}</div>
            {item.context.qa_verdict && (
              <div className="mt-2">
                <div className="font-medium">QA Feedback:</div>
                <div className="text-gray-600">{item.context.qa_verdict.overall_feedback}</div>
              </div>
            )}
          </div>
        </div>

        {/* Form */}
        <div className="p-4 space-y-4">
          {/* Action selector */}
          <div>
            <label className="block text-sm font-medium mb-1">Action</label>
            <select
              value={action}
              onChange={(e) => setAction(e.target.value as HitlAction)}
              className="w-full border rounded px-3 py-2"
            >
              {item.options.map((opt) => (
                <option key={opt} value={opt}>
                  {opt.charAt(0).toUpperCase() + opt.slice(1)}
                </option>
              ))}
            </select>
          </div>

          {/* Feedback */}
          <div>
            <label className="block text-sm font-medium mb-1">Feedback (optional)</label>
            <textarea
              value={feedback}
              onChange={(e) => setFeedback(e.target.value)}
              className="w-full border rounded px-3 py-2 h-24"
              placeholder="Add any notes or guidance..."
            />
          </div>

          {/* Modified criteria (for modify action) */}
          {action === "modify" && (
            <div>
              <label className="block text-sm font-medium mb-1">
                Acceptance Criteria (one per line)
              </label>
              <textarea
                value={criteria}
                onChange={(e) => setCriteria(e.target.value)}
                className="w-full border rounded px-3 py-2 h-32 font-mono text-sm"
              />
            </div>
          )}
        </div>

        {/* Actions */}
        <div className="p-4 border-t flex justify-end gap-2">
          <button
            onClick={onClose}
            className="px-4 py-2 text-gray-600 hover:bg-gray-100 rounded"
            disabled={isLoading}
          >
            Cancel
          </button>
          <button
            onClick={handleSubmit}
            disabled={isLoading}
            className={`px-4 py-2 rounded text-white font-medium ${
              action === "approve"
                ? "bg-green-600 hover:bg-green-700"
                : action === "reject" || action === "abandon"
                ? "bg-red-600 hover:bg-red-700"
                : "bg-blue-600 hover:bg-blue-700"
            }`}
          >
            {isLoading ? "Processing..." : `${action.charAt(0).toUpperCase() + action.slice(1)}`}
          </button>
        </div>
      </div>
    </div>
  );
}
'''

# -----------------------------------------------------------------------------
# frontend/src/components/tasks/TaskStatusBadge.tsx
# -----------------------------------------------------------------------------

TASK_STATUS_BADGE_TSX = '''
import type { TaskStatus } from "../../types";

const statusConfig: Record<TaskStatus, { label: string; className: string }> = {
  planned: { label: "Planned", className: "bg-gray-100 text-gray-700" },
  ready: { label: "Ready", className: "bg-blue-100 text-blue-700" },
  blocked: { label: "Blocked", className: "bg-amber-100 text-amber-700" },
  active: { label: "Active", className: "bg-purple-100 text-purple-700" },
  awaiting_qa: { label: "Awaiting QA", className: "bg-orange-100 text-orange-700" },
  failed_qa: { label: "Failed QA", className: "bg-red-100 text-red-700" },
  complete: { label: "Complete", className: "bg-green-100 text-green-700" },
  waiting_human: { label: "Needs Human", className: "bg-pink-100 text-pink-700" },
  abandoned: { label: "Abandoned", className: "bg-gray-200 text-gray-500" },
};

interface TaskStatusBadgeProps {
  status: TaskStatus;
}

export function TaskStatusBadge({ status }: TaskStatusBadgeProps) {
  const config = statusConfig[status] || statusConfig.planned;
  
  return (
    <span className={`px-2 py-0.5 rounded text-xs font-medium ${config.className}`}>
      {config.label}
    </span>
  );
}
'''

# -----------------------------------------------------------------------------
# frontend/package.json
# -----------------------------------------------------------------------------

PACKAGE_JSON = '''
{
  "name": "orchestrator-dashboard",
  "private": true,
  "version": "1.0.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc && vite build",
    "preview": "vite preview",
    "lint": "eslint src --ext ts,tsx"
  },
  "dependencies": {
    "react": "^18.2.0",
    "react-dom": "^18.2.0",
    "react-router-dom": "^6.20.0",
    "@tanstack/react-query": "^5.8.0",
    "axios": "^1.6.0",
    "reactflow": "^11.10.0",
    "dagre": "^0.8.5",
    "date-fns": "^2.30.0",
    "clsx": "^2.0.0"
  },
  "devDependencies": {
    "@types/react": "^18.2.0",
    "@types/react-dom": "^18.2.0",
    "@types/dagre": "^0.7.52",
    "@vitejs/plugin-react": "^4.2.0",
    "typescript": "^5.2.0",
    "vite": "^5.0.0",
    "tailwindcss": "^3.3.0",
    "autoprefixer": "^10.4.16",
    "postcss": "^8.4.31",
    "eslint": "^8.54.0",
    "@typescript-eslint/eslint-plugin": "^6.12.0",
    "@typescript-eslint/parser": "^6.12.0"
  }
}
'''


# =============================================================================
# PART 3: IMPLEMENTATION GUIDE
# =============================================================================

IMPLEMENTATION_GUIDE = """
# Implementation Guide

## Quick Start

### Backend Setup

```bash
# Create project
mkdir orchestrator-dashboard && cd orchestrator-dashboard
mkdir -p backend/api backend/services backend/models
mkdir -p frontend/src

# Backend dependencies
cd backend
python -m venv venv
source venv/bin/activate  # or `venv\\Scripts\\activate` on Windows
pip install fastapi uvicorn pydantic-settings langgraph langchain-core websockets

# Copy the Python files from this spec into the backend directory
# Then run:
uvicorn main:app --reload --port 8000
```

### Frontend Setup

```bash
# From project root
cd frontend
npm create vite@latest . -- --template react-ts
npm install

# Install dependencies
npm install react-router-dom @tanstack/react-query axios reactflow dagre date-fns clsx
npm install -D @types/dagre tailwindcss autoprefixer postcss

# Initialize Tailwind
npx tailwindcss init -p

# Copy TypeScript files from this spec, then run:
npm run dev
```

## API Endpoints Summary

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | /api/v1/runs | List all runs |
| POST | /api/v1/runs | Create new run |
| GET | /api/v1/runs/{id} | Get run details |
| POST | /api/v1/runs/{id}/pause | Pause run |
| POST | /api/v1/runs/{id}/resume | Resume run |
| GET | /api/v1/runs/{id}/graph | Get task DAG |
| GET | /api/v1/runs/{id}/tasks | List tasks |
| GET | /api/v1/runs/{id}/tasks/{task_id} | Get task detail |
| POST | /api/v1/runs/{id}/tasks/{task_id}/retry | Retry task |
| GET | /api/v1/hitl/queue | Get all HITL items |
| POST | /api/v1/hitl/resolve/{run_id}/{task_id} | Resolve HITL |
| WS | /ws/runs/{id} | Real-time updates |
| WS | /ws/hitl | HITL notifications |

## WebSocket Events

| Event Type | Description |
|------------|-------------|
| initial_state | Connection established, includes current state |
| task_update | Task status changed |
| node_start | LangGraph node began execution |
| node_end | LangGraph node finished |
| log | Execution log message |
| error | Error occurred |
| heartbeat | Keep-alive ping |

## HITL Resolution Actions

| Action | Effect |
|--------|--------|
| approve | Task -> READY, execution resumes |
| reject | Task -> ABANDONED |
| modify | Update criteria/description, Task -> READY |
| retry | Reset retry count, clear memories, Task -> READY |
| abandon | Task -> ABANDONED with reason |

## Integration Notes

The OrchestratorService imports from your existing spec files:
- orchestrator_types.py
- langgraph_definition.py

Ensure these are importable from the backend directory.
"""


# =============================================================================
# EXPORTS
# =============================================================================

__all__ = [
    # Backend
    "CONFIG_PY",
    "RESPONSES_PY", 
    "REQUESTS_PY",
    "ORCHESTRATOR_SERVICE_PY",
    "RUNS_API_PY",
    "TASKS_API_PY",
    "HITL_API_PY",
    "WEBSOCKET_API_PY",
    "MAIN_PY",
    # Frontend
    "TYPES_TS",
    "API_CLIENT_TS",
    "RUNS_API_TS",
    "HITL_API_TS",
    "WEBSOCKET_TS",
    "USE_WEBSOCKET_TS",
    "TASK_GRAPH_TSX",
    "HUMAN_QUEUE_TSX",
    "RESOLUTION_MODAL_TSX",
    "TASK_STATUS_BADGE_TSX",
    "PACKAGE_JSON",
    # Guide
    "IMPLEMENTATION_GUIDE",
]
