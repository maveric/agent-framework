"""
Unit tests for task readiness evaluation.
Tests the evaluate_readiness function from director/readiness.py
"""
import pytest
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from orchestrator_types import Task, TaskStatus, TaskPhase
from nodes.director.readiness import evaluate_readiness


class TestEvaluateReadiness:
    """Test evaluate_readiness function."""

    def test_ready_task_with_no_dependencies(self):
        """Test that planned task with no dependencies becomes READY."""
        task = Task(
            id="task1",
            component="test",
            phase=TaskPhase.BUILD,
            description="Test task",
            status=TaskStatus.PLANNED,
            depends_on=[]
        )

        result = evaluate_readiness(task, [task])
        assert result == TaskStatus.READY

    def test_ready_task_with_completed_dependencies(self):
        """Test that task becomes READY when all dependencies are complete."""
        dep1 = Task(
            id="dep1",
            component="test",
            phase=TaskPhase.PLAN,
            description="Dependency 1",
            status=TaskStatus.COMPLETE
        )
        dep2 = Task(
            id="dep2",
            component="test",
            phase=TaskPhase.PLAN,
            description="Dependency 2",
            status=TaskStatus.COMPLETE
        )
        task = Task(
            id="task1",
            component="test",
            phase=TaskPhase.BUILD,
            description="Test task",
            status=TaskStatus.PLANNED,
            depends_on=["dep1", "dep2"]
        )

        all_tasks = [dep1, dep2, task]
        result = evaluate_readiness(task, all_tasks)
        assert result == TaskStatus.READY

    def test_planned_task_with_incomplete_dependency(self):
        """Test that task stays PLANNED if any dependency is not complete."""
        dep1 = Task(
            id="dep1",
            component="test",
            phase=TaskPhase.PLAN,
            description="Dependency 1",
            status=TaskStatus.COMPLETE
        )
        dep2 = Task(
            id="dep2",
            component="test",
            phase=TaskPhase.PLAN,
            description="Dependency 2",
            status=TaskStatus.ACTIVE  # Not complete
        )
        task = Task(
            id="task1",
            component="test",
            phase=TaskPhase.BUILD,
            description="Test task",
            status=TaskStatus.PLANNED,
            depends_on=["dep1", "dep2"]
        )

        all_tasks = [dep1, dep2, task]
        result = evaluate_readiness(task, all_tasks)
        assert result == TaskStatus.PLANNED

    def test_planned_task_with_missing_dependency(self):
        """Test that task stays PLANNED if dependency doesn't exist yet."""
        task = Task(
            id="task1",
            component="test",
            phase=TaskPhase.BUILD,
            description="Test task",
            status=TaskStatus.PLANNED,
            depends_on=["nonexistent"]
        )

        result = evaluate_readiness(task, [task])
        assert result == TaskStatus.PLANNED

    def test_blocked_task_with_abandoned_dependency(self):
        """Test that task becomes BLOCKED if dependency is abandoned."""
        dep = Task(
            id="dep1",
            component="test",
            phase=TaskPhase.PLAN,
            description="Abandoned dependency",
            status=TaskStatus.ABANDONED
        )
        task = Task(
            id="task1",
            component="test",
            phase=TaskPhase.BUILD,
            description="Test task",
            status=TaskStatus.PLANNED,
            depends_on=["dep1"]
        )

        all_tasks = [dep, task]
        result = evaluate_readiness(task, all_tasks)
        assert result == TaskStatus.BLOCKED

    def test_non_planned_task_unchanged(self):
        """Test that non-PLANNED tasks return their current status."""
        statuses = [
            TaskStatus.READY,
            TaskStatus.ACTIVE,
            TaskStatus.COMPLETE,
            TaskStatus.BLOCKED,
            TaskStatus.FAILED,
            TaskStatus.AWAITING_QA,
            TaskStatus.FAILED_QA,
            TaskStatus.WAITING_HUMAN
        ]

        for status in statuses:
            task = Task(
                id="task1",
                component="test",
                phase=TaskPhase.BUILD,
                description="Test task",
                status=status,
                depends_on=["dep1"]
            )
            dep = Task(
                id="dep1",
                component="test",
                phase=TaskPhase.PLAN,
                description="Dependency",
                status=TaskStatus.COMPLETE
            )

            result = evaluate_readiness(task, [task, dep])
            assert result == status, f"Status {status} should be unchanged"

    def test_multiple_dependencies_mixed_states(self):
        """Test task with multiple dependencies in various states."""
        dep1 = Task(id="dep1", component="test", phase=TaskPhase.PLAN,
                   description="Complete", status=TaskStatus.COMPLETE)
        dep2 = Task(id="dep2", component="test", phase=TaskPhase.PLAN,
                   description="Active", status=TaskStatus.ACTIVE)
        dep3 = Task(id="dep3", component="test", phase=TaskPhase.PLAN,
                   description="Ready", status=TaskStatus.READY)

        task = Task(
            id="task1",
            component="test",
            phase=TaskPhase.BUILD,
            description="Test task",
            status=TaskStatus.PLANNED,
            depends_on=["dep1", "dep2", "dep3"]
        )

        all_tasks = [dep1, dep2, dep3, task]
        result = evaluate_readiness(task, all_tasks)
        # Should stay PLANNED because dep2 and dep3 are not COMPLETE
        assert result == TaskStatus.PLANNED

    def test_chain_of_dependencies(self):
        """Test task at end of dependency chain."""
        task1 = Task(id="task1", component="test", phase=TaskPhase.PLAN,
                    description="First", status=TaskStatus.COMPLETE, depends_on=[])
        task2 = Task(id="task2", component="test", phase=TaskPhase.BUILD,
                    description="Second", status=TaskStatus.COMPLETE, depends_on=["task1"])
        task3 = Task(id="task3", component="test", phase=TaskPhase.TEST,
                    description="Third", status=TaskStatus.PLANNED, depends_on=["task2"])

        all_tasks = [task1, task2, task3]
        result = evaluate_readiness(task3, all_tasks)
        assert result == TaskStatus.READY

    def test_empty_task_list(self):
        """Test evaluation with empty task list."""
        task = Task(
            id="task1",
            component="test",
            phase=TaskPhase.BUILD,
            description="Solo task",
            status=TaskStatus.PLANNED,
            depends_on=[]
        )

        result = evaluate_readiness(task, [task])
        assert result == TaskStatus.READY


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
