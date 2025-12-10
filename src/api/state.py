"""
API State Management
====================
Centralized state management for the orchestrator API server.
"""

import logging
from typing import Dict, Any
from langgraph_definition import create_orchestrator

logger = logging.getLogger(__name__)

# In-memory storage for runs (in a real app, this would be a DB)
# We use the LangGraph checkpointing for the actual state, but we need an index
runs_index: Dict[str, Dict[str, Any]] = {}

# Track running background tasks for cancellation
running_tasks: Dict[str, Any] = {}  # run_id -> asyncio.Task

# Store full run states for restart capability
run_states: Dict[str, Dict[str, Any]] = {}  # run_id -> full state dict

# Global checkpointer (initialized at startup)
global_checkpointer = None

# Global connection manager (initialized by server)
manager = None

# Track active task queues per run for task-specific cancellation
# Maps run_id -> TaskCompletionQueue
active_task_queues: Dict[str, Any] = {}



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
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Error serializing config: {e}")
        return None
