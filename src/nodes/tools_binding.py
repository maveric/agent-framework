"""
Tool binding and wrapper functions for worker agents.
"""

import logging
from typing import List, Callable, Dict, Any

from langchain_core.tools import StructuredTool

from orchestrator_types import WorkerProfile

logger = logging.getLogger(__name__)


def _create_read_file_wrapper(tool, worktree_path):
    async def read_file_wrapper(path: str, encoding: str = "utf-8"):
        """Read the contents of a file."""
        return await tool(path, encoding, root=worktree_path)
    return read_file_wrapper


def _create_write_file_wrapper(tool, worktree_path):
    async def write_file_wrapper(path: str, content: str, encoding: str = "utf-8"):
        """Write content to a file."""
        return await tool(path, content, encoding, root=worktree_path)
    return write_file_wrapper


def _create_append_file_wrapper(tool, worktree_path):
    async def append_file_wrapper(path: str, content: str, encoding: str = "utf-8"):
        """Append content to an existing file."""
        return await tool(path, content, encoding, root=worktree_path)
    return append_file_wrapper


def _create_list_directory_wrapper(tool, worktree_path):
    async def list_directory_wrapper(path: str = ".", recursive: bool = False, pattern: str = "*"):
        """List files and directories."""
        return await tool(path, recursive, pattern, root=worktree_path)
    return list_directory_wrapper


def _create_file_exists_wrapper(tool, worktree_path):
    async def file_exists_wrapper(path: str):
        """Check if a file or directory exists."""
        return await tool(path, root=worktree_path)
    return file_exists_wrapper


def _create_delete_file_wrapper(tool, worktree_path):
    async def delete_file_wrapper(path: str, confirm: bool):
        """Delete a file."""
        return await tool(path, confirm, root=worktree_path)
    return delete_file_wrapper


def _create_run_python_wrapper(tool, worktree_path, workspace_path=None):
    async def run_python_wrapper(code: str, timeout: int = 30):
        """Execute Python code using shared venv if available."""
        return await tool(code, timeout, cwd=worktree_path, workspace_path=workspace_path)
    return run_python_wrapper


def _create_run_shell_wrapper(tool, worktree_path):
    async def run_shell_wrapper(command: str, timeout: int = 30):
        """Execute shell command."""
        return await tool(command, timeout, cwd=worktree_path)
    return run_shell_wrapper


def _create_subtasks_wrapper(tool, worktree_path):
    def create_subtasks_wrapper(subtasks: List[Dict[str, Any]]):
        """Create subtasks for the project."""
        return tool(subtasks)  # This one is sync (create_subtasks is sync)
    return create_subtasks_wrapper


