"""
Worker utility functions.
"""

from orchestrator_types import Task, WorkerResult, AAR


def _detect_modified_files_via_git(worktree_path) -> list[str]:
    """
    Use git to detect actual file changes in the worktree.
    More reliable than parsing tool calls - catches all changes including deletions.

    Returns:
        List of modified file paths (relative to worktree root)
    """
    import subprocess
    from pathlib import Path

    files_modified = []

    try:
        # Get list of modified, added, and deleted files using git status
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=worktree_path,
            capture_output=True,
            text=True,
            timeout=5
        )

        if result.returncode == 0:
            # Parse git status output
            # Format: XY filename (or XY  filename with varying whitespace)
            # X = status in index, Y = status in worktree
            # M = modified, A = added, D = deleted, R = renamed, etc.
            for line in result.stdout.strip().split('\n'):
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
                        print(f"  [GIT-TRACKED] {status_part.strip()} {filename}", flush=True)


            print(f"  [GIT] Detected {len(files_modified)} modified file(s) via git status", flush=True)
        else:
            print(f"  [GIT-WARNING] git status failed: {result.stderr}", flush=True)

    except Exception as e:
        print(f"  [GIT-ERROR] Failed to detect file changes via git: {e}", flush=True)

    return files_modified


def _mock_execution(task: Task) -> WorkerResult:
    """Mock execution for testing."""
    print("  MOCK: Executing task...", flush=True)
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
