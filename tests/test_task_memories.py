"""
Test: Task Memories Flow
========================
Tests that task_memories are correctly accumulated through:
1. Worker completion (should have full agent conversation)
2. QA/Strategist evaluation (should APPEND QA messages, not overwrite)

This test does NOT use an LLM - it mocks worker and strategist returns.
"""

import pytest
from typing import Dict, List, Any
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage, BaseMessage

# Import the reducer
import sys
sys.path.insert(0, 'src')
from state import task_memories_reducer


class TestTaskMemoriesReducer:
    """Test task_memories_reducer in isolation"""
    
    def test_append_to_existing_task(self):
        """Verify new messages are appended to existing task memories"""
        # Existing state: worker has already added messages
        existing = {
            "task_abc123": [
                SystemMessage(content="Worker system prompt"),
                HumanMessage(content="User task request"),
                AIMessage(content="I will implement this..."),
                HumanMessage(content="Tool result: file written"),
                AIMessage(content="Task complete!"),
            ]
        }
        
        # QA strategist returns just its messages
        qa_updates = {
            "task_abc123": [
                SystemMessage(content="QA Evaluation Process"),
                HumanMessage(content="Evaluating against criteria..."),
                SystemMessage(content="Verdict: PASS"),
            ]
        }
        
        # Merge
        result = task_memories_reducer(existing, qa_updates)
        
        # Should have ALL messages - worker + QA
        assert len(result["task_abc123"]) == 8, (
            f"Expected 8 messages (5 worker + 3 QA), got {len(result['task_abc123'])}"
        )
        
        # First 5 should be worker
        assert result["task_abc123"][0].content == "Worker system prompt"
        assert result["task_abc123"][4].content == "Task complete!"
        
        # Last 3 should be QA
        assert result["task_abc123"][5].content == "QA Evaluation Process"
        assert result["task_abc123"][7].content == "Verdict: PASS"
        
    def test_add_new_task(self):
        """Verify new task memories are added correctly"""
        existing = {
            "task_existing": [HumanMessage(content="existing")]
        }
        
        updates = {
            "task_new": [HumanMessage(content="new task message")]
        }
        
        result = task_memories_reducer(existing, updates)
        
        assert "task_existing" in result
        assert "task_new" in result
        assert len(result["task_new"]) == 1
        
    def test_empty_existing(self):
        """Verify reducer works when existing is empty"""
        existing = {}
        
        updates = {
            "task_abc": [HumanMessage(content="first message")]
        }
        
        result = task_memories_reducer(existing, updates)
        
        assert len(result["task_abc"]) == 1
        
    def test_clear_operation(self):
        """Verify _clear special key removes tasks"""
        existing = {
            "task_a": [HumanMessage(content="a")],
            "task_b": [HumanMessage(content="b")],
            "task_c": [HumanMessage(content="c")],
        }
        
        updates = {
            "_clear": ["task_a", "task_b"]  # Clear these two
        }
        
        result = task_memories_reducer(existing, updates)
        
        assert "task_a" not in result
        assert "task_b" not in result
        assert "task_c" in result


class TestTaskMemoriesFlow:
    """
    Integration tests simulating the full flow:
    Worker -> Server merge -> Strategist -> Server merge
    """
    
    def test_worker_then_qa_flow(self):
        """
        Simulate the full flow that's currently broken:
        1. Worker returns messages
        2. Server merges worker messages into state
        3. Strategist runs QA, returns QA messages
        4. Server merges QA messages into state
        5. Verify BOTH worker AND QA messages exist
        """
        # === STEP 1: Initial state (no task memories) ===
        state = {
            "task_memories": {}
        }
        
        # === STEP 2: Worker completes and returns messages ===
        worker_result = {
            "task_memories": {
                "task_xyz789": [
                    SystemMessage(content="You are a code worker..."),
                    HumanMessage(content="Build the auth module"),
                    AIMessage(content="Let me analyze the requirements..."),
                    HumanMessage(content="Tool: read_file result: ..."),
                    AIMessage(content="I'll create the auth.py file"),
                    HumanMessage(content="Tool: write_file success"),
                    AIMessage(content="Auth module complete!"),
                ]
            }
        }
        
        # Server merges worker result using reducer
        state["task_memories"] = task_memories_reducer(
            state.get("task_memories", {}),
            worker_result["task_memories"]
        )
        
        # Verify worker messages are stored
        assert "task_xyz789" in state["task_memories"]
        assert len(state["task_memories"]["task_xyz789"]) == 7, (
            f"Expected 7 worker messages, got {len(state['task_memories']['task_xyz789'])}"
        )
        print(f"After worker: {len(state['task_memories']['task_xyz789'])} messages")
        
        # === STEP 3: Strategist evaluates and returns QA messages ===
        # NOTE: Strategist creates a fresh dict, only returns QA messages
        strategist_result = {
            "task_memories": {
                "task_xyz789": [
                    SystemMessage(content="QA Evaluation Process"),
                    HumanMessage(content="Evaluating task_xyz789 against criteria..."),
                    HumanMessage(content="Test Results: All tests passing"),
                    SystemMessage(content="Verdict: PASS\nFeedback: Great implementation!"),
                ]
            }
        }
        
        # Server merges QA result using reducer
        state["task_memories"] = task_memories_reducer(
            state.get("task_memories", {}),
            strategist_result["task_memories"]
        )
        
        # === STEP 4: VERIFY BOTH worker AND QA messages exist ===
        total_messages = len(state["task_memories"]["task_xyz789"])
        print(f"After QA merge: {total_messages} messages")
        
        assert total_messages == 11, (
            f"Expected 11 messages (7 worker + 4 QA), got {total_messages}.\n"
            f"This indicates the reducer is not appending correctly!"
        )
        
        # Verify order: worker messages first, then QA
        msgs = state["task_memories"]["task_xyz789"]
        assert msgs[0].content == "You are a code worker..."
        assert msgs[6].content == "Auth module complete!"
        assert msgs[7].content == "QA Evaluation Process"
        assert "PASS" in msgs[10].content
        
        print("✅ All messages preserved correctly!")


