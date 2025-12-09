"""
API Request/Response Types
===========================
Pydantic models for API request and response validation.
"""

from typing import List, Dict, Any, Optional
from pydantic import BaseModel


class CreateRunRequest(BaseModel):
    """Request model for creating a new orchestrator run."""
    objective: str
    spec: Optional[Dict[str, Any]] = None
    tags: Optional[List[str]] = None
    workspace: Optional[str] = None


class RunSummary(BaseModel):
    """Summary information for a run."""
    run_id: str
    objective: str
    status: str
    created_at: str
    updated_at: str
    task_counts: Dict[str, int]
    tags: List[str]
    workspace_path: Optional[str] = None


class HumanResolution(BaseModel):
    """Human resolution for an interrupted task."""
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
