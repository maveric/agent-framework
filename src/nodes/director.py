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
                        description=f"Fix issues in {task.component} reported by QA.\n\nQA Feedback:\n{feedback}",
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
                    
                    # Include QA feedback in the task for context if available
                    if task.qa_verdict and hasattr(task.qa_verdict, 'overall_feedback'):
                        feedback = task.qa_verdict.overall_feedback
                        print(f"  Previous failure: {feedback[:100]}", flush=True)
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

        # Check for suggested tasks (Hierarchical Planning) from AWAITING_QA tasks
        # Note: We check this even if status didn't change, because the worker might have just finished
        if task.status == TaskStatus.AWAITING_QA:
            # We need to access the raw task dict from state to get 'suggested_tasks'
            # because _dict_to_task might not have preserved it if it's not in the Task dataclass yet
            # (Wait, we didn't add suggested_tasks to Task dataclass, but it IS in the dict in state)
            raw_task = next((t for t in tasks if t["id"] == task.id), None)
            suggested_tasks_data = raw_task.get("suggested_tasks", []) if raw_task else []
            
            if suggested_tasks_data:
                print(f"Director: Found {len(suggested_tasks_data)} suggested tasks from {task.id}", flush=True)
                
                # We need to do this properly. Let's collect them first.
                new_tasks_to_create = []
                title_to_id_map = {}
                
                for st_data in suggested_tasks_data:
                    new_task_id = f"task_{uuid.uuid4().hex[:8]}"
                    title = st_data.get("description", "Untitled") # Use description as title for mapping
                    title_to_id_map[title] = new_task_id
                    
                    new_tasks_to_create.append({
                        "id": new_task_id,
                        "data": st_data
                    })
                    
                for item in new_tasks_to_create:
                    new_id = item["id"]
                    st_data = item["data"]
                    
                    # Resolve dependencies
                    raw_deps = st_data.get("depends_on", [])
                    resolved_deps = []
                    for dep in raw_deps:
                        if dep in title_to_id_map:
                            resolved_deps.append(title_to_id_map[dep])
                        else:
                            # It might be an existing task ID or just a string we can't resolve
                            # For now, keep it if it looks like an ID, otherwise warn
                            if dep.startswith("task_"):
                                resolved_deps.append(dep)
                            else:
                                print(f"  Warning: Could not resolve dependency '{dep}' for new task", flush=True)
                    
                    # Determine profile
                    phase_str = st_data.get("phase", "build").lower()
                    phase = TaskPhase.BUILD
                    if phase_str == "test": phase = TaskPhase.TEST
                    elif phase_str == "plan": phase = TaskPhase.PLAN
                    
                    profile = WorkerProfile.CODER
                    if phase == TaskPhase.TEST: profile = WorkerProfile.TESTER
                    elif phase == TaskPhase.PLAN: profile = WorkerProfile.PLANNER
                        
                    new_task = Task(
                        id=new_id,
                        component=st_data.get("component", task.component),
                        phase=phase,
                        status=TaskStatus.PLANNED,
                        assigned_worker_profile=profile,
                        description=st_data.get("description", "No description"),
                        acceptance_criteria=st_data.get("acceptance_criteria", []),
                        depends_on=resolved_deps,
                        created_at=datetime.now(),
                        updated_at=datetime.now()
                    )
                    
                    print(f"  Created task {new_id}: {new_task.description[:50]}...", flush=True)
                    updates.append(task_to_dict(new_task))
                
                # Clear suggested tasks so we don't process them again
                # We can't easily modify the state dict here directly to remove it, 
                # but since we are generating new tasks, the next director run won't see them as "new" suggestions 
                # unless we have a way to mark them processed.
                # Actually, if we don't clear them, we'll create duplicates every loop!
                # We must update the parent task to remove suggested_tasks.
                raw_task["suggested_tasks"] = [] # Clear it
                updates.append(raw_task) # Add parent task update

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
    """Use LLM to decompose objective into tasks."""
    # Get orchestrator config from state (has user's model settings)
    orch_config = state.get("orch_config")
    if not orch_config:
        from config import OrchestratorConfig
        orch_config = OrchestratorConfig()
    
    model_config = orch_config.director_model
    
    llm = get_llm(model_config)
    structured_llm = llm.with_structured_output(DecompositionResponse)
    
    prompt = ChatPromptTemplate.from_messages([
        ("system", """Decompose the objective into 2-5 tasks following these phases:
- PLAN phase: Design, architecture, planning tasks (use planner_worker)
- BUILD phase: Implementation, coding tasks (use code_worker)
- TEST phase: Testing, validation, QA tasks (use test_worker)

IMPORTANT: Include at least one TEST phase task to validate the implementation."""),
        ("user", "Objective: {objective}")
    ])
    
    try:
        response = structured_llm.invoke(prompt.format(objective=objective))
        tasks = []
        for t_def in response.tasks:
            # Map string phase to enum
            phase_map = {
                "plan": TaskPhase.PLAN,
                "build": TaskPhase.BUILD,
                "test": TaskPhase.TEST
            }
            phase = phase_map.get(t_def.phase.lower(), TaskPhase.BUILD)
            
            # Map worker profile string to enum
            profile_map = {
                "planner_worker": WorkerProfile.PLANNER,
                "code_worker": WorkerProfile.CODER,
                "test_worker": WorkerProfile.TESTER,
                "research_worker": WorkerProfile.RESEARCHER,
                "writer_worker": WorkerProfile.WRITER
            }
            worker_profile = profile_map.get(t_def.worker_profile, WorkerProfile.CODER)
            
            task = Task(
                id=f"task_{uuid.uuid4().hex[:8]}",
                component=t_def.component,
                phase=phase,
                status=TaskStatus.PLANNED,
                assigned_worker_profile=worker_profile,
                description=t_def.description,
                acceptance_criteria=t_def.acceptance_criteria,
                depends_on=[],  # Will be populated after all tasks created
                created_at=datetime.now(),
                updated_at=datetime.now()
            )
            tasks.append(task)
        
        # Infer dependencies based on phases:
        # - BUILD tasks depend on all PLAN tasks in same component
        # - TEST tasks depend on all BUILD tasks in same component
        for task in tasks:
            if task.phase == TaskPhase.BUILD:
                # Depend on all PLAN tasks in same component
                task.depends_on = [
                    t.id for t in tasks 
                    if t.phase == TaskPhase.PLAN and t.component == task.component
                ]
            elif task.phase == TaskPhase.TEST:
                # Depend on all BUILD tasks in same component
                task.depends_on = [
                    t.id for t in tasks 
                    if t.phase == TaskPhase.BUILD and t.component == task.component
                ]
                # If no BUILD tasks in component, depend on PLAN tasks
                if not task.depends_on:
                    task.depends_on = [
                        t.id for t in tasks 
                        if t.phase == TaskPhase.PLAN and t.component == task.component
                    ]
        
        return tasks
    except Exception as e:
        print(f"Decomposition error: {e}")
        # Fallback: single task
        return [Task(
            id=f"task_{uuid.uuid4().hex[:8]}",
            component="main",
            phase=TaskPhase.BUILD,
            status=TaskStatus.PLANNED,
            assigned_worker_profile=WorkerProfile.CODER,
            description=objective,
            acceptance_criteria=["Complete objective"],
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
