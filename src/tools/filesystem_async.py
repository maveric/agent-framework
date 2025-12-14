"""
Agent Orchestrator — Async Filesystem Tools
============================================
Version 2.0 — December 2025

Async implementation of filesystem operations using aiofiles.
These async versions are used by async node handlers.

The sync versions in filesystem.py are kept for backwards compatibility.
"""

import os
import asyncio
from pathlib import Path
from typing import List, Optional

try:
    import aiofiles
    import aiofiles.os
    AIOFILES_AVAILABLE = True
except ImportError:
    AIOFILES_AVAILABLE = False

import platform

WORKSPACE_ROOT = Path(os.getcwd())
PLATFORM = f"OS - {platform.system()}, Release: {platform.release()}"


def _get_workspace_root(root: Optional[Path] = None) -> Path:
    """Get workspace root from argument or default."""
    if root:
        return Path(root)
    return WORKSPACE_ROOT


def _is_safe_path(path: str, root: Optional[Path] = None) -> bool:
    """Ensure path is within workspace."""
    workspace_root = _get_workspace_root(root).resolve()
    try:
        path_obj = Path(path)
        
        # Handle absolute paths (e.g., F:\coding\agent-workspaces\...)
        # On Windows, paths like "F:\..." are absolute
        # On Unix, paths like "/home/..." are absolute
        if path_obj.is_absolute():
            target = path_obj.resolve()
        else:
            # Relative path - join with workspace root
            normalized_path = path.lstrip('/\\')
            target = (workspace_root / normalized_path).resolve()
        
        # Robust comparison handling case sensitivity
        root_str = str(workspace_root)
        target_str = str(target)
        
        # On Windows, normalize case for comparison
        if platform.system() == "Windows":
            root_str = root_str.lower()
            target_str = target_str.lower()
            
        is_safe = target_str.startswith(root_str)
        
        if not is_safe:
            print(f"  [SECURITY] Access denied: {target_str} is not in {root_str}", flush=True)
            
        return is_safe
    except Exception as e:
        print(f"  [SECURITY] Path check error: {e}", flush=True)
        return False


async def read_file_async(path: str, encoding: str = "utf-8", root: Optional[Path] = None) -> str:
    """
    Read the contents of a file asynchronously.
    
    Args:
        path: Relative path to the file
        encoding: File encoding (default: utf-8)
        root: Optional workspace root override
    
    Returns:
        File contents as string
    """
    if not _is_safe_path(path, root):
        raise ValueError(f"Access denied: {path} is outside workspace")
    
    normalized_path = path.lstrip('/\\')
    target_path = _get_workspace_root(root) / normalized_path
    
    if not target_path.exists():
        return f"File not found: {path}"
    
    if target_path.is_dir():
        return f"Error: {path} is a directory, not a file. Use list_directory instead."
    
    if AIOFILES_AVAILABLE:
        async with aiofiles.open(target_path, mode='r', encoding=encoding) as f:
            return await f.read()
    else:
        # Fallback to thread pool
        return await asyncio.to_thread(_read_file_sync, target_path, encoding)


async def write_file_async(path: str, content: str, encoding: str = "utf-8", root: Optional[Path] = None) -> str:
    """
    Write content to a file asynchronously. Creates parent directories if needed.
    
    Args:
        path: Relative path to the file
        content: Content to write
        encoding: File encoding (default: utf-8)
        root: Optional workspace root override
        
    Returns:
        Success message with byte count
    """
    if not path:
        raise ValueError("ERROR: 'path' parameter is required!")
    
    if content is None:
        raise ValueError("ERROR: 'content' parameter is required!")
    
    if not _is_safe_path(path, root):
        raise ValueError(f"Access denied: {path} is outside workspace")
    
    normalized_path = path.lstrip('/\\')
    target_path = _get_workspace_root(root) / normalized_path
    
    # Create parent directories (sync is fine here - fast operation)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    
    if AIOFILES_AVAILABLE:
        async with aiofiles.open(target_path, mode='w', encoding=encoding) as f:
            await f.write(content)
    else:
        await asyncio.to_thread(_write_file_sync, target_path, content, encoding)
    
    return f"Successfully wrote {len(content)} bytes to {path}"


async def append_file_async(path: str, content: str, encoding: str = "utf-8", root: Optional[Path] = None) -> str:
    """
    Append content to an existing file asynchronously.
    
    Args:
        path: Relative path to the file
        content: Content to append
        encoding: File encoding (default: utf-8)
        root: Optional workspace root override
        
    Returns:
        Success message
    """
    if not _is_safe_path(path, root):
        raise ValueError(f"Access denied: {path} is outside workspace")
    
    normalized_path = path.lstrip('/\\')
    target_path = _get_workspace_root(root) / normalized_path
    
    if not target_path.exists():
        return f"File not found: {path}"
    
    if AIOFILES_AVAILABLE:
        async with aiofiles.open(target_path, mode='a', encoding=encoding) as f:
            await f.write(content)
    else:
        await asyncio.to_thread(_append_file_sync, target_path, content, encoding)
    
    return f"Successfully appended to {path}"


