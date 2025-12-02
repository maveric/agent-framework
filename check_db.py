import sqlite3

conn = sqlite3.connect('orchestrator.db')
cursor = conn.cursor()

# Get column names
cursor.execute("PRAGMA table_info(checkpoints)")
columns = cursor.fetchall()
print("Checkpoint table schema:")
for col in columns:
    print(f"  {col[1]} ({col[2]})")

# Get the most recent checkpoint metadata
cursor.execute('''
    SELECT thread_id, checkpoint_id, parent_checkpoint_id, type, metadata
    FROM checkpoints 
    ORDER BY checkpoint_id DESC 
    LIMIT 5
''')

print("\nMost recent checkpoints:")
for row in cursor.fetchall():
    thread_id, cp_id, parent_id, cp_type, metadata = row
    print(f"\nThread: {thread_id[:20]}...")
    print(f"  Checkpoint ID: {cp_id}")
    print(f"  Type: {cp_type}")
    if metadata:
        print(f"  Metadata length: {len(metadata)} bytes")

# Count total checkpoints
cursor.execute("SELECT COUNT(*) FROM checkpoints")
total = cursor.fetchone()[0]
print(f"\nTotal checkpoints in database: {total}")

# Count by thread
cursor.execute('''
    SELECT thread_id, COUNT(*) as count
    FROM checkpoints
    GROUP BY thread_id
    ORDER BY count DESC
    LIMIT 10
''')

print("\nTop threads by checkpoint count:")
for thread_id, count in cursor.fetchall():
    print(f"  {thread_id[:30]}...: {count} checkpoints")

conn.close()