class TestServerMergeSimulation:
    """
    Simulate exactly what server.py does to find the bug.
    """
    
    def test_server_merge_pattern(self):
        """
        Replicate the exact merge pattern from server.py
        to verify if the issue is in the server logic.
        """
        # Simulate state as it exists in server.py
        state = {"task_memories": {}}
        
        # === Phase 1: Worker completes ===
        # This is what server.py does at line ~1388
        worker_task_memories = {
            "task_test1": [
                HumanMessage(content="Worker message 1"),
                AIMessage(content="Worker message 2"),
            ]
        }
        
        # Debug logging like server.py lines 1385-1387
        for tid, msgs in worker_task_memories.items():
            existing_count = len(state.get("task_memories", {}).get(tid, []))
            new_count = len(msgs)
            print(f"[Worker merge] {tid}: existing={existing_count}, adding={new_count}")
        
        state["task_memories"] = task_memories_reducer(
            state.get("task_memories", {}),
            worker_task_memories
        )
        
        for tid, msgs in worker_task_memories.items():
            merged_count = len(state.get("task_memories", {}).get(tid, []))
            print(f"[Worker merge] After: {tid}: total={merged_count}")
        
        # === Phase 2: Strategist evaluates ===
        # This is what server.py does at line ~1515
        qa_task_memories = {
            "task_test1": [
                SystemMessage(content="QA message 1"),
                SystemMessage(content="QA message 2"),
            ]
        }
        
        # Debug logging like server.py lines 1511-1518
        for tid, msgs in qa_task_memories.items():
            existing_count = len(state.get("task_memories", {}).get(tid, []))
            new_count = len(msgs)
            print(f"[Strategist merge] {tid}: existing={existing_count}, adding={new_count}")
        
        state["task_memories"] = task_memories_reducer(
            state.get("task_memories", {}),
            qa_task_memories
        )
        
        for tid, msgs in qa_task_memories.items():
            merged_count = len(state.get("task_memories", {}).get(tid, []))
            print(f"[Strategist merge] After: {tid}: total={merged_count}")
        
        # === Verification ===
        final_count = len(state["task_memories"]["task_test1"])
        assert final_count == 4, f"Expected 4 (2+2), got {final_count}"
        
        print("✅ Server merge pattern works correctly in isolation!")


