import aiosqlite
import asyncio

async def check_db():
    conn = await aiosqlite.connect("orchestrator.db")
    cursor = await conn.cursor()
    
    # Check tables
    await cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = await cursor.fetchall()
    print(f"Tables: {tables}")
    
    # Check checkpoints count
    await cursor.execute("SELECT COUNT(*) FROM checkpoints")
    count = await cursor.fetchone()
    print(f"Checkpoint count: {count[0]}")
    
    # Check some thread_ids
    await cursor.execute("SELECT DISTINCT thread_id FROM checkpoints LIMIT 5")
    threads = await cursor.fetchall()
    print(f"Sample thread_ids: {threads}")
    
    await conn.close()

asyncio.run(check_db())
