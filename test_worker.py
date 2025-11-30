
import sys
import os
sys.path.append(os.path.join(os.getcwd(), "src"))

from nodes.worker import worker_node
from orchestrator_types import Task, TaskStatus, TaskPhase, WorkerProfile
from datetime import datetime
import uuid

def test_worker_mock():
    print("Testing Worker in Mock Mode...")
    
    # Create dummy task
    task_id = f"task_{uuid.uuid4().hex[:8]}"
    task = {
        "id": task_id,
        "component": "test_comp",
        "phase": "build",
        "status": "planned",
        "assigned_worker_profile": "code_worker",
        "description": "Test task",
        "acceptance_criteria": ["Criteria 1"],
        "depends_on": [],
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat()
    }
    
    state = {
        "tasks": [task],
        "task_id": task_id
    }
    
    config = {"configurable": {"mock_mode": True}}
    
    try:
        result = worker_node(state, config)
        print("Result:", result)
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_worker_mock()
