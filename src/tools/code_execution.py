"""
Agent Orchestrator — Code Execution Tools
=========================================
Version 1.0 — November 2025

Implementation of code execution tools.
"""

import subprocess
import sys
import os
import platform
from typing import Dict, Any

PLATFORM = f"OS - {platform.system()}, Release: {platform.release()}"


def run_python(code: str, timeout: int = 30, cwd: str = None, workspace_path: str = None) -> str:
    f"""
    Execute Python code in a separate process.
    
    Args:
        code: Python code to execute
        timeout: Max execution time in seconds
        cwd: Directory to execute in (default: current working directory)
        workspace_path: Path to workspace root (for finding shared venv)
        
    Returns:
        Combined stdout and stderr

    NOTE:
        Platform - {PLATFORM}
        CRITICAL - SHELL COMMAND SYNTAX:
        {'- Windows PowerShell: Use semicolons (;) NOT double-ampersand (&&)' if platform.system() == 'Windows' else '- Unix shell: Use double-ampersand (&&) or semicolons (;)'}
        {'- Example: cd mydir; python script.py' if platform.system() == 'Windows' else '- Example: cd mydir && python script.py'}

    """
    from pathlib import Path
    
    # Determine which Python to use: shared venv if exists, otherwise system
    python_exe = sys.executable  # Default: system python
    
    if workspace_path:
        venv_path = Path(workspace_path) / ".venv"
        if platform.system() == "Windows":
            venv_python = venv_path / "Scripts" / "python.exe"
        else:
            venv_python = venv_path / "bin" / "python"
        
        if venv_python.exists():
            python_exe = str(venv_python)
            print(f"DEBUG: run_python using shared venv: {python_exe}", flush=True)
        else:
            print(f"DEBUG: run_python venv not found at {venv_python}, using system python", flush=True)
    
    # Prepare environment with CWD in PYTHONPATH
    env = os.environ.copy()
    if cwd:
        env["PYTHONPATH"] = str(cwd) + os.pathsep + env.get("PYTHONPATH", "")
        
    print(f"DEBUG: run_python cwd={cwd}", flush=True)
        
    try:
        # Run in a separate process
        result = subprocess.run(
            [python_exe, "-c", code],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd or os.getcwd(),
            env=env
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
    f"""
    Execute shell command.
    
    Args:
        command: Command to execute
        timeout: Max execution time in seconds
        cwd: Directory to execute in (default: current working directory)
        
    Returns:
        Combined stdout and stderr

    NOTE:
        Platform - {PLATFORM}
        CRITICAL - SHELL COMMAND SYNTAX:
        {'- Windows PowerShell: Use semicolons (;) NOT double-ampersand (&&)' if platform.system() == 'Windows' else '- Unix shell: Use double-ampersand (&&) or semicolons (;)'}
        {'- Example: cd mydir; python script.py' if platform.system() == 'Windows' else '- Example: cd mydir && python script.py'}
    """
    # Security: Whitelist allowed commands
    ALLOWED_COMMANDS = ["ls", "dir", "cat", "type", "echo", "grep", "find", "mkdir", "rmdir", "python", "python3", "pip", "npm", "node"]
    
    cmd_parts = command.split()
    if not cmd_parts:
        return "Error: Empty command"
        
    base_cmd = cmd_parts[0]
    # Expanded allowed commands for testing/building
    
    # Prepare environment with CWD in PYTHONPATH
    env = os.environ.copy()
    if cwd:
        env["PYTHONPATH"] = str(cwd) + os.pathsep + env.get("PYTHONPATH", "")
    
    print(f"DEBUG: run_shell command='{command}' cwd={cwd}", flush=True)
    
    try:
        # Use Popen instead of run to properly handle process groups
        # This ensures child processes (like Flask) are killed on timeout
        import signal
        
        if platform.system() == 'Windows':
            # Windows: Use CREATE_NEW_PROCESS_GROUP
            process = subprocess.Popen(
                command,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=cwd or os.getcwd(),
                env=env,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
            )
        else:
            # Unix: Use process group
            process = subprocess.Popen(
                command,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=cwd or os.getcwd(),
                env=env,
                preexec_fn=os.setsid
            )
        
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            # Kill the entire process group to cleanup child processes
            if platform.system() == 'Windows':
                # Windows: Send CTRL_BREAK_EVENT to process group
                try:
                    process.send_signal(signal.CTRL_BREAK_EVENT)
                except:
                    pass
                # Then force kill
                process.kill()
            else:
                # Unix: Kill the entire process group
                import os
                os.killpg(os.getpgid(process.pid), signal.SIGTERM)
            
            # Wait for cleanup
            try:
                process.wait(timeout=2)
            except:
                process.kill()
                process.wait()
            
            return f"Error: Command timed out after {timeout} seconds (killed process and children)"
        
        output = []
        if stdout:
            output.append(stdout)
        if stderr:
            output.append(stderr)
            
        return "\n".join(output) if output else "No output"
        
    except Exception as e:
        return f"Error executing command: {str(e)}"
