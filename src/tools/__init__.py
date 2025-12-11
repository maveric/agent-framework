"""
Agent Orchestrator — Tools Package
==================================
Version 2.0 — December 2025

Tool registry and async tool exports.
All tools are async for non-blocking execution.
"""

from .base import ToolDefinition, ToolRegistry, ToolCategory, DetailLevel

# Async implementations
from .filesystem_async import (
    read_file_async, write_file_async, append_file_async,
    list_directory_async, file_exists_async, delete_file_async
)
from .code_execution_async import run_python_async, run_shell_async
from .git_async import (
    git_commit_async, git_status_async, git_diff_async,
    git_add_async, git_log_async
)

__all__ = [
    # Metadata
    "ToolDefinition",
    "ToolRegistry",
    "ToolCategory",
    "DetailLevel",

    # Filesystem (async)
    "read_file_async",
    "write_file_async",
    "append_file_async",
    "list_directory_async",
    "file_exists_async",
    "delete_file_async",

    # Code Execution (async)
    "run_python_async",
    "run_shell_async",

    # Git (async)
    "git_commit_async",
    "git_status_async",
    "git_diff_async",
    "git_add_async",
    "git_log_async",
]
