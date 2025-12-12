"""
Director Module - Plan Integration
===================================
Integrates proposed tasks from multiple planners into a cohesive plan.
Resolves cross-component dependencies and validates scope.
"""

import json
import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List
from pydantic import BaseModel, Field
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.messages import SystemMessage

from orchestrator_types import Task, TaskStatus, TaskPhase, WorkerProfile
from llm_client import get_llm
from .graph_utils import detect_and_break_cycles

logger = logging.getLogger(__name__)


# =============================================================================
# PYDANTIC SCHEMAS
# =============================================================================

class IntegratedTaskDefinition(BaseModel):
    """Task definition with resolved string dependencies."""
    title: str = Field(description="Task title")
    component: str = Field(description="Component name")
    phase: str = Field(description="plan, build, or test")
    description: str
    acceptance_criteria: List[str]
    depends_on: List[str] = Field(description="List of EXACT TITLES of local dependencies (tasks in this deduplicated list)")
    dependency_queries: List[str] = Field(default_factory=list, description="Natural language queries for external dependencies")
    worker_profile: str = "code_worker"


class RejectedTask(BaseModel):
    """Task rejected during integration for being out of scope."""
    title: str
    reason: str = Field(description="Why this task was rejected")


class IntegrationResponse(BaseModel):
    """LLM response for global plan integration."""
    tasks: List[IntegratedTaskDefinition]
    rejected_tasks: List[RejectedTask] = Field(default_factory=list, description="Tasks rejected as out of scope")


class DependencyResolution(BaseModel):
    """Resolved dependency mapping from query to task ID."""
    task_title: str = Field(description="Title of the task that has the dependency query")
    query: str = Field(description="The natural language dependency query")
    matched_task_title: str = Field(description="Title of the task that satisfies the query, or 'MISSING' if not found")
    confidence: str = Field(description="high, medium, or low confidence in the match")


class QueryResolutionResponse(BaseModel):
    """LLM response for dependency query resolution."""
    resolutions: List[DependencyResolution]


# =============================================================================
# FUNCTIONS
# =============================================================================

async def resolve_dependency_queries(tasks: List[Task], state: Dict[str, Any]) -> List[Task]:
    """
    PASS 2: Resolve dependency_queries to actual task IDs using semantic matching.

    This function takes deduplicated tasks and resolves their natural language
    dependency queries to actual task dependencies.

    Args:
        tasks: List of Task objects with dependency_queries
        state: Current orchestrator state (for config, workspace_path, etc.)

    Returns:
        List of Task objects with resolved dependencies added to depends_on
    """
    # Get LLM
    orch_config = state.get("orch_config")
    if not orch_config:
        from config import OrchestratorConfig
        orch_config = OrchestratorConfig()

    model_config = orch_config.director_model
    llm = get_llm(model_config)

    # Collect all tasks with dependency queries
    tasks_with_queries = []
    all_tasks_for_matching = []

    for task in tasks:
        # Build task list for matching
        all_tasks_for_matching.append({
            "title": task.title,
            "id": task.id,
            "component": task.component,
            "phase": task.phase.value if hasattr(task.phase, 'value') else str(task.phase),
            "description": task.description
        })

        # Check if task has dependency queries
        if task.dependency_queries:
            for query in task.dependency_queries:
                tasks_with_queries.append({
                    "task_title": task.title,
                    "task_id": task.id,
                    "query": query
                })

    # If no queries to resolve, return tasks as-is
    if not tasks_with_queries:
        logger.info("No dependency queries to resolve")
        return tasks

    logger.info(f"Resolving {len(tasks_with_queries)} dependency queries across {len(tasks)} tasks")

    # Build prompt for query resolution
    prompt = ChatPromptTemplate.from_messages([
        ("system", """You are resolving cross-component dependencies using semantic matching.

TASK: Match natural language dependency queries to specific tasks.

You will be given:
1. A list of tasks with dependency queries (tasks that NEED something)
2. A complete list of all available tasks (tasks that might PROVIDE what's needed)

YOUR JOB: For each dependency query, find the task that best satisfies it.

MATCHING RULES:
- Use SEMANTIC understanding, not exact string matching
- "Backend API endpoint for user profile data" matches "Create user profile API endpoint"
- "Completed database schema setup" matches "Initialize SQLite database with user tables"
- If NO task satisfies the query, return "MISSING" as the matched_task_title
- Rate your confidence: "high" (clearly matches), "medium" (probable match), "low" (weak match)

CRITICAL:
- You are doing MATCHING ONLY, not creating new tasks
- If a query can't be satisfied, mark it MISSING (this will be flagged before execution)
- Prefer tasks that are semantically closest to the query's intent

OUTPUT: For each query, provide the matched task title (or MISSING) and confidence level.
        """),
        ("user", """Tasks with dependency queries:
{tasks_with_queries}

Available tasks to match against:
{all_tasks}

Resolve each dependency query to a task title.""")
    ])

    structured_llm = llm.with_structured_output(QueryResolutionResponse)

    try:
        response = await structured_llm.ainvoke(prompt.format(
            tasks_with_queries=json.dumps(tasks_with_queries, indent=2),
            all_tasks=json.dumps(all_tasks_for_matching, indent=2)
        ), config={"callbacks": []})

        # Apply resolutions to task dependencies
        title_to_id_map = {t["title"].lower(): t["id"] for t in all_tasks_for_matching}

        for resolution in response.resolutions:
            # Find the task that has this query
            task = next((t for t in tasks if t.id == next(
                (tq["task_id"] for tq in tasks_with_queries if tq["query"] == resolution.query), None
            )), None)

            if not task:
                continue

            # Handle missing dependencies
            if resolution.matched_task_title == "MISSING":
                logger.warning(f"❌ MISSING DEPENDENCY: Task '{resolution.task_title}' needs '{resolution.query}' but no task provides it!")
                # Don't add to depends_on - this will cause the task to be blocked
                continue

            # Find the matched task ID
            matched_id = title_to_id_map.get(resolution.matched_task_title.lower())
            if not matched_id:
                logger.warning(f"Could not find ID for matched task '{resolution.matched_task_title}'")
                continue

            # Add dependency if not already present
            if matched_id not in task.depends_on:
                task.depends_on.append(matched_id)
                logger.info(f"✅ Resolved '{resolution.query}' → '{resolution.matched_task_title}' (confidence: {resolution.confidence})")

        return tasks

    except Exception as e:
        logger.error(f"Error resolving dependency queries: {e}")
        import traceback
        logger.error(traceback.format_exc())
        # Return tasks unchanged if resolution fails
        return tasks