async def list_directory_async(
    path: str = ".", 
    recursive: bool = False, 
    pattern: str = "*", 
    root: Optional[Path] = None,
    max_depth: int = 3,
    max_results: int = 500
) -> List[str]:
    """
    List files and directories asynchronously.
    
    Args:
        path: Directory path (default: ".")
        recursive: Include subdirectories (default: False)
        pattern: Glob pattern (default: "*")
        root: Optional workspace root override
        max_depth: Maximum recursion depth (default: 3, prevents deep venv/node_modules)
        max_results: Maximum number of results to return (default: 500)
        
    Returns:
        List of file paths
    """
    if not _is_safe_path(path, root):
        raise ValueError(f"Access denied: {path} is outside workspace")
    
    normalized_path = path.lstrip('/\\')
    workspace_root = _get_workspace_root(root)
    target_path = workspace_root / normalized_path
    
    if not target_path.exists():
        return [f"Directory not found: {path}"]
    
    # Directories to always exclude (token killers)
    EXCLUDED_DIRS = {
        'node_modules', 'venv', '.venv', '__pycache__', '.git', '.svn',
        'dist', 'build', '.tox', '.pytest_cache', '.mypy_cache',
        'site-packages', '.eggs', '*.egg-info', 'coverage', '.coverage',
        '.idea', '.vscode', 'htmlcov'
    }
    
    # Walk directory with depth limit and exclusions
    def _do_walk():
        import fnmatch
        results = []
        base_depth = len(target_path.parts)
        
        for root_dir, dirs, files in os.walk(target_path):
            root_path = Path(root_dir)
            current_depth = len(root_path.parts) - base_depth
            
            # Depth limit
            if current_depth >= max_depth:
                dirs[:] = []  # Don't recurse deeper
                continue
            
            # Exclude problematic directories (modifies dirs in-place)
            dirs[:] = [d for d in dirs if d not in EXCLUDED_DIRS and 
                       not any(fnmatch.fnmatch(d, ex) for ex in EXCLUDED_DIRS if '*' in ex)]
            
            # If not recursive, clear dirs to stop after first level
            if not recursive:
                dirs[:] = []
            
            # Match files and dirs against pattern
            for name in files + dirs:
                if fnmatch.fnmatch(name, pattern):
                    full_path = root_path / name
                    rel_path = os.path.relpath(full_path, workspace_root)
                    rel_path = rel_path.replace("\\", "/")
                    results.append(rel_path)
                    
                    # Limit results to prevent token explosion
                    if len(results) >= max_results:
                        results.append(f"... (truncated at {max_results} results, use pattern to filter)")
                        return results
        
        return sorted(results) if results else ["Directory is empty."]
    
    return await asyncio.to_thread(_do_walk)


async def file_exists_async(path: str, root: Optional[Path] = None) -> bool:
    """
    Check if a file or directory exists asynchronously.
    
    Args:
        path: Path to check
        root: Optional workspace root override
        
    Returns:
        True if exists
    """
    if not _is_safe_path(path, root):
        return False
    
    target_path = _get_workspace_root(root) / path.lstrip('/\\')
    
    if AIOFILES_AVAILABLE:
        return await aiofiles.os.path.exists(target_path)
    else:
        return await asyncio.to_thread(target_path.exists)


async def delete_file_async(path: str, confirm: bool, root: Optional[Path] = None) -> str:
    """
    Delete a file asynchronously.
    
    Args:
        path: Path to delete
        confirm: Must be True
        root: Optional workspace root override
        
    Returns:
        Success message
    """
    if not confirm:
        raise ValueError("Deletion requires confirmation=True")
    
    if not _is_safe_path(path, root):
        raise ValueError(f"Access denied: {path} is outside workspace")
    
    normalized_path = path.lstrip('/\\')
    target_path = _get_workspace_root(root) / normalized_path
    
    if not target_path.exists():
        return f"File not found: {path}"
    
    if not target_path.is_file():
        return f"{path} is not a file."
    
    if AIOFILES_AVAILABLE:
        await aiofiles.os.remove(target_path)
    else:
        await asyncio.to_thread(os.remove, target_path)
    
    return f"Successfully deleted {path}"


# ========================================
# Sync fallbacks for when aiofiles unavailable
# ========================================

def _read_file_sync(path: Path, encoding: str) -> str:
    with open(path, 'r', encoding=encoding) as f:
        return f.read()


def _write_file_sync(path: Path, content: str, encoding: str) -> None:
    with open(path, 'w', encoding=encoding) as f:
        f.write(content)


def _append_file_sync(path: Path, content: str, encoding: str) -> None:
    with open(path, 'a', encoding=encoding) as f:
        f.write(content)
