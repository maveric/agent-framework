"""
Unit tests for state reducers.
Tests all 4 reducers: tasks_reducer, insights_reducer, design_log_reducer, task_memories_reducer
"""
import pytest
from langchain_core.messages import HumanMessage, AIMessage
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from state import (
    tasks_reducer,
    insights_reducer,
    design_log_reducer,
    task_memories_reducer
)


class TestTasksReducer:
    """Test tasks_reducer functionality."""

    def test_add_new_task(self):
        """Test adding a new task to empty list."""
        existing = []
        updates = [{"id": "task1", "title": "Test task", "status": "pending"}]
        result = tasks_reducer(existing, updates)

        assert len(result) == 1
        assert result[0]["id"] == "task1"
        assert result[0]["title"] == "Test task"

    def test_update_existing_task(self):
        """Test updating an existing task by ID."""
        existing = [
            {"id": "task1", "title": "Old title", "status": "pending"},
            {"id": "task2", "title": "Task 2", "status": "completed"}
        ]
        updates = [{"id": "task1", "title": "New title", "status": "in_progress"}]
        result = tasks_reducer(existing, updates)

        assert len(result) == 2
        task1 = next(t for t in result if t["id"] == "task1")
        assert task1["title"] == "New title"
        assert task1["status"] == "in_progress"

    def test_add_multiple_new_tasks(self):
        """Test adding multiple new tasks at once."""
        existing = [{"id": "task1", "title": "Task 1", "status": "pending"}]
        updates = [
            {"id": "task2", "title": "Task 2", "status": "pending"},
            {"id": "task3", "title": "Task 3", "status": "pending"}
        ]
        result = tasks_reducer(existing, updates)

        assert len(result) == 3
        ids = {t["id"] for t in result}
        assert ids == {"task1", "task2", "task3"}

    def test_delete_task(self):
        """Test deleting a task using _delete flag."""
        existing = [
            {"id": "task1", "title": "Task 1", "status": "pending"},
            {"id": "task2", "title": "Task 2", "status": "pending"}
        ]
        updates = [{"id": "task1", "_delete": True}]
        result = tasks_reducer(existing, updates)

        assert len(result) == 1
        assert result[0]["id"] == "task2"

    def test_delete_nonexistent_task(self):
        """Test deleting a task that doesn't exist (should be no-op)."""
        existing = [{"id": "task1", "title": "Task 1", "status": "pending"}]
        updates = [{"id": "task999", "_delete": True}]
        result = tasks_reducer(existing, updates)

        assert len(result) == 1
        assert result[0]["id"] == "task1"

    def test_mixed_operations(self):
        """Test mix of add, update, and delete in single batch."""
        existing = [
            {"id": "task1", "title": "Task 1", "status": "pending"},
            {"id": "task2", "title": "Task 2", "status": "pending"}
        ]
        updates = [
            {"id": "task1", "title": "Updated Task 1", "status": "completed"},  # update
            {"id": "task2", "_delete": True},  # delete
            {"id": "task3", "title": "New Task", "status": "pending"}  # add
        ]
        result = tasks_reducer(existing, updates)

        assert len(result) == 2
        ids = {t["id"] for t in result}
        assert ids == {"task1", "task3"}
        task1 = next(t for t in result if t["id"] == "task1")
        assert task1["status"] == "completed"

    def test_empty_updates(self):
        """Test that empty updates list returns existing list."""
        existing = [{"id": "task1", "title": "Task 1", "status": "pending"}]
        updates = []
        result = tasks_reducer(existing, updates)

        assert result == existing


class TestInsightsReducer:
    """Test insights_reducer functionality."""

    def test_add_new_insight(self):
        """Test adding a new insight."""
        existing = []
        updates = [{"id": "insight1", "content": "Test insight", "timestamp": "2025-01-01"}]
        result = insights_reducer(existing, updates)

        assert len(result) == 1
        assert result[0]["id"] == "insight1"

    def test_append_multiple_insights(self):
        """Test that insights are appended, not replaced."""
        existing = [{"id": "insight1", "content": "First insight", "timestamp": "2025-01-01"}]
        updates = [
            {"id": "insight2", "content": "Second insight", "timestamp": "2025-01-02"},
            {"id": "insight3", "content": "Third insight", "timestamp": "2025-01-03"}
        ]
        result = insights_reducer(existing, updates)

        assert len(result) == 3
        ids = [i["id"] for i in result]
        assert ids == ["insight1", "insight2", "insight3"]

    def test_ignore_duplicate_ids(self):
        """Test that duplicate insight IDs are ignored."""
        existing = [{"id": "insight1", "content": "Original", "timestamp": "2025-01-01"}]
        updates = [
            {"id": "insight1", "content": "Duplicate attempt", "timestamp": "2025-01-02"},
            {"id": "insight2", "content": "New insight", "timestamp": "2025-01-02"}
        ]
        result = insights_reducer(existing, updates)

        assert len(result) == 2
        insight1 = next(i for i in result if i["id"] == "insight1")
        assert insight1["content"] == "Original"  # Should keep original

    def test_empty_updates(self):
        """Test that empty updates returns existing list."""
        existing = [{"id": "insight1", "content": "Test", "timestamp": "2025-01-01"}]
        updates = []
        result = insights_reducer(existing, updates)

        assert result == existing


