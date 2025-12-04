"""
HITL Test Script - Simulate Task Failures Without Burning Tokens
=================================================================

This script creates a test run with pre-failed tasks to test the
Human-in-the-Loop interrupt mechanism.

Usage:
    python test_hitl_simulation.py
    
Then open the dashboard to see the interrupt modal appear.
"""

import sys
import os
import sqlite3
import json
import uuid
from datetime import datetime
from pathlib import Path

# Add src to path
sys.path.append(os.path.join(os.path.dirname(__file__), 'src'))

from orchestrator_types import Task, TaskStatus, TaskPhase, WorkerProfile, AAR
from state import OrchestratorState

def create_test_run_with_failed_task():
    """Create a test run with tasks that have exceeded max retries."""
    
    # Setup paths
    db_path = Path("orchestrator.db")
    
    # Generate IDs
    run_id = f"test_run_{uuid.uuid4().hex[:8]}"
    thread_id = str(uuid.uuid4())
    
    print(f"Creating test run: {run_id}")
    print(f"Thread ID: {thread_id}")
    
    # Create tasks with different states
    tasks = []
    
    # Task 1: Completed successfully
    task1 = Task(
        id=f"task_{uuid.uuid4().hex[:8]}",
        component="Database Schema",
        phase=TaskPhase.BUILD,
        status=TaskStatus.COMPLETE,
        assigned_worker_profile=WorkerProfile.CODER,
        description="Create database schema for tasks table",
        acceptance_criteria=["Schema created", "Tables exist"],
        depends_on=[],
        created_at=datetime.now(),
        updated_at=datetime.now(),
        retry_count=0
    )
    tasks.append(task1)
    
    # Task 2: Failed 4 times (WILL TRIGGER INTERRUPT)
    failed_task = Task(
        id=f"task_{uuid.uuid4().hex[:8]}",
        component="API Routes",
        phase=TaskPhase.BUILD,
        status=TaskStatus.FAILED,
        assigned_worker_profile=WorkerProfile.CODER,
        description="Implement REST API endpoints for task CRUD operations. This task has been failing repeatedly.",
        acceptance_criteria=[
            "GET /api/tasks returns all tasks",
            "POST /api/tasks creates new task",
            "PUT /api/tasks/<id> updates task",
            "DELETE /api/tasks/<id> removes task"
        ],
        depends_on=[task1.id],
        created_at=datetime.now(),
        updated_at=datetime.now(),
        retry_count=4,  # Exceeded max retries!
        aar=AAR(
            summary="Failed to implement PUT endpoint - syntax error in route handler. Agent keeps making the same mistake with parameter binding.",
            approach="Attempted to create Flask route with @app.put decorator",
            challenges=["Syntax error in parameter binding", "Agent repeating same mistake", "PUT endpoint not working"],
            decisions_made=["Tried decoratorapproach", "Attempted to fix parameter binding 4 times"],
            files_modified=["api/routes.py"],
            time_spent_estimate="~30 minutes across 4 retries"
        )
    )
    tasks.append(failed_task)
    
    # Task 3: Waiting on failed task
    task3 = Task(
        id=f"task_{uuid.uuid4().hex[:8]}",
        component="Frontend",
        phase=TaskPhase.BUILD,
        status=TaskStatus.PLANNED,
        assigned_worker_profile=WorkerProfile.CODER,
        description="Build frontend UI for task management",
        acceptance_criteria=["UI displays tasks", "User can add/edit tasks"],
        depends_on=[failed_task.id],
        created_at=datetime.now(),
        updated_at=datetime.now(),
        retry_count=0
    )
    tasks.append(task3)
    
    # Convert tasks to dicts for state
    from orchestrator_types import task_to_dict
    task_dicts = [task_to_dict(t) for t in tasks]
    
    # Create initial state
    initial_state = {
        "run_id": run_id,
        "objective": "Test HITL with pre-failed tasks",
        "spec": {},
        "tasks": task_dicts,
        "insights": [],
        "design_log": [],
        "task_memories": {},
        "filesystem_index": {},
        "guardian": {},
        "strategy_status": "progressing",
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat(),
        "mock_mode": False,
        "_workspace_path": str(Path("test-workspace").resolve()),
        "replan_requested": False
    }
    
    # Connect to the database that the server uses
    try:
        from langgraph.checkpoint.sqlite import SqliteSaver
    except ImportError:
        # Try alternative import
        from langgraph.checkpoint.sqlite.aio import SqliteSaver
    
    import sqlite3
    
    conn = sqlite3.connect(db_path, check_same_thread=False)
    checkpointer = SqliteSaver(conn)
    
    # Create config for this thread
    config = {"configurable": {"thread_id": thread_id}}
    
    # We need to actually run the graph to create a proper checkpoint
    # Let's use the orchestrator from server
    from langgraph_definition import create_orchestrator
    
    orchestrator = create_orchestrator(checkpointer=checkpointer)
    
    # Put the initial state - this creates the checkpoint
    # We use update_state to inject our pre-failed tasks
    try:
        # First invoke with initial state to create the run
        print("Creating checkpoint in database...")
        orchestrator.update_state(config, initial_state, as_node="__start__")
        print("✅ Checkpoint created!")
        
    except Exception as e:
        print(f"Note: Using alternative method: {e}")
        # Alternative: just update the state
        orchestrator.update_state(config, initial_state)
    
    print("\n" + "="*60)
    print("TEST RUN CREATED SUCCESSFULLY")
    print("="*60)
    print(f"\nRun ID: {run_id}")
    print(f"Thread ID: {thread_id}")
    print(f"\nFailed Task ID: {failed_task.id}")
    print(f"Retry Count: {failed_task.retry_count} (MAX = 4)")
    print(f"\nFailure Reason:")
    print(f"  {failed_task.aar.summary}")
    print("\n" + "="*60)
    print("NEXT STEPS:")
    print("="*60)
    print("\n1. Open dashboard at http://localhost:3000")
    print("\n2. You should see the test run in the list")
    print(f"\n3. Click on run '{run_id}'")
    print("\n4. The director will process the failed task and trigger HITL")
    print("   - Watch server logs for 'requesting human intervention'")
    print("\n5. The InterruptModal should appear automatically!")
    print("\n6. Or manually check via API:")
    print(f"   curl http://localhost:8085/api/runs/{run_id}/interrupts")
    print("="*60)
    
    conn.close()
    
    return run_id, thread_id, failed_task.id


