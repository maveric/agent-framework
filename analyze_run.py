import sqlite3
import json
import pickle
from collections import Counter

conn = sqlite3.connect('orchestrator.db')
cursor = conn.cursor()

# Get the most recent checkpoint
cursor.execute('''
    SELECT thread_id, checkpoint_id, checkpoint, metadata 
    FROM checkpoints 
    ORDER BY checkpoint_id DESC 
    LIMIT 1
''')

row = cursor.fetchone()
if row:
    thread_id, checkpoint_id, checkpoint_data, metadata = row
    
    print(f"Thread ID: {thread_id}")
    print(f"Checkpoint ID: {checkpoint_id}\n")
    
    # Parse the checkpoint - LangGraph stores the state in the checkpoint
    state = pickle.loads(checkpoint_data)
    
    # Extract channel values (the actual state)
    channel_values = state.get('channel_values', {})
    
    # Get tasks
    tasks = channel_values.get('tasks', [])
    print(f"Total tasks in run: {len(tasks)}\n")
    
    # Analyze task distribution
    phases = Counter()
    statuses = Counter()
    workers = Counter()
    
    for task in tasks:
        # Tasks might be dicts or objects
        if isinstance(task, dict):
            phase = task.get('phase', 'unknown')
            status = task.get('status', 'unknown')
            worker = task.get('assigned_worker_profile', 'unknown')
        else:
            phase = getattr(task, 'phase', 'unknown')
            status = getattr(task, 'status', 'unknown')
            worker = getattr(task, 'assigned_worker_profile', 'unknown')
        
        phases[phase] += 1
        statuses[status] += 1
        workers[worker] += 1
    
    print("Task Distribution:")
    print("-" * 50)
    print("\nBy Phase:")
    for phase, count in phases.most_common():
        print(f"  {phase}: {count}")
    
    print("\nBy Status:")
    for status, count in statuses.most_common():
        print(f"  {status}: {count}")
        
    print("\nBy Worker Type:")
    for worker, count in workers.most_common():
        print(f"  {worker}: {count}")
    
    # Find test_worker failures
    print("\n" + "=" * 50)
    print("Test Worker Tasks (showing first 3):")
    print("=" * 50)
    test_count = 0
    for task in tasks:
        if isinstance(task, dict):
            worker = task.get('assigned_worker_profile')
            task_id = task.get('id')
            status = task.get('status')
            desc = task.get('description', '')
        else:
            worker = getattr(task, 'assigned_worker_profile', None)
            task_id = getattr(task, 'id', None)
            status = getattr(task, 'status', None)
            desc = getattr(task, 'description', '')
        
        if worker == 'test_worker' and test_count < 3:
            test_count += 1
            print(f"\nTask ID: {task_id}")
            print(f"  Status: {status}")
            print(f"  Description: {desc[:100]}")
    
    # Show planner task creation patterns
    print("\n" + "=" * 50)
    print("Planner Tasks (showing first 5):")
    print("=" * 50)
    plan_count = 0
    for task in tasks:
        if isinstance(task, dict):
            worker = task.get('assigned_worker_profile')
            task_id = task.get('id')
            desc = task.get('description', '')
        else:
            worker = getattr(task, 'assigned_worker_profile', None)
            task_id = getattr(task, 'id', None)
            desc = getattr(task, 'description', '')
        
        if worker == 'planner_worker' and plan_count < 5:
            plan_count += 1
            print(f"\nPlanner {plan_count}: {task_id}")
            print(f"  Description: {desc[:150]}")
    
    # Show suggested_tasks field if present
    print("\n" + "=" * 50)
    print("Checking for task explosion source:")
    print("=" * 50)
    max_suggested = 0
    max_task_id = None
    for task in tasks:
        if isinstance(task, dict):
            suggested = task.get('suggested_tasks', [])
            task_id = task.get('id')
        else:
            suggested = getattr(task, 'suggested_tasks', [])
            task_id = getattr(task, 'id', None)
        
        if len(suggested) > max_suggested:
            max_suggested = len(suggested)
            max_task_id = task_id
    
    if max_suggested > 0:
        print(f"\nMax suggested tasks from single task: {max_suggested}")
        print(f"  Task ID: {max_task_id}")
else:
    print("No checkpoints found in database")

conn.close()
