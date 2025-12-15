"""
Agent Orchestrator — Async Utilities
=====================================
Version 1.0 — December 2025

Async subprocess and I/O utilities for the orchestrator.
These utilities provide non-blocking alternatives to subprocess.run and file I/O.
"""

import asyncio
import sys
import platform
from typing import Optional, List, Tuple
from pathlib import Path


async def run_subprocess(
    cmd: List[str],
    cwd: Optional[str] = None,
    timeout: int = 30,
    capture_output: bool = True,
    check: bool = False
) -> Tuple[int, str, str]:
    """
    Async replacement for subprocess.run with command list.
    
    Args:
        cmd: Command as list of strings (e.g., ["git", "status"])
        cwd: Working directory
        timeout: Timeout in seconds
        capture_output: Whether to capture stdout/stderr
        check: If True, raise exception on non-zero exit code
        
    Returns:
        Tuple of (return_code, stdout, stderr)
        
    Raises:
        asyncio.TimeoutError: If command times out
        subprocess.CalledProcessError: If check=True and command fails
    """
    try:
        # Windows-specific: Use CREATE_NEW_PROCESS_GROUP to isolate subprocess
        kwargs = {
            'stdout': asyncio.subprocess.PIPE if capture_output else None,
            'stderr': asyncio.subprocess.PIPE if capture_output else None,
            'cwd': cwd
        }
        if platform.system() == 'Windows':
            import subprocess
            kwargs['creationflags'] = subprocess.CREATE_NEW_PROCESS_GROUP

        process = await asyncio.create_subprocess_exec(*cmd, **kwargs)

        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                process.communicate(),
                timeout=timeout
            )
        except asyncio.TimeoutError:
            # Safe kill on timeout
            if platform.system() == 'Windows':
                import subprocess as sp
                try:
                    sp.run(['taskkill', '/F', '/T', '/PID', str(process.pid)],
                           capture_output=True, timeout=5)
                except Exception:
                    pass
            process.kill()
            await process.wait()
            raise asyncio.TimeoutError(f"Command timed out after {timeout}s: {' '.join(cmd)}")
        
        stdout = stdout_bytes.decode("utf-8", errors="replace") if stdout_bytes else ""
        stderr = stderr_bytes.decode("utf-8", errors="replace") if stderr_bytes else ""
        
        if check and process.returncode != 0:
            import subprocess
            raise subprocess.CalledProcessError(
                process.returncode, cmd, stdout, stderr
            )
        
        return process.returncode, stdout, stderr
        
    except FileNotFoundError:
        raise FileNotFoundError(f"Command not found: {cmd[0]}")


async def run_shell_async(
    command: str,
    cwd: Optional[str] = None,
    timeout: int = 30,
    capture_output: bool = True,
    check: bool = False
) -> Tuple[int, str, str]:
    """
    Async shell command execution.
    
    Args:
        command: Shell command string
        cwd: Working directory
        timeout: Timeout in seconds
        capture_output: Whether to capture stdout/stderr
        check: If True, raise exception on non-zero exit code
        
    Returns:
        Tuple of (return_code, stdout, stderr)
    """
    try:
        # Windows-specific: Use CREATE_NEW_PROCESS_GROUP to isolate subprocess
        kwargs = {
            'stdout': asyncio.subprocess.PIPE if capture_output else None,
            'stderr': asyncio.subprocess.PIPE if capture_output else None,
            'cwd': cwd
        }
        if platform.system() == 'Windows':
            import subprocess
            kwargs['creationflags'] = subprocess.CREATE_NEW_PROCESS_GROUP

        process = await asyncio.create_subprocess_shell(command, **kwargs)

        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                process.communicate(),
                timeout=timeout
            )
        except asyncio.TimeoutError:
            # Safe kill on timeout
            if platform.system() == 'Windows':
                import subprocess as sp
                try:
                    sp.run(['taskkill', '/F', '/T', '/PID', str(process.pid)],
                           capture_output=True, timeout=5)
                except Exception:
                    pass
            process.kill()
            await process.wait()
            raise asyncio.TimeoutError(f"Command timed out after {timeout}s: {command}")
        
        stdout = stdout_bytes.decode("utf-8", errors="replace") if stdout_bytes else ""
        stderr = stderr_bytes.decode("utf-8", errors="replace") if stderr_bytes else ""
        
        if check and process.returncode != 0:
            import subprocess
            raise subprocess.CalledProcessError(
                process.returncode, command, stdout, stderr
            )
        
        return process.returncode, stdout, stderr
        
    except Exception as e:
        if isinstance(e, asyncio.TimeoutError):
            raise
        raise RuntimeError(f"Shell command failed: {e}")


async def run_python_async(
    code: str,
    timeout: int = 30,
    cwd: Optional[str] = None
) -> Tuple[int, str, str]:
    """
    Execute Python code asynchronously in a subprocess.
    
    Args:
        code: Python code to execute
        timeout: Timeout in seconds
        cwd: Working directory
        
    Returns:
        Tuple of (return_code, stdout, stderr)
    """
    return await run_subprocess(
        [sys.executable, "-c", code],
        cwd=cwd,
        timeout=timeout
    )


# ========================================
# Async file operations using aiofiles
# ========================================

async def read_file_async(path: str, encoding: str = "utf-8") -> str:
    """
    Read file contents asynchronously.
    
    Args:
        path: Path to file
        encoding: File encoding
        
    Returns:
        File contents as string
    """
    try:
        import aiofiles
    except ImportError:
        # Fallback to sync if aiofiles not installed
        return await asyncio.to_thread(_read_file_sync, path, encoding)
    
    async with aiofiles.open(path, mode='r', encoding=encoding) as f:
        return await f.read()


async def write_file_async(path: str, content: str, encoding: str = "utf-8") -> int:
    """
    Write content to file asynchronously.
    
    Args:
        path: Path to file
        content: Content to write
        encoding: File encoding
        
    Returns:
        Number of bytes written
    """
    try:
        import aiofiles
    except ImportError:
        # Fallback to sync if aiofiles not installed
        return await asyncio.to_thread(_write_file_sync, path, content, encoding)
    
    # Ensure parent directories exist
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    
    async with aiofiles.open(path, mode='w', encoding=encoding) as f:
        await f.write(content)
        return len(content.encode(encoding))


async def file_exists_async(path: str) -> bool:
    """Check if file exists asynchronously."""
    return await asyncio.to_thread(Path(path).exists)


async def list_directory_async(path: str) -> List[str]:
    """List directory contents asynchronously."""
    def _list_dir():
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"Directory not found: {path}")
        return [str(f) for f in p.iterdir()]
    
    return await asyncio.to_thread(_list_dir)


# ========================================
# Sync fallbacks (used when aiofiles not available)
# ========================================

def _read_file_sync(path: str, encoding: str = "utf-8") -> str:
    with open(path, 'r', encoding=encoding) as f:
        return f.read()


def _write_file_sync(path: str, content: str, encoding: str = "utf-8") -> int:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'w', encoding=encoding) as f:
        f.write(content)
        return len(content.encode(encoding))
