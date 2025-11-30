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
WORKSPACE_ROOT = Path(os.getcwd())

def _is_safe_path(path: str) -> bool:
    """Ensure path is within workspace."""
    try:
        # Resolve absolute path
        target = (WORKSPACE_ROOT / path).resolve()
        # Check if it starts with workspace root
        return str(target).startswith(str(WORKSPACE_ROOT))
    except Exception:
        return False

def read_file(path: str, encoding: str = "utf-8") -> str:
    """
    Read the contents of a file.
    
    Args:
        path: Relative path to the file
        encoding: File encoding (default: utf-8)
    
    Returns:
        File contents as string
    """
    if not _is_safe_path(path):
        raise ValueError(f"Access denied: {path} is outside workspace")
    
    target_path = WORKSPACE_ROOT / path
    if not target_path.exists():
        raise FileNotFoundError(f"File not found: {path}")
        
    with open(target_path, "r", encoding=encoding) as f:
        return f.read()

def write_file(path: str, content: str, encoding: str = "utf-8") -> str:
    """
    Write content to a file. Creates or overwrites.
    
    Args:
        path: Relative path to the file
        content: Content to write
        encoding: File encoding (default: utf-8)
        
    Returns:
        Success message
    """
    if not _is_safe_path(path):
        raise ValueError(f"Access denied: {path} is outside workspace")
        
    target_path = WORKSPACE_ROOT / path
    
    # Create parent directories if needed
    target_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(target_path, "w", encoding=encoding) as f:
        f.write(content)
        
    return f"Successfully wrote {len(content)} bytes to {path}"

def append_file(path: str, content: str, encoding: str = "utf-8") -> str:
    """
    Append content to an existing file.
    
    Args:
        path: Relative path to the file
        content: Content to append
        encoding: File encoding (default: utf-8)
        
    Returns:
        Success message
    """
    if not _is_safe_path(path):
        raise ValueError(f"Access denied: {path} is outside workspace")
        
    target_path = WORKSPACE_ROOT / path
    if not target_path.exists():
        raise FileNotFoundError(f"File not found: {path}")
        
    with open(target_path, "a", encoding=encoding) as f:
        f.write(content)
        
    return f"Successfully appended to {path}"

def list_directory(path: str = ".", recursive: bool = False, pattern: str = "*") -> List[str]:
    """
    List files and directories.
    
    Args:
        path: Directory path (default: ".")
        recursive: Include subdirectories (default: False)
        pattern: Glob pattern (default: "*")
        
    Returns:
        List of file paths
    """
    if not _is_safe_path(path):
        raise ValueError(f"Access denied: {path} is outside workspace")
        
    target_path = WORKSPACE_ROOT / path
    if not target_path.exists():
        raise FileNotFoundError(f"Directory not found: {path}")
        
    search_pattern = f"{path}/**/{pattern}" if recursive else f"{path}/{pattern}"
    
    # Use glob to find files
    # Note: glob.glob returns absolute paths or relative depending on input
    # We want relative paths from workspace root
    
    # Change dir context temporarily or use relative logic
    # Simpler: use glob with root_dir in python 3.10+, but for compatibility:
    
    results = []
    for p in glob.glob(str(target_path / pattern) if not recursive else str(target_path / "**" / pattern), recursive=recursive):
        rel_path = os.path.relpath(p, WORKSPACE_ROOT)
        # Normalize slashes
        rel_path = rel_path.replace("\\", "/")
        if rel_path != ".":
            results.append(rel_path)
            
    return sorted(results)

def file_exists(path: str) -> bool:
    """
    Check if a file or directory exists.
    
    Args:
        path: Path to check
        
    Returns:
        True if exists
    """
    if not _is_safe_path(path):
        return False
    return (WORKSPACE_ROOT / path).exists()

def delete_file(path: str, confirm: bool) -> str:
    """
    Delete a file.
    
    Args:
        path: Path to delete
        confirm: Must be True
        
    Returns:
        Success message
    """
    if not confirm:
        raise ValueError("Deletion requires confirmation=True")
        
    if not _is_safe_path(path):
        raise ValueError(f"Access denied: {path} is outside workspace")
        
    target_path = WORKSPACE_ROOT / path
    if not target_path.exists():
        raise FileNotFoundError(f"File not found: {path}")
        
    if target_path.is_dir():
        raise ValueError(f"{path} is a directory. Use delete_directory (not implemented) or ensure path is a file.")
        
    os.remove(target_path)
    return f"Successfully deleted {path}"
