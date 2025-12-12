"""
Director Module - Objective Decomposition
=========================================
Breaks down high-level objectives into concrete tasks.
"""

import json
import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List
from pydantic import BaseModel, Field
from langchain_core.prompts import ChatPromptTemplate

from orchestrator_types import Task, TaskStatus, TaskPhase, WorkerProfile
from llm_client import get_llm

logger = logging.getLogger(__name__)


# =============================================================================
# PYDANTIC SCHEMAS
# =============================================================================

class TaskDefinition(BaseModel):
    """LLM-generated task definition."""
    title: str = Field(description="Short title")
    component: str = Field(description="Component name")
    phase: str = Field(description="plan, build, or test")
    description: str
    acceptance_criteria: List[str]
    depends_on_indices: List[int] = Field(default_factory=list)
    worker_profile: str = "code_worker"


class DecompositionResponse(BaseModel):
    """LLM response for task decomposition."""
    tasks: List[TaskDefinition]


# =============================================================================
# FUNCTIONS
# =============================================================================

def mock_decompose(objective: str) -> List[Task]:
    """Mock decomposition for testing - creates realistic task breakdown."""
    logger.info(f"MOCK: Decomposing '{objective}' without LLM")

    # Generate base IDs
    base_id = uuid.uuid4().hex[:6]
    plan_id = f"task_{base_id}_plan"
    impl_id = f"task_{base_id}_impl"
    test_id = f"task_{base_id}_test"

    return [
        # Task 1: Planning
        Task(
            id=plan_id,
            title="Design API architecture",
            component="api",
            phase=TaskPhase.PLAN,
            status=TaskStatus.PLANNED,
            assigned_worker_profile=WorkerProfile.PLANNER,
            description="Design API architecture and endpoints",
            acceptance_criteria=[
                "Architecture document created",
                "Endpoints documented"
            ],
            depends_on=[],
            created_at=datetime.now(),
            updated_at=datetime.now()
        ),
        # Task 2: Implementation (depends on plan)
        Task(
            id=impl_id,
            title="Implement API endpoints",
            component="api",
            phase=TaskPhase.BUILD,
            status=TaskStatus.PLANNED,
            assigned_worker_profile=WorkerProfile.CODER,
            description="Implement API endpoints based on design",
            acceptance_criteria=[
                "API code implemented",
                "Unit tests written",
                "Code committed"
            ],
            depends_on=[plan_id],
            created_at=datetime.now(),
            updated_at=datetime.now()
        ),
        # Task 3: Testing (depends on implementation)
        Task(
            id=test_id,
            title="Test API endpoints",
            component="api",
            phase=TaskPhase.TEST,
            status=TaskStatus.PLANNED,
            assigned_worker_profile=WorkerProfile.TESTER,
            description="Validate API meets acceptance criteria",
            acceptance_criteria=[
                "Integration tests pass",
                "API responds correctly"
            ],
            depends_on=[impl_id],
            created_at=datetime.now(),
            updated_at=datetime.now()
        )
    ]


