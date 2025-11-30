"""
Agent Orchestrator — Tools Package
==================================
Version 1.0 — November 2025

Tool registry and exports.
"""

from .base import ToolDefinition, ToolRegistry, ToolCategory, DetailLevel

# Import implementations
from .filesystem import (
    read_file, write_file, append_file, 
    list_directory, file_exists, delete_file
)
from .code_execution import run_python, run_shell
from .git import git_commit, git_status, git_diff, git_add, git_log

__all__ = [
    # Metadata
    "ToolDefinition", 
    "ToolRegistry",
    "ToolCategory",
    "DetailLevel",
    
    # Filesystem
    "read_file", 
    "write_file", 
    "append_file", 
    "list_directory", 
    "file_exists", 
    "delete_file",
    
    # Code Execution
    "run_python",
    "run_shell",
    
    # Git
    "git_commit",
    "git_status",
    "git_diff",
    "git_add",
    "git_log",
]
