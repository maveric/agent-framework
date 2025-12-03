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
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
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


class RejectedTask(BaseModel):
    """Task rejected during integration for being out of scope."""
    title: str
    reason: str = Field(description="Why this task was rejected")


class IntegrationResponse(BaseModel):
    """LLM response for global plan integration."""
    tasks: List[IntegratedTaskDefinition]
    rejected_tasks: List[RejectedTask] = Field(default_factory=list, description="Tasks rejected as out of scope")


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
                
                # SPECIAL HANDLING: If TEST task failed QA, check if it's a code issue or test worker error
                # Note: task.qa_verdict is a QAVerdict object, not a dict
                if task.phase == TaskPhase.TEST and task.qa_verdict and not task.qa_verdict.passed:
                    feedback = task.qa_verdict.overall_feedback
                    
                    # Detect if this is a TEST WORKER ERROR (missing test results file)
                    # vs an actual TEST EXECUTION FAILURE (code bugs found)
                    is_test_worker_error = "MISSING TEST RESULTS FILE" in feedback
                    
                    if is_test_worker_error:
                        # TEST WORKER ERROR: Just retry the TEST task itself
                        # The test worker needs to write the results file - no code fix needed
                        print(f"  QA Failure: Test worker error (missing results file). Retrying TEST task.", flush=True)
                        task.status = TaskStatus.PLANNED
                        task.retry_count = retry_count + 1
                        task.updated_at = datetime.now()
                        
                        # Append feedback to description so test worker sees it on retry
                        if "MISSING TEST RESULTS FILE" not in task.description:
                            task.description += f"\n\nPREVIOUS FAILURE: {feedback}"
                        
                        # Immediately evaluate readiness for instant retry
                        new_status = _evaluate_readiness(task, all_tasks)
                        if new_status == TaskStatus.READY:
                            print(f"  Phoenix: Task {task.id} immediately READY for retry", flush=True)
                            task.status = new_status
                        
                        updates.append(task_to_dict(task))
                    else:
                        # ACTUAL TEST EXECUTION FAILURE: Spawn a BUILD task to fix code issues
                        print(f"  QA Failure: Test execution failed. Spawning fix task.", flush=True)
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
                        
                        # Evaluate readiness (will be PLANNED since it now depends on fix_task)
                        # But good to be explicit about status
                        task.status = _evaluate_readiness(task, all_tasks)
                        
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
                    
                    # Immediately evaluate readiness for instant retry
                    new_status = _evaluate_readiness(task, all_tasks)
                    if new_status == TaskStatus.READY:
                        print(f"  Phoenix: Task {task.id} immediately READY for retry", flush=True)
                        task.status = new_status
                    
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
    
    # Check for manual replan request
    replan_requested = state.get("replan_requested", False)
    
    # 1. Check for Active Planners (Blocking Condition)
    # We still want to wait for the initial planning phase to complete globally
    planner_tasks = [t for t in all_tasks if t.assigned_worker_profile == WorkerProfile.PLANNER]
    active_planners = [t for t in planner_tasks if t.status not in [TaskStatus.COMPLETE, TaskStatus.FAILED]]
    
    if active_planners:
        print(f"Director: Waiting for {len(active_planners)} planners to complete before integrating plans.", flush=True)
    elif replan_requested:
        # MANUAL REPLAN TRIGGER
        print("Director: Manual replan requested. Re-integrating pending tasks...", flush=True)
        
        # Gather all pending tasks (PLANNED)
        # We exclude COMPLETE, FAILED, and ACTIVE tasks from being reshuffled, 
        # but we include them in the integration context so dependencies can point to them.
        pending_tasks = [t for t in all_tasks if t.status == TaskStatus.PLANNED]
        
        if pending_tasks:
            # Convert to dicts for the integrator
            suggestions = [task_to_dict(t) for t in pending_tasks]
            
            try:
                # Re-run integration
                new_tasks = _integrate_plans(suggestions, state)
                
                # Update the pending tasks with new definitions (dependencies, etc.)
                # We match by ID if possible, or replace if IDs changed (though _integrate_plans tries to preserve)
                # Actually _integrate_plans generates NEW IDs usually. 
                # To avoid duplicates, we should probably mark the old pending tasks as "replaced" or just update them in place.
                # For simplicity in this v1, let's try to update them if titles match, or replace them.
                
                # Strategy: The integrator returns a list of Task objects.
                # We need to update the state.
                
                # Since _integrate_plans returns NEW task objects with potentially new IDs,
                # we need to be careful.
                # Let's just append the new ones and mark the old pending ones as FAILED (or removed).
                # BUT, removing tasks is hard in append-only log.
                # BETTER STRATEGY: Update the EXISTING task objects in place if possible.
                
                # _integrate_plans uses title matching to map to existing IDs.
                # So it SHOULD return tasks with the SAME IDs if the titles match.
                
                updates.extend([task_to_dict(t) for t in new_tasks])
                
                # Reset flag
                # We can't easily "remove" the flag from state in LangGraph without a specific reducer.
                # But we can set it to False in the update.
                # Assuming the state schema allows overwriting.
                # For now, we'll just print it. The state update needs to handle this.
                # We'll return it in the result.
                
            except Exception as e:
                print(f"Director Error: Replan failed: {e}", flush=True)
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
            print(f"Director: Integrating {len(all_suggestions)} task suggestions...", flush=True)
            
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

    # Capture Director logs
    # We construct a synthetic message history for the Director's actions
    director_messages = []
    
    # 1. Spec Creation Log
    if 'spec_prompt' in locals() and 'spec_response' in locals():
        director_messages.extend([
            SystemMessage(content="Director: Creating Design Specification"),
            HumanMessage(content=spec_prompt.format(objective=state.get("objective", ""))[0].content), # Approximate prompt
            AIMessage(content=str(spec_response.content))
        ])
        
    # 2. Decomposition Log
    if 'decomp_prompt' in locals() and 'response' in locals():
        director_messages.extend([
            SystemMessage(content="Director: Decomposing Objective into Tasks"),
            HumanMessage(content=f"Objective: {state.get('objective', '')}\n\nSpec Summary: {spec_summary if 'spec_summary' in locals() else '...'}"),
            AIMessage(content=f"Created {len(tasks) if 'tasks' in locals() else 0} planner tasks.")
        ])
        
    # 3. Integration Log
    if 'all_suggestions' in locals() and all_suggestions:
        director_messages.extend([
            SystemMessage(content="Director: Integrating Plans"),
            HumanMessage(content=f"Integrating {len(all_suggestions)} suggestions..."),
            AIMessage(content=f"Integrated {len(new_tasks) if 'new_tasks' in locals() else 0} new tasks.")
        ])



    # PENDING REORG: Block new task starts, wait for active tasks, then reorg
    pending_reorg = state.get("pending_reorg", False)
    if pending_reorg:
        active_tasks = [t for t in all_tasks if t.status == TaskStatus.ACTIVE]
        
        if active_tasks:
            # Still have active tasks - block new task dispatch
            print(f"Director: Reorg pending. Waiting on {len(active_tasks)} active tasks to finish. No new tasks started.", flush=True)
            # Don't update tasks or dispatch - just return with flag still set
            return {"pending_reorg": True}  # Keep flag set
        else:
            # All active tasks done - execute reorg NOW
            print("Director: All tasks complete. Executing reorg now...", flush=True)
            
            # Gather all PLANNED tasks for reorganization
            planned_tasks = [t for t in all_tasks if t.status == TaskStatus.PLANNED]
            
            if planned_tasks:
                suggestions = [task_to_dict(t) for t in planned_tasks]
                try:
                    new_tasks = _integrate_plans(suggestions, state)
                    updates.extend([task_to_dict(t) for t in new_tasks])
                    print(f"Director: Reorganized {len(new_tasks)} tasks", flush=True)
                except Exception as e:
                    print(f"Director Error: Reorg failed: {e}", flush=True)
                    import traceback
                    traceback.print_exc()
            
            # Clear the flag - reorg complete
            result = {"tasks": updates, "pending_reorg": False} if updates else {"pending_reorg": False}
            if director_messages:
                result["task_memories"] = {"director": director_messages}
            return result
    
    # Return updates and logs
    result = {"tasks": updates, "replan_requested": False} if updates else {}
    if director_messages:
        # We use a special key "director" for these logs. 
        # The frontend will need to be updated to display them, or we can attach them to a dummy task.
        # For now, we just expose them in the state.
        result["task_memories"] = {"director": director_messages}
        
    return result



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
5. **ALWAYS include dependency isolation** to prevent package pollution across projects

