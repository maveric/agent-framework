"""
Agent Orchestrator — Strategist Node
====================================
Version 2.1 — December 2025

QA evaluation node with LLM-based test result evaluation.
Now includes TDD validation for Red/Green verification.
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


# =============================================================================
# TDD VALIDATION FUNCTIONS
# =============================================================================

async def _validate_tdd_red_phase(task: Dict[str, Any], workspace_path: str, config: Any) -> Dict[str, Any]:
    """
    Validate that a TEST phase task in TDD wrote tests that FAIL (Red phase).

    Returns:
        Dict with keys: passed (bool), feedback (str), is_red_verified (bool)
    """
    task_id = task["id"]
    component = task.get("component", task_id)
    test_spec_path = Path(workspace_path) / f"agents-work/test-specs/test-spec-{component}.md"

    if not test_spec_path.exists():
        return {
            "passed": False,
            "feedback": f"TDD RED VERIFICATION FAILED: Missing test specification file at agents-work/test-specs/test-spec-{component}.md",
            "is_red_verified": False
        }

    try:
        content = test_spec_path.read_text(encoding="utf-8")

        # Check for RED verification section
        content_lower = content.lower()

        # Look for evidence that tests were run and failed
        has_red_verification = "red verification" in content_lower or "tests must fail" in content_lower
        has_failure_output = "failed" in content_lower or "error" in content_lower or "failure" in content_lower
        has_test_command = "pytest" in content_lower or "jest" in content_lower or "npm test" in content_lower

        # Check for anti-patterns (tests that pass when they shouldn't)
        has_passing_warning = "unexpected passes" in content_lower or "tests pass" in content_lower

        if has_red_verification and has_failure_output and has_test_command:
            # Good - tests were run and failed as expected
            return {
                "passed": True,
                "feedback": "TDD RED PHASE VERIFIED: Tests were written and confirmed to fail before implementation.",
                "is_red_verified": True
            }
        elif not has_test_command:
            return {
                "passed": False,
                "feedback": "TDD RED VERIFICATION INCOMPLETE: Test specification exists but no test execution command was documented.",
                "is_red_verified": False
            }
        else:
            return {
                "passed": False,
                "feedback": "TDD RED VERIFICATION INCOMPLETE: Could not confirm tests fail as expected. Ensure RED verification section shows actual test failures.",
                "is_red_verified": False
            }

    except Exception as e:
        return {
            "passed": False,
            "feedback": f"TDD RED VERIFICATION ERROR: Failed to read test specification: {e}",
            "is_red_verified": False
        }


async def _validate_tdd_green_phase(task: Dict[str, Any], workspace_path: str, config: Any) -> Dict[str, Any]:
    """
    Validate that a BUILD phase task in TDD made all tests PASS (Green phase).

    This is called when task.test_file_paths is set, indicating TDD mode.

    Returns:
        Dict with keys: passed (bool), feedback (str), tests_passing (bool)
    """
    test_file_paths = task.get("test_file_paths", [])

    if not test_file_paths:
        # Not a TDD task - skip green validation
        return {
            "passed": True,
            "feedback": "Not a TDD task (no test_file_paths specified).",
            "tests_passing": None
        }

    # Look for test results in standard locations
    task_id = task["id"]
    component = task.get("component", task_id)
    test_results_path = Path(workspace_path) / f"agents-work/test-results/test-{component}.md"

    # Also check AAR for test execution evidence
    aar = task.get("aar", {})
    aar_summary = aar.get("summary", "").lower()

    # Evidence of test execution in AAR
    tests_mentioned_in_aar = "test" in aar_summary and ("pass" in aar_summary or "green" in aar_summary)

    if test_results_path.exists():
        try:
            content = test_results_path.read_text(encoding="utf-8")
            content_lower = content.lower()

            # Check for passing evidence
            has_all_passed = "all tests passed" in content_lower or "100%" in content_lower or "0 failed" in content_lower
            has_failures = "failed" in content_lower and "0 failed" not in content_lower

            if has_all_passed and not has_failures:
                return {
                    "passed": True,
                    "feedback": "TDD GREEN PHASE VERIFIED: All tests pass. Implementation satisfies the contract.",
                    "tests_passing": True
                }
            elif has_failures:
                return {
                    "passed": False,
                    "feedback": "TDD GREEN PHASE FAILED: Some tests still failing. Implementation incomplete.",
                    "tests_passing": False
                }
            else:
                return {
                    "passed": False,
                    "feedback": "TDD GREEN VERIFICATION UNCLEAR: Test results file exists but could not confirm all tests pass.",
                    "tests_passing": None
                }

        except Exception as e:
            return {
                "passed": False,
                "feedback": f"TDD GREEN VERIFICATION ERROR: Failed to read test results: {e}",
                "tests_passing": None
            }

    elif tests_mentioned_in_aar:
        # No explicit test results file, but AAR mentions tests passing
        return {
            "passed": True,
            "feedback": "TDD GREEN PHASE: Test execution mentioned in AAR. Consider creating explicit test results file.",
            "tests_passing": True
        }

    else:
        # TDD mode but no test evidence
        return {
            "passed": False,
            "feedback": f"TDD GREEN VERIFICATION FAILED: Task has test_file_paths but no test results found at agents-work/test-results/test-{component}.md",
            "tests_passing": None
        }


def _check_test_triviality(test_content: str) -> Dict[str, Any]:
    """
    Check if tests appear trivial (anti-pattern detection).

    Returns:
        Dict with is_trivial (bool), warnings (List[str])
    """
    warnings = []
    content_lower = test_content.lower()

    # Anti-patterns to detect
    trivial_patterns = [
        ("assert true", "Found 'assert True' - tests should make meaningful assertions"),
        ("assert 1 == 1", "Found '1 == 1' assertion - tests should validate actual behavior"),
        ("pass  # todo", "Found 'pass # TODO' - tests are incomplete"),
        ("# todo: implement", "Found TODO comments indicating incomplete tests"),
    ]

    for pattern, warning in trivial_patterns:
        if pattern in content_lower:
            warnings.append(warning)

    # Check for empty test functions
    import re
    empty_test_pattern = r'def test_\w+\([^)]*\):\s*pass'
    if re.search(empty_test_pattern, test_content):
        warnings.append("Found empty test functions (def test_*(): pass)")

    return {
        "is_trivial": len(warnings) > 0,
        "warnings": warnings
    }


# =============================================================================
# BUILD TASK QA FUNCTIONS
# =============================================================================

import subprocess
import platform

async def _run_tests_for_qa(
    task: Dict[str, Any], 
    workspace_path: str, 
    worktree_path: Optional[str]
) -> Dict[str, Any]:
    """
    Run tests for a BUILD task to verify they pass.
    Uses test harness pattern (subprocess + terminate) to avoid hanging.
    
    Args:
        task: The task dict with test_file_paths
        workspace_path: Root workspace (where .venv lives)
        worktree_path: Path to the task's worktree (where code lives)
        
    Returns:
        Dict with keys: success (bool), output (str), error (str or None)
    """
    test_file_paths = task.get("test_file_paths", [])
    
    if not test_file_paths:
        return {
            "success": True,
            "output": "No test_file_paths specified - skipping test execution",
            "error": None
        }
    
    # Determine execution path (worktree if available, else workspace)
    exec_path = worktree_path if worktree_path and Path(worktree_path).exists() else workspace_path
    
    # Build venv python path
    is_windows = platform.system() == "Windows"
    if is_windows:
        venv_python = str(Path(workspace_path) / ".venv" / "Scripts" / "python.exe")
    else:
        venv_python = str(Path(workspace_path) / ".venv" / "bin" / "python")
    
    # Check if venv exists
    if not Path(venv_python).exists():
        logger.warning(f"  [QA] Venv not found at {venv_python}, falling back to system python")
        venv_python = "python"
    
    # Build pytest command with the specific test files
    test_paths_str = " ".join(test_file_paths)
    cmd = [venv_python, "-m", "pytest"] + test_file_paths + ["-v", "--tb=short"]
    
    logger.info(f"  [QA] Running tests: {' '.join(cmd[:5])}...")
    
    try:
        # Use test harness pattern: spawn process with timeout
        result = subprocess.run(
            cmd,
            cwd=exec_path,
            capture_output=True,
            text=True,
            timeout=120  # 2 minute timeout for tests
        )
        
        output = result.stdout + "\n" + result.stderr
        success = result.returncode == 0
        
        if success:
            logger.info(f"  [QA] ✅ Tests passed")
        else:
            logger.warning(f"  [QA] ❌ Tests failed (exit code: {result.returncode})")
        
        return {
            "success": success,
            "output": output[:5000],  # Cap output size
            "error": None if success else f"Exit code: {result.returncode}"
        }
        
    except subprocess.TimeoutExpired as e:
        logger.error(f"  [QA] Tests timed out after 120s")
        return {
            "success": False,
            "output": str(e.stdout or "") + "\n" + str(e.stderr or ""),
            "error": "Test execution timed out after 120 seconds"
        }
    except FileNotFoundError as e:
        logger.error(f"  [QA] Could not find python/pytest: {e}")
        return {
            "success": False,
            "output": "",
            "error": f"Could not execute tests: {e}"
        }
    except Exception as e:
        logger.error(f"  [QA] Test execution error: {e}")
        return {
            "success": False,
            "output": "",
            "error": str(e)
        }


async def _evaluate_build_task_with_llm(
    task: Dict[str, Any], 
    test_output: Optional[str],
    files_modified: List[str],
    objective: str
) -> Dict[str, Any]:
    """
    LLM evaluation of BUILD task completion.
    Checks acceptance criteria fulfillment and test results.
    
    Args:
        task: The task dict
        test_output: Output from running tests (or None if no tests)
        files_modified: List of files the coder modified
        objective: Project objective for context
        
    Returns:
        Dict with keys: passed (bool), feedback (str), focus (str)
    """
    from config import OrchestratorConfig
    orch_config = OrchestratorConfig()
    llm = get_llm(orch_config.strategist_model)
    
    acceptance_criteria = task.get("acceptance_criteria", [])
    criteria_text = "\n".join(f"- {c}" for c in acceptance_criteria) if acceptance_criteria else "No specific criteria defined"
    test_file_paths = task.get("test_file_paths", [])
    
    # Build test results section
    if test_output:
        test_section = f"""
