"""
Plan handler for planning tasks.
"""

from typing import Dict, Any
import logging
import platform

from orchestrator_types import Task, WorkerProfile, WorkerResult, AAR

logger = logging.getLogger(__name__)

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
        logger.warning(f"Max planner limit reached ({MAX_PLANNERS}). Forcing direct task creation.")

    tools = [read_file, write_file, list_directory, file_exists, create_subtasks]
    tools = _bind_tools(tools, state, WorkerProfile.PLANNER)

    # Platform-specific shell warning
    is_windows = platform.system() == 'Windows'
    correct_path = "python folder\\\\script.py" if is_windows else "python folder/script.py"
    platform_warning = f"""
**🚨 CRITICAL - SHELL COMMANDS ({platform.system()}) 🚨**:
{"⚠️ YOU ARE ON WINDOWS - NEVER USE && IN COMMANDS!" if is_windows else "Unix shell: Use && or ; for chaining"}
- ❌ FORBIDDEN: `cd folder && python script.py` (BREAKS ON WINDOWS)
- ✅ CORRECT: `{correct_path}` (Run from project root)
The run_shell tool ALREADY runs in the correct working directory. DO NOT use cd.
"""

    # ==========================================================================
    # HIERARCHY-AWARE PLANNER: Foundation vs Feature
    # ==========================================================================
    # Get component name from task to determine role
    component_name = getattr(task, 'component', '') or ''
    is_foundation = component_name.lower() in ["foundation", "infrastructure"]
    
    logger.info(f"Planner {task.id} component='{component_name}' is_foundation={is_foundation}")

    # ROLE-SPECIFIC INSTRUCTIONS
    if is_foundation:
        role_instructions = """
**🏗️ ROLE: FOUNDATION ARCHITECT**
You are pouring the concrete foundation. You OWN the project scaffolding.

✅ **YOU MUST**:
- Create a massive "Scaffold/Setup" task that handles ALL initial configuration
- Install ALL dependencies from the design spec (package.json, requirements.txt)
- Setup database connections, environment config, base routing
- Create folder structure, base CSS/styling, auth setup if needed

✅ **YOU OWN**:
- package.json, requirements.txt, pyproject.toml
- vite.config.js, tailwind.config.js, tsconfig.json  
- database.py, db/connection.py, config files
- Base CSS, global styles, layout components

🧪 **FOUNDATION TESTS = SIMPLE SMOKE TESTS ONLY**:
Your test task should ONLY verify:
- Dependencies installed successfully (npm install / pip install worked)
- Dev server starts without crashing
- Database connection works (if applicable)
- Basic folders exist

DO NOT test features, APIs, or UI. NO Playwright. NO pytest for routes.
Feature planners handle their own feature tests.

**Your tasks should have NO dependency_queries** - you are the root of the tree.
"""
    else:
        role_instructions = f"""
**🪑 ROLE: FEATURE ARCHITECT** (Component: {component_name})
You are adding a room to an existing house. The system automatically ensures foundation completes before your feature starts.

❌ **FORBIDDEN - DO NOT DO THESE**:
- Do NOT create "Setup", "Init", "Install", or "Scaffold" tasks
- Do NOT touch package.json, requirements.txt, or any config files
- Do NOT install dependencies (foundation handles that)
- Do NOT create database connection logic (foundation handles that)
- Do NOT setup routing/framework base (foundation handles that)

✅ **ASSUME** (foundation is FULLY complete before your tasks run):
- Project is fully scaffolded and configured
- All dependencies are installed
- Database connection exists and works
- Router/framework is initialized
- You can focus 100% on your feature logic

🔗 **FOUNDATION LINKING IS AUTOMATIC**:
- The system automatically links your first task to wait for foundation
- You do NOT need to add dependency_queries for foundation
- Focus on feature-to-feature dependencies if your feature needs another feature

**CROSS-FEATURE DEPENDENCIES** (if needed):
If your feature depends on ANOTHER feature (not foundation), add dependency_queries:
```json
"dependency_queries": ["User authentication API is complete"]
```

**Your job**: Build the {component_name} feature ONLY - models, routes, UI, tests for THIS feature.
"""

    # ==========================================================================
    # UNIFIED PLANNER PROMPT - OPTIMIZED FOR PARALLELISM
    # ==========================================================================
    system_prompt = f"""You are a Lead Architect & Component Planner for: "{component_name or 'unknown'}"
{platform_warning}

{role_instructions}

---

**TOOL USAGE RULES**:
- Use `list_directory(".")` to see the project root.
- Use relative paths: "design_spec.md" or "agents-work/plans/".
- Use `read_file()` for FILES only, use `list_directory()` for directories.

**RESEARCH WORKERS - USE SPARINGLY**:
Research tasks are blocking. Create them ONLY for niche/esoteric technology.
- ❌ DO NOT research standard tech (React, FastAPI, SQL, etc). Implement directly.

---

### 🚀 PLANNING STRATEGY: VERTICAL SLICING

**{"FOUNDATION PLANNER" if is_foundation else "FEATURE PLANNER"} INSTRUCTIONS:**

{"" if is_foundation else '''
**Since you are a FEATURE planner, your tasks should be vertical slices:**
- Each task delivers a WORKING FEATURE (Model + API + UI + Test)
- Minimize dependencies between your tasks
- All your tasks should query for foundation completion
'''}

{"" if not is_foundation else '''
**Since you are the FOUNDATION planner, create ONE massive setup task:**
- Install ALL dependencies from the spec
- Configure ALL tooling (vite, tailwind, eslint, etc)
- Setup database connection
- Create folder structure
- This unblocks ALL other planners to work in parallel
'''}

---

### DEPENDENCIES (CRITICAL)

**LOCAL DEPENDENCIES (`depends_on`):**
- EXACT TASK TITLES from YOUR create_subtasks call
- ✅ CORRECT: `"depends_on": ["Initialize Project Structure"]`

**EXTERNAL DEPENDENCIES (`dependency_queries`):**
- Natural language queries for tasks from OTHER planners
- ✅ CORRECT: `"dependency_queries": ["Project foundation and base configuration is complete"]`
- The Director semantically matches these to actual tasks

{"" if is_foundation else '''
🚨 **REMINDER**: Your first task MUST have:
```json
"dependency_queries": ["Project foundation and base configuration is complete"]
```
'''}

---

### CRITICAL INSTRUCTIONS
1. **READ THE SPEC**: Check `design_spec.md`. This is your source of truth.
2. **EXPLORE**: Use `list_directory` to see what exists.
3. **WRITE PLAN**: Write to `agents-work/plans/plan-{component_name or 'component'}-{task.id[:8]}.md`.
4. **CREATE TASKS**: Use `create_subtasks`.

**TASK SCHEMA (JSON):**
```json
{{{{
  "title": "{"Initialize Project & Install Dependencies" if is_foundation else "Implement [Feature] Models & API"}",
  "worker_profile": "code_worker",
  "phase": "build",
  "depends_on": [],
  "dependency_queries": {"[]" if is_foundation else '["Project foundation and base configuration is complete"]'},
  "description": "{"Scaffold complete project. Install ALL deps. Setup DB. Create folder structure." if is_foundation else "Build the [feature] logic. Follow design_spec.md."}",
  "acceptance_criteria": ["..."]
}}}}
```

---

### 🚨 MANDATORY TEST TASKS 🚨
You MUST create at least ONE task with `phase: "test"`.
- Worker: `test_worker`
- Dependencies: Must depend on the build tasks it validates

---

### ABSOLUTE CONSTRAINTS
- **NO SCOPE EXPANSION**: Only what's in design_spec.md.
- {"**YOU OWN SCAFFOLDING**: Create the foundation for others." if is_foundation else "**NO SCAFFOLDING**: Foundation handles that. Focus on your feature ONLY."}
- **MANDATORY TESTING**: At least one task with phase:"test".

Generate your plan now.
"""

    result = await _execute_react_loop(task, tools, system_prompt, state, config)

    # VALIDATION: Planners MUST create tasks
    if not result or not result.suggested_tasks or len(result.suggested_tasks) == 0:
        logger.error(f"Planner {task.id} completed without creating any tasks!")
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

    # VALIDATION: Planners MUST create at least one TEST task
    test_tasks = [
        t for t in result.suggested_tasks 
        if hasattr(t, 'phase') and (
            t.phase == 'test' or 
            str(t.phase).lower() == 'test' or 
            (hasattr(t.phase, 'value') and t.phase.value == 'test')
        )
    ]
    
    if len(test_tasks) == 0:
        logger.error(f"Planner {task.id} created {len(result.suggested_tasks)} tasks but ZERO test tasks!")
        logger.error(f"Task phases: {[str(t.phase) if hasattr(t, 'phase') else 'no-phase' for t in result.suggested_tasks]}")
        return WorkerResult(
            status="failed",
            result_path=result.result_path if result else "",
            aar=AAR(
                summary=f"FAILED: Planner created {len(result.suggested_tasks)} tasks but NO test tasks. Every plan MUST include at least one task with phase:'test'.",
                approach="N/A",
                challenges=["Did not create any test tasks (phase: 'test')"],
                decisions_made=[],
                files_modified=result.aar.files_modified if result and result.aar else []
            ),
            suggested_tasks=[]
        )

    # INFO: Note if feature planners have any cross-feature dependency_queries
    # Foundation linking is now handled automatically in code (integration.py)
    if not is_foundation:
        tasks_with_dep_queries = [
            t for t in result.suggested_tasks
            if hasattr(t, 'dependency_queries') and t.dependency_queries and len(t.dependency_queries) > 0
        ]
        
        if len(tasks_with_dep_queries) == 0:
            logger.info(f"ℹ️ Feature planner {task.id} has no cross-feature dependency_queries (foundation linking is automatic)")
        else:
            logger.info(f"Feature planner has {len(tasks_with_dep_queries)} task(s) with cross-feature dependency_queries")

    logger.info(f"Planner created {len(result.suggested_tasks)} tasks ({len(test_tasks)} test tasks)")
    return result

