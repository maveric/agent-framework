import sqlite3
import json

conn = sqlite3.connect('orchestrator.db')

# Query for the run
cur = conn.execute("SELECT state_json FROM runs WHERE run_id = 'run_1bc26e7e'")
row = cur.fetchone()

if row:
    state = json.loads(row[0]) if row[0] else {}
    task_memories = state.get('task_memories', {})
    print(f'Total tasks with memories: {len(task_memories)}')
    
    # Check task with only QA vs full logs
    for task_id in ['task_8febc77b', 'task_392c8d4d']:
        msgs = task_memories.get(task_id, [])
        print(f'\n--- {task_id} ---')
        print(f'Total messages: {len(msgs)}')
        for i, m in enumerate(msgs[:10]):
            msg_type = m.get('type', '?')
            content = str(m.get('content', ''))[:60] if m.get('content') else '[no content]'
            print(f'  {i}: {msg_type} - {content}')
else:
    print('No run found')

conn.close()
