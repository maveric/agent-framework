import sqlite3

# Connect to database
conn = sqlite3.connect('orchestrator.db')
cursor = conn.cursor()

# Get all tables
cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = cursor.fetchall()
print(f"Found tables: {tables}")

# Clear checkpoints and writes
cursor.execute("DELETE FROM checkpoints")
cursor.execute("DELETE FROM writes")
conn.commit()

print("✅ Database cleared! All checkpoints and writes deleted.")
conn.close()
