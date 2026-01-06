"""
QA Tools for strategist verification.

These are READ-ONLY tools that allow the QA agent to verify agent claims
by actually reading files from the worktree.
"""

import os
import logging
from typing import List, Optional
from pathlib import Path
from langchain_core.tools import tool

logger = logging.getLogger(__name__)


def create_qa_tools(worktree_path: str, workspace_path: str = None):
    """
    Create QA tools bound to a specific worktree path.
    
    All file operations are relative to the worktree.
    These are READ-ONLY - QA cannot modify files.
    
    Args:
        worktree_path: Path to the task's worktree
        workspace_path: Main workspace path (for running tests)
    """
    
    @tool
    def read_file(file_path: str) -> str:
        """
        Read the contents of a file from the agent's worktree.
        
        Use this to verify that a file exists and contains expected content.
        
        Args:
            file_path: Relative path to the file (e.g., 'backend/main.py')
            
        Returns:
            The file contents, or an error message if file not found.
        """
        try:
            # Handle both relative and absolute paths
            if Path(file_path).is_absolute():
                full_path = Path(file_path)
            else:
                full_path = Path(worktree_path) / file_path
            
            if not full_path.exists():
                # Try searching for the file by name
                filename = Path(file_path).name
                for root, dirs, files in os.walk(worktree_path):
                    if filename in files:
                        full_path = Path(root) / filename
                        break
                else:
                    return f"ERROR: File not found at {file_path} (searched worktree: {worktree_path})"
            
            if not full_path.is_file():
                return f"ERROR: {file_path} is not a file"
            
            content = full_path.read_text(encoding="utf-8", errors="ignore")
            
            # Truncate very long files
            if len(content) > 5000:
                return content[:5000] + f"\n\n... (truncated, {len(content)} total chars)"
            
            logger.info(f"  [QA Tool] read_file: {full_path}")
            return content
            
        except Exception as e:
            return f"ERROR reading file: {e}"
    
    @tool
    def file_exists(file_path: str) -> str:
        """
        Check if a file exists in the agent's worktree.
        
        Args:
            file_path: Relative path to check
            
        Returns:
            "true" if file exists, "false" otherwise, with the full path.
        """
        try:
            if Path(file_path).is_absolute():
                full_path = Path(file_path)
            else:
                full_path = Path(worktree_path) / file_path
            
            exists = full_path.exists()
            
            if not exists:
                # Try searching by filename
                filename = Path(file_path).name
                for root, dirs, files in os.walk(worktree_path):
                    if filename in files:
                        found_path = Path(root) / filename
                        logger.info(f"  [QA Tool] file_exists: {file_path} -> found at {found_path}")
                        return f"true (found at {found_path})"
            
            logger.info(f"  [QA Tool] file_exists: {full_path} = {exists}")
            return f"{'true' if exists else 'false'} (path: {full_path})"
            
        except Exception as e:
            return f"ERROR checking file: {e}"
    
    @tool
    def list_directory(dir_path: str = ".") -> str:
        """
        List contents of a directory in the agent's worktree.
        
        Args:
            dir_path: Relative path to directory (default: root)
            
        Returns:
            List of files and directories.
        """
        try:
            if Path(dir_path).is_absolute():
                full_path = Path(dir_path)
            else:
                full_path = Path(worktree_path) / dir_path
            
            if not full_path.exists():
                return f"ERROR: Directory not found: {dir_path}"
            
            if not full_path.is_dir():
                return f"ERROR: {dir_path} is not a directory"
            
            items = []
            for item in sorted(full_path.iterdir()):
                if item.name.startswith('.'):
                    continue  # Skip hidden files
                if item.is_dir():
                    items.append(f"[DIR] {item.name}/")
                else:
                    size = item.stat().st_size
                    items.append(f"[FILE] {item.name} ({size} bytes)")
            
            logger.info(f"  [QA Tool] list_directory: {full_path} ({len(items)} items)")
            return "\n".join(items) if items else "(empty directory)"
            
        except Exception as e:
            return f"ERROR listing directory: {e}"
    
    @tool
    def run_tests(test_command: str) -> str:
        """
        Run tests and return the output.
        
        Use this to verify that tests pass.
        
        Args:
            test_command: The test command to run (e.g., "python -m pytest backend/tests/ -v")
            
        Returns:
            Test output with pass/fail results.
        """
        import subprocess
        
        try:
            # Run from worktree path
            result = subprocess.run(
                test_command,
                shell=True,
                cwd=worktree_path,
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='replace',  # Handle non-UTF8 chars gracefully
                timeout=120  # 2 minute timeout
            )
            
            output = result.stdout + result.stderr
            
            # Truncate very long output
            if len(output) > 5000:
                output = output[:5000] + f"\n\n... (truncated, {len(output)} total chars)"
            
            logger.info(f"  [QA Tool] run_tests: exit code {result.returncode}")
            return f"Exit code: {result.returncode}\n\n{output}"
            
        except subprocess.TimeoutExpired:
            return "ERROR: Test command timed out after 120 seconds"
        except Exception as e:
            return f"ERROR running tests: {e}"
    
    return [read_file, file_exists, list_directory, run_tests]
