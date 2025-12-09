"""
Research handler for research tasks.
"""

from typing import Dict, Any

from orchestrator_types import Task, WorkerProfile, WorkerResult

# Import tools (ASYNC versions for non-blocking execution)
from tools import (
    read_file_async as read_file,
    list_directory_async as list_directory
)

from ..tools_binding import _bind_tools
from ..execution import _execute_react_loop


async def _research_handler(task: Task, state: Dict[str, Any], config: Dict[str, Any] = None) -> WorkerResult:
    """Research tasks (async)."""
    # Note: Web tools not yet implemented/imported, falling back to basic tools
    tools = [read_file, list_directory]
    tools = _bind_tools(tools, state, WorkerProfile.RESEARCHER)

    system_prompt = """You are a researcher.
    Your goal is to gather information.
    """

    return await _execute_react_loop(task, tools, system_prompt, state, config)