async def decompose_objective(objective: str, spec: Dict[str, Any], state: Dict[str, Any]) -> List[Task]:
    """
    High-level decomposition + spec creation (async version).

    The Director (using the smartest model) creates design_spec.md
    and delegates to 1-5 component planners.

    Args:
        objective: High-level user objective
        spec: Additional specification details
        state: Current orchestrator state (for workspace_path, config, etc.)

    Returns:
        List of planner tasks
    """
    # Get orchestrator config from state (has user's model settings)
    orch_config = state.get("orch_config")
    if not orch_config:
        from config import OrchestratorConfig
        orch_config = OrchestratorConfig()

    model_config = orch_config.director_model
    workspace_path = state.get("_workspace_path")

    llm = get_llm(model_config)

    # STEP 0: Explore existing project structure (if workspace exists)
    project_context = ""
    if workspace_path:
        logger.info("Exploring existing project structure")

        try:
            # List root directory
            ws_path = Path(workspace_path)
            if ws_path.exists():
                import os
                entries = os.listdir(ws_path)
                # Format as a tree-like listing
                listing_lines = []
                for entry in sorted(entries):
                    entry_path = ws_path / entry
                    if entry_path.is_dir():
                        listing_lines.append(f"📁 {entry}/")
                    else:
                        listing_lines.append(f"📄 {entry}")
                root_listing = "\n".join(listing_lines[:50])  # Limit to 50 entries
                if len(entries) > 50:
                    root_listing += f"\n... and {len(entries) - 50} more files"
                project_context += f"## Existing Project Structure\n```\n{root_listing}\n```\n\n"

            # Check for common config files
            common_files = [
                "package.json", "requirements.txt", "pyproject.toml",
                "README.md", "design_spec.md", "tsconfig.json",
                "vite.config.ts", "vite.config.js"
            ]

            for filename in common_files:
                filepath = ws_path / filename
                if filepath.exists():
                    try:
                        content = filepath.read_text(encoding="utf-8")
                        # Truncate very long files
                        if len(content) > 2000:
                            content = content[:2000] + "\n... (truncated)"
                        project_context += f"## {filename}\n```\n{content}\n```\n\n"
                        logger.info(f"Read: {filename}")
                    except Exception as e:
                        logger.warning(f"Could not read {filename}: {e}")

            logger.info(f"Project exploration complete. Found {len(project_context)} chars of context")
        except Exception as e:
            logger.warning(f"Project exploration failed: {e}")

    # STEP 1: Write design specification
    logger.info("Creating design specification")

    spec_prompt = ChatPromptTemplate.from_messages([
        ("system", """You are a Lead Architect creating a design specification.

CRITICAL INSTRUCTIONS:
1. Analyze the objective and determine the necessary components (e.g., Backend, Frontend, Database, Testing)
2. Create a comprehensive design specification that will guide all workers
3. You have leeway to make architectural decisions that best serve the objective
4. Focus on MVP - deliver the core functionality requested, avoid unnecessary extras
5. **ALWAYS include dependency isolation** to prevent package pollution across projects
6. **CONSIDER EXISTING PROJECT STRUCTURE** - if files already exist, build upon them rather than recreating

{project_context}

OUTPUT:
Write a design specification in markdown format with these sections:
- **Overview**: Brief project summary
- **Components**: List each component (Backend, Frontend, etc.)
- **Existing Code Analysis**: If project files exist, describe what's already there and what needs work
- **Dependency Isolation**: MANDATORY instructions for isolated environments
  * Python: Use `python -m venv .venv` and activate it before installing packages
  * Node.js: Use `npm install` (creates local node_modules)
  * Other: Specify equivalent isolation mechanism
- **API Routes** (if applicable): Methods, paths, request/response formats
- **Data Models** (if applicable): Schemas, database tables, field types
- **File Structure**: Where files should be created
- **Technology Stack**: What frameworks/libraries to use
- **.gitignore Requirements**: MANDATORY - must include: .venv/, venv/, node_modules/, __pycache__/, *.pyc, .env

  * **CRITICAL**: Make sure the design spec includes a .gitignore that excludes:
    - .venv/ or venv/
    - node_modules/
    - __pycache__/
    - *.pyc
    - *.db (if using SQLite for development)
    - Any other generated files
  * This prevents worktree pollution and keeps git operations fast

Be specific enough that workers can implement without ambiguity."""),
        ("user", "Objective: {objective}")
    ])

    # LOG: Director spec creation request
    logs_base_path = state.get("_logs_base_path")
    if logs_base_path:
        log_dir = Path(logs_base_path) / "director"
        log_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        request_log = log_dir / f"spec_request_{timestamp}.json"
        with open(request_log, 'w', encoding='utf-8') as f:
            json.dump({
                "timestamp": datetime.now().isoformat(),
                "type": "spec_creation",
                "objective": objective,
                "project_context_length": len(project_context)
            }, f, indent=2)
        logger.info(f"Director spec request logged: {request_log}")

    try:
        spec_response = await llm.ainvoke(spec_prompt.format(objective=objective, project_context=project_context))
        spec_content = str(spec_response.content)

        # LOG: Director spec response
        if logs_base_path:
            response_log = log_dir / f"spec_response_{timestamp}.json"
            with open(response_log, 'w', encoding='utf-8') as f:
                json.dump({
                    "timestamp": datetime.now().isoformat(),
                    "type": "spec_creation",
                    "spec_length": len(spec_content),
                    "spec_preview": spec_content[:1000] + "..." if len(spec_content) > 1000 else spec_content
                }, f, indent=2)
            logger.info(f"Director spec response logged: {response_log} ({len(spec_content)} chars)")

        # Write spec to workspace
        if workspace_path:
            spec_path = Path(workspace_path) / "design_spec.md"
            spec_path.write_text(spec_content, encoding="utf-8")
            logger.info("Written: design_spec.md")

            # Commit to main to avoid merge conflicts later
            wt_manager = state.get("_wt_manager")
            if wt_manager and not state.get("mock_mode", False):
                try:
                    await wt_manager.commit_to_main(
                        message="Director: Add design specification",
                        files=["design_spec.md"]
                    )
                    logger.info("Committed: design_spec.md")
                except Exception as e:
                    logger.warning(f"Failed to commit spec: {e}")
    except Exception as e:
        logger.warning(f"Failed to create spec: {e}")
        spec_content = f"# Design Spec\n\nObjective: {objective}\n\nPlease create a minimal viable implementation."

    # STEP 2: Decompose into 1-5 component planner tasks
    logger.info("Creating component planner tasks")

    structured_llm = llm.with_structured_output(DecompositionResponse)

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
Create planner tasks following this schema. Order them: infrastructure -> features -> validation."""),
        ("user", """Objective: {objective}

