"""
Agent Orchestrator — Filesystem Tools
=====================================
Version 1.0 — November 2025

Implementation of filesystem operations.
"""

import os
import glob
from pathlib import Path
from typing import List, Dict, Any, Optional

# Security: Restrict operations to the workspace root
# This will be overridden by passing workspace_path in tool calls
WORKSPACE_ROOT = Path(os.getcwd())

def _get_workspace_root(root: Optional[Path] = None) -> Path:
    """Get workspace root from argument or default."""
    if root:
        return root
    return WORKSPACE_ROOT

def _is_safe_path(path: str, root: Optional[Path] = None) -> bool:
    """Ensure path is within workspace."""
    workspace_root = _get_workspace_root(root)
    try:
        # Resolve absolute path
        target = (workspace_root / path).resolve()
        # Check if it starts with workspace root
        return str(target).startswith(str(workspace_root))
    except Exception:
        return False

def read_file(path: str, encoding: str = "utf-8", root: Optional[Path] = None) -> str:
    """
    Read the contents of a file.
    
    Args:
        path: Relative path to the file
        encoding: File encoding (default: utf-8)
        root: Optional workspace root override
    
    Returns:
        File contents as string
    """
    if not _is_safe_path(path, root):
        raise ValueError(f"Access denied: {path} is outside workspace")
    
    target_path = _get_workspace_root(root) / path
    if not target_path.exists():
        return f"File not found: {path}"
        
    with open(target_path, "r", encoding=encoding) as f:
        return f.read()

def write_file(path: str, content: str, encoding: str = "utf-8", root: Optional[Path] = None) -> str:
    """
    Write content to a file. Creates or overwrites.
    
    Args:
        path: Relative path to the file
        content: Content to write
        encoding: File encoding (default: utf-8)
        root: Optional workspace root override
        
    Returns:
        Success message
    """
    if not _is_safe_path(path, root):
        raise ValueError(f"Access denied: {path} is outside workspace")
        
    target_path = _get_workspace_root(root) / path
    
    # Create parent directories if needed
    target_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(target_path, "w", encoding=encoding) as f:
        f.write(content)
        
    return f"Successfully wrote {len(content)} bytes to {path}"

def append_file(path: str, content: str, encoding: str = "utf-8", root: Optional[Path] = None) -> str:
    """
    Append content to an existing file.
    
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
        
    target_path = _get_workspace_root(root) / path
    if not target_path.exists():
        return f"File not found: {path}"
        
    with open(target_path, "a", encoding=encoding) as f:
        f.write(content)
        
    return f"Successfully appended to {path}"

def list_directory(path: str = ".", recursive: bool = False, pattern: str = "*", root: Optional[Path] = None) -> List[str]:
    """
    List files and directories.
    
    Args:
        path: Directory path (default: ".")
        recursive: Include subdirectories (default: False)
        pattern: Glob pattern (default: "*")
        root: Optional workspace root override
        
    Returns:
        List of file paths
    """
    if not _is_safe_path(path, root):
        raise ValueError(f"Access denied: {path} is outside workspace")
        
    workspace_root = _get_workspace_root(root)
    target_path = workspace_root / path
    if not target_path.exists():
        return f"Directory not found: {path}"
        
    # Use glob to find files
    results = []
    # We need to change dir context or construct patterns carefully
    # Using glob with root_dir is only in Python 3.10+
    # Fallback: construct absolute pattern and strip root
    
    abs_pattern = str(target_path / "**" / pattern) if recursive else str(target_path / pattern)
    for p in glob.glob(abs_pattern, recursive=recursive):
        rel_path = os.path.relpath(p, workspace_root)
        # Normalize slashes
        rel_path = rel_path.replace("\\", "/")
        if rel_path != ".":
            results.append(rel_path)
            
    if not results:
        return "Directory is empty."
        
    return sorted(results)

def file_exists(path: str, root: Optional[Path] = None) -> bool:
    """
    Check if a file or directory exists.
    
    Args:
        path: Path to check
        root: Optional workspace root override
        
    Returns:
        True if exists
    """
    if not _is_safe_path(path, root):
        return False
    return (_get_workspace_root(root) / path).exists()

def delete_file(path: str, confirm: bool, root: Optional[Path] = None) -> str:
    """
    Delete a file.
    
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
        
    target_path = _get_workspace_root(root) / path
    if not target_path.exists():
        return f"File not found: {path}"
        
    if not target_path.is_file(): # Changed from is_dir() to is_file() and adjusted message
        return f"{path} is not a file. Use delete_directory (not implemented) or ensure path is a file."
        
    os.remove(target_path)
    return f"Successfully deleted {path}"
