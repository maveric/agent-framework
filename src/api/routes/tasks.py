"""
Tasks API Routes
================
FastAPI routes for managing individual tasks within runs.
"""

import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

# Import API modules
from api.state import runs_index, run_states, manager, get_orchestrator_graph

logger = logging.getLogger(__name__)

# Create router with prefix and tags
router = APIRouter(prefix="/api/v1/runs/{run_id}/tasks", tags=["tasks"])


# =============================================================================
# REQUEST MODELS
# =============================================================================

class DependencyUpdate(BaseModel):
    """Request body for updating task dependencies."""
    add_dependency: Optional[str] = None
    remove_dependency: Optional[str] = None


# =============================================================================
# ROUTES
# =============================================================================

@router.patch("/{task_id}")
async def update_task_dependencies(run_id: str, task_id: str, body: DependencyUpdate):
    """
    Update task dependencies without triggering a full replan.
    
    Use cases:
    - Add dependency: {"add_dependency": "other_task_id"}
    - Remove dependency: {"remove_dependency": "other_task_id"}
    """
    if run_id not in runs_index:
        raise HTTPException(status_code=404, detail="Run not found")
    
    state = run_states.get(run_id)
    if not state:
        raise HTTPException(status_code=404, detail="Run state not found")
    
    try:
        tasks = state.get("tasks", [])
        task = next((t for t in tasks if t.get("id") == task_id), None)
        
        if not task:
            raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
        
        # Initialize depends_on if missing
        if "depends_on" not in task:
            task["depends_on"] = []
        
        # Add dependency
        if body.add_dependency:
            # Verify the dependency target exists
            dep_task = next((t for t in tasks if t.get("id") == body.add_dependency), None)
            if not dep_task:
                raise HTTPException(status_code=404, detail=f"Dependency target {body.add_dependency} not found")
            
            # Prevent duplicates
            if body.add_dependency not in task["depends_on"]:
                task["depends_on"].append(body.add_dependency)
                logger.info(f"Added dependency: {task_id} now depends on {body.add_dependency}")
        
        # Remove dependency
        if body.remove_dependency:
            if body.remove_dependency in task["depends_on"]:
                task["depends_on"].remove(body.remove_dependency)
                logger.info(f"Removed dependency: {task_id} no longer depends on {body.remove_dependency}")
        
        task["updated_at"] = datetime.now().isoformat()
        
        # Broadcast state update via WebSocket (no replan needed)
        if manager:
            await manager.broadcast_to_run(run_id, {
                "type": "state_update",
                "payload": {
                    "tasks": tasks
                }
            })
        
        return {
            "task_id": task_id,
            "depends_on": task["depends_on"],
            "updated": True
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update task dependencies: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{task_id}")
async def delete_task(run_id: str, task_id: str):
    """Mark a task as ABANDONED and trigger replan."""
    if run_id not in runs_index:
        raise HTTPException(status_code=404, detail="Run not found")

    try:
        orchestrator = get_orchestrator_graph()
        config = {"configurable": {"thread_id": runs_index[run_id]["thread_id"]}}

        # Update task status to ABANDONED and request replan
        # sending as_node="director" to attribute the change to the director
        await orchestrator.aupdate_state(
            config,
            {
                "tasks": [{"id": task_id, "status": "abandoned", "updated_at": datetime.now().isoformat()}],
                "replan_requested": True
            },
            as_node="director"
        )

        logger.info(f"Task {task_id} marked ABANDONED and replan requested for run {run_id}.")
        return {"status": "abandoned", "replan_requested": True}
    except Exception as e:
        logger.error(f"Failed to delete task: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
