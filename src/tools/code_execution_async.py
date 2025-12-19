"""
Agent Orchestrator — Async Code Execution Tools
================================================
Version 2.0 — December 2025

Async implementation of code execution tools.
"""

import asyncio
import sys
import os
import platform
from typing import Tuple

PLATFORM = f"OS - {platform.system()}, Release: {platform.release()}"


async def run_python_async(code: str, timeout: int = 30, cwd: str = None, workspace_path: str = None) -> str:
    f"""
    Execute Python code asynchronously in a subprocess.
    
    Args:
        code: Python code to execute
        timeout: Max execution time in seconds
        cwd: Directory to execute in (default: current working directory)
        workspace_path: Path to workspace root (for finding shared venv)
        
    Returns:
        Combined stdout and stderr

    NOTE:
        Platform - {PLATFORM}
    """
    from pathlib import Path
    
    # Determine which Python to use: shared venv if exists, otherwise system
    python_exe = sys.executable
    
    if workspace_path:
        venv_path = Path(workspace_path) / ".venv"
        if platform.system() == "Windows":
            venv_python = venv_path / "Scripts" / "python.exe"
        else:
            venv_python = venv_path / "bin" / "python"
        
        if venv_python.exists():
            python_exe = str(venv_python)
    
    env = os.environ.copy()
    if cwd:
        env["PYTHONPATH"] = str(cwd) + os.pathsep + env.get("PYTHONPATH", "")
    
    try:
        # Create process with proper process group handling
        if platform.system() == 'Windows':
            import subprocess
            process = await asyncio.create_subprocess_exec(
                python_exe, "-c", code,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd or os.getcwd(),
                env=env,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
            )
        else:
            process = await asyncio.create_subprocess_exec(
                python_exe, "-c", code,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd or os.getcwd(),
                env=env,
                preexec_fn=os.setsid
            )
        
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=timeout
            )
        except asyncio.TimeoutError:
            # Kill the subprocess tree safely
            if platform.system() == 'Windows':
                # CRITICAL: Do NOT use CTRL_BREAK_EVENT - it kills the parent console too!
                # Use taskkill /T to kill process tree, or just process.kill()
                import subprocess as sp
                try:
                    # taskkill /T kills the process AND its children
                    # /F = force, /T = tree (children), /PID = process ID
                    sp.run(['taskkill', '/F', '/T', '/PID', str(process.pid)], 
                           capture_output=True, timeout=5)
                except Exception:
                    pass
                try:
                    process.kill()
                except (ProcessLookupError, OSError):
                    pass
            else:
                import signal
                try:
                    os.killpg(os.getpgid(process.pid), signal.SIGTERM)
                except (ProcessLookupError, OSError, PermissionError):
                    # Process group may not exist or we don't have permission
                    try:
                        process.kill()
                    except (ProcessLookupError, OSError):
                        pass

            await process.wait()
            return f"Error: Execution timed out after {timeout} seconds (killed process and children)"
        
        output = []
        stdout_str = stdout.decode("utf-8", errors="replace") if stdout else ""
        stderr_str = stderr.decode("utf-8", errors="replace") if stderr else ""
        
        if stdout_str:
            output.append(f"STDOUT:\n{stdout_str}")
        if stderr_str:
            output.append(f"STDERR:\n{stderr_str}")
        
        if process.returncode != 0:
            output.append(f"Exit Code: {process.returncode}")
        
        return "\n".join(output) if output else "No output"
        
    except Exception as e:
        return f"Error executing code: {str(e)}"


async def run_shell_async(command: str, timeout: int = 30, cwd: str = None, workspace_path: str = None) -> str:
    f"""
    Execute shell command asynchronously.

    Args:
        command: Command to execute
        timeout: Max execution time in seconds
        cwd: Directory to execute in (default: current working directory)
        workspace_path: Path to workspace root (for finding workspace venv)

    Returns:
        Combined stdout and stderr

    NOTE:
        Platform - {PLATFORM}
        Shell: cmd.exe on Windows, /bin/sh on Unix. Both support && for command chaining.
        Python and npm are both located in the workspace venv. Do NOT use system Python or npm.
    """
    from pathlib import Path

    env = os.environ.copy()
    if cwd:
        env["PYTHONPATH"] = str(cwd) + os.pathsep + env.get("PYTHONPATH", "")

    # Prepend workspace venv to PATH so agents use workspace's npm/python, not framework's
    if workspace_path:
        venv_path = Path(workspace_path) / ".venv"
        if platform.system() == "Windows":
            venv_bin = venv_path / "Scripts"
        else:
            venv_bin = venv_path / "bin"

        if venv_bin.exists():
            env["PATH"] = str(venv_bin) + os.pathsep + env.get("PATH", "")
    
    try:
        # Create process with proper process group handling
        if platform.system() == 'Windows':
            # Windows: Use CREATE_NEW_PROCESS_GROUP
            import subprocess
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd or os.getcwd(),
                env=env,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
            )
        else:
            # Unix: Use process group
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd or os.getcwd(),
                env=env,
                preexec_fn=os.setsid
            )
        
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=timeout
            )
        except asyncio.TimeoutError:
            # Kill the subprocess tree safely
            if platform.system() == 'Windows':
                # CRITICAL: Do NOT use CTRL_BREAK_EVENT - it kills the parent console too!
                # Use taskkill /T to kill process tree, or just process.kill()
                import subprocess as sp
                try:
                    # taskkill /T kills the process AND its children
                    # /F = force, /T = tree (children), /PID = process ID
                    sp.run(['taskkill', '/F', '/T', '/PID', str(process.pid)], 
                           capture_output=True, timeout=5)
                except Exception:
                    pass
                try:
                    process.kill()
                except (ProcessLookupError, OSError):
                    pass
            else:
                # Unix: Kill process group
                import signal
                try:
                    os.killpg(os.getpgid(process.pid), signal.SIGTERM)
                except (ProcessLookupError, OSError, PermissionError):
                    # Process group may not exist or we don't have permission
                    try:
                        process.kill()
                    except (ProcessLookupError, OSError):
                        pass

            await process.wait()
            return f"Error: Command timed out after {timeout} seconds (killed process and children)"
        
        output = []
        stdout_str = stdout.decode("utf-8", errors="replace") if stdout else ""
        stderr_str = stderr.decode("utf-8", errors="replace") if stderr else ""
        
        if stdout_str:
            output.append(stdout_str)
        if stderr_str:
            output.append(stderr_str)
        
        return "\n".join(output) if output else "No output"
        
    except Exception as e:
        return f"Error executing command: {str(e)}"