def create_simple_api_test():
    """Create a simpler test that just uses the API to create a run."""
    
    print("\n" + "="*60)
    print("SIMPLE API TEST APPROACH")
    print("="*60)
    print("\nInstead of manually creating database entries,")
    print("let's create a run that will QUICKLY fail:\n")
    
    test_script = """
# Create a run with an impossible task that will fail fast
curl -X POST http://localhost:8085/api/runs \\
  -H "Content-Type: application/json" \\
  -d '{
    "objective": "Create a file called IMPOSSIBLE.txt but the write_file tool is intentionally broken",
    "spec": {}
  }'

# Wait for it to fail 4 times (should be quick with wrong tool usage)
# Then check for interrupts:
# curl http://localhost:8085/api/runs/{run_id}/interrupts

# Or just open the dashboard and watch it fail!
"""
    
    print(test_script)
    print("="*60)


if __name__ == "__main__":
    print("HITL Testing Simulation")
    print("="*60)
    print("\nOption 1: Create pre-failed test run (direct DB)")
    print("Option 2: Create impossible task via API (quick fail)")
    print()
    
    choice = input("Choose option (1 or 2, or 'q' to quit): ").strip()
    
    if choice == "1":
        try:
            run_id, thread_id, failed_task_id = create_test_run_with_failed_task()
            print(f"\n✅ Test run created!")
            print(f"\nTo continue this run through the director:")
            print(f"  1. The director will detect the failed task")
            print(f"  2. Call interrupt() and pause")
            print(f"  3. Dashboard will show modal")
            
        except Exception as e:
            print(f"\n❌ Error: {e}")
            import traceback
            traceback.print_exc()
            
    elif choice == "2":
        create_simple_api_test()
        
    else:
        print("Exiting...")
