"""
Tasks API Routes
================
FastAPI routes for managing individual tasks within runs.
"""

import logging
from datetime import datetime

from fastapi import APIRouter, HTTPException

# Import API modules
from api.state import runs_index, get_orchestrator_graph

logger = logging.getLogger(__name__)

# Create router with prefix and tags
router = APIRouter(prefix="/api/runs/{run_id}/tasks", tags=["tasks"])


# =============================================================================
# ROUTES
# =============================================================================

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
