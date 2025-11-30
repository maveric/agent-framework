"""
Agent Orchestrator — Strategist Node
====================================
Version 1.0 — November 2025

QA evaluation node.
"""

from typing import Any, Dict
from datetime import datetime
from state import OrchestratorState


def strategist_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Strategist: QA evaluation (auto-approve for now).
    """
    tasks = state.get("tasks", [])
    updates = []
    
    for task in tasks:
        if task.get("status") == "awaiting_qa":
            print(f"Strategist: Auto-approving {task['id']}", flush=True)
            task["status"] = "complete"
            task["updated_at"] = datetime.now().isoformat()
            updates.append(task)
            
            # Merge to main if not in mock mode
            wt_manager = state.get("_wt_manager")
            if wt_manager and not state.get("mock_mode", False):
                try:
                    result = wt_manager.merge_to_main(task["id"])
                    if result.success:
                        print(f"  Merged {task['id']} to main", flush=True)
                    else:
                        print(f"  Warning: Merge conflict for {task['id']}", flush=True)
                except Exception as e:
                    print(f"  Warning: Failed to merge: {e}", flush=True)
    
    return {"tasks": updates} if updates else {}
