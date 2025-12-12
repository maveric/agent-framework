"""
Plan handler for planning tasks.
"""

from typing import Dict, Any
import platform

from orchestrator_types import Task, WorkerProfile, WorkerResult, AAR

# Import tools (ASYNC versions for non-blocking execution)
from tools import (
    read_file_async as read_file,
    write_file_async as write_file,
    list_directory_async as list_directory,
    file_exists_async as file_exists
)

from ..tools_binding import _bind_tools
from ..shared_tools import create_subtasks
from ..execution import _execute_react_loop


async def _plan_handler(task: Task, state: Dict[str, Any], config: Dict[str, Any] = None) -> WorkerResult:
    """Planning tasks (async)."""

    # PREVENT PLANNER EXPLOSION: Count existing planners
    existing_tasks = state.get("tasks", [])
    planner_count = sum(1 for t in existing_tasks
                       if (hasattr(t, 'assigned_worker_profile') and t.assigned_worker_profile == WorkerProfile.PLANNER)
                       or (isinstance(t, dict) and t.get('assigned_worker_profile') == 'planner_worker'))

    MAX_PLANNERS = 10  # Hard limit: should be plenty
    if planner_count >= MAX_PLANNERS:
        print(f"  [WARNING] Max planner limit reached ({MAX_PLANNERS}). Forcing direct task creation.", flush=True)

    tools = [read_file, write_file, list_directory, file_exists, create_subtasks]
    tools = _bind_tools(tools, state, WorkerProfile.PLANNER)

    # Platform-specific shell warning
    is_windows = platform.system() == 'Windows'
    correct_path = "python folder\\\\script.py" if is_windows else "python folder/script.py"
    platform_warning = f"""
**🚨 CRITICAL - SHELL COMMANDS ({platform.system()}) 🚨**:
{"⚠️ YOU ARE ON WINDOWS - NEVER USE && IN COMMANDS!" if is_windows else "Unix shell: Use && or ; for chaining"}
- ❌ FORBIDDEN: `cd folder && python script.py` (BREAKS ON WINDOWS)
- ❌ FORBIDDEN: `cd . && python test.py` (USELESS AND BREAKS)
- ✅ CORRECT: `{correct_path}` (Run from project root)
The run_shell tool ALREADY runs in the correct working directory. DO NOT use cd.
"""

    # UNIFIED PLANNER PROMPT - All planners work the same way
    system_prompt = f"""You are a component planner.
{platform_warning}

**TOOL USAGE RULES**:
- Use `list_directory(".")` to see the project root (NOT list_directory("/") - that's invalid)
- Use relative paths: "design_spec.md" or "agents-work/plans/" (NOT "/design_spec.md")
- Use `read_file()` for FILES only, use `list_directory()` for directories

**RESEARCH WORKERS - USE SPARINGLY**:
Research workers search the web for information. Create research tasks ONLY when:
- ✅ User explicitly requests research (e.g., "research GraphQL patterns first")
- ✅ Implementing niche/esoteric technology (e.g., Qdrant, Temporal.io, specific ML frameworks)
- ✅ Unfamiliar package with unclear documentation (not common libraries)

Otherwise, implement directly - most web frameworks, databases, and patterns are well-known.

**Research Task Format:** 
- phase: "research"
- worker_profile: "research_worker"
- description: "Research [specific topic] for [purpose]"
- Should depend_on nothing, and have build tasks depend on it

**Examples:**
- ❌ DON'T: "Research FastAPI basics" (well-documented, common)
- ❌ DON'T: "Research React patterns" (extremely common)
- ✅ DO: "Research Qdrant vector database integration patterns" (niche)
- ✅ DO: "Research authentication with Keycloak" (specific, less common)


Your goal is to create a detailed implementation plan for YOUR COMPONENT and break it into executable build/test tasks.

CRITICAL INSTRUCTIONS:
1. **READ THE SPEC FIRST**: Check `design_spec.md` in the project root - this is YOUR CONTRACT
2. Explore the codebase using `list_directory` and `read_file`
3. Write your plan to `agents-work/plans/plan-{{component}}-{task.id[:8]}.md` using `write_file` (UNIQUE filename with task ID!)
4. **CREATE COMMIT-LEVEL TASKS**: Use `create_subtasks` to define atomic, reviewable changes:

   GRANULARITY: Think in terms of GIT COMMITS
   - ✅ GOOD: "Implement POST /api/tasks endpoint with validation"
   - ✅ GOOD: "Add drag-drop UI for task movement"
   - ✅ GOOD: "Add Playwright test for task creation flow"
   - ❌ TOO BIG: "Build entire backend API"
   - ❌ TOO SMALL: "Add import statement"

   Each task should:
   - Implement ONE atomic, testable change
   - Be reviewable as a standalone PR
   - Include its own verification (unit test in same commit, or integration test right after)
   - Have 3-6 clear acceptance criteria

   BUILD TESTING INTO YOUR TASKS:
   - Don't separate "build" from "test" - test what you build
   - Unit tests: Include in same task as code
   - Integration tests: Separate task that depends on the feature tasks
   - E2E tests: Final task after feature is complete

   DEPENDENCIES (CRITICAL - READ CAREFULLY):

   **LOCAL DEPENDENCIES (Within your component):**
   - The "depends_on" field MUST contain EXACT TASK TITLES from YOUR create_subtasks call
   - ❌ WRONG: "depends_on": ["infra-1", "task-1", "setup"]
   - ✅ CORRECT: "depends_on": ["Create tasks table in SQLite database"]
   - Link YOUR tasks in logical build order (database → API → UI → tests)
   - Use the FULL TITLE you defined earlier in the same create_subtasks call
   - Tasks within same feature can run parallel if independent (empty depends_on)

   **EXTERNAL DEPENDENCIES (From other components/planners):**
   - Other planners are working INDEPENDENTLY - you don't know their task titles
   - For cross-component dependencies, use "dependency_queries" with natural language
   - ✅ CORRECT: "dependency_queries": ["A backend API endpoint that provides user profile data"]
   - ✅ CORRECT: "dependency_queries": ["Completed database schema setup"]
   - ✅ CORRECT: "dependency_queries": ["Frontend UI components for user authentication"]
   - The Director will match your query to the actual task created by the other planner

   **Examples:**
   Frontend planner creating tasks:
   ```json
   {{
     "title": "Wire up user API calls in profile page",
     "depends_on": ["Build user profile UI component"],  // Local dependency
     "dependency_queries": ["Backend API endpoint for fetching user profile data"]  // External dependency
   }}
   ```

   Backend planner creating tasks:
   ```json
   {{
     "title": "Create user profile API endpoint",
     "depends_on": ["Setup database connection"],  // Local dependency
     "dependency_queries": []  // No external dependencies
   }}
   ```

   The Director will semantically match the frontend's query to the backend's task title.
5. **MANDATORY**: In EVERY subtask description, explicitly reference the spec: "Follow design_spec.md"
6. **CRITICAL**: Include at least ONE TEST task to validate your component
7. DO NOT output the plan in the chat - use tools only

**ABSOLUTE SCOPE CONSTRAINTS - ZERO TOLERANCE:**
- **NO SCOPE EXPANSION**: You have ZERO authority to expand scope beyond design_spec.md
- **STICK TO THE SPEC**: Only create tasks that implement what's in design_spec.md
- **NO EXTRAS**: Do NOT add Docker, CI/CD, deployment, monitoring, logging, analytics, or ANY "nice-to-haves"
- **NO "BEST PRACTICES" ADDITIONS**: Do not add infrastructure that "would be good in production"
- **MINIMUM VIABLE**: Create ONLY the tasks needed for core functionality in the spec
- **EXAMPLE**: If spec says "REST API with CRUD", create ONLY: models, routes, basic validation. NOT: caching, rate limiting, webhooks, admin panel, etc.
- **IF IN DOUBT**: Leave it out. The Director has already decided the scope. Your job is execution only.

Remember: The spec is law. You execute, you don't expand.

TASK QUALITY REQUIREMENTS:
1. **Commit-level granularity**: Reviewable as one PR
2. **Self-contained**: Includes build + verification
3. **Clear scope**: 3-6 specific acceptance criteria
4. **Logical order**: Dependencies make sense in development flow
5. **Ensure testing**: Include at least one test task - unit tests for feature level work, integration tests for integration level work, or end-to-end tests for end-to-end work

AVOID THESE PATTERNS:
- ❌ Creating "backend" vs "frontend" silos
- ❌ Separating all building from all testing
- ❌ Tasks too large (>400 LOC changes) or too small (trivial changes)
- ❌ Vague criteria like "make it work"
"""

    result = await _execute_react_loop(task, tools, system_prompt, state, config)

    # VALIDATION: Planners MUST create tasks
    if not result or not result.suggested_tasks or len(result.suggested_tasks) == 0:
        print(f"  [ERROR] Planner {task.id} completed without creating any tasks!", flush=True)
        # Return failed result
        return WorkerResult(
            status="failed",
            result_path=result.result_path if result else "",
            aar=AAR(
                summary="FAILED: Planner did not create any tasks. Must call create_subtasks.",
                approach="N/A",
                challenges=["Did not call create_subtasks"],
                decisions_made=[],
                files_modified=result.aar.files_modified if result and result.aar else []
            ),
            suggested_tasks=[]
        )


    print(f"  [SUCCESS] Planner created {len(result.suggested_tasks)} tasks", flush=True)
    return result