OUTPUT:
Write a design specification in markdown format with these sections:
- **Overview**: Brief project summary
- **Components**: List each component (Backend, Frontend, etc.)
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
    
    try:
        spec_response = llm.invoke(spec_prompt.format(objective=objective))
        spec_content = str(spec_response.content)
        
        # Write spec to workspace
        if workspace_path:
            from pathlib import Path
            spec_path = Path(workspace_path) / "design_spec.md"
            spec_path.write_text(spec_content, encoding="utf-8")
            print(f"  Written: design_spec.md", flush=True)
            
            # Commit to main to avoid merge conflicts later
            wt_manager = state.get("_wt_manager")
            if wt_manager and not state.get("mock_mode", False):
                try:
                    wt_manager.commit_to_main(
                        message="Director: Add design specification",
                        files=["design_spec.md"]
                    )
                    print(f"  Committed: design_spec.md", flush=True)
                except Exception as e:
                    print(f"  Warning: Failed to commit spec: {e}", flush=True)
    except Exception as e:
        print(f"  Warning: Failed to create spec: {e}", flush=True)
        spec_content = f"# Design Spec\n\nObjective: {objective}\n\nPlease create a minimal viable implementation."
    
    # STEP 2: Decompose into 1-5 component planner tasks
    print("Director: Creating component planner tasks...", flush=True)
    
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
Create planner tasks following this schema. Order them: infrastructure → features → validation."""),
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
            "depends_on": s.get("depends_on", []),
            "rationale": s.get("rationale", "")
        })
        
    prompt = ChatPromptTemplate.from_messages([
        ("system", """You are the Lead Architect integrating project plans.
        
        INPUT: A list of proposed tasks from different component planners (Frontend, Backend, etc.).
        
        YOUR JOB:
        1. **Deduplicate**: If multiple planners proposed the same task (e.g., "Create Database"), keep only one.
        2. **Link Dependencies**: Ensure logical flow across components.
           - **CRITICAL RULE**: Test tasks MUST depend on the Build tasks they are testing.
           - Frontend tasks MUST depend on their corresponding Backend tasks.
           - **Commit granularity**: Each task should be one atomic commit
           - **Parallel when possible**: Tasks within same feature can run parallel if deps allow
           - **Example flow**: 
            * Database schema → API endpoint → UI component → Integration test
                * NOT: All backend → All frontend → All tests
        3. **Return**: The final, clean list of tasks with CORRECT `depends_on` lists (use exact titles).
        
        CHAIN OF THOUGHT (Internal):
        - First, identify all BUILD tasks.
        - Then, identify all TEST tasks.
        - For each TEST task, find the BUILD task it verifies and add it to `depends_on`.
        - For each FRONTEND task, find the BACKEND task it needs and add it to `depends_on`.
        
        CRITICAL:
        - Do not invent new tasks unless necessary for integration.
        - Ensure every task has a valid dependency path (no cycles).
        - Use the EXACT TITLES for dependencies.
        """),
        ("user", "Proposed Tasks:\n{tasks_json}")
    ])
    
    
    # Get design spec for scope context
    spec = state.get("spec", {})
    spec_content = spec.get("content", "No design specification")[:2000]  # Truncate if too long
    objective = state.get("objective", "")
    
    structured_llm = llm.with_structured_output(IntegrationResponse)
    
    print("  Calling LLM for plan integration...", flush=True)
    # Get design spec for scope context
    spec = state.get("spec", {})
    spec_content = spec.get("content", "No design specification available")
    objective = state.get("objective", "")
    
    prompt = ChatPromptTemplate.from_messages([
        ("system", """You are the Lead Architect integrating project plans.
        
        OBJECTIVE: {objective}
        
        DESIGN SPECIFICATION (THE SCOPE BOUNDARY):
        {spec_content}
        
        INPUT: Proposed tasks from planners and workers.
        
        YOUR JOB - IN THIS EXACT ORDER:
        1. **Deduplicate**: Merge duplicate or nearly-identical tasks.
        
        2. **Validate Scope**: Check EACH task against the design specification.
           - REJECT tasks that are not in the spec (accessibility, CI/CD, extensive testing utilities, etc.)
           - APPROVE tasks that implement the spec
           - Be strict - only what's in the spec gets built
           
        3. **Identify Gaps**: After rejecting out-of-scope tasks, check for broken dependencies.
           - Did rejection create orphaned tasks?
           - Are there missing links between components? (e.g., backend ↔ frontend integration)
           - Do tests depend on non-existent tasks?
           
        4. **Fill Gaps (YOU HAVE AUTHORITY)**: Create minimal necessary tasks to bridge gaps.
           - Example: If backend and frontend exist but no integration test, create one
           - Example: If frontend depends on rejected API utility, create minimal API connection task
           - Keep it minimal - ONLY what's needed for dependencies to work
        
        5. **Link Dependencies**: Create a SINGLE unified dependency tree.
           - **NO SILOS**: Frontend, Backend, and Tests must be interconnected
           - **Backend first**: Frontend MUST depend on backend API being built
           - **Tests last**: ALL test tasks MUST depend on what they're testing
           - **Integration tests**: MUST depend on BOTH frontend AND backend completion
           - **CRITICAL**: Every task must trace back to root - no independent trees
           - Example flow: Backend DB → Backend API → Frontend → Integration Tests
           - If you see disconnected trees, ADD dependency links to connect them

           
        6. **Return**: Two lists:
           - `tasks`: Approved + gap-filling tasks with correct depends_on
           - `rejected_tasks`: Out-of-scope tasks with reasons
        
        CRITICAL RULES:
        - Design spec is LAW - reject anything not in it
        - After rejection, you MUST check for gaps
        - You MAY create minimal bridge tasks to fix broken dependencies
        - No cycles in dependencies
        - Use EXACT TITLES for depends_on
        """),
        ("user", "Proposed Tasks:\n{tasks_json}")
    ])

    structured_llm = llm.with_structured_output(IntegrationResponse)
    
    print("  Calling LLM for plan integration with scope validation...", flush=True)
    try:
        response = structured_llm.invoke(prompt.format(
            objective=objective,
            spec_content=spec_content[:3000],  # Truncate if too long
            tasks_json=str(tasks_input)
        ))
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
    
    # Handle rejected tasks - send feedback to source workers
    if hasattr(response, 'rejected_tasks') and response.rejected_tasks:
        print(f"  LLM rejected {len(response.rejected_tasks)} tasks as out of scope:", flush=True)
        for rejected in response.rejected_tasks:
            print(f"    ✗ {rejected.title}: {rejected.reason}", flush=True)
            
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
