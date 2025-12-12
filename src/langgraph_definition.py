"""
Agent Orchestrator — LangGraph Definition
=========================================
Version 1.0 — November 2025

Assembles all nodes into a StateGraph.
"""

import logging
from langgraph.graph import StateGraph, END
try:
    from langgraph.checkpoint.sqlite import SqliteSaver
except ImportError:
    SqliteSaver = None

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

logger = logging.getLogger(__name__)


def create_orchestrator(
    config: OrchestratorConfig = None,
    checkpoint_mode: str = "memory",
    checkpointer = None
):
    """
    Create and compile the orchestrator graph.
    
    Args:
        config: Orchestrator configuration
        checkpoint_mode: "sqlite" or "memory" (ignored if checkpointer is provided)
        checkpointer: Optional pre-configured checkpointer
    
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
    if checkpointer is None:
        if checkpoint_mode == "sqlite" and SqliteSaver is not None:
            checkpointer = SqliteSaver.from_conn_string(":memory:")
        else:
            if checkpoint_mode == "sqlite":
                logger.warning("SqliteSaver not available, falling back to MemorySaver")
            checkpointer = MemorySaver()
    
    # Compile
    return graph.compile(checkpointer=checkpointer)


async def start_run(objective: str, workspace: str = "../workspace", spec: dict = None, config: OrchestratorConfig = None, checkpointer = None):
    """
    Start an orchestrator run (async version).
    
    Args:
        objective: What to build
        workspace: Directory where project will be built
        spec: Optional specification
        config: Orchestrator configuration
        checkpointer: Optional checkpointer
    
    Returns:
        Final state
    """
    import uuid
    from datetime import datetime
    from pathlib import Path
    from git_manager import AsyncWorktreeManager as WorktreeManager
    from git_manager import AsyncWorktreeManager as WorktreeManager, initialize_git_repo_async as initialize_git_repo
    
    orchestrator = create_orchestrator(config, checkpointer=checkpointer)
    
    # Setup workspace directory
    workspace_path = Path(workspace).resolve()
    workspace_path.mkdir(parents=True, exist_ok=True)
    
    logger.info(f"Initializing workspace: {workspace_path}")

    # Initialize git repository in workspace
    await initialize_git_repo(workspace_path)
    
    # Ensure config exists for path methods
    if config is None:
        config = OrchestratorConfig()
    
    # Generate run_id first (needed for path methods)
    run_id = f"run_{uuid.uuid4().hex[:8]}"
    
    # Create worktree manager with path OUTSIDE workspace (avoids gitignore conflicts)
    worktree_base = config.get_worktree_base(run_id)
    worktree_base.mkdir(parents=True, exist_ok=True)
    
    wt_manager = WorktreeManager(
        repo_path=workspace_path,
        worktree_base=worktree_base
    )
    
    # Get logs path (also OUTSIDE workspace)
    logs_base_path = config.get_llm_logs_path(run_id)
    
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
        "mock_mode": config.mock_mode if config else False,
        # Store WorktreeManager instance and paths
        "_wt_manager": wt_manager,
        "_workspace_path": str(workspace_path),
        "_worktree_base_path": str(worktree_base),  # Worktrees outside workspace
        "_logs_base_path": str(logs_base_path),  # LLM logs outside workspace
        "orch_config": config,  # Store config (public key to ensure persistence)
    }
    
    # Generate unique thread ID for this run
    thread_id = str(uuid.uuid4())
    logger.info(f"Starting run with thread_id: {thread_id}")
    
    # Run graph with thread_id for checkpointing (async)
    run_config = {
        "configurable": {
            "thread_id": thread_id,
            "mock_mode": config.mock_mode if config else False
        }
    }
    result = await orchestrator.ainvoke(initial_state, config={
        "recursion_limit": 150,  # Circuit breaker to prevent runaway token costs
        "configurable": {
            "thread_id": thread_id,
            "mock_mode": config.mock_mode if config else False
        }
    })
    
    # Check if run is paused for HITL (not actually complete)
    final_snapshot = await orchestrator.aget_state({
        "configurable": {
            "thread_id": thread_id,
            "mock_mode": config.mock_mode if config else False
        }
    })
    
    # If snapshot.next is non-empty, graph is paused/interrupted
    if final_snapshot.next:
        result["_paused_for_hitl"] = True
        logger.info("GRAPH PAUSED - WAITING FOR HUMAN INPUT")
        logger.info(f"Thread ID: {thread_id}")
        
        # Find tasks waiting for human
        tasks = result.get("tasks", [])
        waiting_tasks = [t for t in tasks if t.get("status") == "waiting_human"]
        if waiting_tasks:
            logger.info(f"Tasks waiting for resolution: {len(waiting_tasks)}")
            for task in waiting_tasks:
                logger.info(f"  - {task.get('id')}: {task.get('description', '')[:60]}...")
    
    return result