class TestDesignLogReducer:
    """Test design_log_reducer functionality."""

    def test_add_new_decision(self):
        """Test adding a new design decision."""
        existing = []
        updates = [{"id": "decision1", "decision": "Use async", "rationale": "Better performance"}]
        result = design_log_reducer(existing, updates)

        assert len(result) == 1
        assert result[0]["id"] == "decision1"

    def test_append_multiple_decisions(self):
        """Test that decisions are appended in order."""
        existing = [{"id": "decision1", "decision": "First", "rationale": "Reason 1"}]
        updates = [
            {"id": "decision2", "decision": "Second", "rationale": "Reason 2"},
            {"id": "decision3", "decision": "Third", "rationale": "Reason 3"}
        ]
        result = design_log_reducer(existing, updates)

        assert len(result) == 3
        ids = [d["id"] for d in result]
        assert ids == ["decision1", "decision2", "decision3"]

    def test_ignore_duplicate_ids(self):
        """Test that duplicate decision IDs are ignored (append-only)."""
        existing = [{"id": "decision1", "decision": "Original", "rationale": "First"}]
        updates = [
            {"id": "decision1", "decision": "Duplicate", "rationale": "Second"},
            {"id": "decision2", "decision": "New", "rationale": "Valid"}
        ]
        result = design_log_reducer(existing, updates)

        assert len(result) == 2
        decision1 = result[0]
        assert decision1["decision"] == "Original"  # Should keep original

    def test_empty_updates(self):
        """Test that empty updates returns existing list."""
        existing = [{"id": "decision1", "decision": "Test", "rationale": "Test"}]
        updates = []
        result = design_log_reducer(existing, updates)

        assert result == existing


class TestTaskMemoriesReducer:
    """Test task_memories_reducer functionality."""

    def test_add_messages_to_new_task(self):
        """Test adding messages to a task that has no memory yet."""
        existing = {}
        updates = {
            "task1": [HumanMessage(content="Hello"), AIMessage(content="Hi")]
        }
        result = task_memories_reducer(existing, updates)

        assert "task1" in result
        assert len(result["task1"]) == 2
        assert result["task1"][0].content == "Hello"
        assert result["task1"][1].content == "Hi"

    def test_append_messages_to_existing_task(self):
        """Test appending new messages to existing task memory."""
        existing = {
            "task1": [HumanMessage(content="First")]
        }
        updates = {
            "task1": [AIMessage(content="Second"), HumanMessage(content="Third")]
        }
        result = task_memories_reducer(existing, updates)

        assert len(result["task1"]) == 3
        assert result["task1"][0].content == "First"
        assert result["task1"][1].content == "Second"
        assert result["task1"][2].content == "Third"

    def test_add_messages_to_multiple_tasks(self):
        """Test adding messages to multiple tasks at once."""
        existing = {"task1": [HumanMessage(content="Task 1")]}
        updates = {
            "task1": [AIMessage(content="Reply 1")],
            "task2": [HumanMessage(content="Task 2"), AIMessage(content="Reply 2")]
        }
        result = task_memories_reducer(existing, updates)

        assert len(result["task1"]) == 2
        assert len(result["task2"]) == 2

    def test_clear_specific_task_memories(self):
        """Test clearing memories for specific tasks using _clear."""
        existing = {
            "task1": [HumanMessage(content="Keep me")],
            "task2": [HumanMessage(content="Delete me")],
            "task3": [HumanMessage(content="Keep me too")]
        }
        updates = {
            "_clear": ["task2"]  # Clear task2's memory
        }
        result = task_memories_reducer(existing, updates)

        assert "task1" in result
        assert "task2" not in result
        assert "task3" in result

    def test_clear_multiple_task_memories(self):
        """Test clearing memories for multiple tasks at once."""
        existing = {
            "task1": [HumanMessage(content="Memory 1")],
            "task2": [HumanMessage(content="Memory 2")],
            "task3": [HumanMessage(content="Memory 3")]
        }
        updates = {
            "_clear": ["task1", "task3"]
        }
        result = task_memories_reducer(existing, updates)

        assert "task1" not in result
        assert "task2" in result
        assert "task3" not in result

    def test_clear_nonexistent_task(self):
        """Test clearing a task that doesn't exist (should be no-op)."""
        existing = {"task1": [HumanMessage(content="Memory")]}
        updates = {"_clear": ["task999"]}
        result = task_memories_reducer(existing, updates)

        assert "task1" in result
        assert len(result) == 1

    def test_empty_updates(self):
        """Test that empty updates returns existing dict."""
        existing = {"task1": [HumanMessage(content="Memory")]}
        updates = {}
        result = task_memories_reducer(existing, updates)

        assert result == existing

    def test_mixed_add_and_clear(self):
        """Test adding messages and clearing in same update."""
        existing = {
            "task1": [HumanMessage(content="Old")],
            "task2": [HumanMessage(content="Delete")]
        }
        updates = {
            "task1": [AIMessage(content="New")],
            "task3": [HumanMessage(content="Fresh")],
            "_clear": ["task2"]
        }
        result = task_memories_reducer(existing, updates)

        assert len(result["task1"]) == 2  # Old + New
        assert "task2" not in result  # Cleared
        assert len(result["task3"]) == 1  # Fresh


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
