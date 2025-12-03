# Prompt Changes: Feature → Commit Architecture

## Overview
Moving from component-based silos (backend/frontend/testing) to feature-based commits (user capabilities → atomic changes).

---

## CHANGE 1A: Director Spec Creation (Enhancement)

**File:** `src/nodes/director.py`
**Lines:** ~429-489 (in `spec_prompt` within `_decompose_objective`)

**FIND THIS SECTION:**
```python
- **Dependency Isolation**: MANDATORY instructions for isolated environments
  * Python: Use `python -m venv .venv` and activate it before installing packages
  * Node.js: Use `npm install` (creates local node_modules)
  * Other: Specify equivalent isolation mechanism
```

**ADD AFTER IT:**
```python
  * **CRITICAL**: Create .gitignore that excludes:
    - .venv/ or venv/
    - node_modules/
    - __pycache__/
    - *.pyc
    - *.db (if using SQLite for development)
    - Any other generated files
  * This prevents worktree pollution and keeps git operations fast
```

**Why:** Ensures .gitignore is created to prevent huge folders from being copied to worktrees.

---

## CHANGE 1B: Director Planner Decomposition (Full Replacement)

**File:** `src/nodes/director.py`
**Lines:** ~490-508 (the `decomp_prompt` within `_decompose_objective`)

**FIND THIS ENTIRE SECTION:**
```python
decomp_prompt = ChatPromptTemplate.from_messages([
    ("system", """You are the Director decomposing a project into component planners.

CRITICAL INSTRUCTIONS:
1. Create 1-5 PLANNER tasks, one for each major component (e.g., Backend, Frontend, Testing)
2. Each task should have phase="plan" and worker_profile="planner_worker"
3. Do NOT create build or test tasks - planners will create those
4. Keep it minimal - only create planners for components that are truly necessary
5. Component examples: "backend", "frontend", "database", "testing", "api"

OUTPUT:
Create planner tasks following this schema."""),
    ("user", """Objective: {objective}

Design Spec Summary:
{spec_summary}

Create 1-5 planner tasks to delegate component planning.""")
])
```

**REPLACE WITH:**
```python
decomp_prompt = ChatPromptTemplate.from_messages([
    ("system", """You are the Director decomposing a project into FEATURE-LEVEL planners.

CRITICAL INSTRUCTIONS - FEATURE-BASED DECOMPOSITION:

1. **FIRST: Check if infrastructure planner is needed**
   - Does design spec require: Flask setup, database init, React config, etc?
   - If YES: Create "Set up [project] infrastructure" planner as FIRST task
   
2. **THEN: Create planners for user-facing features**
   - Think "User can..." or "System provides..."
   - Order logically: foundational features before dependent ones
   - Example: "User can add items" before "User can delete items"
   
3. **FINALLY: Create validation planner** 
   - "System validates with [test framework]"
   - Always last

FEATURE PLANNER EXAMPLES:

✅ INFRASTRUCTURE (if needed, always FIRST):
- Component: "infrastructure", Description: "Set up kanban application infrastructure"
- Component: "infrastructure", Description: "Initialize React dashboard with routing"

✅ USER FEATURES (in logical order):
- Component: "add-items", Description: "User can add items to the system"
- Component: "view-items", Description: "User can view items in organized layout"
- Component: "modify-items", Description: "User can modify item properties"
- Component: "delete-items", Description: "User can delete items"

✅ VALIDATION (always LAST):
- Component: "validation", Description: "System validates core functionality with Playwright"

❌ NEVER DO THIS:
- Component: "backend" (too technical, not feature-based)
- Component: "frontend" (too technical, not feature-based)
- Component: "testing" (testing is part of features)
- Component: "database" (unless it's the infrastructure planner)

RULES:
- Create 1-7 planner tasks (infra + features + validation)
- Each task should have phase="plan" and worker_profile="planner_worker"
- Do NOT create build or test tasks - planners will create those
- Component name should be the feature slug (e.g., "add-items", "infrastructure")
- Features should be user-facing capabilities, NOT technical components

OUTPUT:
Create planner tasks following this schema. Order them: infrastructure → features → validation."""),
    ("user", """Objective: {objective}

Design Spec Summary:
{spec_summary}

Create feature-level planner tasks based on the design spec. Remember:
- Infrastructure first (if needed)
- User features in logical order
- Validation last""")
])
```

**Why:** Changes from component-based (backend/frontend/testing) to feature-based (user capabilities) decomposition.





---

## CHANGE 2: Planner System Prompt

**File:** `src/nodes/worker.py`
**Lines:** ~920-980 (planner worker system prompt)

**FIND THIS SECTION:**
```python
# Around line 940-960 in the planner system prompt
4. **CREATE BUILD AND TEST TASKS**: Use `create_subtasks` to define concrete work items:
   - BUILD phase tasks for implementation
   - TEST phase tasks for verification
   - Each task should have clear acceptance criteria
   - Link dependencies (test tasks depend on build tasks)
```

**REPLACE WITH:**
```python
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
   
   DEPENDENCIES:
   - Link tasks in logical build order
   - Database/models → API endpoints → UI → Integration tests
   - Tasks within same feature can run parallel if independent
```

---

## CHANGE 3: Integration Dependency Linking

**File:** `src/nodes/director.py`  
**Lines:** ~636-650 (plan integration prompt)

