"""
Agent Orchestrator — Strategist Node
====================================
Version 2.0 — November 2025

QA evaluation node with LLM-based test result evaluation.
"""

from typing import Any, Dict
from datetime import datetime
from pathlib import Path
from state import OrchestratorState
from llm_client import get_llm
from langchain_core.messages import SystemMessage, HumanMessage


def _evaluate_test_results_with_llm(task: Dict[str, Any], test_results_content: str, config: Any) -> Dict[str, Any]:
    """
    Use LLM to evaluate test results against acceptance criteria.
    
    Returns:
        dict with keys: passed (bool), feedback (str), suggestions (list)
    """
    # Get orchestrator config for LLM
    from config import OrchestratorConfig
    orch_config = config if config else OrchestratorConfig()
    
    # Use strategist model (same as director for planning tasks)
    llm = get_llm(orch_config.strategist_model)
    
    # Build evaluation prompt
    acceptance_criteria = task.get("acceptance_criteria", [])
    criteria_text = "\n".join(f"- {c}" for c in acceptance_criteria)
    
    system_prompt = """You are a QA engineer evaluating test results.

Your job is to determine if the test results satisfy the acceptance criteria.

Respond in this EXACT format:
VERDICT: PASS or FAIL
FEEDBACK: One sentence explaining why
SUGGESTIONS: Comma-separated list of 2-3 improvements (or "None" if passing)

Be strict - if tests failed or didn't run properly, mark as FAIL."""

    user_prompt = f"""Task Description: {task.get('description', 'N/A')}

Acceptance Criteria:
{criteria_text}

Test Results:
{test_results_content}

Evaluate whether the test results satisfy ALL acceptance criteria."""

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_prompt)
    ]
    
    try:
        response = llm.invoke(messages)
        content = str(response.content)
        
        # Parse response
        lines = content.strip().split('\n')
        verdict = "FAIL"
        feedback = "Unable to parse LLM response"
        suggestions = []
        
        for line in lines:
            if line.startswith("VERDICT:"):
                verdict = "PASS" if "PASS" in line.upper() else "FAIL"
            elif line.startswith("FEEDBACK:"):
                feedback = line.replace("FEEDBACK:", "").strip()
            elif line.startswith("SUGGESTIONS:"):
                sugg_text = line.replace("SUGGESTIONS:", "").strip()
                if sugg_text and sugg_text.lower() != "none":
                    suggestions = [s.strip() for s in sugg_text.split(",")]
        
        return {
            "passed": verdict == "PASS",
            "feedback": feedback,
            "suggestions": suggestions
        }
    except Exception as e:
        print(f"  [QA ERROR]: LLM evaluation failed: {e}", flush=True)
        return {
            "passed": False,
            "feedback": f"QA evaluation error: {str(e)}",
            "suggestions": ["Fix QA evaluation system"]
        }


def strategist_node(state: Dict[str, Any], config: Dict[str, Any] = None) -> Dict[str, Any]:
    """
    Strategist: LLM-based QA evaluation of test results.
    """
    tasks = state.get("tasks", [])
    updates = []
    mock_mode = state.get("mock_mode", False)
    workspace_path = state.get("_workspace_path")
    
    for task in tasks:
        if task.get("status") == "awaiting_qa":
            task_id = task["id"]
            print(f"Strategist: Evaluating {task_id}", flush=True)
            
            # Basic sanity checks
            qa_passed = True
            failure_reason = None
            qa_verdict = None
            
            # Check 1: AAR exists
            aar = task.get("aar")
            if not aar:
                qa_passed = False
                failure_reason = "No AAR provided"
                qa_verdict = {
                    "passed": False,
                    "feedback": failure_reason,
                    "suggestions": ["Ensure worker returns valid AAR"]
                }
            
            # Check 2: Files were modified
            elif not aar.get("files_modified"):
                qa_passed = False
                failure_reason = "No files modified"
                qa_verdict = {
                    "passed": False,
                    "feedback": failure_reason,
                    "suggestions": ["Worker should modify files to complete task"]
                }
            
            # Check 3: For TEST tasks, evaluate actual test results
            elif task.get("phase") == "test":
                # Try to read test results file
                test_results_path = None
                files_modified = aar.get("files_modified", [])
                
                # Look for test results in modified files
                for file in files_modified:
                    if "test" in file.lower() and file.endswith(".md"):
                        # Construct path to file in worktree
                        if workspace_path:
                            worktree_path = Path(workspace_path) / ".worktrees" / task_id
                            test_results_path = worktree_path / file
                            break
                
                if test_results_path and test_results_path.exists():
                    try:
                        test_results_content = test_results_path.read_text(encoding="utf-8")
                        print(f"  Reading test results from {test_results_path.name}", flush=True)
                        
                        # Use LLM to evaluate
                        qa_verdict = _evaluate_test_results_with_llm(task, test_results_content, state.get("orch_config"))
                        qa_passed = qa_verdict["passed"]
                        failure_reason = qa_verdict["feedback"] if not qa_passed else None
                        
                    except Exception as e:
                        print(f"  [ERROR]: Failed to read test results: {e}", flush=True)
                        qa_passed = False
                        failure_reason = f"Failed to read test results: {e}"
                        qa_verdict = {
                            "passed": False,
                            "feedback": failure_reason,
                            "suggestions": ["Fix test results file access"]
                        }
                else:
                    # No test results file found - fail QA
                    qa_passed = False
                    failure_reason = "No test results file found"
                    qa_verdict = {
                        "passed": False,
                        "feedback": "Test task must produce test_results.md or similar file",
                        "suggestions": ["Create proper test results documentation"]
                    }
            
            # Update task status
            if qa_passed:
                print(f"  [QA PASS]", flush=True)
                task["status"] = "complete"
                if qa_verdict:
                    task["qa_verdict"] = qa_verdict
                
                # Merge to main if not in mock mode
                wt_manager = state.get("_wt_manager")
                if wt_manager and not mock_mode:
                    try:
                        result = wt_manager.merge_to_main(task_id)
                        if result.success:
                            print(f"  [MERGED]", flush=True)
                        else:
                            print(f"  [CONFLICT]", flush=True)
                    except Exception as e:
                        print(f"  [MERGE ERROR]: {e}", flush=True)
            else:
                print(f"  [QA FAIL]: {failure_reason}", flush=True)
                task["status"] = "failed"
                if qa_verdict:
                    task["qa_verdict"] = qa_verdict
            
            task["updated_at"] = datetime.now().isoformat()
            updates.append(task)
    
    return {"tasks": updates} if updates else {}