def _bind_tools(tools: List[Callable], state: Dict[str, Any], profile: WorkerProfile = None) -> List[Callable]:
    """
    Bind tools to the worktree context.
    Wraps filesystem and execution tools to operate within the task's worktree.

    Args:
        tools: List of tool functions/objects
        state: Orchestrator state (containing worktree manager)
        profile: Worker profile (optional, for permission checks)
    """
    worktree_path = state.get("worktree_path") or state.get("_workspace_path")

    if not worktree_path:
        # CRITICAL: Cannot proceed without a workspace path - this indicates corrupt state
        # This usually happens when resuming a run from a database that was saved before
        # workspace_path was properly persisted.
        raise ValueError(
            "Cannot bind tools: No worktree_path or _workspace_path found in state. "
            "This run may be from before workspace persistence was fixed. "
            "Please start a new run."
        )

    logger.debug(f"Binding tools to path: {worktree_path}")

    bound_tools = []
    for tool in tools:
        # Check if tool accepts 'root' argument (filesystem tools)
        # NOTE: Handle both sync names (read_file) and async names (read_file_async)
        fs_tools = ["read_file", "write_file", "append_file", "list_directory", "file_exists", "delete_file",
                    "read_file_async", "write_file_async", "append_file_async", "list_directory_async",
                    "file_exists_async", "delete_file_async"]
        if tool.__name__ in fs_tools:

            # Use factory functions to avoid closure loop variable capture issues
            # NOTE: Pass coroutine= directly - LangChain infers schema from the async function signature
            if tool.__name__ in ["read_file", "read_file_async"]:
                wrapper = _create_read_file_wrapper(tool, worktree_path)
                bound_tools.append(StructuredTool.from_function(func=wrapper, coroutine=wrapper, name="read_file", description="Read the contents of a file.", handle_tool_error=True))

            elif tool.__name__ in ["write_file", "write_file_async"]:
                wrapper = _create_write_file_wrapper(tool, worktree_path)
                bound_tools.append(StructuredTool.from_function(func=wrapper, coroutine=wrapper, name="write_file", description="Write content to a file.", handle_tool_error=True))

            elif tool.__name__ in ["append_file", "append_file_async"]:
                wrapper = _create_append_file_wrapper(tool, worktree_path)
                bound_tools.append(StructuredTool.from_function(func=wrapper, coroutine=wrapper, name="append_file", description="Append content to an existing file.", handle_tool_error=True))

            elif tool.__name__ in ["list_directory", "list_directory_async"]:
                wrapper = _create_list_directory_wrapper(tool, worktree_path)
                bound_tools.append(StructuredTool.from_function(func=wrapper, coroutine=wrapper, name="list_directory", description="List files and directories.", handle_tool_error=True))

            elif tool.__name__ in ["file_exists", "file_exists_async"]:
                wrapper = _create_file_exists_wrapper(tool, worktree_path)
                bound_tools.append(StructuredTool.from_function(func=wrapper, coroutine=wrapper, name="file_exists", description="Check if a file or directory exists.", handle_tool_error=True))

            elif tool.__name__ in ["delete_file", "delete_file_async"]:
                wrapper = _create_delete_file_wrapper(tool, worktree_path)
                bound_tools.append(StructuredTool.from_function(func=wrapper, coroutine=wrapper, name="delete_file", description="Delete a file.", handle_tool_error=True))

        elif tool.__name__ in ["run_python", "run_shell", "run_python_async", "run_shell_async"]:
            workspace_path = state.get("_workspace_path")  # For shared venv lookup
            if tool.__name__ in ["run_python", "run_python_async"]:
                wrapper = _create_run_python_wrapper(tool, worktree_path, workspace_path=workspace_path)
                bound_tools.append(StructuredTool.from_function(func=wrapper, coroutine=wrapper, name="run_python", description="Execute Python code using shared venv if available.", handle_tool_error=True))
            elif tool.__name__ in ["run_shell", "run_shell_async"]:
                wrapper = _create_run_shell_wrapper(tool, worktree_path)
                bound_tools.append(StructuredTool.from_function(func=wrapper, coroutine=wrapper, name="run_shell", description="Execute shell command.", handle_tool_error=True))

        elif tool.__name__ == "create_subtasks":
             # Allow Planners, Testers, and Coders to create subtasks
             if profile in [WorkerProfile.PLANNER, WorkerProfile.TESTER, WorkerProfile.CODER]:
                 bound_tools.append(StructuredTool.from_function(
                     func=tool,
                     name="create_subtasks",
                     description="Create COMMIT-LEVEL subtasks to be executed by other workers. Each task should be one atomic, reviewable change."
                 ))
             else:
                 # Skip for other profiles
                 pass

        elif tool.__name__ == "report_existing_implementation":
            # Convert plain function to StructuredTool for proper LLM usage
            bound_tools.append(StructuredTool.from_function(
                func=tool,
                name="report_existing_implementation",
                description="Report that existing code already implements the required feature. ONLY use if you made ZERO modifications."
            ))

        else:
            bound_tools.append(tool)

    return bound_tools
