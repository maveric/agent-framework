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


async def _evaluate_test_results_with_llm(task: Dict[str, Any], test_results_content: str, objective: str, config: Any) -> Dict[str, Any]:
    """
    Use LLM to evaluate test results against acceptance criteria AND original objective (async version).
    
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
FEEDBACK: Detailed description all reasons for verdict
SUGGESTIONS: Comma-separated list of up to 7 improvements (or "None" if passing)

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
    
    # RETRY LOGIC: LLM sometimes returns malformed responses
    # Retry up to 3 times before giving up
    MAX_RETRIES = 3
    
    for attempt in range(MAX_RETRIES):
        try:
            response = await llm.ainvoke(messages)
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
            
            # Check if parsing succeeded
            if feedback != "Unable to parse LLM response":
                # Success! Return the parsed result
                return {
                    "passed": verdict == "PASS",
                    "feedback": feedback,
                    "suggestions": suggestions
                }
            else:
                # Parsing failed - retry
                if attempt < MAX_RETRIES - 1:
                    print(f"  [QA RETRY] Parse failed (attempt {attempt + 1}/{MAX_RETRIES}), retrying...", flush=True)
                    continue
                else:
                    # Final attempt failed, include raw output
                    print(f"  [QA ERROR] Parse failed after {MAX_RETRIES} attempts", flush=True)
                    feedback = f"Unable to parse LLM response after {MAX_RETRIES} attempts. Raw output:\n{content[:500]}..."
                    return {
                        "passed": False,
                        "feedback": feedback,
                        "suggestions": []
                    }
                    
        except Exception as e:
            if attempt < MAX_RETRIES - 1:
                print(f"  [QA RETRY] LLM evaluation exception (attempt {attempt + 1}/{MAX_RETRIES}): {e}", flush=True)
                continue
            else:
                print(f"  [QA ERROR]: LLM evaluation failed after {MAX_RETRIES} attempts: {e}", flush=True)
                return {

            "passed": False,
            "feedback": f"QA evaluation error: {str(e)}",
            "suggestions": ["Fix QA evaluation system"]
        }


from langchain_core.runnables import RunnableConfig

async def strategist_node(state: Dict[str, Any], config: RunnableConfig = None) -> Dict[str, Any]:
    """
    Strategist: LLM-based QA evaluation of test results (async version).
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
                            # Try worktree first, then fall back to main workspace
                            # (after merge, files are in main, not worktree)
                            worktree_file = worktree_path / file
                            main_file = Path(workspace_path) / file
                            
                            if worktree_file.exists():
                                test_results_path = worktree_file
                            elif main_file.exists():
                                test_results_path = main_file
                                print(f"  [QA] Found test results in main workspace (post-merge): {file}", flush=True)
                            else:
                                # Try both paths with the file as-is
                                test_results_path = main_file  # Default to main
                        break
            
            # PROACTIVE SEARCH: If no test results found in AAR, check expected location
            # This handles cases where file was written but not tracked in files_modified
            if not test_results_path or not test_results_path.exists():
                task_filename = task.get("component", task_id)
                expected_file = f"agents-work/test-results/test-{task_filename}.md"
                
                worktree_path = Path(workspace_path) / ".worktrees" / task_id
                worktree_expected = worktree_path / expected_file
                main_expected = Path(workspace_path) / expected_file
                
                if worktree_expected.exists():
                    test_results_path = worktree_expected
                    print(f"  [QA] Found test results at expected worktree path: {expected_file}", flush=True)
                elif main_expected.exists():
                    test_results_path = main_expected
                    print(f"  [QA] Found test results at expected main path: {expected_file}", flush=True)
            
            # Check for PROACTIVE FIXES (suggested_tasks) from the worker
            # If the worker suggested fixes, we skip strict QA and reset to PLANNED
            # so the Director can integrate the new tasks into the tree.
            # EXCEPTION: Planners naturally produce suggested_tasks as their output, so we don't reset them.
            if task.get("suggested_tasks") and task.get("assigned_worker_profile") != "planner_worker":
                print(f"  [QA SKIP] Task {task_id} has suggested tasks. Resetting to PLANNED for Director integration.", flush=True)
                task["status"] = "planned"
                task["updated_at"] = datetime.now().isoformat()
                updates.append(task)
                
                # Add a log entry
                qa_messages = [
                    SystemMessage(content="QA Evaluation Process"),
                    HumanMessage(content=f"Worker proposed {len(task.get('suggested_tasks'))} fix tasks. Deferring to Director for integration."),
                    SystemMessage(content="Verdict: PENDING INTEGRATION\nAction: Reset to PLANNED")
                ]
                task_memories[task_id] = qa_messages
                continue

            # Check phase - only TEST tasks strictly require test result files
            task_phase = task.get("phase", "build") # Default to build if not set
            
            if task_phase == "test":
                # STRICT QA for TEST tasks
                if test_results_path and test_results_path.exists():
                    try:
                        test_content = test_results_path.read_text(encoding="utf-8")
                        
                        if not mock_mode:
                            # Use LLM to evaluate test results
                            qa_result = await _evaluate_test_results_with_llm(task, test_content, objective, config)
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
                    # No test results found - FAIL
                    expected_path = f"agents-work/test-results/test-{task.get('component', task_id)}.md"
                    qa_verdict = {
                        "passed": False,
                        "overall_feedback": (
                            f"MISSING TEST RESULTS FILE: No test results documentation found.\n"
                            f"REQUIRED: {expected_path} with actual test output."
                        ),
                        "suggested_focus": "Write test results to agents-work/test-results/"
                    }
                    print(f"  [QA FAIL]: Missing test results file at {expected_path}", flush=True)
            else:
                # SMART VALIDATION for BUILD/PLAN tasks
                # Check if task actually DID something
                aar = task.get("aar", {})
                files_modified = aar.get("files_modified", [])
                
                # Check for "explicit completion" (where agent said "already implemented")
                is_explicitly_completed = False
                if aar.get("summary", "").startswith("ALREADY IMPLEMENTED:"):
                     is_explicitly_completed = True
                
                if files_modified or is_explicitly_completed:
                    print(f"  [QA PASS] Validated work for {task_phase} task {task_id}", flush=True)
                    qa_verdict = {
                        "passed": True,
                        "overall_feedback": f"Validated work (files modified: {len(files_modified)})",
                        "suggested_focus": ""
                    }
                else:
                    # FAIL: No work done
                    print(f"  [QA FAIL] No files modified for {task_phase} task {task_id}", flush=True)
                    qa_verdict = {
                        "passed": False,
                        "overall_feedback": (
                            "NO WORK DETECTED: Task marked complete but no files were modified and "
                            "no 'report_existing_implementation' tool was used.\n\n"
                            "REQUIRED: You must either write code (using write_file) or explicitly "
                            "report an existing implementation."
                        ),
                        "suggested_focus": "Use write_file or report_existing_implementation"
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
            
            # CRITICAL: APPEND QA logs to existing task memories, don't overwrite!
            # The worker already populated task_memories with the full conversation
            if qa_verdict:
                qa_messages = [
                    SystemMessage(content="QA Evaluation Process"),
                    HumanMessage(content=f"Evaluating task {task_id} against criteria:\n" + "\n".join(task.get("acceptance_criteria", []))),
                    HumanMessage(content=f"Test Results:\n{test_content[:500]}..." if test_content else "No test content"),
                    SystemMessage(content=f"Verdict: {'PASS' if qa_verdict['passed'] else 'FAIL'}\nFeedback: {qa_verdict['overall_feedback']}")
                ]
                # CRITICAL: Return ONLY the new QA messages. 
                # The server's reducer will handle appending them to the existing worker history.
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
