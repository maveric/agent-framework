"""
Unit tests for task serialization (to_dict/from_dict).
Tests round-trip serialization for Task and related types.
"""
import pytest
from datetime import datetime
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from orchestrator_types import (
    Task,
    TaskStatus,
    TaskPhase,
    WorkerProfile,
    AAR,
    QAVerdict,
    CriterionResult,
    BlockedReason,
    BlockedType,
    task_to_dict,
    _dict_to_task,
)


class TestTaskSerialization:
    """Test Task to_dict/from_dict round-trip."""

    def test_minimal_task_round_trip(self):
        """Test serialization of minimal task with required fields only."""
        task = Task(
            id="task1",
            component="test",
            phase=TaskPhase.PLAN,
            description="Test task"
        )

        task_dict = task_to_dict(task)
        restored = _dict_to_task(task_dict)

        assert restored.id == task.id
        assert restored.component == task.component
        assert restored.phase == task.phase
        assert restored.description == task.description
        assert restored.status == TaskStatus.PLANNED  # default

    def test_full_task_round_trip(self):
        """Test serialization of task with all fields populated."""
        now = datetime.now()
        task = Task(
            id="task2",
            component="api",
            phase=TaskPhase.BUILD,
            description="Build API endpoint",
            status=TaskStatus.ACTIVE,
            depends_on=["task1", "task0"],
            priority=8,
            assigned_worker_profile=WorkerProfile.CODER,
            retry_count=1,
            max_retries=3,
            acceptance_criteria=["Endpoint returns 200", "Tests pass"],
            result_path="/path/to/result.py",
            branch_name="task2-branch",
            worktree_path="/path/to/worktree",
            created_at=now,
            updated_at=now,
            started_at=now,
        )

        task_dict = task_to_dict(task)
        restored = _dict_to_task(task_dict)

        assert restored.id == task.id
        assert restored.component == task.component
        assert restored.phase == task.phase
        assert restored.description == task.description
        assert restored.status == task.status
        assert restored.depends_on == task.depends_on
        assert restored.priority == task.priority
        assert restored.assigned_worker_profile == task.assigned_worker_profile
        assert restored.retry_count == task.retry_count
        assert restored.max_retries == task.max_retries
        assert restored.acceptance_criteria == task.acceptance_criteria
        assert restored.result_path == task.result_path
        assert restored.branch_name == task.branch_name
        assert restored.worktree_path == task.worktree_path

    def test_task_with_aar(self):
        """Test serialization of task with AAR."""
        aar = AAR(
            summary="Completed successfully",
            approach="Used TDD approach",
            challenges=["Complex logic", "Edge cases"],
            decisions_made=["Used async", "Added caching"],
            files_modified=["api.py", "tests.py"],
            time_spent_estimate="2 hours"
        )

        task = Task(
            id="task3",
            component="test",
            phase=TaskPhase.BUILD,
            description="Task with AAR",
            aar=aar
        )

        task_dict = task_to_dict(task)
        restored = _dict_to_task(task_dict)

        assert restored.aar is not None
        assert restored.aar.summary == aar.summary
        assert restored.aar.approach == aar.approach
        assert restored.aar.challenges == aar.challenges
        assert restored.aar.decisions_made == aar.decisions_made
        assert restored.aar.files_modified == aar.files_modified
        assert restored.aar.time_spent_estimate == aar.time_spent_estimate

    def test_task_with_qa_verdict(self):
        """Test serialization of task with QA verdict."""
        criterion1 = CriterionResult(
            criterion="Tests pass",
            passed=True,
            reasoning="All tests passed"
        )
        criterion2 = CriterionResult(
            criterion="Code is clean",
            passed=False,
            reasoning="Has linting errors",
            suggestions="Run formatter"
        )

        verdict = QAVerdict(
            passed=False,
            criterion_results=[criterion1, criterion2],
            overall_feedback="Needs cleanup",
            suggested_focus="Fix linting"
        )

        task = Task(
            id="task4",
            component="test",
            phase=TaskPhase.BUILD,
            description="Task with QA",
            qa_verdict=verdict
        )

        task_dict = task_to_dict(task)
        restored = _dict_to_task(task_dict)

        assert restored.qa_verdict is not None
        assert restored.qa_verdict.passed == verdict.passed
        assert len(restored.qa_verdict.criterion_results) == 2
        assert restored.qa_verdict.criterion_results[0].passed is True
        assert restored.qa_verdict.criterion_results[1].passed is False
        assert restored.qa_verdict.overall_feedback == verdict.overall_feedback

    def test_task_with_blocked_reason(self):
        """Test serialization of task with blocked reason."""
        blocked = BlockedReason(
            type=BlockedType.DEPENDENCY,
            description="Waiting for task1",
            waiting_on=["task1"]
        )

        task = Task(
            id="task5",
            component="test",
            phase=TaskPhase.BUILD,
            description="Blocked task",
            status=TaskStatus.BLOCKED,
            blocked_reason=blocked
        )

        task_dict = task_to_dict(task)
        restored = _dict_to_task(task_dict)

        assert restored.blocked_reason is not None
        assert restored.blocked_reason.type == BlockedType.DEPENDENCY
        assert restored.blocked_reason.description == "Waiting for task1"
        assert restored.blocked_reason.waiting_on == ["task1"]

    def test_task_with_waiting_for_tasks(self):
        """Test serialization of task waiting for subtasks."""
        task = Task(
            id="task6",
            component="test",
            phase=TaskPhase.BUILD,
            description="Task with subtasks",
            waiting_for_tasks=["subtask1", "subtask2"]
        )

        task_dict = task_to_dict(task)
        restored = _dict_to_task(task_dict)

        assert restored.waiting_for_tasks == ["subtask1", "subtask2"]

    def test_datetime_serialization(self):
        """Test that datetime fields serialize and deserialize correctly."""
        now = datetime.now()
        task = Task(
            id="task7",
            component="test",
            phase=TaskPhase.BUILD,
            description="DateTime test",
            created_at=now,
            updated_at=now,
            started_at=now,
            completed_at=now
        )

        task_dict = task_to_dict(task)

        # Check that datetimes are serialized as ISO strings
        assert isinstance(task_dict["created_at"], str)
        assert isinstance(task_dict["updated_at"], str)
        assert isinstance(task_dict["started_at"], str)
        assert isinstance(task_dict["completed_at"], str)

        # Check round-trip
        restored = _dict_to_task(task_dict)
        assert isinstance(restored.created_at, datetime)
        assert isinstance(restored.updated_at, datetime)
        assert isinstance(restored.started_at, datetime)
        assert isinstance(restored.completed_at, datetime)

        # Datetimes should be very close (within 1 second due to precision)
        assert abs((restored.created_at - now).total_seconds()) < 1

    def test_enum_serialization(self):
        """Test that enums serialize to strings and deserialize back."""
        task = Task(
            id="task8",
            component="test",
            phase=TaskPhase.TEST,
            description="Enum test",
            status=TaskStatus.COMPLETE,
            assigned_worker_profile=WorkerProfile.TESTER
        )

        task_dict = task_to_dict(task)

        # Enums should be serialized as strings
        assert task_dict["phase"] == "test"
        assert task_dict["status"] == "complete"
        assert task_dict["assigned_worker_profile"] == "test_worker"

        # Check round-trip
        restored = _dict_to_task(task_dict)
        assert restored.phase == TaskPhase.TEST
        assert restored.status == TaskStatus.COMPLETE
        assert restored.assigned_worker_profile == WorkerProfile.TESTER

    def test_optional_fields_as_none(self):
        """Test that optional fields can be None and serialize correctly."""
        task = Task(
            id="task9",
            component="test",
            phase=TaskPhase.PLAN,
            description="Optional fields test",
            result_path=None,
            qa_verdict=None,
            aar=None,
            blocked_reason=None,
            branch_name=None,
            worktree_path=None,
            started_at=None,
            completed_at=None
        )

        task_dict = task_to_dict(task)
        restored = _dict_to_task(task_dict)

        assert restored.result_path is None
        assert restored.qa_verdict is None
        assert restored.aar is None
        assert restored.blocked_reason is None
        assert restored.branch_name is None
        assert restored.worktree_path is None
        assert restored.started_at is None
        assert restored.completed_at is None

    def test_empty_lists_serialize(self):
        """Test that empty lists serialize correctly."""
        task = Task(
            id="task10",
            component="test",
            phase=TaskPhase.BUILD,
            description="Empty lists test",
            depends_on=[],
            acceptance_criteria=[],
            waiting_for_tasks=[]
        )

        task_dict = task_to_dict(task)
        restored = _dict_to_task(task_dict)

        assert restored.depends_on == []
        assert restored.acceptance_criteria == []
        assert restored.waiting_for_tasks == []


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
