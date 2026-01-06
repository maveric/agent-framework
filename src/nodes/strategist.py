"""
Agent Orchestrator — Strategist Node
====================================
Version 2.0 — November 2025

QA evaluation node with LLM-based test result evaluation.
"""

import logging
import uuid
from typing import Any, Dict, List, Optional
from datetime import datetime
from pathlib import Path
from state import OrchestratorState
from llm_client import get_llm
from langchain_core.messages import SystemMessage, HumanMessage
from orchestrator_types import TaskStatus, TaskPhase, WorkerProfile

logger = logging.getLogger(__name__)


def _create_merge_task(
    original_task: Dict[str, Any],
    conflict_files: List[str],
    error_message: str
) -> Dict[str, Any]:
    """
    Create a merge resolution task to handle git conflicts.

    Args:
        original_task: The task that encountered the merge conflict
        conflict_files: List of files with conflicts
        error_message: The error message from the failed rebase/merge

    Returns:
        A new task dict configured for merge conflict resolution
    """
    original_id = original_task["id"]
    merge_task_id = f"merge_{uuid.uuid4().hex[:8]}"

    # Build a detailed description for the merge agent
    conflict_details = "\n".join(f"  - {f}" for f in conflict_files) if conflict_files else "  (files not specified)"

    description = f"""**MERGE CONFLICT RESOLUTION TASK**

The task "{original_task.get('title', original_id)}" (ID: {original_id}) completed successfully,
but encountered conflicts when trying to merge its changes into the main branch.

**Original Task Description:**
{original_task.get('description', 'No description available')}

**Conflict Error:**
{error_message}

**Conflicting Files:**
{conflict_details}

**Your Mission:**
1. Analyze the conflict between the task branch and main branch
2. Understand what both versions were trying to accomplish
3. Create a merged version that preserves both sets of changes
4. Stage the resolved files using `git add`

After you resolve the conflicts, the system will commit and merge your changes.
"""

    return {
        "id": merge_task_id,
        "title": f"Resolve merge conflicts from {original_task.get('title', original_id)[:30]}",
        "component": original_task.get("component", "merge"),
        "phase": TaskPhase.BUILD.value,
        "description": description,
        "status": TaskStatus.READY.value,  # Ready immediately since original task is done
        "depends_on": [original_id],  # Depends on original task
        "dependency_queries": [],
        "priority": 10,  # High priority - blocks dependent tasks
        "assigned_worker_profile": WorkerProfile.MERGER.value,
        "retry_count": 0,
        "max_retries": 3,
        "acceptance_criteria": [
            "All merge conflicts are resolved",
            "Both versions' changes are preserved where possible",
            "Resolved files are staged with git add",
            "Code still compiles/runs after merge"
        ],
        "result_path": None,
        "qa_verdict": None,
        "aar": None,
        "blocked_reason": None,
        "escalation": None,
        "checkpoint": None,
        "waiting_for_tasks": [],
        "branch_name": original_task.get("branch_name"),  # Use same branch
        "worktree_path": original_task.get("worktree_path"),  # Use same worktree
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat(),
        "started_at": None,
        "completed_at": None,
        # CRITICAL: Tell worker to use original task's worktree (has the branch with changes)
        "_use_worktree_task_id": original_id,
        # Custom fields for merge context
        "_merge_context": {
            "original_task_id": original_id,
            "conflict_files": conflict_files,
            "error_message": error_message
        }
    }


