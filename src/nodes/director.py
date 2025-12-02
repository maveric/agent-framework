"""
Agent Orchestrator — Director Node
==================================
Version 1.0 — November 2025

Director node for task management and orchestration.
"""

from typing import Any, Dict, List
from datetime import datetime
from state import OrchestratorState
from orchestrator_types import (
    Task, TaskStatus, TaskPhase, WorkerProfile,
    _dict_to_task, task_to_dict
)
from llm_client import get_llm
from pydantic import BaseModel, Field
from langchain_core.prompts import ChatPromptTemplate
import uuid


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


class IntegratedTaskDefinition(BaseModel):
    """Task definition with resolved string dependencies."""
    title: str = Field(description="Task title")
    component: str = Field(description="Component name")
    phase: str = Field(description="plan, build, or test")
    description: str
    acceptance_criteria: List[str]
    depends_on: List[str] = Field(description="List of EXACT TITLES of other tasks this depends on")
    worker_profile: str = "code_worker"


class IntegrationResponse(BaseModel):
    """LLM response for global plan integration."""
    tasks: List[IntegratedTaskDefinition]


from langchain_core.runnables import RunnableConfig

def director_node(state: OrchestratorState, config: RunnableConfig = None) -> Dict[str, Any]:
    """
    Director: Task decomposition and readiness evaluation.
    """
    tasks = state.get("tasks", [])
    
    # Get configuration
    mock_mode = state.get("mock_mode", False)
    if not mock_mode and config and "configurable" in config:
        mock_mode = config["configurable"].get("mock_mode", False)
    
    # Initial decomposition if no tasks exist
    if not tasks:
        print("Director: Initial decomposition", flush=True)
        objective = state.get("objective", "")
        
        if mock_mode:
            new_tasks = _mock_decompose(objective)
        else:
            new_tasks = _decompose_objective(objective, state.get("spec", {}), state)
        # Convert to dicts for state
        tasks = [task_to_dict(t) for t in new_tasks]
        # Fall through to readiness evaluation
    
    # Evaluate task readiness and handle failed tasks (Phoenix recovery)
    all_tasks = [_dict_to_task(t) for t in tasks]
    updates = []
    
    MAX_RETRIES = 4  # Maximum number of retries before giving up
    
    for task in all_tasks:
        # Phoenix recovery: Retry failed tasks
        if task.status == TaskStatus.FAILED:
            retry_count = task.retry_count if task.retry_count is not None else 0
            
            if retry_count < MAX_RETRIES:
                print(f"Phoenix: Retrying task {task.id} (attempt {retry_count + 1}/{MAX_RETRIES})", flush=True)
                
                # SPECIAL HANDLING: If TEST task failed QA, spawn a FIX task
                # Note: task.qa_verdict is a QAVerdict object, not a dict
                if task.phase == TaskPhase.TEST and task.qa_verdict and not task.qa_verdict.passed:
                    feedback = task.qa_verdict.overall_feedback
                    print(f"  QA Failure detected. Spawning fix task.", flush=True)
                    print(f"  Feedback: {feedback[:100]}...", flush=True)
                    
                    # Create a new BUILD task to fix the issues
                    fix_task_id = f"task_{uuid.uuid4().hex[:8]}"
                    fix_task = Task(
                        id=fix_task_id,
                        component=task.component,
                        phase=TaskPhase.BUILD,
                        status=TaskStatus.PLANNED,
                        assigned_worker_profile=WorkerProfile.CODER,  # Default to Coder for fixes
                        description=f"Fix issues in {task.component} reported by QA.\n\nQA FEEDBACK (MUST ADDRESS):\n{feedback}",
                        acceptance_criteria=[
                            "Address all QA feedback points",
                            "Ensure code compiles/runs",
                            "Verify fix before re-testing"
                        ],
                        depends_on=task.depends_on.copy(),  # Depend on what the test depended on
                        created_at=datetime.now(),
                        updated_at=datetime.now()
                    )
                    
                    # Add the fix task
                    updates.append(task_to_dict(fix_task))
                    
                    # Update the TEST task to depend on the fix task
                    task.depends_on.append(fix_task_id)
                    task.status = TaskStatus.PLANNED
                    task.retry_count = retry_count + 1
                    task.updated_at = datetime.now()
                    updates.append(task_to_dict(task))
                    
                else:
                    # Standard retry (reset to PLANNED)
                    task.status = TaskStatus.PLANNED
                    task.retry_count = retry_count + 1
                    task.updated_at = datetime.now()
                    
                    # Include QA feedback OR AAR failure reason in description
                    failure_reason = ""
                    if task.qa_verdict and hasattr(task.qa_verdict, 'overall_feedback'):
                        failure_reason = f"QA FEEDBACK: {task.qa_verdict.overall_feedback}"
                    elif task.aar and task.aar.summary:
                         failure_reason = f"PREVIOUS FAILURE: {task.aar.summary}"
                    
                    if failure_reason:
                        print(f"  Previous failure: {failure_reason[:100]}", flush=True)
                        # Append to description if not already there to avoid duplication
                        if "PREVIOUS FAILURE:" not in task.description and "QA FEEDBACK:" not in task.description:
                             task.description += f"\n\n{failure_reason}"
                    
                    updates.append(task_to_dict(task))
            else:
                print(f"Phoenix: Task {task.id} exceeded max retries ({MAX_RETRIES}), marking as permanently failed", flush=True)
                # Update task status to a terminal state and add to updates
                # This prevents infinite retrying
                task.status = TaskStatus.FAILED
                task.updated_at = datetime.now()
                # Mark that we've already processed this max-retry failure
                # by ensuring retry_count is set high enough to skip next time
                task.retry_count = MAX_RETRIES + 1  
                updates.append(task_to_dict(task))
        
        # Standard readiness evaluation for planned tasks
        elif task.status == TaskStatus.PLANNED:
            new_status = _evaluate_readiness(task, all_tasks)
            if new_status != task.status:
                task.status = new_status
                task.updated_at = datetime.now()
                updates.append(task_to_dict(task))
            # If it was just created (and thus not in original state), we must add it
            elif task.id not in [t["id"] for t in state.get("tasks", [])]:
                updates.append(task_to_dict(task))

    # GLOBAL PLAN INTEGRATION (Sync & Link)
    
    # 1. Check for Active Planners (Blocking Condition)
    # We still want to wait for the initial planning phase to complete globally
    planner_tasks = [t for t in all_tasks if t.assigned_worker_profile == WorkerProfile.PLANNER]
    active_planners = [t for t in planner_tasks if t.status not in [TaskStatus.COMPLETE, TaskStatus.FAILED]]
    
    if active_planners:
        print(f"Director: Waiting for {len(active_planners)} planners to complete before integrating plans.", flush=True)
    else:
        # 2. Collect suggestions from ALL completed/failed tasks
        # (Not just planners, but any task that might have used create_subtasks, e.g. Testers)
        all_suggestions = []
        tasks_with_suggestions = []
        
        for task in all_tasks:
            # We only process suggestions from tasks that are done running
            if task.status in [TaskStatus.COMPLETE, TaskStatus.FAILED]:
                raw_task = next((t for t in tasks if t["id"] == task.id), None)
                if raw_task and raw_task.get("suggested_tasks"):
                    all_suggestions.extend(raw_task["suggested_tasks"])
                    tasks_with_suggestions.append(raw_task)
        
        if all_suggestions:
            print(f"Director: Integrating {len(all_suggestions)} tasks from {len(tasks_with_suggestions)} sources...", flush=True)
            
            try:
                new_tasks = _integrate_plans(all_suggestions, state)
                updates.extend([task_to_dict(t) for t in new_tasks])
                
                # Clear suggestions so we don't re-process
                for raw_t in tasks_with_suggestions:
                    raw_t["suggested_tasks"] = []
                    updates.append(raw_t)
            except Exception as e:
                print(f"Director Error: Integration failed: {e}", flush=True)
                import traceback
                traceback.print_exc()

    return {"tasks": updates} if updates else {}


