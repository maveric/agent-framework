"""
Agent Orchestrator — Async Git Tools
=====================================
Version 2.0 — December 2025

Async git operations for workers using asyncio subprocess.
"""

import asyncio
from typing import List, Optional


async def git_commit_async(message: str, add_all: bool = False) -> str:
    """
    Commit changes asynchronously in the current worktree.
    
    Args:
        message: Commit message
        add_all: If True, stage all changes before committing
        
    Returns:
        Commit hash if successful, or status message
    """
    try:
        if add_all:
            process = await asyncio.create_subprocess_exec(
                "git", "add", "-A",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            await process.communicate()
        
        # Check if there are staged changes
        process = await asyncio.create_subprocess_exec(
            "git", "diff", "--cached", "--quiet",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        await process.communicate()
        
        if process.returncode == 0:
            return "No changes staged for commit"
        
        # Commit
        process = await asyncio.create_subprocess_exec(
            "git", "commit", "-m", message,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()
        
        if process.returncode != 0:
            error = stderr.decode("utf-8", errors="replace")
            return f"Error committing: {error}"
        
        # Get commit hash
        process = await asyncio.create_subprocess_exec(
            "git", "rev-parse", "HEAD",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await process.communicate()
        
        commit_hash = stdout.decode("utf-8").strip()
        return f"Committed successfully: {commit_hash[:8]}"
        
    except Exception as e:
        return f"Error committing: {str(e)}"


async def git_status_async() -> str:
    """
    Get current git status asynchronously.
    
    Returns:
        Human-readable status of working directory
    """
    try:
        process = await asyncio.create_subprocess_exec(
            "git", "status", "--short",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()
        
        if process.returncode != 0:
            error = stderr.decode("utf-8", errors="replace")
            return f"Error getting status: {error}"
        
        output = stdout.decode("utf-8")
        return output if output else "Working directory clean"
        
    except Exception as e:
        return f"Error getting status: {str(e)}"


async def git_diff_async(target: str = "HEAD", path: Optional[str] = None) -> str:
    """
    Show diff of changes asynchronously.
    
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
        
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()
        
        if process.returncode != 0:
            error = stderr.decode("utf-8", errors="replace")
            return f"Error getting diff: {error}"
        
        output = stdout.decode("utf-8")
        return output if output else "No differences found"
        
    except Exception as e:
        return f"Error getting diff: {str(e)}"


async def git_add_async(paths: List[str]) -> str:
    """
    Stage files for commit asynchronously.
    
    Args:
        paths: List of file paths to stage
        
    Returns:
        Success message
    """
    if not paths:
        return "No paths specified"
    
    try:
        for path in paths:
            process = await asyncio.create_subprocess_exec(
                "git", "add", path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await process.communicate()
            
            if process.returncode != 0:
                error = stderr.decode("utf-8", errors="replace")
                return f"Error staging {path}: {error}"
        
        return f"Staged {len(paths)} file(s): {', '.join(paths)}"
        
    except Exception as e:
        return f"Error staging files: {str(e)}"


async def git_log_async(count: int = 10) -> str:
    """
    Show commit history asynchronously.
    
    Args:
        count: Number of commits to show
        
    Returns:
        Formatted log output
    """
    try:
        process = await asyncio.create_subprocess_exec(
            "git", "log", f"-{count}", "--oneline", "--decorate",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()
        
        if process.returncode != 0:
            error = stderr.decode("utf-8", errors="replace")
            return f"Error getting log: {error}"
        
        output = stdout.decode("utf-8")
        return output if output else "No commits found"
        
    except Exception as e:
        return f"Error getting log: {str(e)}"


# Keep sync versions available for backwards compatibility
from .git import git_commit, git_status, git_diff, git_add, git_log
