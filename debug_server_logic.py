import os
import sys
import sqlite3
from langgraph.checkpoint.sqlite import SqliteSaver

# Add src to path
sys.path.append(os.path.join(os.getcwd(), "src"))

# Mock OrchestratorState if needed, but we just need the checkpointer to work
# We need to make sure we can unpickle the state if it uses custom classes
# So we need to import them
from src.state import OrchestratorState
from src.orchestrator_types import Task, TaskStatus, TaskPhase

def debug_list_runs():
    db_path = "orchestrator.db"
    print(f"Opening DB at {db_path}")
    
    conn = sqlite3.connect(db_path, check_same_thread=False)
    checkpointer = SqliteSaver(conn)
    
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT thread_id FROM checkpoints")
    thread_ids = [row[0] for row in cursor.fetchall()]
    print(f"Found thread_ids: {thread_ids}")
    
    for thread_id in thread_ids:
        print(f"\nChecking thread: {thread_id}")
        config = {"configurable": {"thread_id": thread_id}}
        state_snapshot = checkpointer.get(config)
        
        # print(f"Snapshot: {state_snapshot}")
        if state_snapshot:
            print(f"Snapshot keys: {state_snapshot.keys()}")
            if 'channel_values' in state_snapshot:
                state = state_snapshot['channel_values']
                print(f"Run ID: {state.get('run_id')}")
                print(f"Objective: {state.get('objective')}")
                print(f"Status: {state.get('strategy_status')}")

if __name__ == "__main__":
    debug_list_runs()
