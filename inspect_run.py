import sqlite3
import json

conn = sqlite3.connect('orchestrator.db')
cursor = conn.cursor()

# Find the checkpoint for run_377c55cc
cursor.execute('''
    SELECT checkpoint, metadata 
    FROM checkpoints 
    WHERE thread_id LIKE ? 
    ORDER BY checkpoint_id DESC 
    LIMIT 1
''', ('%377c55cc%',))

row = cursor.fetchone()
if row:
    checkpoint_data, metadata = row
    
    # Parse the checkpoint
    import pickle
    state = pickle.loads(checkpoint_data)
    
    # Count tasks
    tasks = state.get('channel_values', {}).get('tasks', [])
    print(f"Total tasks in run: {len(tasks)}")
    print(f"\nTask breakdown by phase and status:")
    
    from collections import Counter
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
    
    print("\nBy Phase:")
    for phase, count in phases.most_common():
        print(f"  {phase}: {count}")
    
    print("\nBy Status:")
    for status, count in statuses.most_common():
        print(f"  {status}: {count}")
        
    print("\nBy Worker:")
    for worker, count in workers.most_common():
        print(f"  {worker}: {count}")
    
    # Find test_worker failures
    print("\n\nTest worker tasks:")
    for task in tasks:
        if task.get('assigned_worker_profile') == 'test_worker':
            print(f"\nTask ID: {task.get('id')}")
            print(f"  Status: {task.get('status')}")
            print(f"  Description: {task.get('description', '')[:100]}")
            if task.get('qa_verdict'):
                verdict = task['qa_verdict']
                print(f"  QA Passed: {verdict.get('passed')}")
                print(f"  QA Feedback: {verdict.get('overall_feedback', '')[:150]}")

else:
    print("Run not found")

conn.close()
