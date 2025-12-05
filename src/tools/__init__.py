"""
Agent Orchestrator — Tools Package
==================================
Version 2.0 — December 2025

Tool registry and exports (sync and async versions).
"""

from .base import ToolDefinition, ToolRegistry, ToolCategory, DetailLevel

# Sync implementations (backwards compatible)
from .filesystem import (
    read_file, write_file, append_file, 
    list_directory, file_exists, delete_file
)
from .code_execution import run_python, run_shell
from .git import git_commit, git_status, git_diff, git_add, git_log

# Async implementations (new)
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
    
    # Filesystem (sync)
    "read_file", 
    "write_file", 
    "append_file", 
    "list_directory", 
    "file_exists", 
    "delete_file",
    
    # Filesystem (async)
    "read_file_async",
    "write_file_async",
    "append_file_async",
    "list_directory_async",
    "file_exists_async",
    "delete_file_async",
    
    # Code Execution (sync)
    "run_python",
    "run_shell",
    
    # Code Execution (async)
    "run_python_async",
    "run_shell_async",
    
    # Git (sync)
    "git_commit",
    "git_status",
    "git_diff",
    "git_add",
    "git_log",
    
    # Git (async)
    "git_commit_async",
    "git_status_async",
    "git_diff_async",
    "git_add_async",
    "git_log_async",
]
