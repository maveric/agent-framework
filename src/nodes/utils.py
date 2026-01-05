"""
Worker utility functions.
"""

import asyncio
import logging
from orchestrator_types import Task, WorkerResult, AAR

logger = logging.getLogger(__name__)


async def _detect_modified_files_via_git(worktree_path) -> list[str]:
    """
    Use git to detect actual file changes in the worktree (async).
    More reliable than parsing tool calls - catches all changes including deletions.

    Returns:
        List of modified file paths (relative to worktree root)
    """
    from pathlib import Path

    files_modified = []

    try:
        # Get list of modified, added, and deleted files using git status
        process = await asyncio.create_subprocess_exec(
            "git", "status", "--porcelain",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(worktree_path)
        )

        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=5.0)
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            logger.error("git status timed out")
            return files_modified

        stdout_str = stdout.decode("utf-8", errors="replace") if stdout else ""
        stderr_str = stderr.decode("utf-8", errors="replace") if stderr else ""

        if process.returncode == 0:
            # Parse git status output
            # Format: XY filename (or XY  filename with varying whitespace)
            # X = status in index, Y = status in worktree
            # M = modified, A = added, D = deleted, R = renamed, etc.
            for line in stdout_str.strip().split('\n'):
                if line and len(line) >= 4:  # At least "XY f" where f is a filename
                    # Use split to handle variable whitespace between status and filename
                    # The first 2 chars are status, rest is filename with possible leading space
                    status_part = line[:2]
                    # Find the filename - skip the status chars and any whitespace
                    filename = line[2:].lstrip()

                    # Skip if filename is empty or is in .git directory
                    if filename and not filename.startswith('.git/'):
                        # Handle renamed files (format: "old_name -> new_name")
                        if ' -> ' in filename:
                            filename = filename.split(' -> ')[1]

                        files_modified.append(filename)
                        logger.debug(f"[GIT-TRACKED] {status_part.strip()} {filename}")


            logger.info(f"Detected {len(files_modified)} modified file(s) via git status")
        else:
            logger.warning(f"git status failed: {stderr_str}")

    except Exception as e:
        logger.error(f"Failed to detect file changes via git: {e}")

    return files_modified


def _mock_execution(task: Task) -> WorkerResult:
    """Mock execution for testing."""
    logger.info("MOCK: Executing task...")
    return WorkerResult(
        status="complete",
        result_path="mock_output.py",
        aar=AAR(
            summary="Mock execution",
            approach="Mock",
            challenges=[],
            decisions_made=[],
            files_modified=["mock_output.py"]
        )
    )


def get_phoenix_retry_context(task: Task) -> str:
    """
    Generate Phoenix retry context section for system prompts.
    
    Returns an empty string if this is the first attempt,
    or a formatted section with the previous attempt summary.
    """
    # Check if this is a retry (retry_count > 0 means we've already tried once)
    if task.retry_count <= 0:
        return ""
    
    # Get the summary from the task
    summary = getattr(task, 'previous_attempt_summary', None)
    if not summary:
        return ""
    
    return f"""
## ⚠️ PHOENIX RETRY - LEARN FROM PREVIOUS FAILURE ⚠️

**This is retry attempt #{task.retry_count}.** Your previous attempt failed.
Read the summary below carefully to avoid repeating the same mistakes.

{summary}

---
**CRITICAL**: Use the information above to:
1. Avoid repeating failed approaches
2. Build on what worked
3. Fix the specific issues mentioned
4. Verify your work before completing

"""

