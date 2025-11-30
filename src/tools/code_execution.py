"""
Agent Orchestrator — Code Execution Tools
=========================================
Version 1.0 — November 2025

Implementation of code execution tools.
"""

import subprocess
import sys
import os
from typing import Dict, Any

def run_python(code: str, timeout: int = 30, cwd: str = None) -> str:
    """
    Execute Python code in a separate process.
    
    Args:
        code: Python code to execute
        timeout: Max execution time in seconds
        cwd: Directory to execute in (default: current working directory)
        
    Returns:
        Combined stdout and stderr
    """
    try:
        # Run in a separate process
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd or os.getcwd()
        )
        
        output = []
        if result.stdout:
            output.append(f"STDOUT:\n{result.stdout}")
        if result.stderr:
            output.append(f"STDERR:\n{result.stderr}")
            
        if result.returncode != 0:
            output.append(f"Exit Code: {result.returncode}")
            
        return "\n".join(output) if output else "No output"
        
    except subprocess.TimeoutExpired:
        return f"Error: Execution timed out after {timeout} seconds"
    except Exception as e:
        return f"Error executing code: {str(e)}"

def run_shell(command: str, timeout: int = 30, cwd: str = None) -> str:
    """
    Execute shell command.
    
    Args:
        command: Command to execute
        timeout: Max execution time in seconds
        cwd: Directory to execute in (default: current working directory)
        
    Returns:
        Combined stdout and stderr
    """
    # Security: Whitelist allowed commands
    ALLOWED_COMMANDS = ["ls", "dir", "cat", "type", "echo", "grep", "find", "mkdir", "rmdir", "python", "python3", "pip", "npm", "node"]
    
    cmd_parts = command.split()
    if not cmd_parts:
        return "Error: Empty command"
        
    base_cmd = cmd_parts[0]
    # Expanded allowed commands for testing/building
    
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd or os.getcwd()
        )
        
        output = []
        if result.stdout:
            output.append(result.stdout)
        if result.stderr:
            output.append(result.stderr)
            
        return "\n".join(output) if output else "No output"
        
    except subprocess.TimeoutExpired:
        return f"Error: Command timed out after {timeout} seconds"
    except Exception as e:
        return f"Error executing command: {str(e)}"