async def integrate_plans(suggestions: List[Dict[str, Any]], state: Dict[str, Any]) -> List[Task]:
    """
    Integrate proposed tasks from multiple planners into a cohesive plan.
    Resolves cross-component dependencies and validates scope against design spec.

    Args:
        suggestions: List of suggested tasks from planners/workers
        state: Current orchestrator state (for config, workspace_path, etc.)

    Returns:
        List of integrated Task objects with resolved dependencies
    """
    # Get LLM
    orch_config = state.get("orch_config")
    if not orch_config:
        from config import OrchestratorConfig
        orch_config = OrchestratorConfig()

    model_config = orch_config.director_model
    llm = get_llm(model_config)

    # Prepare input for LLM
    tasks_input = []
    for s in suggestions:
        # Get title and description
        title = s.get("title", "Untitled")
        desc = s.get("description", "")

        tasks_input.append({
            "title": title,
            "component": s.get("component", "unknown"),
            "phase": s.get("phase", "build"),
            "description": desc,
            "depends_on": s.get("depends_on", []),
            "dependency_queries": s.get("dependency_queries", []),  # Preserve for Pass 2
            "rationale": s.get("rationale", "")
        })

    # Get design spec for scope context
    spec = state.get("spec", {})
    spec_content = spec.get("content", "No design specification available")
    objective = state.get("objective", "")

    # Get existing active/pending tasks for context
    existing_tasks = state.get("tasks", [])
    relevant_existing_tasks = []

    for t_dict in existing_tasks:
        status = t_dict.get("status")
        if status in [TaskStatus.ACTIVE, TaskStatus.PLANNED, TaskStatus.READY]:
            # Get title (with backwards compatibility fallback)
            title = t_dict.get("title", "Untitled")

            relevant_existing_tasks.append({
                "id": t_dict.get("id"),
                "title": title,
                "component": t_dict.get("component"),
                "phase": t_dict.get("phase"),
                "status": status,
                "description": t_dict.get("description", ""),
                "depends_on": t_dict.get("depends_on", [])
            })

    logger.info(f"Including {len(relevant_existing_tasks)} active/pending tasks in integration context")

    prompt = ChatPromptTemplate.from_messages([
        ("system", """You are the Lead Architect integrating project plans.

OBJECTIVE: {objective}

DESIGN SPECIFICATION (THE SCOPE BOUNDARY):
{spec_content}

EXISTING ACTIVE/PENDING TASKS (THE RUNNING SYSTEM):
{existing_tasks_json}

INPUT: Proposed tasks from planners and workers.

YOUR JOB (PASS 1: DEDUPLICATION & SCOPE VALIDATION ONLY):

1. **Smart Deduplication**:
   - Merge ONLY truly duplicate tasks (same work, same outcome).
   - **DO NOT over-deduplicate tests**: If planners propose unit tests for Backend AND unit tests for Frontend, keep BOTH. They test different things.
   - Unit tests per component are GOOD. Integration tests are ALSO good.
   - When in doubt, keep the task rather than merging.
   - When merging, COMBINE both tasks' depends_on and dependency_queries fields (union)

2. **Validate Scope**: Check EACH task against the design specification.
   - REJECT tasks clearly outside the spec (CI/CD pipelines, accessibility features not requested, etc.)
   - APPROVE tasks that implement features in the spec
   - Tests are ALWAYS in scope if they test something in scope

3. **Preserve Dependencies**:
   - Keep the "depends_on" field from the original tasks (local dependencies within planner's scope)
   - Keep the "dependency_queries" field intact (cross-component dependencies will be resolved in Pass 2)
   - DO NOT try to wire cross-component dependencies yourself - that happens in a separate pass

4. **Output**:
   - Return the COMPLETE deduplicated task list
   - Use EXACT task titles in `depends_on` fields
   - Preserve dependency_queries for later resolution

MANDATORY REQUIREMENT - TEST TASKS:
⚠️ Your output MUST include AT LEAST ONE task with phase="test".
This could be unit tests, integration tests, E2E tests, or a final validation task.
If you fail to include any test tasks, your response will be REJECTED and you will be asked to try again.

CRITICAL RULES:
- Design spec defines what to build. Tests for those features are always valid.
- Include all valid existing tasks in your output.
- Do NOT over-merge tests! Backend unit tests ≠ Frontend unit tests.

🚨🚨🚨 ABSOLUTE CRITICAL - NO CIRCULAR DEPENDENCIES 🚨🚨🚨
**CIRCULAR DEPENDENCIES WILL BREAK THE ENTIRE SYSTEM!**

A circular dependency means Task A depends on Task B, which depends on Task C, which depends on Task A.
This creates a deadlock where NO tasks can ever become ready.

BEFORE SUBMITTING YOUR RESPONSE:
1. For EACH task, trace its depends_on chain
2. Verify no task eventually depends on itself
3. If you find a cycle, BREAK IT by removing one dependency

Examples of FORBIDDEN patterns:
- Task A depends_on: ["Task B"], Task B depends_on: ["Task A"]  ❌
- Frontend depends on Backend, Backend depends on Frontend ❌
- Any chain that loops back to itself ❌

SAFE patterns:
- Linear: A → B → C → D (each only depends on previous) ✅
- Tree: A → B, A → C, B → D, C → D (diamond is OK) ✅
- Backend → Frontend → Tests (one-directional flow) ✅
        """),
        ("user", "Proposed Tasks:\n{tasks_json}")
    ])

    structured_llm = llm.with_structured_output(IntegrationResponse)

    logger.info("Calling LLM for plan integration with scope validation")

    # LOG: Director integration request
    logs_base_path = state.get("_logs_base_path")
    if logs_base_path:
        log_dir = Path(logs_base_path) / "director"
        log_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        request_log = log_dir / f"integration_request_{timestamp}.json"
        with open(request_log, 'w', encoding='utf-8') as f:
            json.dump({
                "timestamp": datetime.now().isoformat(),
                "objective": objective,
                "spec_content_length": len(spec_content),
                "tasks_input_count": len(tasks_input),
                "existing_tasks_count": len(relevant_existing_tasks),
                "tasks_input": tasks_input,
                "existing_tasks_input": relevant_existing_tasks
            }, f, indent=2)
        logger.info(f"Director request logged: {request_log} ({len(tasks_input)} new + {len(relevant_existing_tasks)} existing)")

    try:
        response = await structured_llm.ainvoke(prompt.format(
            objective=objective,
            spec_content=spec_content[:3000],  # Truncate if too long
            tasks_json=str(tasks_input),
            existing_tasks_json=str(relevant_existing_tasks)
        ), config={"callbacks": []})

        # LOG: Director integration response
        if logs_base_path:
            response_log = log_dir / f"integration_response_{timestamp}.json"
            with open(response_log, 'w', encoding='utf-8') as f:
                json.dump({
                    "timestamp": datetime.now().isoformat(),
                    "tasks_returned": len(response.tasks) if hasattr(response, 'tasks') else 0,
                    "tasks_rejected": len(response.rejected_tasks) if hasattr(response, 'rejected_tasks') else 0,
                    "total_accounted": (len(response.tasks) if hasattr(response, 'tasks') else 0) +
                                       (len(response.rejected_tasks) if hasattr(response, 'rejected_tasks') else 0),
                    "tasks_input_count": len(tasks_input),
                    "MISSING_COUNT": len(tasks_input) -
                                     ((len(response.tasks) if hasattr(response, 'tasks') else 0) +
                                      (len(response.rejected_tasks) if hasattr(response, 'rejected_tasks') else 0)),
                    "response_tasks": [{"title": t.title, "phase": t.phase, "depends_on": t.depends_on}
                                       for t in response.tasks] if hasattr(response, 'tasks') else [],
                    "rejected_tasks": [{"title": t.title, "reason": t.reason}
                                       for t in response.rejected_tasks] if hasattr(response, 'rejected_tasks') else []
                }, f, indent=2)
            logger.info(f"Director response logged: {response_log}")
            logger.info(f"Input: {len(tasks_input)} tasks -> Output: {len(response.tasks)} approved + {len(response.rejected_tasks)} rejected")
            missing = len(tasks_input) - (len(response.tasks) + len(response.rejected_tasks))
            if missing > 0:
                logger.warning(f"{missing} tasks UNACCOUNTED FOR by LLM (deduplicated/merged)!")

        # ENFORCEMENT: Check for at least one test task
        test_tasks = [t for t in response.tasks if hasattr(t, 'phase') and t.phase.lower() == 'test']

        if not test_tasks:
            logger.warning("NO TEST TASKS in LLM response! Retrying with enforcement message")

            # Build retry prompt with scolding message
            retry_user_message = f"""Your previous response did NOT include any tasks with phase="test".

This is a MANDATORY requirement. Every project MUST have at least one test task.

Please review the task list again and include appropriate test tasks:
- Unit tests for backend components
- Unit tests for frontend components
- Integration tests
- E2E tests
- Or at minimum, a final validation test task

Original proposed tasks:
{str(tasks_input)}

Reread the instructions carefully and provide a complete task list INCLUDING TEST TASKS."""

            try:
                retry_prompt = ChatPromptTemplate.from_messages([
                    ("system", prompt.messages[0].prompt.template),  # Reuse system prompt
                    ("user", retry_user_message)
                ])

                response = await structured_llm.ainvoke(retry_prompt.format(
                    objective=objective,
                    spec_content=spec_content[:3000],
                    tasks_json=str(tasks_input),
                    existing_tasks_json=str(relevant_existing_tasks)
                ), config={"callbacks": []})

                # Check again
                test_tasks = [t for t in response.tasks if hasattr(t, 'phase') and t.phase.lower() == 'test']
                if test_tasks:
                    logger.info(f"Retry successful! Got {len(test_tasks)} test task(s)")
                else:
                    logger.warning("Retry still has no test tasks. Proceeding anyway")

            except Exception as retry_error:
                logger.error(f"Retry failed: {retry_error}. Proceeding with original response")

    except Exception as e:
        import traceback
        error_type = type(e).__name__
        error_msg = str(e)

        # Detect specific error types
        is_timeout = "timeout" in error_msg.lower() or "timed out" in error_msg.lower()
        is_rate_limit = "rate limit" in error_msg.lower() or "429" in error_msg
        is_overloaded = "overloaded" in error_msg.lower() or "503" in error_msg

        logger.error(f"Integration LLM Error ({error_type}): {error_msg}")
        if is_timeout:
            logger.error("  ⏱️  TIMEOUT: LLM did not respond within timeout period")
            logger.error("  Possible causes: Complex prompt, slow model response, network issues")
        elif is_rate_limit:
            logger.error("  🚫 RATE LIMIT: Too many requests to LLM provider")
            logger.error("  Retries with exponential backoff are automatic")
        elif is_overloaded:
            logger.error("  ⚠️  OVERLOADED: LLM provider is experiencing high load")

        logger.error(f"  Full traceback:\n{traceback.format_exc()}")

        # Fallback: Return tasks as-is (converted to Task objects)
        logger.warning("Fallback: Converting suggestions directly without integration")
        fallback_tasks = []
        for s in suggestions:
            t_id = f"task_{uuid.uuid4().hex[:8]}"
            fallback_tasks.append(Task(
                id=t_id,
                component=s.get("component", "unknown"),
                phase=TaskPhase(s.get("phase", "build")),
                status=TaskStatus.PLANNED,
                assigned_worker_profile=WorkerProfile.CODER,  # Default
                description=s.get("description", ""),
                depends_on=[],  # Lost dependencies in fallback
                created_at=datetime.now(),
                updated_at=datetime.now()
            ))
        return fallback_tasks

    # Convert response to Task objects
    new_tasks = []
    title_to_id_map = {}

    # Handle rejected tasks - send feedback to source workers
    if hasattr(response, 'rejected_tasks') and response.rejected_tasks:
        logger.info(f"LLM rejected {len(response.rejected_tasks)} tasks as out of scope:")
        for rejected in response.rejected_tasks:
            logger.info(f"  ✗ {rejected.title}: {rejected.reason}")

            # Find the source task that suggested this
            for suggestion in suggestions:
                if suggestion.get("title") == rejected.title or rejected.title in suggestion.get("description", ""):
                    source_id = suggestion.get("suggested_by_task")
                    if source_id:
                        feedback = SystemMessage(
                            content=f"DIRECTOR FEEDBACK (LLM Validation): Task suggestion '{rejected.title}' was rejected by the Lead Architect.\n\n"
                                    f"Reason: {rejected.reason}\n\n"
                                    f"The suggested task does not align with the design specification. "
                                    f"Please continue your work within the defined scope or provide stronger justification if this is truly required."
                        )
                        if "task_memories" not in state:
                            state["task_memories"] = {}
                        if source_id not in state["task_memories"]:
                            state["task_memories"][source_id] = []
                        state["task_memories"][source_id].append(feedback)
                    break

    # Pre-populate map with EXISTING tasks (to allow linking to completed tasks)
    existing_tasks = state.get("tasks", [])
    for t in existing_tasks:
        t_title = t.get("title", "")
        if t_title:
            title_to_id_map[t_title.lower()] = t["id"]

    # Create IDs and Map Titles for NEW tasks
    for t_def in response.tasks:
        # Check if title already exists in map (case-insensitive)
        existing_id = title_to_id_map.get(t_def.title.lower())

        if existing_id:
            # Reuse existing ID to prevent duplication
            logger.info(f"Reusing ID {existing_id} for '{t_def.title}'")
        else:
            # Generate new ID
            new_id = f"task_{uuid.uuid4().hex[:8]}"
            title_to_id_map[t_def.title.lower()] = new_id

    # Create Task Objects with Resolved Dependencies
    for t_def in response.tasks:
        new_id = title_to_id_map[t_def.title.lower()]

        resolved_deps = []
        for dep in t_def.depends_on:
            dep_lower = dep.lower().strip()

            # Exact match (new or existing)
            if dep_lower in title_to_id_map:
                resolved_deps.append(title_to_id_map[dep_lower])
            else:
                # Fuzzy match
                best_match = None
                best_score = 0
                for known_title, known_id in title_to_id_map.items():
                    if dep_lower in known_title or known_title in dep_lower:
                        score = len(known_title)
                        if score > best_score:
                            best_score = score
                            best_match = known_id

                if best_match:
                    resolved_deps.append(best_match)
                else:
                    logger.warning(f"Could not resolve dependency '{dep}' for '{t_def.title}'")

        # Determine profile
        profile = WorkerProfile.CODER
        phase = TaskPhase.BUILD

        p_str = t_def.phase.lower()
        if p_str == "test":
            phase = TaskPhase.TEST
            profile = WorkerProfile.TESTER
        elif p_str == "plan":
            phase = TaskPhase.PLAN
            profile = WorkerProfile.PLANNER

        new_task = Task(
            id=new_id,
            title=t_def.title,
            component=t_def.component,
            phase=phase,
            status=TaskStatus.PLANNED,
            assigned_worker_profile=profile,
            description=t_def.description,
            acceptance_criteria=t_def.acceptance_criteria,
            depends_on=resolved_deps,
            dependency_queries=t_def.dependency_queries,  # Preserve for Pass 2
            created_at=datetime.now(),
            updated_at=datetime.now()
        )
        new_tasks.append(new_task)

    # PASS 1 COMPLETE: Tasks are deduplicated with local dependencies
    logger.info(f"Pass 1 complete: Deduplicated {len(new_tasks)} tasks")

    # PASS 2: Resolve dependency queries to actual task IDs
    logger.info("Pass 2: Resolving cross-component dependency queries...")
    new_tasks = await resolve_dependency_queries(new_tasks, state)

    # CRITICAL: Detect and break circular dependencies
    cycles_broken = detect_and_break_cycles(new_tasks)
    if cycles_broken > 0:
        logger.warning(f"FIXED {cycles_broken} circular dependency(ies) in task graph!")

    logger.info(f"Integration complete: {len(new_tasks)} tasks with resolved dependencies")
    return new_tasks
