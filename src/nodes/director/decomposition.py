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
from typing import Any, Dict, List, Optional
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
# TDD INTERFACE SCHEMAS
# =============================================================================

class APIEndpoint(BaseModel):
    """Single API endpoint definition."""
    method: str = Field(description="HTTP method (GET, POST, PUT, DELETE, PATCH)")
    path: str = Field(description="URL path (e.g., /api/users)")
    request_body: Optional[str] = Field(default=None, description="Request body schema as Python dict/Pydantic string")
    response_body: str = Field(description="Response body schema as Python dict/Pydantic string")
    description: str = Field(description="What this endpoint does")


class DataModel(BaseModel):
    """Data model/schema definition."""
    name: str = Field(description="Model name (e.g., User, Task)")
    fields: Dict[str, str] = Field(description="Field name to type mapping (e.g., {'id': 'int', 'name': 'str'})")
    description: str = Field(description="What this model represents")


class InterfaceSpec(BaseModel):
    """Complete interface specification for TDD."""
    endpoints: List[APIEndpoint] = Field(default_factory=list, description="API endpoints")
    models: List[DataModel] = Field(default_factory=list, description="Data models/schemas")
    has_frontend: bool = Field(default=False, description="Whether project has a frontend component")
    frontend_components: List[str] = Field(default_factory=list, description="Key frontend components if applicable")


# =============================================================================
# INTERFACE GENERATION (TDD)
# =============================================================================

async def generate_interface_specs(
    objective: str,
    design_spec_content: str,
    workspace_path: str,
    state: Dict[str, Any]
) -> Optional[str]:
    """
    Generate concrete interface specifications from the design spec.

    This is the TDD "Contract" step - creating executable specifications
    that Test Architects will use to write failing tests.

    Args:
        objective: High-level user objective
        design_spec_content: The design_spec.md content
        workspace_path: Path to write interface files
        state: Current orchestrator state

    Returns:
        Path to the generated interface spec file, or None if failed
    """
    orch_config = state.get("orch_config")
    if not orch_config:
        from config import OrchestratorConfig
        orch_config = OrchestratorConfig()

    llm = get_llm(orch_config.director_model)
    structured_llm = llm.with_structured_output(InterfaceSpec)

    await broadcast_progress(state, "Generating interface specifications (TDD)...", "initialization")

    interface_prompt = ChatPromptTemplate.from_messages([
        ("system", """You are a Contract Architect defining precise, testable interfaces.

Your job is to extract CONCRETE, EXECUTABLE specifications from the design document.
These specifications will be used by Test Architects to write failing tests BEFORE any code is written.

**CRITICAL RULES:**
1. Every endpoint must have explicit request/response schemas
2. Every model must have explicit field types
3. Be PRECISE - vague specs lead to test/implementation mismatches
4. Use standard types: str, int, float, bool, List[X], Optional[X], Dict[str, X], datetime

**OUTPUT REQUIREMENTS:**

For each API endpoint, specify:
- HTTP method (GET, POST, PUT, DELETE, PATCH)
- Path (e.g., /api/users, /api/tasks/{task_id})
- Request body as a Python dict or Pydantic-style schema string
- Response body as a Python dict or Pydantic-style schema string
- Brief description

For each data model, specify:
- Model name (PascalCase)
- Field name to type mapping
- Brief description

Example endpoint:
```
method: POST
path: /api/users
request_body: {{"name": "str", "email": "str", "password": "str"}}
response_body: {{"id": "int", "name": "str", "email": "str", "created_at": "datetime"}}
description: Create a new user account
```

Example model:
```
name: User
fields: {{"id": "int", "name": "str", "email": "str", "password_hash": "str", "created_at": "datetime"}}
description: User account information
```

Analyze the design spec and extract ALL necessary interfaces."""),
        ("user", """Objective: {objective}

Design Specification:
{design_spec}

Extract all API endpoints and data models from this specification.""")
    ])

    try:
        response = await structured_llm.ainvoke(
            interface_prompt.format(
                objective=objective,
                design_spec=design_spec_content[:8000]  # Limit to avoid token overflow
            )
        )

        # Create interfaces directory
        interfaces_dir = Path(workspace_path) / "interfaces"
        interfaces_dir.mkdir(parents=True, exist_ok=True)

        # Generate api_spec.yaml (OpenAPI-style)
        api_spec_content = _generate_openapi_spec(response)
        api_spec_path = interfaces_dir / "api_spec.yaml"
        api_spec_path.write_text(api_spec_content, encoding="utf-8")
        logger.info(f"Written: interfaces/api_spec.yaml ({len(response.endpoints)} endpoints)")

        # Generate models.py (Pydantic models)
        models_content = _generate_pydantic_models(response)
        models_path = interfaces_dir / "models.py"
        models_path.write_text(models_content, encoding="utf-8")
        logger.info(f"Written: interfaces/models.py ({len(response.models)} models)")

        # Generate types.ts if frontend detected
        if response.has_frontend:
            types_content = _generate_typescript_types(response)
            types_path = interfaces_dir / "types.ts"
            types_path.write_text(types_content, encoding="utf-8")
            logger.info(f"Written: interfaces/types.ts")

        # Commit interface files
        wt_manager = state.get("_wt_manager")
        if wt_manager and not state.get("mock_mode", False):
            try:
                files_to_commit = ["interfaces/api_spec.yaml", "interfaces/models.py"]
                if response.has_frontend:
                    files_to_commit.append("interfaces/types.ts")
                await wt_manager.commit_to_main(
                    message="Director: Add TDD interface specifications",
                    files=files_to_commit
                )
                logger.info("Committed: interface specifications")
            except Exception as e:
                logger.warning(f"Failed to commit interfaces: {e}")

        await broadcast_progress(state, f"✓ Interface specs created ({len(response.endpoints)} endpoints, {len(response.models)} models)", "initialization")
        return str(api_spec_path)

    except Exception as e:
        logger.error(f"Failed to generate interface specs: {e}")
        await broadcast_progress(state, f"⚠ Interface generation failed: {e}", "initialization")
        return None