def _mock_decompose(objective: str) -> List[Task]:
    """Mock decomposition for testing - creates realistic task breakdown."""
    print(f"MOCK: Decomposing '{objective}' without LLM", flush=True)
    
    # Generate base IDs
    base_id = uuid.uuid4().hex[:6]
    plan_id = f"task_{base_id}_plan"
    impl_id = f"task_{base_id}_impl"
    test_id = f"task_{base_id}_test"
    
    return [
        # Task 1: Planning
        Task(
            id=plan_id,
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


def _decompose_objective(objective: str, spec: Dict[str, Any], state: Dict[str, Any]) -> List[Task]:
    """
    Director: High-level decomposition + spec creation.
    
    The Director (using the smartest model) has leeway to decide what's best.
    Creates the design_spec.md and delegates to 1-5 component planners.
    """
    # Get orchestrator config from state (has user's model settings)
    orch_config = state.get("orch_config")
    if not orch_config:
        from config import OrchestratorConfig
        orch_config = OrchestratorConfig()
    
    model_config = orch_config.director_model
    workspace_path = state.get("_workspace_path")
    
    llm = get_llm(model_config)
    
    # STEP 1: Write design specification
    print("Director: Creating design specification...", flush=True)
    
    spec_prompt = ChatPromptTemplate.from_messages([
        ("system", """You are a Lead Architect creating a design specification.

CRITICAL INSTRUCTIONS:
1. Analyze the objective and determine the necessary components (e.g., Backend, Frontend, Database, Testing)
2. Create a comprehensive design specification that will guide all workers
3. You have leeway to make architectural decisions that best serve the objective
4. Focus on MVP - deliver the core functionality requested, avoid unnecessary extras

OUTPUT:
Write a design specification in markdown format with these sections:
- **Overview**: Brief project summary
- **Components**: List each component (Backend, Frontend, etc.)
- **API Routes** (if applicable): Methods, paths, request/response formats
- **Data Models** (if applicable): Schemas, database tables, field types
- **File Structure**: Where files should be created
- **Technology Stack**: What frameworks/libraries to use

Be specific enough that workers can implement without ambiguity."""),
        ("user", "Objective: {objective}")
    ])
    
    try:
        spec_response = llm.invoke(spec_prompt.format(objective=objective))
        spec_content = str(spec_response.content)
        
        # Write spec to workspace
        if workspace_path:
            from pathlib import Path
            spec_path = Path(workspace_path) / "design_spec.md"
            spec_path.write_text(spec_content, encoding="utf-8")
            print(f"  Written: design_spec.md", flush=True)
    except Exception as e:
        print(f"  Warning: Failed to create spec: {e}", flush=True)
        spec_content = f"# Design Spec\n\nObjective: {objective}\n\nPlease create a minimal viable implementation."
    
    # STEP 2: Decompose into 1-5 component planner tasks
    print("Director: Creating component planner tasks...", flush=True)
    
    structured_llm = llm.with_structured_output(DecompositionResponse)
    
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
    
    try:
        # Use first 500 chars of spec as summary
        spec_summary = spec_content[:500] + "..." if len(spec_content) > 500 else spec_content
        
        response = structured_llm.invoke(decomp_prompt.format(
            objective=objective,
            spec_summary=spec_summary
        ))
        
        tasks = []
        for t_def in response.tasks:
            # Ensure it's a planner task
            if t_def.phase.lower() != "plan":
                print(f"  Warning: Director tried to create {t_def.phase} task, converting to 'plan'", flush=True)
            
            task = Task(
                id=f"task_{uuid.uuid4().hex[:8]}",
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
        
        print(f"  Created {len(tasks)} planner task(s)", flush=True)
        return tasks
        
    except Exception as e:
        print(f"Decomposition error: {e}, using fallback", flush=True)
        # Fallback: single planner for the entire project
        return [Task(
            id=f"task_{uuid.uuid4().hex[:8]}",
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


def _evaluate_readiness(task: Task, all_tasks: List[Task]) -> TaskStatus:
    """Check if task dependencies are met."""
    if task.status != TaskStatus.PLANNED:
        return task.status
    
    # Check all dependencies are complete
    for dep_id in task.depends_on:
        dep = next((t for t in all_tasks if t.id == dep_id), None)
        if not dep or dep.status != TaskStatus.COMPLETE:
            return TaskStatus.PLANNED
    
    return TaskStatus.READY


def _integrate_plans(suggestions: List[Dict[str, Any]], state: Dict[str, Any]) -> List[Task]:
    """
    Integrate proposed tasks from multiple planners into a cohesive plan.
    Resolves cross-component dependencies.
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
        # Extract title if embedded in description
        desc = s.get("description", "")
        title = s.get("title", "Untitled")
        if "Title: " in desc and title == "Untitled":
             title = desc.split("Title: ")[-1].strip()
             
        tasks_input.append({
            "title": title,
            "component": s.get("component", "unknown"),
            "phase": s.get("phase", "build"),
            "description": desc,
            "depends_on": s.get("depends_on", [])
        })
        
    prompt = ChatPromptTemplate.from_messages([
        ("system", """You are the Lead Architect integrating project plans.
        
        INPUT: A list of proposed tasks from different component planners (Frontend, Backend, etc.).
        
        YOUR JOB:
        1. **Deduplicate**: If multiple planners proposed the same task (e.g., "Create Database"), keep only one.
        2. **Link Dependencies**: Ensure logical flow across components.
           - Frontend tasks MUST depend on their corresponding Backend tasks.
           - Test tasks MUST depend on the Build tasks they test.
        3. **Return**: The final, clean list of tasks with CORRECT `depends_on` lists (use exact titles).
        
        CRITICAL:
        - Do not invent new tasks unless necessary for integration.
        - Ensure every task has a valid dependency path (no cycles).
        - Use the EXACT TITLES for dependencies.
        """),
        ("user", "Proposed Tasks:\n{tasks_json}")
    ])
    
    structured_llm = llm.with_structured_output(IntegrationResponse)
    
    print("  Calling LLM for plan integration...", flush=True)
    try:
        response = structured_llm.invoke(prompt.format(tasks_json=str(tasks_input)))
    except Exception as e:
        print(f"  Integration LLM Error: {e}", flush=True)
        # Fallback: Return tasks as-is (converted to Task objects)
        # This prevents the pipeline from crashing, though dependencies might be broken
        print("  Fallback: Converting suggestions directly without integration.", flush=True)
        fallback_tasks = []
        for s in suggestions:
            t_id = f"task_{uuid.uuid4().hex[:8]}"
            fallback_tasks.append(Task(
                id=t_id,
                component=s.get("component", "unknown"),
                phase=TaskPhase(s.get("phase", "build")),
                status=TaskStatus.PLANNED,
                assigned_worker_profile=WorkerProfile.CODER, # Default
                description=s.get("description", ""),
                depends_on=[], # Lost dependencies in fallback
                created_at=datetime.now(),
                updated_at=datetime.now()
            ))
        return fallback_tasks

    # Convert response to Task objects
    new_tasks = []
    title_to_id_map = {}
    
    # 0. Pre-populate map with EXISTING tasks (to allow linking to completed tasks)
    existing_tasks = state.get("tasks", [])
    for t in existing_tasks:
        t_desc = t.get("description", "")
        t_title = ""
        if "Title: " in t_desc:
            t_title = t_desc.split("Title: ")[-1].strip()
        else:
            t_title = t_desc.split("\n")[0].strip()
        
        if t_title:
            title_to_id_map[t_title.lower()] = t["id"]
    
    # 1. Create IDs and Map Titles for NEW tasks
    for t_def in response.tasks:
        new_id = f"task_{uuid.uuid4().hex[:8]}"
        title_to_id_map[t_def.title.lower()] = new_id
        
    # 2. Create Task Objects with Resolved Dependencies
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
                    print(f"    Warning: Could not resolve dependency '{dep}' for '{t_def.title}'", flush=True)
        
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
            component=t_def.component,
            phase=phase,
            status=TaskStatus.PLANNED,
            assigned_worker_profile=profile,
            description=f"{t_def.description}\n\nTitle: {t_def.title}",
            acceptance_criteria=t_def.acceptance_criteria,
            depends_on=resolved_deps,
            created_at=datetime.now(),
            updated_at=datetime.now()
        )
        new_tasks.append(new_task)
        
    print(f"  Integrated {len(new_tasks)} tasks into the graph.", flush=True)
    return new_tasks
