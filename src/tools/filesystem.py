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
from .safe_wrapper import safe_tool
import platform

# Security: Restrict operations to the workspace root
# This will be overridden by passing workspace_path in tool calls
WORKSPACE_ROOT = Path(os.getcwd())
PLATFORM = f"OS - {platform.system()}, Release: {platform.release()}"

def _get_workspace_root(root: Optional[Path] = None) -> Path:
    """Get workspace root from argument or default."""
    if root:
        return root
    return WORKSPACE_ROOT

def _is_safe_path(path: str, root: Optional[Path] = None) -> bool:
    """Ensure path is within workspace."""
    workspace_root = _get_workspace_root(root)
    try:
        # Normalize the path:
        # 1. Strip leading slashes to prevent absolute path escapes
        # 2. Convert Path to handle '.', '..', etc.
        normalized_path = path.lstrip('/\\')
        
        # Resolve absolute path relative to workspace
        target = (workspace_root / normalized_path).resolve()
        
        # Check if it starts with workspace root
        workspace_str = str(workspace_root.resolve())
        target_str = str(target)
        
        return target_str.startswith(workspace_str)
    except Exception:
        return False

@safe_tool
def read_file(path: str, encoding: str = "utf-8", root: Optional[Path] = None) -> str:
    f"""
    Read the contents of a file.
    
    Args:
        path: Relative path to the file
        encoding: File encoding (default: utf-8)
        root: Optional workspace root override
    
    Returns:
        File contents as string

    NOTE:
        Platform - {PLATFORM}
    """
    if not _is_safe_path(path, root):
        raise ValueError(f"Access denied: {path} is outside workspace")
    
    # Normalize path (strip leading slashes)
    normalized_path = path.lstrip('/\\')
    target_path = _get_workspace_root(root) / normalized_path
    
    if not target_path.exists():
        return f"File not found: {path}"
    
    if target_path.is_dir():
        return f"Error: {path} is a directory, not a file. Use list_directory instead."
        
    with open(target_path, "r", encoding=encoding) as f:
        return f.read()

@safe_tool
def write_file(path: str, content: str, encoding: str = "utf-8", root: Optional[Path] = None) -> str:
    f"""
    Write content to a file. Creates parent directories automatically if needed.
    
    CRITICAL: You MUST provide BOTH 'path' AND 'content' parameters!
    
    Args:
        path: (REQUIRED) Relative path to the file (e.g., "index.html", "src/app.py", "frontend/styles.css")
        content: (REQUIRED) The actual file content to write. This CANNOT be empty!
        encoding: File encoding (default: utf-8)
        root: Optional workspace root override (internal use)
    
    Example Usage:
        write_file("index.html", "<html><body>Hello</body></html>")
        write_file("backend/app.py", "print('Hello World')")
    
    Common Errors:
        - "content: Field required" → You forgot to provide the 'content' parameter!
        - "Access denied" → Path is outside workspace (don't use absolute paths)
        
    Returns:
        Success message with byte count

    NOTE:
        Platform - {PLATFORM}
    """
    # Explicit parameter validation with helpful errors
    if not path:
        raise ValueError("ERROR: 'path' parameter is required! You must specify where to write the file.")
    
    if content is None:
        raise ValueError(
            "ERROR: 'content' parameter is required! You cannot create an empty file.\n"
            "You must provide the actual file content as a string.\n"
            "Example: write_file('index.html', '<html>...</html>')"
        )
    
    if not _is_safe_path(path, root):
        raise ValueError(f"Access denied: {path} is outside workspace")
    
    # Normalize path (strip leading slashes)
    normalized_path = path.lstrip('/\\')
    target_path = _get_workspace_root(root) / normalized_path
    
    # Create parent directories if needed
    try:
        target_path.parent.mkdir(parents=True, exist_ok=True)
    except FileExistsError:
        # This can happen if a file exists with the same name as a directory
        # We'll try to proceed, but the open() call might fail if the path is invalid
        pass
    
    with open(target_path, "w", encoding=encoding) as f:
        f.write(content)
        
    return f"Successfully wrote {len(content)} bytes to {path}"


@safe_tool
def append_file(path: str, content: str, encoding: str = "utf-8", root: Optional[Path] = None) -> str:
    f"""
    Append content to an existing file.
    
    Args:
        path: Relative path to the file
        content: Content to append
        encoding: File encoding (default: utf-8)
        root: Optional workspace root override
        
    Returns:
        Success message

    NOTE:
        Platform - {PLATFORM}
    """
    if not _is_safe_path(path, root):
        raise ValueError(f"Access denied: {path} is outside workspace")
    
    # Normalize path (strip leading slashes)
    normalized_path = path.lstrip('/\\')
    target_path = _get_workspace_root(root) / normalized_path
    if not target_path.exists():
        return f"File not found: {path}"
        
    with open(target_path, "a", encoding=encoding) as f:
        f.write(content)
        
    return f"Successfully appended to {path}"

@safe_tool
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
    
    # Normalize path (strip leading slashes)
    normalized_path = path.lstrip('/\\')
    workspace_root = _get_workspace_root(root)
    target_path = workspace_root / normalized_path
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

@safe_tool
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

@safe_tool
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
    
    # Normalize path (strip leading slashes)
    normalized_path = path.lstrip('/\\')
    target_path = _get_workspace_root(root) / normalized_path
    if not target_path.exists():
        return f"File not found: {path}"
        
    if not target_path.is_file(): # Changed from is_dir() to is_file() and adjusted message
        return f"{path} is not a file. Use delete_directory (not implemented) or ensure path is a file."
        
    os.remove(target_path)
    return f"Successfully deleted {path}"
