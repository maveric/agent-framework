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
    Strategist: QA evaluation with basic validation.
    """
    tasks = state.get("tasks", [])
    updates = []
    mock_mode = state.get("mock_mode", False)
    
    for task in tasks:
        if task.get("status") == "awaiting_qa":
            task_id = task["id"]
            print(f"Strategist: Evaluating {task_id}", flush=True)
            
            # Basic QA checks
            qa_passed = True
            failure_reason = None
            
            # Check 1: AAR exists
            aar = task.get("aar")
            if not aar:
                qa_passed = False
                failure_reason = "No AAR provided"
            
            # Check 2: Files were modified
            elif not aar.get("files_modified"):
                qa_passed = False
                failure_reason = "No files modified"
            
            # Check 3: Result path exists
            elif not task.get("result_path"):
                qa_passed = False
                failure_reason = "No result path specified"
            
            # Update task status
            if qa_passed:
                print(f"  ✓ QA Passed", flush=True)
                task["status"] = "complete"
                
                # Merge to main if not in mock mode
                wt_manager = state.get("_wt_manager")
                if wt_manager and not mock_mode:
                    try:
                        result = wt_manager.merge_to_main(task_id)
                        if result.success:
                            print(f"  ✓ Merged to main", flush=True)
                        else:
                            print(f"  ⚠ Merge conflict", flush=True)
                    except Exception as e:
                        print(f"  ⚠ Merge failed: {e}", flush=True)
            else:
                print(f"  ✗ QA Failed: {failure_reason}", flush=True)
                task["status"] = "failed"
            
            task["updated_at"] = datetime.now().isoformat()
            updates.append(task)
    
    return {"tasks": updates} if updates else {}