═══════════════════════════════════════════════════════════
TEST EXECUTION RESULTS
═══════════════════════════════════════════════════════════
Tests that were required to pass: {', '.join(test_file_paths) if test_file_paths else 'None specified'}

Test Output:
{test_output}
"""
    else:
        test_section = """
═══════════════════════════════════════════════════════════
TEST EXECUTION RESULTS
═══════════════════════════════════════════════════════════
No tests were executed (task has no test_file_paths).
"""

    system_prompt = """You are a QA engineer evaluating BUILD/coding task completion.

YOUR ROLE: Verify the coder did what they were supposed to do FOR THIS SPECIFIC TASK.

═══════════════════════════════════════════════════════════
EVALUATION CRITERIA
═══════════════════════════════════════════════════════════

**STEP 1: Check ACCEPTANCE CRITERIA**
Each acceptance criterion for THIS TASK must be satisfied:
- Look at the task description and criteria list
- Did the coder's work address each point?
- Files modified should align with what was requested

**STEP 2: Check TEST RESULTS (TASK-SCOPED EVALUATION)**
🚨 CRITICAL: Only evaluate tests that are RELEVANT TO THIS TASK'S SCOPE 🚨

The test file may contain tests for MULTIPLE features. This task may only be responsible 
for implementing SOME of them. Your job is to determine which test failures (if any) 
are this task's responsibility.