def _generate_openapi_spec(interface: InterfaceSpec) -> str:
    """Generate OpenAPI-style YAML specification."""
    lines = [
        "# TDD Interface Specification",
        "# Auto-generated by Director - DO NOT EDIT MANUALLY",
        "# Test Architects use this to write failing tests",
        "",
        "openapi: '3.0.0'",
        "info:",
        "  title: API Specification",
        "  version: '1.0.0'",
        "  description: Auto-generated interface contract for TDD",
        "",
        "paths:"
    ]

    for endpoint in interface.endpoints:
        method = endpoint.method.lower()
        lines.append(f"  {endpoint.path}:")
        lines.append(f"    {method}:")
        lines.append(f"      summary: {endpoint.description}")
        if endpoint.request_body:
            lines.append("      requestBody:")
            lines.append("        required: true")
            lines.append("        content:")
            lines.append("          application/json:")
            lines.append(f"            schema: {endpoint.request_body}")
        lines.append("      responses:")
        lines.append("        '200':")
        lines.append("          description: Success")
        lines.append("          content:")
        lines.append("            application/json:")
        lines.append(f"              schema: {endpoint.response_body}")
        lines.append("")

    if interface.models:
        lines.append("components:")
        lines.append("  schemas:")
        for model in interface.models:
            lines.append(f"    {model.name}:")
            lines.append(f"      description: {model.description}")
            lines.append("      type: object")
            lines.append("      properties:")
            for field_name, field_type in model.fields.items():
                openapi_type = _python_type_to_openapi(field_type)
                lines.append(f"        {field_name}:")
                lines.append(f"          type: {openapi_type}")

    return "\n".join(lines)