**FIND THIS SECTION:**
```python
5. **Link Dependencies**: Create a SINGLE unified dependency tree.
   - **NO SILOS**: Frontend, Backend, and Tests must be interconnected
   - **Backend first**: Frontend MUST depend on backend API being built
   ...
```

**ADD TO THE END:**
```python
   - **Commit granularity**: Each task should be one atomic commit
   - **Parallel when possible**: Tasks within same feature can run parallel if deps allow
   - **Example flow**: 
     * Database schema → API endpoint → UI component → Integration test
     * NOT: All backend → All frontend → All tests
```

---

## CHANGE 4: Task Quality Checks

**File:** `src/nodes/worker.py`
**Lines:** ~870-900 (planner guidance section)

**ADD TO PLANNER GUIDELINES:**
```python
TASK QUALITY REQUIREMENTS:
1. **Commit-level granularity**: Reviewable as one PR
2. **Self-contained**: Includes build + verification
3. **Clear scope**: 3-6 specific acceptance criteria
4. **Logical order**: Dependencies make sense in development flow

AVOID THESE PATTERNS:
- ❌ Creating "backend" vs "frontend" silos
- ❌ Separating all building from all testing
- ❌ Tasks too large (>100 LOC changes) or too small (trivial changes)
- ❌ Vague criteria like "make it work"
```

---

## CHANGE 5: Create Subtasks Tool Documentation

**File:** `src/nodes/worker.py`
**Lines:** ~771-799 (create_subtasks tool docstring)

**FIND:**
```python
def create_subtasks(subtasks: List[Dict[str, Any]]) -> str:
    """
    Create a list of subtasks to be executed by other workers.
    ...
    Args:
        subtasks: List of dicts, each containing:
            - title: str
            - description: str
            - phase: "build" | "test" | "plan" | "research"
            - component: str (e.g., "backend", "frontend")
```

**REPLACE WITH:**
```python
def create_subtasks(subtasks: List[Dict[str, Any]]) -> str:
    """
    Create COMMIT-LEVEL subtasks to be executed by other workers.
    
    IMPORTANT: Think in terms of GIT COMMITS, not components!
    Each task should represent ONE atomic, reviewable change.
    
    Args:
        subtasks: List of dicts, each containing:
            - title: str (concise, commit-message-style)
            - description: str (what changes, why, acceptance criteria)
            - phase: "build" | "test" (NOT separate - build includes inline tests)
            - component: str (optional, use feature name instead of "backend"/"frontend")
            - depends_on: List[str] (titles of tasks this depends on)
            - worker_profile: "code_worker" | "test_worker" (default based on phase)
    
    EXAMPLES OF GOOD TASKS:
    {
      "title": "Create tasks table in SQLite database",
      "description": "Set up database schema with id, title, status columns. Include migration script and verification query.",
      "phase": "build",
      "depends_on": []
    },
    {
      "title": "Implement GET /api/tasks endpoint",
      "description": "Create Flask route to return all tasks as JSON. Include unit test for happy path and empty state.",
      "phase": "build",
      "depends_on": ["Create tasks table in SQLite database"]
    },
    {
      "title": "Playwright test: Add and view task",
      "description": "E2E test that adds a task via UI and verifies it appears in correct column.",
      "phase": "test",
      "depends_on": ["Implement POST /api/tasks endpoint", "Add task creation UI component"]
    }
```

---

## Summary of Changes

| Location | What to Change | Why |
|----------|---------------|-----|
| `director.py` decomposition | Component silos → Feature capabilities | Natural user-facing breakdown |
| `worker.py` planner prompt | BUILD+TEST phases → Commit-level tasks | Atomic, reviewable units |
| `director.py` integration | Component linking → Commit flow | Logical development order |
| `worker.py` quality checks | Add commit granularity rules | Prevent too-large/too-small |
| `worker.py` tool docs | Update examples | Show commit-style thinking |

## Expected Results

**Before:**
```
Director
├── Plan backend (3 tasks)
│   ├── Build API
│   ├── Build DB
│   └── Build validation
├── Plan frontend (4 tasks)
│   └── ...
└── Plan testing (2 tasks)
    └── ...
```

**After:**
```
Director
├── Set up kanban application infrastructure (4 commits)
│   ├── Initialize Flask application with CORS
│   ├── Create SQLite database with tasks table
│   ├── Add requirements.txt and .gitignore
│   └── Verify basic app runs
├── User can add tasks (3 commits) [DEPENDS ON: infrastructure]
│   ├── Implement POST /api/tasks endpoint
│   ├── Add task creation UI component
│   └── Test task addition flow
├── User can move tasks (2 commits) [DEPENDS ON: add tasks]
│   ├── Implement PUT /api/tasks/<id> endpoint
│   └── Add drag-drop UI with state updates
└── System validates with Playwright (2 commits) [DEPENDS ON: all features]
    ├── Set up Playwright test environment
    └── E2E test: Complete kanban workflow
```

**Key Differences:**
1. ✅ Infrastructure feature comes FIRST
2. ✅ User features depend on infrastructure
3. ✅ Features ordered by dependency (add before move)
4. ✅ Validation last after all features
5. ✅ NO backend/frontend silos


## Notes for Implementation

1. Apply changes in order (Director first, then Planner)
2. Test with small objective first
3. Watch for planners still creating silos - may need iteration
4. Console output should show "feature" language, not "backend/frontend"