✅ PASS if:
• All tests RELEVANT to this task's scope passed
• Failing tests are for features this task was NOT meant to implement
• Test output shows the specific tests for this task's work are green

❌ FAIL if:
• Tests that are directly related to this task's description/criteria failed
• The task was supposed to make specific tests pass and those tests failed

HOW TO DETERMINE RELEVANCE:
1. Read the task description and acceptance criteria carefully
2. Look at which tests failed and what they're testing
3. If a failing test is testing functionality this task was meant to implement → FAIL
4. If a failing test is testing OTHER functionality not in this task → IGNORE IT

Example: Task is "Implement user login API"
- test_user_login FAILED → This is relevant → FAIL
- test_user_profile FAILED → This is a different feature → IGNORE, still PASS

**STEP 3: Check WORK QUALITY**
- Did they modify the right files?
- Does the work appear complete (not stub implementations)?
- Any red flags (empty files, placeholder code)?

═══════════════════════════════════════════════════════════
RESPONSE FORMAT
═══════════════════════════════════════════════════════════

VERDICT: PASS or FAIL
FEEDBACK: [Explain your reasoning for each step. Be specific about what passed/failed.]
FOCUS: [If FAIL, what should the coder fix? If PASS, say "None"]"""

    user_prompt = f"""═══════════════════════════════════════════════════════════
