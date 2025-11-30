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
    _dict_to_task, _task_to_dict
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
        tasks = [_task_to_dict(t) for t in new_tasks]
        # Fall through to readiness evaluation
    
    # Evaluate task readiness and handle failed tasks (Phoenix recovery)
    all_tasks = [_dict_to_task(t) for t in tasks]
    updates = []
    
    MAX_RETRIES = 2  # Maximum number of retries before giving up
    
    for task in all_tasks:
        # Phoenix recovery: Retry failed tasks
        if task.status == TaskStatus.FAILED:
            retry_count = task.retry_count if task.retry_count is not None else 0
            
            if retry_count < MAX_RETRIES:
                # Reset task for retry
                print(f"Phoenix: Retrying task {task.id} (attempt {retry_count + 1}/{MAX_RETRIES})", flush=True)
                task.status = TaskStatus.PLANNED
                task.retry_count = retry_count + 1
                task.updated_at = datetime.now()
                
                # Include QA feedback in the task for context
                if task.qa_verdict and hasattr(task.qa_verdict, 'overall_feedback'):
                    feedback = task.qa_verdict.overall_feedback
                    print(f"  Previous failure: {feedback[:100]}", flush=True)
                
                updates.append(_task_to_dict(task))
            else:
                print(f"Phoenix: Task {task.id} exceeded max retries ({MAX_RETRIES}), marking as permanently failed", flush=True)
                # Keep as failed permanently
        
        # Standard readiness evaluation for planned tasks
        elif task.status == TaskStatus.PLANNED:
            new_status = _evaluate_readiness(task, all_tasks)
            if new_status != task.status:
                task.status = new_status
                task.updated_at = datetime.now()
                updates.append(_task_to_dict(task))
            # If it was just created (and thus not in original state), we must add it
            elif task.id not in [t["id"] for t in state.get("tasks", [])]:
                updates.append(_task_to_dict(task))
    
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
                depends_on=[],
                created_at=datetime.now(),
                updated_at=datetime.now()
            )
            tasks.append(task)
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
