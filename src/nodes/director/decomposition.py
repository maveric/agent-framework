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
from .integration import broadcast_progress

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
        await broadcast_progress(state, "Exploring existing project structure...", "initialization")

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
    await broadcast_progress(state, "Creating design specification (AI)...", "initialization")

    spec_prompt = ChatPromptTemplate.from_messages([
        ("system", """You are a Lead Architect creating a design specification.

CRITICAL INSTRUCTIONS:
1. Analyze the objective and determine the necessary components (Backend, Frontend, Database, Testing).
2. **DESIGN FOR PARALLELISM**: Structure the application so that features are loosely coupled. Avoid monolithic files (e.g., instead of one huge `routes.py`, suggest `routes/auth.py`, `routes/tasks.py`).
3. Focus on MVP - deliver the core functionality requested.
4. **CONSIDER EXISTING PROJECT STRUCTURE** - If files exist, explicitly state how to integrate with them. Do not reinvent the wheel.
5. **DEPENDENCY ISOLATION**: MANDATORY.

{project_context}

OUTPUT:
Write a design specification in markdown format with these sections:

- **Overview**: Brief project summary.

- **Scaffolding & Setup**: 
  * Define the commands to initialize the project (e.g., `npm create vite`, `python -m venv`).
  * List MAJOR dependencies (FastAPI, React, Tailwind, SQLAlchemy, etc.).
  * Define the **Exact File Structure** (CRITICAL: Define the folder hierarchy strictly to prevent agents from creating conflicting paths).

- **Testing Strategy**:
  * Define tools (Pytest, Playwright, Jest).
  * Define where tests should live (e.g., `backend/tests/` or `src/components/__tests__/`).

- **Feature Specifications (Vertical Slices)**:
  * Break the app down by FEATURE (e.g., "User Auth", "Todo Management", "Settings").
  * For EACH feature, define:
    * **Data Models**: The specific tables/schemas needed.
    * **API Routes**: The endpoints required (Method, Path, Request/Response).
    * **UI Components**: The frontend views/components needed.
  * *Grouping requirements by feature helps workers build vertically without blocking each other.*

- **.gitignore Requirements**: 
  * MUST include: .venv/, venv/, node_modules/, __pycache__/, *.pyc, .env, *.db, dist/, build/, coverage/
  * Explicitly state that `agents-work/` is the workspace directory.

- **Implementation Guidelines**:
  * Specific coding standards or patterns to use.

Be specific enough that multiple workers can implement different features simultaneously without conflict."""),
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
            await broadcast_progress(state, "✓ Design specification created", "initialization")

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
    await broadcast_progress(state, "Creating component planners (AI)...", "initialization")

    structured_llm = llm.with_structured_output(DecompositionResponse)

    decomp_prompt = ChatPromptTemplate.from_messages([
        ("system", """You are the Lead Architect decomposing a complex objective into parallel execution streams.

    OBJECTIVE: {objective}

    **CORE RESPONSIBILITY:**
    Identify the "Foundation" (what must happen first) and the "Workstreams" (what can happen in parallel).

    **DECOMPOSITION STRATEGY:**
    1. **Identify the Foundation (The "Setup" Component):**
    - Is there shared context, configuration, or environment setup required before work begins?
    - *Coding Example:* "Project Scaffolding & Config"
    - *Writing Example:* "Outline & Character Profiles"
    - *Research Example:* "Literature Review & Methodology Definition"
    - **Constraint:** Create EXACTLY ONE component for this if needed. Name it "foundation".

    2. **Identify Parallel Workstreams (The "Execution" Components):**
    - Break the main effort into independent, logical units.
    - *Coding:* Vertical Features (e.g., "User Auth", "Payment Processing")
    - *Writing:* Chapters or Sections (e.g., "Chapter 1-3", "Chapter 4-6")
    - *Marketing:* Channels (e.g., "Social Media Content", "Email Campaign")
    - **Rule:** These should NOT depend on each other if possible. They only depend on "foundation".

    3. **Identify Verification (The "Quality" Component):**
    - How do we validate the result?
    - Name it "verification".

    **OUTPUT SCHEMA:**
    Create planner tasks.
    - `component`: "foundation" | [workstream-slug] | "verification"
    - `description`: CLEARLY define boundaries.
    - For "foundation": "ESTABLISH the environment/context for others."
    - For "workstreams": "ASSUME foundation is done. Execute specific scope."
    """),
        ("user", "Objective: {objective}\nSpec Summary: {spec_summary}")
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
        await broadcast_progress(state, f"✓ Created {len(tasks)} component planners", "initialization")
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