TASK BEING EVALUATED
═══════════════════════════════════════════════════════════
Title: {task.get('title', 'N/A')}
Description: {task.get('description', 'N/A')}

ACCEPTANCE CRITERIA (MUST SATISFY):
{criteria_text}

FILES MODIFIED BY CODER:
{chr(10).join(f"- {f}" for f in files_modified) if files_modified else "- No files modified"}
{test_section}
═══════════════════════════════════════════════════════════
PROJECT CONTEXT (for reference only)
═══════════════════════════════════════════════════════════
{objective}

Evaluate this BUILD task strictly."""

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_prompt)
    ]
    
    MAX_RETRIES = 3
    
    for attempt in range(MAX_RETRIES):
        try:
            response = await llm.ainvoke(messages)
            content = str(response.content)
            
            # Parse response
            verdict = "FAIL"
            feedback = "Unable to parse LLM response"
            focus = ""
            
            normalized_content = content.replace("*", "")
            
            if "VERDICT:" in normalized_content.upper():
                verdict_line = normalized_content.upper().split("VERDICT:", 1)[1].split("\n")[0]
                verdict = "PASS" if "PASS" in verdict_line else "FAIL"
            
            if "FEEDBACK:" in normalized_content.upper():
                content_upper = normalized_content.upper()
                feedback_start = content_upper.find("FEEDBACK:")
                after_feedback = normalized_content[feedback_start + len("FEEDBACK:"):]
                focus_pos = after_feedback.upper().find("FOCUS:")
                if focus_pos != -1:
                    feedback = after_feedback[:focus_pos].strip()
                else:
                    feedback = after_feedback.strip()
            
            if "FOCUS:" in normalized_content.upper():
                content_upper = normalized_content.upper()
                focus_start = content_upper.find("FOCUS:")
                focus = normalized_content[focus_start + len("FOCUS:"):].strip().split("\n")[0]
            
            if feedback != "Unable to parse LLM response":
                return {
                    "passed": verdict == "PASS",
                    "feedback": feedback,
                    "focus": focus if focus.lower() != "none" else ""
                }
            else:
                if attempt < MAX_RETRIES - 1:
                    logger.info(f"  [QA RETRY] Parse failed (attempt {attempt + 1}/{MAX_RETRIES}), retrying...")
                    continue
                else:
                    logger.error(f"  [QA ERROR] Parse failed after {MAX_RETRIES} attempts")
                    return {
                        "passed": False,
                        "feedback": f"QA evaluation parse error. Raw: {content[:1000]}",
                        "focus": "Fix QA system"
                    }
                    
        except Exception as e:
            if attempt < MAX_RETRIES - 1:
                logger.info(f"  [QA RETRY] LLM error (attempt {attempt + 1}/{MAX_RETRIES}): {e}")
                continue
            else:
                logger.error(f"  [QA ERROR] LLM failed after {MAX_RETRIES} attempts: {e}")
                return {
                    "passed": False,
                    "feedback": f"QA evaluation error: {str(e)}",
                    "focus": "Retry task"
                }
    
    # Should not reach here, but just in case
    return {
        "passed": False,
        "feedback": "QA evaluation failed unexpectedly",
        "focus": "Retry task"
    }


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

            # Check phase - only TEST tasks strictly require test result files
            task_phase = task.get("phase", "build") # Default to build if not set
            worker_profile = task.get("assigned_worker_profile", "")

            # TDD: Check if this is a Test Architect task (RED phase validation)
            is_test_architect = worker_profile == WorkerProfile.TEST_ARCHITECT.value or worker_profile == "test_architect"

            if task_phase == "test":
                # STRICT QA for TEST tasks
                if is_test_architect:
                    # TDD RED PHASE: Validate tests were written and FAIL as expected
                    logger.info(f"  [TDD] Test Architect task - validating RED phase")
                    tdd_result = await _validate_tdd_red_phase(task, workspace_path, config)

                    if tdd_result["passed"]:
                        qa_verdict = {
                            "passed": True,
                            "overall_feedback": tdd_result["feedback"],
                            "suggested_focus": ""
                        }
                        # Mark is_red_verified on the task
                        task["is_red_verified"] = tdd_result.get("is_red_verified", False)
                        logger.info(f"  [TDD RED PASS] Tests confirmed to fail before implementation")
                    else:
                        qa_verdict = {
                            "passed": False,
                            "overall_feedback": tdd_result["feedback"],
                            "suggested_focus": "Ensure tests are written and fail as expected (RED state)"
                        }
                        logger.error(f"  [TDD RED FAIL] {tdd_result['feedback']}")

                elif test_results_path and test_results_path.exists():
                    try:
                        test_content = test_results_path.read_text(encoding="utf-8")

                        # TDD: Check for trivial tests (anti-pattern)
                        triviality_check = _check_test_triviality(test_content)
                        if triviality_check["is_trivial"]:
                            logger.warning(f"  [TDD WARNING] Trivial tests detected: {triviality_check['warnings']}")

                        if not mock_mode:
                            # Use LLM to evaluate test results
                            qa_result = await _evaluate_test_results_with_llm(task, test_content, objective, config)

                            # Add triviality warnings to feedback
                            feedback = qa_result["feedback"]
                            if triviality_check["is_trivial"]:
                                feedback += f"\n\n⚠️ TRIVIALITY WARNING: {'; '.join(triviality_check['warnings'])}"

                            qa_verdict = {
                                "passed": qa_result["passed"],
                                "overall_feedback": feedback,
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

                # TDD: Check if this is a GREEN phase task (has test_file_paths)
                test_file_paths = task.get("test_file_paths", [])
                is_tdd_build = len(test_file_paths) > 0 if test_file_paths else False

                # Check for "explicit completion" (where agent said "already implemented")
                is_explicitly_completed = False
                if aar.get("summary", "").startswith("ALREADY IMPLEMENTED:"):
                     is_explicitly_completed = True

                # TDD GREEN PHASE: Validate all tests pass
                if is_tdd_build:
                    logger.info(f"  [TDD] Build task with tests - validating GREEN phase")
                    tdd_result = await _validate_tdd_green_phase(task, workspace_path, config)

                    if tdd_result["passed"]:
                        qa_verdict = {
                            "passed": True,
                            "overall_feedback": tdd_result["feedback"],
                            "suggested_focus": ""
                        }
                        logger.info(f"  [TDD GREEN PASS] All tests now pass")
                    else:
                        qa_verdict = {
                            "passed": False,
                            "overall_feedback": tdd_result["feedback"],
                            "suggested_focus": "Make all tests pass (GREEN state)"
                        }
                        logger.error(f"  [TDD GREEN FAIL] {tdd_result['feedback']}")

                elif files_modified or is_explicitly_completed:
                    # Check if this is a CODER worker - only coders get LLM test evaluation
                    is_coder = worker_profile == WorkerProfile.CODER.value or worker_profile == "code_worker"
                    
                    if is_coder:
                        # LLM-BASED QA for CODER tasks only
                        # Run tests if test_file_paths specified, then use LLM to evaluate
                        logger.info(f"  [CODER QA] Evaluating coder task with LLM validation...")
                        
                        # Get worktree path for test execution
                        worktree_base = state.get("_worktree_base_path")
                        if worktree_base:
                            task_worktree_path = str(Path(worktree_base) / task_id)
                        else:
                            task_worktree_path = str(Path(workspace_path) / ".worktrees" / task_id)
                        
                        # Run tests if this task has test_file_paths
                        test_output = None
                        tests_all_passed = True
                        if test_file_paths:
                            logger.info(f"  [CODER QA] Running {len(test_file_paths)} test file(s) for verification...")
                            test_result = await _run_tests_for_qa(task, workspace_path, task_worktree_path)
                            test_output = test_result["output"]
                            tests_all_passed = test_result["success"]
                            
                            if tests_all_passed:
                                logger.info(f"  [CODER QA] ✅ All tests passed")
                            else:
                                # Tests had failures - but let LLM decide if they're relevant to this task
                                logger.info(f"  [CODER QA] ⚠️ Some tests failed - LLM will evaluate relevance to task scope")
                        
                        # Always run LLM evaluation for coders
                        if not mock_mode:
                            qa_result = await _evaluate_build_task_with_llm(
                                task, 
                                test_output, 
                                files_modified,
                                objective
                            )
                            qa_verdict = {
                                "passed": qa_result["passed"],
                                "overall_feedback": qa_result["feedback"],
                                "suggested_focus": qa_result.get("focus", "")
                            }
                            if qa_result["passed"]:
                                logger.info(f"  [CODER QA] ✅ LLM evaluation passed")
                            else:
                                logger.warning(f"  [CODER QA] ❌ LLM evaluation failed: {qa_result['feedback'][:200]}")
                        else:
                            # Mock mode - pass with warning
                            qa_verdict = {
                                "passed": True,
                                "overall_feedback": "MOCK: QA skipped (mock mode enabled)",
                                "suggested_focus": ""
                            }
                    else:
                        # NON-CODER workers (planners, etc) - simple files_modified check
                        logger.info(f"  [QA PASS] Non-coder task ({worker_profile}) validated (files modified: {len(files_modified)})")
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
                task["status"] = "pending_complete"  # Director will confirm (pending confirmation)
                task["qa_verdict"] = qa_verdict

                # Rebase on main, then merge (only after QA passes)
                wt_manager = state.get("_wt_manager")
                if wt_manager and not mock_mode:
                    # Check if this is already a merge task (to prevent infinite chains)
                    is_merge_task = task.get("assigned_worker_profile") == WorkerProfile.MERGER.value

                    # Step 1: Rebase on main to handle concurrent edits
                    try:
                        logger.info(f"  [REBASE] Starting rebase for {task_id}...")
                        rebase_result = await wt_manager.rebase_on_main(task_id)

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
                                merge_result = await wt_manager.merge_to_main(task_id)
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
