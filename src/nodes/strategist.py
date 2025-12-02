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
    
    task_memories = {}
    
    for task in tasks:
        if task.get("status") == "awaiting_qa":
            task_id = task["id"]
            print(f"QA: Evaluating task {task_id}", flush=True)
            
            # Find test results file
            test_results_path = None
            qa_verdict = None
            test_content = ""
            
            # Get orch config from state
            orch_config = state.get("orch_config")
            objective = state.get("objective", "")
            
            # Check for test results in files_modified (aar)
            if task.get("aar") and task["aar"].get("files_modified"):
                worktree_path = Path(workspace_path) / ".worktrees" / task_id
                
                for file in task["aar"]["files_modified"]:
                    if "test" in file.lower() and file.endswith((".md", ".txt", ".log")):
                        # Handle both relative and absolute paths
                        if Path(file).is_absolute():
                            test_results_path = Path(file)
                        else:
                            test_results_path = worktree_path / file
                        break
            
            if test_results_path and test_results_path.exists():
                try:
                    test_content = test_results_path.read_text(encoding="utf-8")
                    
                    if not mock_mode:
                        # Use LLM to evaluate test results
                        qa_result = _evaluate_test_results_with_llm(task, test_content, objective, config)
                        qa_verdict = {
                            "passed": qa_result["passed"],
                            "overall_feedback": qa_result["feedback"],
                            "suggested_focus": ", ".join(qa_result["suggestions"])
                        }
                    else:
                        # Mock QA always passes
                        qa_verdict = {
                            "passed": True,
                            "overall_feedback": "MOCK: QA skipped",
                            "suggested_focus": ""
                        }
                except Exception as e:
                    print(f"  [ERROR]: Failed to read test results: {e}", flush=True)
                    qa_verdict = {
                        "passed": False,
                        "overall_feedback": f"Failed to read test results: {e}",
                        "suggested_focus": "Fix test results file access"
                    }
            else:
                # No test results found - fail QA
                qa_verdict = {
                    "passed": False,
                    "overall_feedback": "Test task must produce test results file",
                    "suggested_focus": "Create proper test results documentation"
                }
            
            # Update task status based on QA verdict
            if qa_verdict and qa_verdict["passed"]:
                print(f"  [QA PASS]", flush=True)
                task["status"] = "complete"
                task["qa_verdict"] = qa_verdict
                
                # Merge to main
                wt_manager = state.get("_wt_manager")
                if wt_manager and not mock_mode:
                    try:
                        result = wt_manager.merge_to_main(task_id)
                        if result.success:
                            print(f"  [MERGED] Task {task_id} merged successfully", flush=True)
                        else:
                            print(f"  [MERGE CONFLICT]: {result.error_message}", flush=True)
                            task["status"] = "failed"
                            task["qa_verdict"]["passed"] = False
                            task["qa_verdict"]["overall_feedback"] += f"\n\nMERGE ERROR: {result.error_message}"
                    except Exception as e:
                        print(f"  [MERGE ERROR]: {e}", flush=True)
                        task["status"] = "failed"
                        task["qa_verdict"]["passed"] = False
                        task["qa_verdict"]["overall_feedback"] += f"\n\nMERGE ERROR: {e}"
            else:
                print(f"  [QA FAIL]: {qa_verdict['overall_feedback'] if qa_verdict else 'Unknown error'}", flush=True)
                task["status"] = "failed"
                task["qa_verdict"] = qa_verdict
            
            task["updated_at"] = datetime.now().isoformat()
            updates.append(task)
            
            # Append QA logs to task memories
            if qa_verdict:
                qa_messages = [
                    SystemMessage(content="QA Evaluation Process"),
                    HumanMessage(content=f"Evaluating task {task_id} against criteria:\n" + "\n".join(task.get("acceptance_criteria", []))),
                    HumanMessage(content=f"Test Results:\n{test_content[:500]}..." if test_content else "No test content"),
                    SystemMessage(content=f"Verdict: {'PASS' if qa_verdict['passed'] else 'FAIL'}\nFeedback: {qa_verdict['overall_feedback']}")
                ]
                task_memories[task_id] = qa_messages
            
    # PENDING REORG: Show countdown after task completion
    pending_reorg = state.get("pending_reorg", False)
    if pending_reorg and updates:
        # Count remaining active tasks
        all_tasks_raw = state.get("tasks", [])
        from orchestrator_types import _dict_to_task, TaskStatus
        all_tasks = [_dict_to_task(t) for t in all_tasks_raw]
        # Count active tasks, excluding the ones we just updated
        updated_ids = {u["id"] for u in updates}
        remaining_active = [t for t in all_tasks if t.status == TaskStatus.ACTIVE and t.id not in updated_ids]
        
        completed_id = updates[0]["id"][:8]
        print(f"Director: task_{completed_id} finished. Reorg pending. Waiting on {len(remaining_active)} tasks to finish. No new tasks started.", flush=True)  

    return {"tasks": updates, "task_memories": task_memories} if updates else {}
