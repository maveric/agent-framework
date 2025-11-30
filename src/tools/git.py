"""
Agent Orchestrator — Git Tools
===============================
Version 1.0 — November 2025

Git operations for workers. These tools wrap git commands for use in the ReAct loop.
"""

import subprocess
from typing import List, Optional
from pathlib import Path


def git_commit(message: str, add_all: bool = False) -> str:
    """
    Commit changes in the current worktree.
    
    Args:
        message: Commit message
        add_all: If True, stage all changes before committing
        
    Returns:
        Commit hash if successful, or status message
    """
    try:
        # Stage files if requested
        if add_all:
            result = subprocess.run(
                ["git", "add", "-A"],
                capture_output=True,
                text=True,
                check=True
            )
        
        # Check if there are staged changes
        status_result = subprocess.run(
            ["git", "diff", "--cached", "--quiet"],
            capture_output=True
        )
        
        if status_result.returncode == 0:
            return "No changes staged for commit"
        
        # Commit
        subprocess.run(
            ["git", "commit", "-m", message],
            capture_output=True,
            text=True,
            check=True
        )
        
        # Get commit hash
        hash_result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True
        )
        
        commit_hash = hash_result.stdout.strip()
        return f"Committed successfully: {commit_hash[:8]}"
        
    except subprocess.CalledProcessError as e:
        return f"Error committing: {e.stderr if e.stderr else str(e)}"


def git_status() -> str:
    """
    Get current git status.
    
    Returns:
        Human-readable status of working directory
    """
    try:
        result = subprocess.run(
            ["git", "status", "--short"],
            capture_output=True,
            text=True,
            check=True
        )
        
        if not result.stdout:
            return "Working directory clean"
        
        return result.stdout
        
    except subprocess.CalledProcessError as e:
        return f"Error getting status: {e.stderr if e.stderr else str(e)}"


def git_diff(target: str = "HEAD", path: Optional[str] = None) -> str:
    """
    Show diff of changes.
    
    Args:
        target: What to diff against (default: HEAD)
        path: Specific file/directory to diff (None = all changes)
        
    Returns:
        Diff output
    """
    try:
        cmd = ["git", "diff", target]
        if path:
            cmd.append(path)
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True
        )
        
        if not result.stdout:
            return "No differences found"
        
        return result.stdout
        
    except subprocess.CalledProcessError as e:
        return f"Error getting diff: {e.stderr if e.stderr else str(e)}"


def git_add(paths: List[str]) -> str:
    """
    Stage files for commit.
    
    Args:
        paths: List of file paths to stage
        
    Returns:
        Success message
    """
    if not paths:
        return "No paths specified"
    
    try:
        for path in paths:
            subprocess.run(
                ["git", "add", path],
                capture_output=True,
                text=True,
                check=True
            )
        
        return f"Staged {len(paths)} file(s): {', '.join(paths)}"
        
    except subprocess.CalledProcessError as e:
        return f"Error staging files: {e.stderr if e.stderr else str(e)}"


def git_log(count: int = 10) -> str:
    """
    Show commit history.
    
    Args:
        count: Number of commits to show
        
    Returns:
        Formatted log output
    """
    try:
        result = subprocess.run(
            ["git", "log", f"-{count}", "--oneline", "--decorate"],
            capture_output=True,
            text=True,
            check=True
        )
        
        if not result.stdout:
            return "No commits found"
        
        return result.stdout
        
    except subprocess.CalledProcessError as e:
        return f"Error getting log: {e.stderr if e.stderr else str(e)}"
