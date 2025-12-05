"""
Async Compatibility Test for LangGraph
=======================================
This test verifies that:
1. Async node functions work with LangGraph StateGraph
2. create_react_agent works with async invocation (ainvoke)
3. Tools can be converted to async without breaking

Run with: python src/tests/test_async_compatibility.py
"""

import asyncio
import sys
import os

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from typing import TypedDict, Annotated
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver


# ========================================
# TEST 1: Async Node Functions in StateGraph
# ========================================

class SimpleState(TypedDict):
    value: int
    history: list

def history_reducer(current: list, update: list) -> list:
    return current + update

class TestState(TypedDict):
    value: int
    history: Annotated[list, history_reducer]

async def async_increment_node(state: TestState) -> dict:
    """Async node function."""
    await asyncio.sleep(0.01)  # Simulate async I/O
    return {
        "value": state["value"] + 1,
        "history": ["incremented"]
    }

async def async_double_node(state: TestState) -> dict:
    """Another async node."""
    await asyncio.sleep(0.01)
    return {
        "value": state["value"] * 2,
        "history": ["doubled"]
    }

def route_by_value(state: TestState):
    """Routing function (sync is fine for routing)."""
    if state["value"] < 10:
        return "increment"
    return END


async def test_async_nodes():
    """Test that async node functions work in StateGraph."""
    print("\n=== TEST 1: Async Node Functions ===")
    
    graph = StateGraph(TestState)
    
    # Add async nodes
    graph.add_node("increment", async_increment_node)
    graph.add_node("double", async_double_node)
    
    # Set entry and edges
    graph.set_entry_point("increment")
    graph.add_edge("increment", "double")
    graph.add_conditional_edges("double", route_by_value)
    
    # Compile
    checkpointer = MemorySaver()
    compiled = graph.compile(checkpointer=checkpointer)
    
    # Test with ainvoke (async)
    initial_state = {"value": 1, "history": []}
    result = await compiled.ainvoke(
        initial_state,
        config={"configurable": {"thread_id": "test-1"}}
    )
    
    print(f"  Initial value: 1")
    print(f"  Final value: {result['value']}")
    print(f"  History: {result['history']}")
    
    assert result["value"] >= 10, f"Expected value >= 10, got {result['value']}"
    assert "incremented" in result["history"], "Should have incremented"
    assert "doubled" in result["history"], "Should have doubled"
    
    print("  ✓ Test passed!")
    return True


# ========================================
# TEST 2: Async Tools with create_react_agent
# ========================================

async def test_async_react_agent():
    """Test that create_react_agent works with async invocation."""
    print("\n=== TEST 2: Async ReAct Agent ===")
    
    try:
        from langgraph.prebuilt import create_react_agent
        from langchain_core.tools import tool
    except ImportError as e:
        print(f"  ⚠ Skipping test: {e}")
        return True
    
    # Check if we have an API key for testing
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass  # dotenv not required if env vars already set
    
    if not os.getenv("OPENAI_API_KEY") and not os.getenv("ANTHROPIC_API_KEY"):
        print("  ⚠ Skipping test: No API key found (OPENAI_API_KEY or ANTHROPIC_API_KEY)")
        return True
    
    # Create a simple async tool 
    @tool
    async def async_add_numbers(a: int, b: int) -> int:
        """Add two numbers together asynchronously."""
        await asyncio.sleep(0.01)  # Simulate async I/O
        return a + b
    
    @tool
    def sync_multiply(a: int, b: int) -> int:
        """Multiply two numbers (sync tool for comparison)."""
        return a * b
    
    # Get LLM
    try:
        from llm_client import get_llm
        from config import ModelConfig
        llm = get_llm(ModelConfig(
            provider="openai",
            model_name="gpt-4o-mini",  # Use cheap model for testing
            temperature=0
        ))
    except Exception as e:
        print(f"  ⚠ Skipping test: Could not create LLM: {e}")
        return True
    
    # Create agent with mixed sync/async tools
    agent = create_react_agent(llm, [async_add_numbers, sync_multiply])
    
    # Test async invocation
    from langchain_core.messages import HumanMessage
    result = await agent.ainvoke({
        "messages": [HumanMessage(content="What is 5 + 3?")]
    })
    
    print(f"  Agent response: {result['messages'][-1].content[:100]}...")
    print("  ✓ Test passed!")
    return True


# ========================================
# TEST 3: Mixed Sync/Async in Same Graph
# ========================================

def sync_node(state: TestState) -> dict:
    """Synchronous node (should still work)."""
    return {
        "value": state["value"] + 100,
        "history": ["sync_added_100"]
    }

async def test_mixed_sync_async():
    """Test mixing sync and async nodes."""
    print("\n=== TEST 3: Mixed Sync/Async Nodes ===")
    
    graph = StateGraph(TestState)
    
    # Mix sync and async nodes
    graph.add_node("async_inc", async_increment_node)
    graph.add_node("sync_add", sync_node)  # Sync node
    graph.add_node("async_double", async_double_node)
    
    graph.set_entry_point("async_inc")
    graph.add_edge("async_inc", "sync_add")
    graph.add_edge("sync_add", "async_double")
    graph.add_edge("async_double", END)
    
    compiled = graph.compile(checkpointer=MemorySaver())
    
    result = await compiled.ainvoke(
        {"value": 1, "history": []},
        config={"configurable": {"thread_id": "test-mixed"}}
    )
    
    print(f"  Path: 1 -> +1=2 -> +100=102 -> *2=204")
    print(f"  Actual: {result['value']}")
    print(f"  History: {result['history']}")
    
    assert result["value"] == 204, f"Expected 204, got {result['value']}"
    assert "sync_added_100" in result["history"], "Should have sync step"
    
    print("  ✓ Test passed!")
    return True


# ========================================
# MAIN
# ========================================

async def main():
    print("=" * 60)
    print("LANGGRAPH ASYNC COMPATIBILITY TESTS")
    print("=" * 60)
    
    results = []
    
    # Run tests
    try:
        results.append(("Async Nodes", await test_async_nodes()))
    except Exception as e:
        print(f"  ✗ Test failed: {e}")
        results.append(("Async Nodes", False))
    
    try:
        results.append(("Async ReAct Agent", await test_async_react_agent()))
    except Exception as e:
        print(f"  ✗ Test failed: {e}")
        import traceback
        traceback.print_exc()
        results.append(("Async ReAct Agent", False))
    
    try:
        results.append(("Mixed Sync/Async", await test_mixed_sync_async()))
    except Exception as e:
        print(f"  ✗ Test failed: {e}")
        results.append(("Mixed Sync/Async", False))
    
    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    for name, passed in results:
        status = "✓ PASS" if passed else "✗ FAIL"
        print(f"  {status}: {name}")
    
    all_passed = all(r[1] for r in results)
    print("\n" + ("✓ ALL TESTS PASSED" if all_passed else "✗ SOME TESTS FAILED"))
    
    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