def _generate_pydantic_models(interface: InterfaceSpec) -> str:
    """Generate Pydantic model definitions."""
    lines = [
        '"""',
        'TDD Interface Models',
        'Auto-generated by Director - DO NOT EDIT MANUALLY',
        '',
        'These models define the contract between components.',
        'Test Architects use these to write failing tests.',
        '"""',
        '',
        'from datetime import datetime',
        'from typing import List, Optional, Dict, Any',
        'from pydantic import BaseModel, Field',
        '',
        ''
    ]

    for model in interface.models:
        lines.append(f"class {model.name}(BaseModel):")
        lines.append(f'    """{model.description}"""')
        if not model.fields:
            lines.append("    pass")
        else:
            for field_name, field_type in model.fields.items():
                pydantic_type = _normalize_python_type(field_type)
                lines.append(f"    {field_name}: {pydantic_type}")
        lines.append("")
        lines.append("")

    # Add request/response models for endpoints
    lines.append("# Request/Response Models")
    lines.append("")

    for i, endpoint in enumerate(interface.endpoints):
        # Create request model if there's a request body
        if endpoint.request_body:
            class_name = _endpoint_to_class_name(endpoint.path, endpoint.method, "Request")
            lines.append(f"class {class_name}(BaseModel):")
            lines.append(f'    """{endpoint.description} - Request"""')
            lines.append(f"    # Schema: {endpoint.request_body}")
            lines.append("    pass  # TODO: Expand from schema")
            lines.append("")

        # Create response model
        class_name = _endpoint_to_class_name(endpoint.path, endpoint.method, "Response")
        lines.append(f"class {class_name}(BaseModel):")
        lines.append(f'    """{endpoint.description} - Response"""')
        lines.append(f"    # Schema: {endpoint.response_body}")
        lines.append("    pass  # TODO: Expand from schema")
        lines.append("")

    return "\n".join(lines)


def _generate_typescript_types(interface: InterfaceSpec) -> str:
    """Generate TypeScript type definitions."""
    lines = [
        "/**",
        " * TDD Interface Types",
        " * Auto-generated by Director - DO NOT EDIT MANUALLY",
        " *",
        " * These types define the contract between frontend and backend.",
        " * Test Architects use these to write failing tests.",
        " */",
        "",
    ]

    for model in interface.models:
        lines.append(f"/** {model.description} */")
        lines.append(f"export interface {model.name} {{")
        for field_name, field_type in model.fields.items():
            ts_type = _python_type_to_typescript(field_type)
            lines.append(f"  {field_name}: {ts_type};")
        lines.append("}")
        lines.append("")

    # Add API endpoint types
    lines.append("// API Endpoint Types")
    lines.append("")

    for endpoint in interface.endpoints:
        class_name = _endpoint_to_class_name(endpoint.path, endpoint.method, "")
        lines.append(f"/** {endpoint.method} {endpoint.path} - {endpoint.description} */")
        if endpoint.request_body:
            lines.append(f"export interface {class_name}Request {{")
            lines.append(f"  // Schema: {endpoint.request_body}")
            lines.append("}")
        lines.append(f"export interface {class_name}Response {{")
        lines.append(f"  // Schema: {endpoint.response_body}")
        lines.append("}")
        lines.append("")

    return "\n".join(lines)


def _python_type_to_openapi(py_type: str) -> str:
    """Convert Python type hint to OpenAPI type."""
    type_map = {
        "str": "string",
        "int": "integer",
        "float": "number",
        "bool": "boolean",
        "datetime": "string",  # format: date-time
        "date": "string",      # format: date
        "bytes": "string",     # format: byte
    }
    base_type = py_type.split("[")[0].lower()
    if "list" in py_type.lower():
        return "array"
    if "dict" in py_type.lower():
        return "object"
    return type_map.get(base_type, "string")


def _python_type_to_typescript(py_type: str) -> str:
    """Convert Python type hint to TypeScript type."""
    type_map = {
        "str": "string",
        "int": "number",
        "float": "number",
        "bool": "boolean",
        "datetime": "string",  # ISO date string
        "date": "string",
        "bytes": "string",
        "any": "any",
    }

    py_type_lower = py_type.lower()

    if py_type_lower.startswith("list["):
        inner = py_type[5:-1]
        return f"{_python_type_to_typescript(inner)}[]"
    if py_type_lower.startswith("optional["):
        inner = py_type[9:-1]
        return f"{_python_type_to_typescript(inner)} | null"
    if py_type_lower.startswith("dict["):
        return "Record<string, any>"

    base_type = py_type.split("[")[0]
    return type_map.get(base_type.lower(), "any")


