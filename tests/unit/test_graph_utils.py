"""
Unit tests for graph utilities (cycle detection).
Tests the detect_and_break_cycles function from director/graph_utils.py
"""
import pytest
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from orchestrator_types import Task, TaskStatus, TaskPhase

# Import directly from module file to avoid nodes/__init__.py conflict
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src" / "nodes" / "director"))
from graph_utils import detect_and_break_cycles


class TestDetectAndBreakCycles:
    """Test detect_and_break_cycles function."""

    def test_no_cycles_in_linear_chain(self):
        """Test that linear dependency chain has no cycles."""
        task1 = Task(
            id="task1",
            component="test",
            phase=TaskPhase.PLAN,
            description="First",
            depends_on=[]
        )
        task2 = Task(
            id="task2",
            component="test",
            phase=TaskPhase.BUILD,
            description="Second",
            depends_on=["task1"]
        )
        task3 = Task(
            id="task3",
            component="test",
            phase=TaskPhase.TEST,
            description="Third",
            depends_on=["task2"]
        )

        tasks = [task1, task2, task3]
        cycles_broken = detect_and_break_cycles(tasks)

        assert cycles_broken == 0
        assert task1.depends_on == []
        assert task2.depends_on == ["task1"]
        assert task3.depends_on == ["task2"]

    def test_no_cycles_in_diamond_dag(self):
        """Test that diamond-shaped DAG has no cycles."""
        task1 = Task(id="task1", component="test", phase=TaskPhase.PLAN,
                    description="Root", depends_on=[])
        task2 = Task(id="task2", component="test", phase=TaskPhase.BUILD,
                    description="Left", depends_on=["task1"])
        task3 = Task(id="task3", component="test", phase=TaskPhase.BUILD,
                    description="Right", depends_on=["task1"])
        task4 = Task(id="task4", component="test", phase=TaskPhase.TEST,
                    description="Merge", depends_on=["task2", "task3"])

        tasks = [task1, task2, task3, task4]
        cycles_broken = detect_and_break_cycles(tasks)

        assert cycles_broken == 0
        # Dependencies should be unchanged
        assert task4.depends_on == ["task2", "task3"]

    def test_simple_two_node_cycle(self):
        """Test detection and breaking of simple 2-node cycle."""
        task1 = Task(
            id="task1",
            component="test",
            phase=TaskPhase.BUILD,
            description="Task 1",
            depends_on=["task2"]
        )
        task2 = Task(
            id="task2",
            component="test",
            phase=TaskPhase.BUILD,
            description="Task 2",
            depends_on=["task1"]
        )

        tasks = [task1, task2]
        cycles_broken = detect_and_break_cycles(tasks)

        assert cycles_broken > 0
        # One of the dependencies should be broken
        assert not (task1.depends_on == ["task2"] and task2.depends_on == ["task1"])

    def test_self_referencing_cycle(self):
        """Test detection of task depending on itself."""
        task1 = Task(
            id="task1",
            component="test",
            phase=TaskPhase.BUILD,
            description="Self-referencing",
            depends_on=["task1"]
        )

        tasks = [task1]
        cycles_broken = detect_and_break_cycles(tasks)

        assert cycles_broken > 0
        assert "task1" not in task1.depends_on

    def test_three_node_cycle(self):
        """Test detection and breaking of 3-node cycle."""
        task1 = Task(
            id="task1",
            component="test",
            phase=TaskPhase.BUILD,
            description="Task 1",
            depends_on=["task2"]
        )
        task2 = Task(
            id="task2",
            component="test",
            phase=TaskPhase.BUILD,
            description="Task 2",
            depends_on=["task3"]
        )
        task3 = Task(
            id="task3",
            component="test",
            phase=TaskPhase.BUILD,
            description="Task 3",
            depends_on=["task1"]
        )

        tasks = [task1, task2, task3]
        cycles_broken = detect_and_break_cycles(tasks)

        assert cycles_broken > 0
        # At least one dependency should be broken to eliminate cycle
        # Verify no cycle remains by checking we can't traverse back to start
        def has_cycle_from(task_id, task_map):
            """Check if task can reach itself through dependencies (cycle exists)."""
            visited = set()
            def dfs(current_id):
                if current_id in visited:
                    return False  # Already checked this path
                visited.add(current_id)
                task = task_map.get(current_id)
                if not task:
                    return False
                for dep in task.depends_on:
                    if dep == task_id:  # Found a path back to start
                        return True
                    if dfs(dep):
                        return True
                return False
            return dfs(task_id)

        task_map = {t.id: t for t in tasks}
        # Should not be able to find a cycle from task1 back to itself
        assert not has_cycle_from("task1", task_map)

    def test_cycle_in_larger_graph(self):
        """Test cycle detection in graph with cycle and non-cycle parts."""
        task1 = Task(id="task1", component="test", phase=TaskPhase.PLAN,
                    description="Root", depends_on=[])
        task2 = Task(id="task2", component="test", phase=TaskPhase.BUILD,
                    description="Valid child", depends_on=["task1"])
        # Cycle between task3 and task4
        task3 = Task(id="task3", component="test", phase=TaskPhase.BUILD,
                    description="Cycle node 1", depends_on=["task4"])
        task4 = Task(id="task4", component="test", phase=TaskPhase.BUILD,
                    description="Cycle node 2", depends_on=["task3"])

        tasks = [task1, task2, task3, task4]
        cycles_broken = detect_and_break_cycles(tasks)

        assert cycles_broken > 0
        # Non-cycle parts should be unchanged
        assert task1.depends_on == []
        assert task2.depends_on == ["task1"]
        # Cycle should be broken
        assert not (task3.depends_on == ["task4"] and task4.depends_on == ["task3"])

    def test_multiple_separate_cycles(self):
        """Test detection of multiple independent cycles."""
        # Cycle 1: task1 <-> task2
        task1 = Task(id="task1", component="test", phase=TaskPhase.BUILD,
                    description="Cycle 1-A", depends_on=["task2"])
        task2 = Task(id="task2", component="test", phase=TaskPhase.BUILD,
                    description="Cycle 1-B", depends_on=["task1"])
        # Cycle 2: task3 <-> task4
        task3 = Task(id="task3", component="test", phase=TaskPhase.BUILD,
                    description="Cycle 2-A", depends_on=["task4"])
        task4 = Task(id="task4", component="test", phase=TaskPhase.BUILD,
                    description="Cycle 2-B", depends_on=["task3"])

        tasks = [task1, task2, task3, task4]
        cycles_broken = detect_and_break_cycles(tasks)

        assert cycles_broken >= 2  # Should break both cycles

    def test_no_cycles_independent_tasks(self):
        """Test that independent tasks with no dependencies have no cycles."""
        task1 = Task(id="task1", component="test", phase=TaskPhase.BUILD,
                    description="Independent 1", depends_on=[])
        task2 = Task(id="task2", component="test", phase=TaskPhase.BUILD,
                    description="Independent 2", depends_on=[])
        task3 = Task(id="task3", component="test", phase=TaskPhase.BUILD,
                    description="Independent 3", depends_on=[])

        tasks = [task1, task2, task3]
        cycles_broken = detect_and_break_cycles(tasks)

        assert cycles_broken == 0

    def test_external_dependency_no_cycle(self):
        """Test that depending on non-existent (external) task doesn't cause issues."""
        task1 = Task(
            id="task1",
            component="test",
            phase=TaskPhase.BUILD,
            description="Has external dep",
            depends_on=["external_task"]
        )

        tasks = [task1]
        cycles_broken = detect_and_break_cycles(tasks)

        assert cycles_broken == 0
        assert task1.depends_on == ["external_task"]  # Should be unchanged

    def test_long_cycle_chain(self):
        """Test detection of longer cycle chain (5 nodes)."""
        task1 = Task(id="task1", component="test", phase=TaskPhase.BUILD,
                    description="Node 1", depends_on=["task2"])
        task2 = Task(id="task2", component="test", phase=TaskPhase.BUILD,
                    description="Node 2", depends_on=["task3"])
        task3 = Task(id="task3", component="test", phase=TaskPhase.BUILD,
                    description="Node 3", depends_on=["task4"])
        task4 = Task(id="task4", component="test", phase=TaskPhase.BUILD,
                    description="Node 4", depends_on=["task5"])
        task5 = Task(id="task5", component="test", phase=TaskPhase.BUILD,
                    description="Node 5", depends_on=["task1"])

        tasks = [task1, task2, task3, task4, task5]
        cycles_broken = detect_and_break_cycles(tasks)

        assert cycles_broken > 0
        # Verify cycle is actually broken
        task_map = {t.id: t for t in tasks}
        visited = set()
        def has_cycle(task_id):
            if task_id in visited:
                return True
            if task_id not in task_map:
                return False
            visited.add(task_id)
            task = task_map[task_id]
            for dep in task.depends_on:
                if has_cycle(dep):
                    return True
            visited.remove(task_id)
            return False

        # No task should have a cycle
        for task in tasks:
            visited.clear()
            assert not has_cycle(task.id)

    def test_empty_task_list(self):
        """Test that empty task list returns 0 cycles."""
        cycles_broken = detect_and_break_cycles([])
        assert cycles_broken == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