Design Spec Summary:
{spec_summary}

Create feature-level planner tasks based on the design spec. Remember:
- Infrastructure first (if needed)
- User features in logical order
- Validation last""")
    ])

    try:
        # Use first 500 chars of spec as summary
        spec_summary = spec_content[:500] + "..." if len(spec_content) > 500 else spec_content

        response = await structured_llm.ainvoke(decomp_prompt.format(
            objective=objective,
            spec_summary=spec_summary
        ))

        tasks = []
        for t_def in response.tasks:
            # Ensure it's a planner task
            if t_def.phase.lower() != "plan":
                logger.warning(f"Director tried to create {t_def.phase} task, converting to 'plan'")

            task = Task(
                id=f"task_{uuid.uuid4().hex[:8]}",
                title=t_def.title,
                component=t_def.component,
                phase=TaskPhase.PLAN,
                status=TaskStatus.PLANNED,
                assigned_worker_profile=WorkerProfile.PLANNER,
                description=f"{t_def.description}\n\nREFERENCE: design_spec.md for architecture details.",
                acceptance_criteria=t_def.acceptance_criteria,
                depends_on=[],
                created_at=datetime.now(),
                updated_at=datetime.now()
            )
            tasks.append(task)

        logger.info(f"Created {len(tasks)} planner task(s)")
        return tasks

    except Exception as e:
        logger.error(f"Decomposition error: {e}, using fallback")
        # Fallback: single planner for the entire project
        return [Task(
            id=f"task_{uuid.uuid4().hex[:8]}",
            title=f"Plan implementation: {objective[:50]}",
            component="main",
            phase=TaskPhase.PLAN,
            status=TaskStatus.PLANNED,
            assigned_worker_profile=WorkerProfile.PLANNER,
            description=f"Plan implementation for: {objective}\n\nREFERENCE: design_spec.md for architecture details.",
            acceptance_criteria=["Create implementation plan", "Define build and test tasks"],
            depends_on=[],
            created_at=datetime.now(),
            updated_at=datetime.now()
        )]
