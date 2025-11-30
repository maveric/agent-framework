"""
Agent Orchestrator — LangGraph Definition
=========================================
Version 1.0 — November 2025

Assembles all nodes into a StateGraph.
"""

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.checkpoint.memory import MemorySaver

from state import OrchestratorState
from nodes import (
    director_node,
    worker_node,
    strategist_node,
    guardian_node,
    route_after_director,
    route_after_worker,
)
from config import OrchestratorConfig


def create_orchestrator(
    config: OrchestratorConfig = None,
    checkpoint_mode: str = "memory"
):
    """
    Create and compile the orchestrator graph.
    
    Args:
        config: Orchestrator configuration
        checkpoint_mode: "sqlite" or "memory"
    
    Returns:
        Compiled StateGraph
    """
    if config is None:
        config = OrchestratorConfig()
    
    # Create graph
    graph = StateGraph(OrchestratorState)
    
    # Add nodes
    graph.add_node("director", director_node)
    graph.add_node("worker", worker_node)
    graph.add_node("strategist", strategist_node)
    
    # Add edges
    graph.set_entry_point("director")
    
    # Director can dispatch to workers or end
    graph.add_conditional_edges("director", route_after_director)
    
    # Worker routes based on task phase:
    # - TEST phase tasks go to Strategist for QA
    # - PLAN/BUILD tasks return to Director (skip QA to avoid echo chamber)
    graph.add_conditional_edges("worker", route_after_worker)
    
    # Strategist goes back to director
    graph.add_edge("strategist", "director")
    
    # Setup checkpointing
    if checkpoint_mode == "sqlite":
        checkpointer = SqliteSaver.from_conn_string(":memory:")
    else:
        checkpointer = MemorySaver()
    
    # Compile
    return graph.compile(checkpointer=checkpointer)


def start_run(objective: str, workspace: str = "../workspace", spec: dict = None, config: OrchestratorConfig = None):
    """
    Start an orchestrator run.
    
    Args:
        objective: What to build
        workspace: Directory where project will be built
        spec: Optional specification
        config: Orchestrator configuration
    
    Returns:
        Final state
    """
    import uuid
    from datetime import datetime
    from pathlib import Path
    from git_manager import WorktreeManager, initialize_git_repo
    
    orchestrator = create_orchestrator(config)
    
    # Setup workspace directory
    workspace_path = Path(workspace).resolve()
    workspace_path.mkdir(parents=True, exist_ok=True)
    
    print(f"Initializing workspace: {workspace_path}")
    
    # Initialize git repository in workspace
    initialize_git_repo(workspace_path)
    
    # Create worktree manager for workspace
    worktree_base = workspace_path / ".worktrees"
    worktree_base.mkdir(exist_ok=True)
    
    wt_manager = WorktreeManager(
        repo_path=workspace_path,
        worktree_base=worktree_base
    )
    
    initial_state = {
        "run_id": f"run_{uuid.uuid4().hex[:8]}",
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
        "mock_mode": config.mock_mode if config else False,
        # Store WorktreeManager instance and workspace path
        "_wt_manager": wt_manager,
        "_wt_manager": wt_manager,
        "_workspace_path": str(workspace_path),
        "orch_config": config,  # Store config (public key to ensure persistence)
    }
    
    # Generate unique thread ID for this run
    thread_id = str(uuid.uuid4())
    print(f"Starting run with thread_id: {thread_id}", flush=True)
    
    # Run graph with thread_id for checkpointing
    run_config = {
        "configurable": {
            "thread_id": thread_id,
            "mock_mode": config.mock_mode if config else False
        }
    }
    result = orchestrator.invoke(initial_state, config=run_config)
    return result
