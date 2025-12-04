"""
HITL Mock Worker - Forces Task Failure for Testing
===================================================

A mock worker that always fails to trigger HITL interrupt testing.

Usage:
    python test_hitl_mock_worker.py --workspace test-ws --objective "Test task"
    
This will:
1. Create tasks that immediately fail
2. Retry 4 times quickly
3. Trigger the HITL interrupt on 5th attempt
4. Allow you to test the resolution UI
"""

import sys
import os
from pathlib import Path

# Add src to path
sys.path.append(os.path.join(os.path.dirname(__file__), 'src'))

from langgraph_definition import create_orchestrator
from config import OrchestratorConfig
from git_manager import WorktreeManager, initialize_git_repo
from datetime import datetime
import uuid

def create_mock_failed_run(workspace_path: Path, objective: str):
    """Create a run that will intentionally fail to test HITL."""
    
    # Initialize workspace
    workspace_path.mkdir(parents=True, exist_ok=True)
    initialize_git_repo(workspace_path)
    
    # Create worktree manager
    worktree_base = workspace_path / ".worktrees"
    worktree_base.mkdir(exist_ok=True)
    
    wt_manager = WorktreeManager(
        repo_path=workspace_path,
        worktree_base=worktree_base
    )
    
    # Create config with FAST retries
    config = OrchestratorConfig(
        mock_mode=False,
        max_concurrent_workers=1  # One at a time for easier testing
    )
    
    # Create orchestrator
    from langgraph.checkpoint.sqlite import SqliteSaver
    import sqlite3
    
    db_path = "orchestrator_test.db"
    db_conn = sqlite3.connect(db_path, check_same_thread=False)
    checkpointer = SqliteSaver(db_conn)
    
    orchestrator = create_orchestrator(checkpointer=checkpointer)
    
    # Generate IDs
    run_id = f"hitl_test_{uuid.uuid4().hex[:8]}"
    thread_id = str(uuid.uuid4())
    
    print(f"\n{'='*60}")
    print(f"Creating HITL Test Run")
    print(f"{'='*60}")
    print(f"Run ID: {run_id}")
    print(f"Thread ID: {thread_id}")
    print(f"Workspace: {workspace_path}")
    print(f"Objective: {objective}")
    print(f"{'='*60}\n")
    
    # Create impossible objective that will fail
    modified_objective = """
    Create a Python file called impossible_task.py that:
    1. Imports a module that doesn't exist: `import nonexistent_module`
    2. Must pass all tests
    
    THIS TASK IS DESIGNED TO FAIL FOR HITL TESTING.
    The worker will fail 4 times, then trigger human intervention.
    """
    
    # Initial state
    initial_state = {
        "run_id": run_id,
        "objective": modified_objective,
        "spec": {},
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
        },
        "recursion_limit": 100
    }
    
    print("Starting orchestrator...")
    print("Watch for 'requesting human intervention' message!\n")
    
    try:
        # Run the orchestrator - it will fail and hit HITL
        result = orchestrator.invoke(initial_state, config=run_config)
        
        print("\n" + "="*60)
        print("ORCHESTRATOR FINISHED")
        print("="*60)
        print("If you saw 'requesting human intervention', the test worked!")
        print(f"\nCheck: http://localhost:8085/api/runs/{run_id}/interrupts")
        print("="*60)
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
    
    return run_id, thread_id


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Test HITL with mock failures")
    parser.add_argument("--workspace", default="test-hitl-workspace",
                       help="Workspace path")
    parser.add_argument("--objective", default="Test HITL with failing task",
                       help="Objective (will be modified to fail)")
    
    args = parser.parse_args()
    
    workspace = Path(args.workspace).resolve()
    
    run_id, thread_id = create_mock_failed_run(workspace, args.objective)
    
    print(f"\n✅ Test completed")
    print(f"Run ID: {run_id}")
    print(f"Thread ID: {thread_id}")
