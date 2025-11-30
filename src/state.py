"""
Agent Orchestrator — State Management
=====================================
Version 1.0 — November 2025

LangGraph state schema and custom reducers for state updates.
"""

from typing import Any, Dict, List, TypedDict, Annotated
from langchain_core.messages import BaseMessage


# =============================================================================
# STATE REDUCERS  
# =============================================================================

def tasks_reducer(
    existing: List[Dict[str, Any]], 
    updates: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """
    Merge task updates into existing task list.
    - If update has matching ID, replace the task
    - If update has new ID, append
    - If update has {"_delete": True, "id": X}, remove task X
    """
    existing_by_id = {t["id"]: t for t in existing}
    
    for update in updates:
        task_id = update.get("id")
        if update.get("_delete"):
            existing_by_id.pop(task_id, None)
        else:
            existing_by_id[task_id] = update
    
    return list(existing_by_id.values())


def insights_reducer(
    existing: List[Dict[str, Any]], 
    updates: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """
    Append new insights. Insights are immutable once created.
    Duplicates (by ID) are ignored.
    """
    existing_ids = {i["id"] for i in existing}
    new_insights = [u for u in updates if u["id"] not in existing_ids]
    return existing + new_insights


def design_log_reducer(
    existing: List[Dict[str, Any]], 
    updates: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """
    Append new design decisions. Design log is append-only.
    """
    existing_ids = {d["id"] for d in existing}
    new_decisions = [u for u in updates if u["id"] not in existing_ids]
    return existing + new_decisions


def task_memories_reducer(
    existing: Dict[str, List[BaseMessage]], 
    updates: Dict[str, List[BaseMessage]]
) -> Dict[str, List[BaseMessage]]:
    """
    Merge task memories. 
    - New messages are appended to existing task memory
    - Special key "_clear" with list of task_ids wipes those memories
    """
    result = dict(existing)
    
    for task_id, messages in updates.items():
        if task_id == "_clear":
            # messages is actually a list of task_ids to clear
            for tid in messages:
                result.pop(tid, None)
        elif task_id in result:
            result[task_id] = result[task_id] + messages
        else:
            result[task_id] = messages
    
    return result


# =============================================================================
# LANGGRAPH STATE SCHEMA
# =============================================================================

class OrchestratorState(TypedDict, total=False):
    """
    LangGraph-compatible state with annotated reducers.
    This is the actual state schema used in the graph.
    """
    # Identity (no reducer - set once)
    run_id: str
    objective: str
    
    # Persistent context with reducers
    spec: Dict[str, Any]  # Last-write-wins (rarely changes)
    design_log: Annotated[List[Dict[str, Any]], design_log_reducer]
    insights: Annotated[List[Dict[str, Any]], insights_reducer]
    
    # Task management with reducer
    tasks: Annotated[List[Dict[str, Any]], tasks_reducer]
    
    # Ephemeral with reducer
    task_memories: Annotated[Dict[str, List[BaseMessage]], task_memories_reducer]
"""
Agent Orchestrator — State Management
=====================================
Version 1.0 — November 2025

LangGraph state schema and custom reducers for state updates.
"""

from typing import Any, Dict, List, TypedDict, Annotated
from langchain_core.messages import BaseMessage


# =============================================================================
# STATE REDUCERS  
# =============================================================================

def tasks_reducer(
    existing: List[Dict[str, Any]], 
    updates: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """
    Merge task updates into existing task list.
    - If update has matching ID, replace the task
    - If update has new ID, append
    - If update has {"_delete": True, "id": X}, remove task X
    """
    existing_by_id = {t["id"]: t for t in existing}
    
    for update in updates:
        task_id = update.get("id")
        if update.get("_delete"):
            existing_by_id.pop(task_id, None)
        else:
            existing_by_id[task_id] = update
    
    return list(existing_by_id.values())


def insights_reducer(
    existing: List[Dict[str, Any]], 
    updates: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """
    Append new insights. Insights are immutable once created.
    Duplicates (by ID) are ignored.
    """
    existing_ids = {i["id"] for i in existing}
    new_insights = [u for u in updates if u["id"] not in existing_ids]
    return existing + new_insights


def design_log_reducer(
    existing: List[Dict[str, Any]], 
    updates: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """
    Append new design decisions. Design log is append-only.
    """
    existing_ids = {d["id"] for d in existing}
    new_decisions = [u for u in updates if u["id"] not in existing_ids]
    return existing + new_decisions


def task_memories_reducer(
    existing: Dict[str, List[BaseMessage]], 
    updates: Dict[str, List[BaseMessage]]
) -> Dict[str, List[BaseMessage]]:
    """
    Merge task memories. 
    - New messages are appended to existing task memory
    - Special key "_clear" with list of task_ids wipes those memories
    """
    result = dict(existing)
    
    for task_id, messages in updates.items():
        if task_id == "_clear":
            # messages is actually a list of task_ids to clear
            for tid in messages:
                result.pop(tid, None)
        elif task_id in result:
            result[task_id] = result[task_id] + messages
        else:
            result[task_id] = messages
    
    return result


# =============================================================================
# LANGGRAPH STATE SCHEMA
# =============================================================================

class OrchestratorState(TypedDict, total=False):
    """
    LangGraph-compatible state with annotated reducers.
    This is the actual state schema used in the graph.
    """
    # Identity (no reducer - set once)
    run_id: str
    objective: str
    
    # Persistent context with reducers
    spec: Dict[str, Any]  # Last-write-wins (rarely changes)
    design_log: Annotated[List[Dict[str, Any]], design_log_reducer]
    insights: Annotated[List[Dict[str, Any]], insights_reducer]
    
    # Task management with reducer
    tasks: Annotated[List[Dict[str, Any]], tasks_reducer]
    
    # Ephemeral with reducer
    task_memories: Annotated[Dict[str, List[BaseMessage]], task_memories_reducer]
    
    # Filesystem (last-write-wins merge)
    filesystem_index: Dict[str, str]
    
    # Control
    guardian: Dict[str, Any]
    # Internal state
    _wt_manager: Any  # WorktreeManager instance
    _workspace_path: str  # Path to workspace root
    orch_config: Any  # OrchestratorConfig instance (public to persist)
    strategy_status: str
    
    # Metadata
    created_at: str
    updated_at: str
    
    # Configuration
    mock_mode: bool
