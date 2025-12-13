"""
Agent Orchestrator — Strategist Node
====================================
Version 2.0 — November 2025

QA evaluation node with LLM-based test result evaluation.
"""

import logging
from typing import Any, Dict
from datetime import datetime
from pathlib import Path
from state import OrchestratorState
from llm_client import get_llm
from langchain_core.messages import SystemMessage, HumanMessage

logger = logging.getLogger(__name__)


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
    
    system_prompt = """You are a QA engineer who evaluates test execution results.

YOUR ROLE: Adaptive evaluator - you check whatever test type the task requires:
- Early in projects: Unit tests, component tests
- Mid-project: Integration tests, API tests
- Later stages: E2E tests, full-stack tests

YOUR JOB: Verify the test worker actually RAN tests AND those tests PASSED.

═══════════════════════════════════════════════════════════
STEP 1: Check for ACTUAL EXECUTION
═══════════════════════════════════════════════════════════

Tests must have actually run, not just be documented.

✅ PASS if you see:
• Command that was executed (e.g., "pytest test.py -v", "npm test", "cypress run")
• Real terminal output with pass/fail counts
• Actual error messages or stack traces (if failures occurred)
• Test names, execution time, or test result summary

❌ FAIL if you see:
• Generic "all tests passed" with NO evidence
• No command shown, just code files
• Bullet points of "what should work" without proof
• Just test code without showing it was executed

═══════════════════════════════════════════════════════════
STEP 2: Check PASS/FAIL STATUS
═══════════════════════════════════════════════════════════

✅ PASS if:
• All executed tests passed (e.g., "25/25 passed", "100% pass rate", "0 failed")

❌ FAIL if:
• ANY test failed (e.g., "24 passed, 1 failed")
• Tests errored or couldn't run
• Execution was incomplete

═══════════════════════════════════════════════════════════
STEP 3: Check SCOPE MATCH
═══════════════════════════════════════════════════════════

Compare results ONLY to TASK DESCRIPTION and ACCEPTANCE CRITERIA.

✅ PASS if tests match what THIS TASK asked for:
• Task: "unit test CRUD" → Backend unit tests with CRUD coverage ✓
• Task: "E2E test login flow" → Browser automation of login ✓
• Task: "test drag-and-drop" → UI interaction tests ✓
• Task: "integration test API + DB" → Tests showing API/DB integration ✓

❌ FAIL if tests don't match THIS TASK:
• Task asks for unit tests → Only E2E tests shown ✗
• Task asks for E2E tests → Only unit tests shown ✗
• Task asks for feature X → Tests only cover feature Y ✗

🚨 CRITICAL: IGNORE requirements from the PROJECT OBJECTIVE that are NOT in THIS TASK.
Example: If project objective mentions "E2E Cypress tests" but THIS TASK says "unit test backend",
then backend unit tests = PASS. Don't fail for missing E2E tests.

═══════════════════════════════════════════════════════════
RESPONSE FORMAT
═══════════════════════════════════════════════════════════

Respond in this EXACT format:
VERDICT: PASS or FAIL
FEEDBACK: [Step 1: Execution check? Step 2: Pass/fail? Step 3: Scope match? Give verdict for each]
SUGGESTIONS: [Comma-separated improvements, or "None" if passing]"""

    user_prompt = f"""═══════════════════════════════════════════════════════════
TASK SCOPE (PRIMARY - this is what you're evaluating)
═══════════════════════════════════════════════════════════
{task.get('description', 'N/A')}

ACCEPTANCE CRITERIA (MUST SATISFY):
{criteria_text}

═══════════════════════════════════════════════════════════
TEST RESULTS TO EVALUATE
═══════════════════════════════════════════════════════════
{test_results_content}

═══════════════════════════════════════════════════════════
PROJECT CONTEXT (for info only - NOT this task's scope)
═══════════════════════════════════════════════════════════
{objective}

Use the 3-step evaluation process above."""

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
            
            # Parse response using SECTION-BASED parsing
            # CRITICAL: LLM often puts multi-line feedback, must capture all of it
            verdict = "FAIL"
            feedback = "Unable to parse LLM response"
            suggestions = []
            
            # Normalize: remove markdown bold markers
            normalized_content = content.replace("*", "")
            
            # Extract VERDICT (usually single line)
            if "VERDICT:" in normalized_content.upper():
                verdict_line = normalized_content.upper().split("VERDICT:", 1)[1].split("\n")[0]
                verdict = "PASS" if "PASS" in verdict_line else "FAIL"
            
            # Extract FEEDBACK section (multi-line until SUGGESTIONS or end)
            if "FEEDBACK:" in normalized_content.upper():
                content_upper = normalized_content.upper()
                feedback_start = content_upper.find("FEEDBACK:")
                
                # Handle case insensitivity by finding position in original
                # Find the actual position in the normalized string
                after_feedback = normalized_content[feedback_start + len("FEEDBACK:"):]
                
                # Find where SUGGESTIONS starts (if any)
                suggestions_pos = after_feedback.upper().find("SUGGESTIONS:")
                if suggestions_pos != -1:
                    feedback = after_feedback[:suggestions_pos].strip()
                else:
                    feedback = after_feedback.strip()
            
            # Extract SUGGESTIONS (everything after SUGGESTIONS:)
            if "SUGGESTIONS:" in normalized_content.upper():
                content_upper = normalized_content.upper()
                suggestions_start = content_upper.find("SUGGESTIONS:")
                sugg_text = normalized_content[suggestions_start + len("SUGGESTIONS:"):].strip()
                # Take first line or comma-separated values
                first_line = sugg_text.split("\n")[0].strip()
                if first_line and first_line.lower() != "none":
                    suggestions = [s.strip() for s in first_line.split(",")]
            
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
                    logger.info(f"  [QA RETRY] Parse failed (attempt {attempt + 1}/{MAX_RETRIES}), retrying...")
                    continue
                else:
                    # Final attempt failed, include raw output
                    logger.error(f"  [QA ERROR] Parse failed after {MAX_RETRIES} attempts")
                    feedback = f"Unable to parse LLM response after {MAX_RETRIES} attempts. Raw output:\n{content[:500]}..."
                    return {
                        "passed": False,
                        "feedback": feedback,
                        "suggestions": []
                    }


        except Exception as e:
            if attempt < MAX_RETRIES - 1:
                logger.info(f"  [QA RETRY] LLM evaluation exception (attempt {attempt + 1}/{MAX_RETRIES}): {e}")
                continue
            else:
                logger.error(f"  [QA ERROR]: LLM evaluation failed after {MAX_RETRIES} attempts: {e}")
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

    # CRITICAL: Import copy for creating task copies
    # Strategist should NOT modify state directly - dispatch is the sole place for that
    import copy

    for task_original in tasks:
        if task_original.get("status") == "awaiting_qa":
            # Create a COPY to modify - don't mutate state directly
            task = copy.deepcopy(task_original)
            task_id = task["id"]
            logger.info(f"QA: Evaluating task {task_id}")
            
            # Find test results file
            test_results_path = None
            qa_verdict = None
            test_content = ""
            
            # Get orch config from state
            orch_config = state.get("orch_config")
            objective = state.get("objective", "")
            
            # Check for test results in files_modified (aar)
            if task.get("aar") and task["aar"].get("files_modified"):
                worktree_base = state.get("_worktree_base_path")
                if worktree_base:
                    worktree_path = Path(worktree_base) / task_id
                else:
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
                                logger.info(f"  [QA] Found test results in main workspace (post-merge): {file}")
                            else:
                                # Try both paths with the file as-is
                                test_results_path = main_file  # Default to main
                        break
            
            # PROACTIVE SEARCH: If no test results found in AAR, check expected location
            # This handles cases where file was written but not tracked in files_modified
            if not test_results_path or not test_results_path.exists():
                task_filename = task.get("component", task_id)
                expected_file = f"agents-work/test-results/test-{task_filename}.md"
                
                # Get worktree base path (may not have been set if no AAR files_modified)
                worktree_base = state.get("_worktree_base_path")
                if worktree_base:
                    worktree_path = Path(worktree_base) / task_id
                else:
                    worktree_path = Path(workspace_path) / ".worktrees" / task_id
                worktree_expected = worktree_path / expected_file
                main_expected = Path(workspace_path) / expected_file


                if worktree_expected.exists():
                    test_results_path = worktree_expected
                    logger.info(f"  [QA] Found test results at expected worktree path: {expected_file}")
                elif main_expected.exists():
                    test_results_path = main_expected
                    logger.info(f"  [QA] Found test results at expected main path: {expected_file}")
            
            # Check for PROACTIVE FIXES (suggested_tasks) from the worker
            # If the worker suggested fixes, we skip strict QA and reset to PLANNED
            # so the Director can integrate the new tasks into the tree.
            # EXCEPTION: Planners naturally produce suggested_tasks as their output, so we don't reset them.
            if task.get("suggested_tasks") and task.get("assigned_worker_profile") != "planner_worker":
                logger.info(f"  [QA SKIP] Task {task_id} has suggested tasks. Resetting to PLANNED for Director integration.")
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
                        logger.error(f"  [ERROR]: Failed to read test results: {e}")
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
                    logger.error(f"  [QA FAIL]: Missing test results file at {expected_path}")
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
                    logger.info(f"  [QA PASS] Validated work for {task_phase} task {task_id}")
                    qa_verdict = {
                        "passed": True,
                        "overall_feedback": f"Validated work (files modified: {len(files_modified)})",
                        "suggested_focus": ""
                    }
                else:
                    # FAIL: No work done
                    logger.error(f"  [QA FAIL] No files modified for {task_phase} task {task_id}")
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
                logger.info(f"  [QA PASS]")
                task["status"] = "pending_complete"  # Director will confirm
                task["qa_verdict"] = qa_verdict
                
                # Merge to main
                wt_manager = state.get("_wt_manager")
                if wt_manager and not mock_mode:
                    try:
                        result = await wt_manager.merge_to_main(task_id)
                        if result.success:
                            logger.info(f"  [MERGED] Task {task_id} merged successfully")
                        else:
                            logger.error(f"  [MERGE CONFLICT]: {result.error_message}")
                            task["status"] = "pending_failed"  # Director will confirm
                            task["qa_verdict"]["passed"] = False
                            task["qa_verdict"]["overall_feedback"] += f"\n\nMERGE ERROR: {result.error_message}"
                    except Exception as e:
                        logger.error(f"  [MERGE ERROR]: {e}")
                        task["status"] = "pending_failed"  # Director will confirm
                        task["qa_verdict"]["passed"] = False
                        task["qa_verdict"]["overall_feedback"] += f"\n\nMERGE ERROR: {e}"
            else:
                logger.error(f"  [QA FAIL]: {qa_verdict['overall_feedback'] if qa_verdict else 'Unknown error'}")
                task["status"] = "pending_failed"  # Director will confirm
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
        logger.info(f"Director: task_{completed_id} finished. Reorg pending. Waiting on {len(remaining_active)} tasks to finish. No new tasks started.")

    return {"tasks": updates, "task_memories": task_memories} if updates else {}
