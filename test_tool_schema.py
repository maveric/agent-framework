
import asyncio
from langchain_core.tools import StructuredTool
from pydantic import BaseModel

async def test_tool_creation():
    print("Testing StructuredTool.from_function with async function...")
    
    # Define an async wrapper function (similar to our worker.py wrappers)
    async def sample_wrapper(path: str, encoding: str = "utf-8"):
        """Read a file asynchronously."""
        return f"Reading {path} with {encoding}"

    try:
        # Attempt 1: Just coroutine (what I did in latest fix)
        # Note: func is the first argument, so we must pass it or rely on valid defaults/handling
        print("\n--- Attempt 1: coroutine=wrapper ---")
        try:
            tool1 = StructuredTool.from_function(coroutine=sample_wrapper, name="read_file", description="desc")
            print(f"Tool created successfully: {tool1.name}")
            print(f"Args schema: {tool1.args_schema.schema()}")
            
            # Test schema contains 'path'
            props = tool1.args_schema.schema().get("properties", {})
            if "path" in props:
                print("✅ Schema contains 'path'")
            else:
                print("❌ Schema MISSING 'path'")
                
        except Exception as e:
            print(f"❌ Failed to create tool: {e}")

        # Attempt 3: func=wrapper AND coroutine=wrapper
        print("\n--- Attempt 3: func=wrapper AND coroutine=wrapper ---")
        try:
            tool3 = StructuredTool.from_function(
                func=sample_wrapper, 
                coroutine=sample_wrapper,
                name="read_file3", 
                description="desc"
            )
            print(f"Tool created successfully: {tool3.name}")
            print(f"Args schema: {tool3.args_schema.schema()}")
            
            if tool3.coroutine:
                print("✅ Tool has coroutine set")
            else:
                print("❌ Tool coroutine is None")

            # Check schema properties
            props = tool3.args_schema.schema().get("properties", {})
            if "path" in props:
                print("✅ Schema contains 'path'")
            else:
                print("❌ Schema MISSING 'path'")
                
        except Exception as e:
            print(f"❌ Failed to create tool: {e}")
            
    except Exception as e:
        print(f"Global Error: {e}")

if __name__ == "__main__":
    asyncio.run(test_tool_creation())