def _normalize_python_type(py_type: str) -> str:
    """Normalize a Python type string for Pydantic."""
    # Handle common variations
    type_map = {
        "string": "str",
        "integer": "int",
        "boolean": "bool",
        "number": "float",
    }

    result = py_type
    for old, new in type_map.items():
        result = result.replace(old, new)

    return result


def _endpoint_to_class_name(path: str, method: str, suffix: str) -> str:
    """Convert endpoint path and method to a class name."""
    # /api/users/{user_id} -> ApiUsersUserId
    parts = path.strip("/").replace("{", "").replace("}", "").split("/")
    name_parts = [part.title() for part in parts if part]
    method_part = method.title()
    return f"{method_part}{''.join(name_parts)}{suffix}"


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

    # STEP 1.5: Generate TDD Interface Specifications
    # This is the "Contract" step - creating precise, testable interfaces
    interface_spec_path = None
    if workspace_path:
        logger.info("Generating TDD interface specifications")
        interface_spec_path = await generate_interface_specs(
            objective=objective,
            design_spec_content=spec_content,
            workspace_path=workspace_path,
            state=state
        )
        if interface_spec_path:
            logger.info(f"Interface specs generated: {interface_spec_path}")
        else:
            logger.warning("Interface generation skipped or failed - TDD tests may lack precise contracts")

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
    - **Each workstream should include its OWN tests** - don't create a separate testing component.

    3. **NO SEPARATE VERIFICATION COMPONENT:**
    - Testing is BUILT INTO each workstream (unit tests, integration tests).
    - Foundation verification is SIMPLE: packages installed, folders exist, server starts.
    - Do NOT create a dedicated "validation" or "testing" workstream.
    - E2E/Playwright tests belong in the LAST feature workstream, not separately.

    **OUTPUT SCHEMA:**
    Create planner tasks.
    - `component`: "foundation" | [workstream-slug]
    - `description`: CLEARLY define boundaries.
    - For "foundation": "ESTABLISH the environment/context. Verification = packages install, dev server starts."
    - For "workstreams": "ASSUME foundation is done. Build feature + its tests."
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

            # Build description with TDD interface reference if available
            desc_parts = [t_def.description, "", "REFERENCE: design_spec.md for architecture details."]
            if interface_spec_path:
                desc_parts.append("TDD CONTRACTS: interfaces/api_spec.yaml and interfaces/models.py for precise specifications.")
                desc_parts.append("IMPORTANT: Generate TEST tasks BEFORE BUILD tasks (Test-Driven Development).")

            task = Task(
                id=f"task_{uuid.uuid4().hex[:8]}",
                title=t_def.title,
                component=t_def.component,
                phase=TaskPhase.PLAN,
                status=TaskStatus.PLANNED,
                assigned_worker_profile=WorkerProfile.PLANNER,
                description="\n".join(desc_parts),
                acceptance_criteria=t_def.acceptance_criteria,
                depends_on=[],
                interface_spec_path=interface_spec_path,  # TDD: Link to interface contracts
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
        fallback_desc = f"Plan implementation for: {objective}\n\nREFERENCE: design_spec.md for architecture details."
        if interface_spec_path:
            fallback_desc += "\nTDD CONTRACTS: interfaces/api_spec.yaml and interfaces/models.py for precise specifications."
            fallback_desc += "\nIMPORTANT: Generate TEST tasks BEFORE BUILD tasks (Test-Driven Development)."

        return [Task(
            id=f"task_{uuid.uuid4().hex[:8]}",
            title=f"Plan implementation: {objective[:50]}",
            component="main",
            phase=TaskPhase.PLAN,
            status=TaskStatus.PLANNED,
            assigned_worker_profile=WorkerProfile.PLANNER,
            description=fallback_desc,
            acceptance_criteria=["Create implementation plan", "Define test tasks before build tasks (TDD)"],
            depends_on=[],
            interface_spec_path=interface_spec_path,  # TDD: Link to interface contracts
            created_at=datetime.now(),
            updated_at=datetime.now()
        )]
