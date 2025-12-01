
import sys
import os
import uuid
from datetime import datetime
from typing import Dict, Any, List

# Add src to path
sys.path.append(os.path.join(os.getcwd(), "src"))

from orchestrator_types import Task, TaskStatus, TaskPhase, WorkerProfile, task_to_dict, SuggestedTask
from nodes.director import director_node

def test_hierarchical_planning():
    print("Testing Hierarchical Planning...")
    
    # Create a mock completed PLAN task with suggested tasks
    plan_task_id = "task_plan_123"
    
    # Mock suggested tasks data (as if it came from worker.py)
    suggested_tasks_data = [
        {
            "suggested_id": "temp_1",
            "component": "backend",
            "phase": "build",
            "description": "Create Database Schema",
            "rationale": "Needed for data",
            "depends_on": [],
            "acceptance_criteria": ["Schema.sql exists"],
            "suggested_by_task": plan_task_id,
            "priority": 5
        },
        {
            "suggested_id": "temp_2",
            "component": "backend",
            "phase": "build",
            "description": "Implement API",
            "rationale": "Needed for frontend",
            "depends_on": ["Create Database Schema"], # Dependency by title
            "acceptance_criteria": ["API works"],
            "suggested_by_task": plan_task_id,
            "priority": 5
        }
    ]
    
    plan_task_dict = {
        "id": plan_task_id,
        "component": "backend",
        "phase": "plan",
        "description": "Plan the backend",
        "status": "awaiting_qa",
        "assigned_worker_profile": "planner_worker",
        "retry_count": 0,
        "max_retries": 3,
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat(),
        "suggested_tasks": suggested_tasks_data # This is what we added to worker.py
    }
    
    # Mock state
    state = {
        "tasks": [plan_task_dict],
        "mock_mode": True
    }
    
    # Run director
    print("Running director_node...")
    updates = director_node(state)
    
    # Verify results
    updated_tasks = updates.get("tasks", [])
    print(f"Director returned {len(updated_tasks)} updates.")
    
    # We expect 2 new tasks
    new_tasks = [t for t in updated_tasks if t["id"] != plan_task_id]
    
    if len(new_tasks) != 2:
        print(f"FAIL: Expected 2 new tasks, got {len(new_tasks)}")
        return
        
    print("PASS: 2 new tasks created")
    
    # Verify dependencies
    db_task = next((t for t in new_tasks if "Database" in t["description"]), None)
    api_task = next((t for t in new_tasks if "API" in t["description"]), None)
    
    if not db_task or not api_task:
        print("FAIL: Could not find DB or API task")
        return
        
    print(f"DB Task ID: {db_task['id']}")
    print(f"API Task ID: {api_task['id']}")
    print(f"API Task Depends On: {api_task['depends_on']}")
    
    if db_task['id'] in api_task['depends_on']:
        print("PASS: Dependency correctly resolved")
    else:
        print("FAIL: API task does not depend on DB task")

if __name__ == "__main__":
    test_hierarchical_planning()
