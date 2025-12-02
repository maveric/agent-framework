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


def _evaluate_test_results_with_llm(task: Dict[str, Any], test_results_content: str, objective: str, config: Any) -> Dict[str, Any]:
    """
    Use LLM to evaluate test results against acceptance criteria AND original objective.
    
    Returns:
        dict with keys: passed (bool), feedback (str), suggestions (list)
    """
    # Get orchestrator config for LLM
    # Get orchestrator config for LLM
    from config import OrchestratorConfig
    # config passed in is RunnableConfig, not OrchestratorConfig
    orch_config = OrchestratorConfig()
    
    # Use strategist model (same as director for planning tasks)
    llm = get_llm(orch_config.strategist_model)
    
    # Build evaluation prompt
    acceptance_criteria = task.get("acceptance_criteria", [])
    criteria_text = "\n".join(f"- {c}" for c in acceptance_criteria)
    
    system_prompt = """You are a QA engineer evaluating test results.

Your role: INTEGRATION testing - verify features work TOGETHER.

For small single-feature projects (no integration to test):
- Just verify unit tests were executed properly
- Pass if unit tests are solid and ran successfully
- Don't fail for lack of integration tests when there's only one feature

For multi-feature projects:
- Verify features integrate correctly
- Check cross-feature compatibility

CRITICAL: Distinguish between ACTUAL test execution vs aspirational documentation.

**Signs of ACTUAL execution:**
- Command that was run (e.g., "pytest test.py", "npm test")
- Real output with pass/fail indicators
- Actual error messages or stack traces
- Execution time or counts

**Signs of ASPIRATIONAL documentation:**
- Generic "all tests passed" without specifics
- No command shown
- Bullet points of "what should work" without evidence

Respond in this EXACT format:
VERDICT: PASS or FAIL
FEEDBACK: One sentence explaining why
SUGGESTIONS: Comma-separated list of 2-3 improvements (or "None" if passing)

Be strict:
- FAIL if tests weren't actually executed
- FAIL if tests failed
- FAIL if technology doesn't match user's request
- PASS if unit tests ran successfully and there's no integration to test"""

    user_prompt = f"""Original User Objective: {objective}

Task Description: {task.get('description', 'N/A')}

Acceptance Criteria:
{criteria_text}

Test Results:
{test_results_content}

Evaluate whether the test results satisfy ALL acceptance criteria AND match the original user objective."""

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
            # Robust parsing: handle bolding (**VERDICT:**) and case sensitivity
            clean_line = line.replace("*", "").strip()
            if "VERDICT:" in clean_line.upper():
                verdict = "PASS" if "PASS" in clean_line.upper() else "FAIL"
            elif "FEEDBACK:" in clean_line.upper():
                feedback = clean_line.split("FEEDBACK:", 1)[1].strip()
            elif "SUGGESTIONS:" in clean_line.upper():
                sugg_text = clean_line.split("SUGGESTIONS:", 1)[1].strip()
                if sugg_text and sugg_text.lower() != "none":
                    suggestions = [s.strip() for s in sugg_text.split(",")]
        
        if feedback == "Unable to parse LLM response":
            # If parsing failed, include the raw content for debugging
            feedback = f"Unable to parse LLM response. Raw output:\n{content[:500]}..."

        
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


from langchain_core.runnables import RunnableConfig

def strategist_node(state: Dict[str, Any], config: RunnableConfig = None) -> Dict[str, Any]:
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
            
            # Check 2: Files were modified (Only strict for BUILD tasks)
            elif task.get("phase") == "build" and not aar.get("files_modified"):
                qa_passed = False
                failure_reason = "No files modified"
                qa_verdict = {
                    "passed": False,
                    "feedback": failure_reason,
                    "suggestions": ["Worker should modify files to complete task"]
                }
            
            # Check 3: For TEST tasks, evaluate actual test results
            elif task.get("phase") == "test":
                # Try to read test results file from agents-work/test-results/
                test_results_path = None
                files_modified = aar.get("files_modified", [])
                
                # Look for test results in modified files
                # Prefer agents-work/test-results/ location
                for file in files_modified:
                    if "agents-work/test-results" in file and file.endswith(".md"):
                        if workspace_path:
                            worktree_path = Path(workspace_path) / ".worktrees" / task_id
                            # Handle both relative and absolute paths in files_modified
                            if Path(file).is_absolute():
                                test_results_path = Path(file)
                            else:
                                test_results_path = worktree_path / file
                            break
                
                # Fallback 1: check for test_results.md in root (old location)
                if not test_results_path:
                    for file in files_modified:
                        if "test" in file.lower() and file.endswith(".md"):
                            if workspace_path:
                                worktree_path = Path(workspace_path) / ".worktrees" / task_id
                                if Path(file).is_absolute():
                                    test_results_path = Path(file)
                                else:
                                    test_results_path = worktree_path / file
                                break
                                
                # Read content
                test_content = "No test results found in artifacts."
                if test_results_path:
                    try:
                        if test_results_path.exists():
                            test_content = test_results_path.read_text(encoding="utf-8")
                        else:
                            test_content = f"Test result file listed but not found: {test_results_path}"
                    except Exception as e:
                        test_content = f"Error reading test results: {e}"
                elif task.get("result_path"):
                     # Fallback to result_path if it exists
                     try:
                         rp = Path(task["result_path"])
                         if rp.exists():
                             test_content = rp.read_text(encoding="utf-8")
                     except:
                         pass

                # Call LLM for evaluation
                print(f"  Evaluating test results ({len(test_content)} chars)...", flush=True)
                qa_result = _evaluate_test_results_with_llm(task, test_content, state.get("objective", ""), config)
                
                qa_verdict = {
                    "passed": qa_result["passed"],
                    "overall_feedback": qa_result["feedback"],
                    "criterion_results": [], 
                    "suggested_focus": ", ".join(qa_result["suggestions"])
                }
                
                task["qa_verdict"] = qa_verdict
                
                if qa_result["passed"]:
                    print(f"  [QA PASS]", flush=True)
                    task["status"] = "complete"
                    
                    # Merge to main if not in mock mode
                    wt_manager = state.get("_wt_manager")
                    if wt_manager and not mock_mode:
                        try:
                            result = wt_manager.merge_to_main(task_id)
                            if result.success:
                                print(f"  [MERGED]", flush=True)
                            else:
                                print(f"  [CONFLICT] Merge failed: {result.error_message}", flush=True)
                                task["status"] = "failed"
                                task["qa_verdict"]["passed"] = False
                                task["qa_verdict"]["overall_feedback"] += f"\n\nMERGE FAILURE: {result.error_message}"
                        except Exception as e:
                            print(f"  [MERGE ERROR]: {e}", flush=True)
                            task["status"] = "failed"
                            task["qa_verdict"]["passed"] = False
                            task["qa_verdict"]["overall_feedback"] += f"\n\nMERGE ERROR: {e}"
                else:
                    print(f"  [QA FAIL]: {qa_result['feedback']}", flush=True)
                    task["status"] = "failed"
            else:
                print(f"  [QA FAIL]: {failure_reason}", flush=True)
                task["status"] = "failed"
                if qa_verdict:
                    task["qa_verdict"] = qa_verdict
            
            task["updated_at"] = datetime.now().isoformat()
            updates.append(task)
    
    return {"tasks": updates} if updates else {}