def _rewire_dependencies_for_merge(
    all_tasks: List[Dict[str, Any]],
    original_task_id: str,
    merge_task_id: str
) -> int:
    """
    Update all tasks that depend on the original task to depend on the merge task instead.

    This ensures that dependent tasks wait for the merge to complete before starting.

    Args:
        all_tasks: List of all task dicts
        original_task_id: ID of the task that had the conflict
        merge_task_id: ID of the new merge resolution task

    Returns:
        Number of tasks that had their dependencies updated
    """
    updated_count = 0

    for task in all_tasks:
        if task["id"] == merge_task_id:
            continue  # Don't modify the merge task itself

        depends_on = task.get("depends_on", [])
        if original_task_id in depends_on:
            # Replace original with merge task
            new_depends = [merge_task_id if dep == original_task_id else dep for dep in depends_on]
            task["depends_on"] = new_depends
            updated_count += 1
            logger.info(f"  [REWIRE] Task {task['id'][:12]} now depends on merge task {merge_task_id[:12]}")

    return updated_count


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
                    # Final attempt failed, include raw output (keep enough for fix task context)
                    logger.error(f"  [QA ERROR] Parse failed after {MAX_RETRIES} attempts")
                    feedback = f"Unable to parse LLM response after {MAX_RETRIES} attempts. Raw output:\n{content[:2000]}"
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
    logger.info("=" * 60)
    logger.info("STRATEGIST NODE: Entry")
    
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

            # ============================================================
            # QA AGENT VERIFICATION (replaces static file path checks)
            # ============================================================
            # The QA agent is a read-only ReAct agent that can:
            # - Read files to find test results anywhere
            # - Run verification commands (pytest, npm test, etc.)
            # - Report PASS/FAIL based on actual evidence
            
            if not mock_mode:
                # Use QA ReAct agent for verification
                from .handlers import _qa_handler
                from orchestrator_types import _dict_to_task, WorkerProfile
                
                # Prepare state for QA agent
                qa_state = state.copy()
                # Use main workspace (post-merge location) for QA
                qa_state["worktree_path"] = workspace_path
                
                # Convert task dict to Task object for handler
                task_obj = _dict_to_task(task)
                
                logger.info(f"  [QA AGENT] Starting verification for {task_id}")
                try:
                    qa_result = await _qa_handler(task_obj, qa_state, config)
                    
                    # Parse QA agent's result
                    # The agent returns WorkerResult with AAR containing its findings
                    # Look for QA_VERDICT in the AAR summary or messages
                    qa_passed = False
                    qa_feedback = "QA agent did not provide a verdict"
                    qa_suggestions = ""
                    
                    if qa_result.aar:
                        summary = qa_result.aar.summary
                        
                        # Parse verdict from AAR summary
                        if "QA_VERDICT: PASS" in summary:
                            qa_passed = True
                            # Extract feedback after PASS
                            if "QA_FEEDBACK:" in summary:
                                qa_feedback = summary.split("QA_FEEDBACK:")[1].split("QA_SUGGESTIONS:")[0].strip()
                            else:
                                qa_feedback = summary
                        elif "QA_VERDICT: FAIL" in summary:
                            qa_passed = False
                            if "QA_FEEDBACK:" in summary:
                                qa_feedback = summary.split("QA_FEEDBACK:")[1].split("QA_SUGGESTIONS:")[0].strip()
                            if "QA_SUGGESTIONS:" in summary:
                                qa_suggestions = summary.split("QA_SUGGESTIONS:")[1].strip()
                        else:
                            # No explicit verdict - check if files were verified
                            qa_feedback = summary
                            # If agent completed without error, assume pass for now
                            qa_passed = qa_result.status == "complete"
                    
                    qa_verdict = {
                        "passed": qa_passed,
                        "overall_feedback": qa_feedback,
                        "suggested_focus": qa_suggestions
                    }
                    
                    # Store QA agent messages for task memories
                    if qa_result.messages:
                        task_memories[task_id] = qa_result.messages
                    
                    logger.info(f"  [QA AGENT] Verdict: {'PASS' if qa_passed else 'FAIL'}")
                    
                except Exception as e:
                    import traceback
                    logger.error(f"  [QA AGENT ERROR]: {e}")
                    logger.error(traceback.format_exc())
                    qa_verdict = {
                        "passed": False,
                        "overall_feedback": f"QA agent error: {str(e)}",
                        "suggested_focus": "Check QA agent configuration"
                    }
            else:
                # Mock mode - skip QA
                qa_verdict = {
                    "passed": True,
                    "overall_feedback": "MOCK: QA skipped",
                    "suggested_focus": ""
                }


            # Update task status based on QA verdict
            if qa_verdict and qa_verdict["passed"]:
                logger.info(f"  [QA PASS]")
                task["status"] = "pending_complete"  # Director will confirm (pending confirmation)
                task["qa_verdict"] = qa_verdict

                # Rebase on main, then merge (only after QA passes)
                wt_manager = state.get("_wt_manager")
                if wt_manager and not mock_mode:
                    # Check if this is already a merge task (to prevent infinite chains)
                    is_merge_task = task.get("assigned_worker_profile") == WorkerProfile.MERGER.value

                    # Step 1: Rebase on main to handle concurrent edits
                    try:
                        # CRITICAL: If this is a merge task, it operated on the ORIGINAL task's worktree/branch
                        # We must rebase/merge THAT worktree, not the merge task ID (which has no worktree)
                        target_task_id = task.get("_use_worktree_task_id", task_id)
                        
                        logger.info(f"  [REBASE] Starting rebase for {target_task_id} (task={task_id})...")
                        rebase_result = await wt_manager.rebase_on_main(target_task_id)

                        if not rebase_result.success:
                            # Rebase failed (conflicts) - spawn merge agent instead of failing
                            # BUT: Don't spawn merge for merge tasks (prevents infinite chains)
                            if rebase_result.conflict and not is_merge_task:
                                logger.warning(f"  [REBASE CONFLICT] Spawning merge agent for {task_id}")

                                # Create merge task
                                merge_task = _create_merge_task(
                                    original_task=task,
                                    conflict_files=rebase_result.conflicting_files,
                                    error_message=rebase_result.error_message
                                )

                                # Rewire dependencies: tasks that depended on original now depend on merge
                                all_tasks = state.get("tasks", [])
                                rewired = _rewire_dependencies_for_merge(
                                    all_tasks, task_id, merge_task["id"]
                                )
                                logger.info(f"  [MERGE AGENT] Created {merge_task['id']}, rewired {rewired} dependents")

                                # Add merge task to updates (will be added to state)
                                updates.append(merge_task)

                                # Original task stays as pending_complete - it did its work
                                # But add a note about the conflict
                                task["qa_verdict"]["overall_feedback"] += (
                                    f"\n\n[MERGE PENDING] Rebase conflict detected. "
                                    f"Merge agent {merge_task['id']} will resolve conflicts."
                                )
                            elif rebase_result.conflict and is_merge_task:
                                # Merge task also has conflict - don't spawn another merge (Phoenix retry)
                                logger.error(f"  [MERGE TASK CONFLICT] Merge task {task_id} also has conflicts - Phoenix retry")
                                task["status"] = "pending_failed"
                                task["qa_verdict"]["passed"] = False
                                task["qa_verdict"]["overall_feedback"] += f"\n\nMERGE TASK CONFLICT: {rebase_result.error_message}"
                            else:
                                # Non-conflict error - fail the task for Phoenix retry
                                logger.error(f"  [REBASE FAILED]: {rebase_result.error_message}")
                                task["status"] = "pending_failed"
                                task["qa_verdict"]["passed"] = False
                                task["qa_verdict"]["overall_feedback"] += f"\n\nREBASE FAILED: {rebase_result.error_message}"
                        else:
                            logger.info(f"  [REBASE SUCCESS] Rebase completed successfully")

                            # Step 2: Merge to main (should be clean since we just rebased)
                            try:
                                logger.info(f"  [MERGE] Merging {target_task_id} to main (task={task_id})...")
                                merge_result = await wt_manager.merge_to_main(target_task_id)
                                if merge_result.success:
                                    logger.info(f"  [MERGED] Task {task_id} merged successfully to main")
                                elif merge_result.conflict and not is_merge_task:
                                    # Merge conflict after successful rebase - spawn merge agent
                                    logger.warning(f"  [MERGE CONFLICT] Spawning merge agent for {task_id}")

                                    try:
                                        logger.info("  [DEBUG] Creating merge task...")
                                        # Create merge task
                                        merge_task = _create_merge_task(
                                            original_task=task,
                                            conflict_files=merge_result.conflicting_files,
                                            error_message=merge_result.error_message
                                        )
                                        logger.info(f"  [DEBUG] Merge task created: {merge_task['id']}")

                                        # Rewire dependencies
                                        all_tasks = state.get("tasks", [])
                                        logger.info(f"  [DEBUG] Rewiring dependencies for {len(all_tasks)} tasks...")
                                        rewired = _rewire_dependencies_for_merge(
                                            all_tasks, task_id, merge_task["id"]
                                        )
                                        logger.info(f"  [MERGE AGENT] Created {merge_task['id']}, rewired {rewired} dependents")

                                        # Add merge task to updates
                                        updates.append(merge_task)
                                        logger.info(f"  [DEBUG] Merge task appended to updates")

                                        # Original task stays as pending_complete
                                        task["qa_verdict"]["overall_feedback"] += (
                                            f"\n\n[MERGE PENDING] Merge conflict detected. "
                                            f"Merge agent {merge_task['id']} will resolve conflicts."
                                        )
                                        logger.info(f"  [DEBUG] Merge agent spawn complete")
                                    except Exception as merge_error:
                                        import traceback
                                        logger.error(f"🚨 STRATEGIST: Failed to spawn merge agent: {merge_error}")
                                        logger.error(f"   Traceback: {traceback.format_exc()}")
                                        # Don't crash - mark task as failed instead
                                        task["status"] = "pending_failed"
                                        task["qa_verdict"]["passed"] = False
                                        task["qa_verdict"]["overall_feedback"] += f"\n\nMERGE SPAWN FAILED: {merge_error}"
                                elif merge_result.conflict and is_merge_task:
                                    # Merge task also has conflict - don't spawn another merge (Phoenix retry)
                                    logger.error(f"  [MERGE TASK CONFLICT] Merge task {task_id} also has conflicts - Phoenix retry")
                                    task["status"] = "pending_failed"
                                    task["qa_verdict"]["passed"] = False
                                    task["qa_verdict"]["overall_feedback"] += f"\n\nMERGE TASK CONFLICT: {merge_result.error_message}"
                                else:
                                    # Non-conflict merge failure
                                    logger.error(f"  [MERGE FAILED]: {merge_result.error_message}")
                                    task["status"] = "pending_failed"
                                    task["qa_verdict"]["passed"] = False
                                    task["qa_verdict"]["overall_feedback"] += f"\n\nMERGE FAILED: {merge_result.error_message}"
                            except Exception as e:
                                logger.error(f"  [MERGE ERROR]: {e}")
                                task["status"] = "pending_failed"
                                task["qa_verdict"]["passed"] = False
                                task["qa_verdict"]["overall_feedback"] += f"\n\nMERGE ERROR: {e}"
                    except Exception as e:
                        logger.error(f"  [REBASE ERROR]: {e}")
                        task["status"] = "pending_failed"
                        task["qa_verdict"]["passed"] = False
                        task["qa_verdict"]["overall_feedback"] += f"\n\nREBASE ERROR: {e}"
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
        try:
            # Count remaining active tasks
            all_tasks_raw = state.get("tasks", [])
            from orchestrator_types import _dict_to_task, TaskStatus
            all_tasks = [_dict_to_task(t) for t in all_tasks_raw]
            # Count active tasks, excluding the ones we just updated
            updated_ids = {u["id"] for u in updates}
            remaining_active = [t for t in all_tasks if t.status == TaskStatus.ACTIVE and t.id not in updated_ids]

            completed_id = updates[0]["id"][:8]
            logger.info(f"Director: task_{completed_id} finished. Reorg pending. Waiting on {len(remaining_active)} tasks to finish. No new tasks started.")
        except Exception as e:
            import traceback
            logger.error(f"🚨 STRATEGIST: Error in pending_reorg section: {e}")
            logger.error(f"   Traceback: {traceback.format_exc()}")
            # Continue - this section is informational only

    logger.info("STRATEGIST NODE: Returning normally")
    return {"tasks": updates, "task_memories": task_memories} if updates else {}
