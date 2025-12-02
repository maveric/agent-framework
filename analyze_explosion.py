import sqlite3
import msgpack
from collections import Counter

conn = sqlite3.connect('orchestrator.db')
cursor = conn.cursor()

# Get the most recent checkpoint for the thread with most checkpoints
cursor.execute('''
    SELECT thread_id, checkpoint, metadata
    FROM checkpoints 
    WHERE thread_id = '282271ab-81a7-44fb-b476-9a635f7d828d'
    ORDER BY checkpoint_id DESC 
    LIMIT 1
''')

row = cursor.fetchone()
if row:
    thread_id, checkpoint_data, metadata_data = row
    
    print(f"Thread ID: {thread_id}\n")
    
    # Decode msgpack
    checkpoint = msgpack.unpackb(checkpoint_data, raw=False)
    
    # Get channel values
    channel_values = checkpoint.get('channel_values', {})
    
    # Get tasks
    tasks = channel_values.get('tasks', [])
    print(f"Total tasks: {len(tasks)}\n")
    
    # Analyze distribution
    phases = Counter()
    statuses = Counter()
    workers = Counter()
    
    for task in tasks:
        phase = task.get('phase', 'unknown')
        status = task.get('status', 'unknown')
        worker = task.get('assigned_worker_profile', 'unknown')
        
        phases[phase] += 1
        statuses[status] += 1
        workers[worker] += 1
    
    print("=" * 60)
    print("TASK DISTRIBUTION ANALYSIS")
    print("=" * 60)
    
    print("\nBy Phase:")
    for phase, count in phases.most_common():
        print(f"  {phase}: {count}")
    
    print("\nBy Status:")
    for status, count in statuses.most_common():
        print(f"  {status}: {count}")
        
    print("\nBy Worker Type:")
    for worker, count in workers.most_common():
        print(f"  {worker}: {count}")
    
    # Find planner tasks and count their suggested_tasks
    print("\n" + "=" * 60)
    print("PLANNER TASK ANALYSIS (Task Creation)")
    print("=" * 60)
    
    planner_tasks = [t for t in tasks if t.get('assigned_worker_profile') == 'planner_worker']
    print(f"\nTotal planner tasks: {len(planner_tasks)}")
    
    # Count suggested tasks
    for i, task in enumerate(planner_tasks[:10], 1):  # Show first 10
        task_id = task.get('id', 'unknown')
        desc = task.get('description', '')[:80]
        status = task.get('status', 'unknown')
        
        # Check if task has suggested_tasks (this might be in the state)
        # For now, let's see the description
        print(f"\nPlanner {i}: {task_id}")
        print(f"  Status: {status}")
        print(f"  Description: {desc}...")
    
    # Find test_worker tasks
    print("\n" + "=" * 60)
    print("TEST WORKER ERROR ANALYSIS")
    print("=" * 60)
    
    test_tasks = [t for t in tasks if t.get('assigned_worker_profile') == 'test_worker']
    print(f"\nTotal test_worker tasks: {len(test_tasks)}")
    
    # Show failed/error test tasks
    failed_tests = [t for t in test_tasks if t.get('status') in ['failed', 'failed_qa']]
    print(f"Failed test tasks: {len(failed_tests)}")
    
    for i, task in enumerate(failed_tests[:3], 1):  # Show first 3 failures
        task_id = task.get('id', 'unknown')
        desc = task.get('description', '')[:80]
        status = task.get('status', 'unknown')
        
        print(f"\nFailed Test {i}: {task_id}")
        print(f"  Status: {status}")
        print(f"  Description: {desc}...")
        
        # Check for QA verdict or error messages
        qa_verdict = task.get('qa_verdict')
        if qa_verdict:
            feedback = qa_verdict.get('overall_feedback', '')[:200]
            print(f"  QA Feedback: {feedback}...")
    
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"Total tasks created: {len(tasks)}")
    print(f"This is excessive and indicates task explosion.")
    print(f"\nLikely causes:")
    print(f"  1. Planner tasks creating too many subtasks")
    print(f"  2. No limits on task creation depth")
    print(f"  3. Sub-planners creating more sub-planners recursively")

else:
    print("No checkpoint found")

conn.close()
