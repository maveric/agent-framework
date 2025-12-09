"""
Write handler for writing/documentation tasks.
"""

from typing import Dict, Any

from orchestrator_types import Task, WorkerProfile, WorkerResult

# Import tools (ASYNC versions for non-blocking execution)
from tools import (
    read_file_async as read_file,
    write_file_async as write_file,
    list_directory_async as list_directory
)

from ..tools_binding import _bind_tools
from ..execution import _execute_react_loop


async def _write_handler(task: Task, state: Dict[str, Any], config: Dict[str, Any] = None) -> WorkerResult:
    """Writing tasks (async)."""
    tools = [read_file, write_file, list_directory]
    tools = _bind_tools(tools, state, WorkerProfile.WRITER)

    system_prompt = """You are a technical writer.
    Your goal is to write documentation.

    CRITICAL INSTRUCTIONS:
    1. You MUST write documentation to files (e.g., `README.md`) using `write_file`.
    2. DO NOT output documentation in the chat.
    3. Keep chat responses concise.
    """

    return await _execute_react_loop(task, tools, system_prompt, state, config)