class TestDispatchLoopSimulation:
    """
    Integration test that simulates the ACTUAL server dispatch loop code.
    This tests the exact code path that was buggy (task_memories merge after break).
    
    NO LLM calls - uses mock returns.
    """
    
    def test_dispatch_loop_task_memories_flow(self):
        """
        Simulate the dispatch loop with mock worker/strategist results.
        This is the actual code pattern from server.py lines 1373-1410.
        """
        print("\n" + "="*60)
        print("Simulating dispatch loop WITH THE ACTUAL CODE PATTERN")
        print("="*60)
        
        # === Setup: Simulated state ===
        state = {
            "task_memories": {},
            "tasks": [
                {"id": "task_abc123", "status": "active", "phase": "build"}
            ]
        }
        
        # === Mock worker completion result ===
        # This is what worker_node returns
        class MockCompletion:
            def __init__(self):
                self.task_id = "task_abc123"
                self.result = {
                    "tasks": [
                        {"id": "task_abc123", "status": "awaiting_qa", "phase": "build"}
                    ],
                    "task_memories": {
                        "task_abc123": [
                            SystemMessage(content="You are a code worker..."),
                            HumanMessage(content="Build the auth module"),
                            AIMessage(content="Let me analyze..."),
                            HumanMessage(content="Tool result: file written"),
                            AIMessage(content="Task complete!"),
                        ]
                    }
                }
                self.error = None
        
        c = MockCompletion()
        
        # === SIMULATE THE EXACT SERVER CODE (lines 1373-1410) ===
        # Find task in state
        task = None
        for t in state["tasks"]:
            if t.get("id") == c.task_id:
                task = t
                break
        
        assert task is not None, "Task not found"
        
        if c.error:
            task["status"] = "failed"
            task["error"] = str(c.error)
        else:
            # Worker returns state updates with modified task
            if c.result and isinstance(c.result, dict):
                # Find the updated task in the result
                result_tasks = c.result.get("tasks", [])
                for rt in result_tasks:
                    if rt.get("id") == c.task_id:
                        # Merge updates
                        task.update(rt)
                        break
                
                # THE FIX: This must be OUTSIDE the for loop!
                # Previously this was INSIDE the for loop, after the break - unreachable!
                if "task_memories" in c.result:
                    worker_memories = c.result["task_memories"]
                    if worker_memories:
                        # Apply reducer to preserve existing memories
                        for tid, msgs in worker_memories.items():
                            existing_count = len(state.get("task_memories", {}).get(tid, []))
                            print(f"  [Worker] {tid[:12]}: existing={existing_count}, adding={len(msgs)}")
                        
                        state["task_memories"] = task_memories_reducer(
                            state.get("task_memories", {}), 
                            worker_memories
                        )
                        
                        for tid, msgs in worker_memories.items():
                            merged_count = len(state.get("task_memories", {}).get(tid, []))
                            print(f"  [Worker] After merge: {tid[:12]}: total={merged_count}")
        
        # Verify worker memories were merged
        assert "task_abc123" in state["task_memories"], "Worker memories not merged!"
        worker_msg_count = len(state["task_memories"]["task_abc123"])
        assert worker_msg_count == 5, f"Expected 5 worker messages, got {worker_msg_count}"
        print(f"✅ Worker phase: {worker_msg_count} messages in state")
        
        # === SIMULATE STRATEGIST (QA) ===
        # This simulates what strategist_node returns
        strategist_result = {
            "tasks": [
                {"id": "task_abc123", "status": "complete", "phase": "build", 
                 "qa_verdict": {"passed": True, "overall_feedback": "Looks good!"}}
            ],
            "task_memories": {
                "task_abc123": [
                    SystemMessage(content="QA Evaluation Process"),
                    HumanMessage(content="Evaluating against criteria..."),
                    SystemMessage(content="Verdict: PASS"),
                ]
            }
        }
        
        # Merge strategist results (simulating server.py lines 1509-1518)
        if "task_memories" in strategist_result:
            qa_memories = strategist_result["task_memories"]
            for tid, msgs in qa_memories.items():
                existing_count = len(state.get("task_memories", {}).get(tid, []))
                print(f"  [Strategist] {tid[:12]}: existing={existing_count}, adding={len(msgs)}")
            
            state["task_memories"] = task_memories_reducer(
                state.get("task_memories", {}), 
                qa_memories
            )
            
            for tid, msgs in qa_memories.items():
                merged_count = len(state.get("task_memories", {}).get(tid, []))
                print(f"  [Strategist] After merge: {tid[:12]}: total={merged_count}")
        
        # === FINAL VERIFICATION ===
        final_count = len(state["task_memories"]["task_abc123"])
        print(f"\n🎯 Final message count: {final_count}")
        
        assert final_count == 8, (
            f"REGRESSION! Expected 8 messages (5 worker + 3 QA), got {final_count}.\n"
            f"The task_memories merge is broken!"
        )
        
        # Verify message order
        msgs = state["task_memories"]["task_abc123"]
        assert msgs[0].content == "You are a code worker...", "First message should be worker"
        assert msgs[4].content == "Task complete!", "Last worker message"
        assert msgs[5].content == "QA Evaluation Process", "First QA message"
        assert msgs[7].content == "Verdict: PASS", "Last QA message"
        
        print("✅ Dispatch loop integration test PASSED!")
        print("   Worker and QA memories correctly accumulated.")


if __name__ == "__main__":
    # Run tests manually for debugging
    print("=" * 60)
    print("Testing task_memories_reducer in isolation...")
    print("=" * 60)
    
    t1 = TestTaskMemoriesReducer()
    t1.test_append_to_existing_task()
    print("✅ test_append_to_existing_task passed")
    
    t1.test_add_new_task()
    print("✅ test_add_new_task passed")
    
    t1.test_empty_existing()
    print("✅ test_empty_existing passed")
    
    print()
    print("=" * 60)
    print("Testing full Worker -> QA flow...")
    print("=" * 60)
    
    t2 = TestTaskMemoriesFlow()
    t2.test_worker_then_qa_flow()
    
    print()
    print("=" * 60)
    print("Testing server merge pattern...")
    print("=" * 60)
    
    t3 = TestServerMergeSimulation()
    t3.test_server_merge_pattern()
    
    print()
    print("=" * 60)
    print("Testing ACTUAL dispatch loop code path...")
    print("=" * 60)
    
    t4 = TestDispatchLoopSimulation()
    t4.test_dispatch_loop_task_memories_flow()
    
    print()
    print("=" * 60)
    print("ALL TESTS PASSED!")
    print("=" * 60)
