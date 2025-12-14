"""
Agent Orchestrator — Async Git Worktree Manager
================================================
Version 2.0 — December 2025

Async version of git worktree manager using asyncio subprocess.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


# Type definitions
class WorktreeStatus(str, Enum):
    """Status of a git worktree."""
    CREATING = "creating"
    ACTIVE = "active"
    COMPLETE = "complete"
    MERGED = "merged"
    FAILED = "failed"
    DELETED = "deleted"


@dataclass
class WorktreeInfo:
    """Tracking information for a worktree."""
    task_id: str
    branch_name: str
    worktree_path: Path
    status: WorktreeStatus
    created_at: datetime = field(default_factory=datetime.now)
    merged_at: Optional[datetime] = None
    deleted_at: Optional[datetime] = None

    # For Phoenix retries
    retry_number: int = 0
    previous_branch: Optional[str] = None

    # Commit tracking
    commits: List[str] = field(default_factory=list)
    files_modified: List[str] = field(default_factory=list)


@dataclass
class MergeResult:
    """Result of attempting to merge a task branch to main."""
    success: bool
    task_id: str
    conflict: bool = False
    conflicting_files: List[str] = field(default_factory=list)
    error_message: str = ""
    llm_resolved: bool = False  # True if LLM resolved the conflict


@dataclass
class AsyncWorktreeManager:
    """
    Async version of WorktreeManager for non-blocking git operations.

    Each task gets its own worktree branching from main.
    Workers commit to their task branch, then merge on QA approval.
    """
    repo_path: Path
    worktree_base: Path
    main_branch: str = "main"
    worktrees: Dict[str, WorktreeInfo] = field(default_factory=dict)

    # Merge lock to prevent concurrent merge race conditions (Strategy 1A)
    _merge_lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)
    
    def _task_branch_name(self, task_id: str) -> str:
        """Generate branch name for a task."""
        return f"task/{task_id}"
    
    def _retry_branch_name(self, task_id: str, retry_num: int) -> str:
        """Generate branch name for a Phoenix retry."""
        return f"task/{task_id}/retry-{retry_num}"
    
    def _worktree_path(self, task_id: str, retry_num: int = 0) -> Path:
        """Generate worktree directory path."""
        safe_id = task_id.replace("/", "_").replace("\\", "_")
        if retry_num > 0:
            return self.worktree_base / f"{safe_id}_retry_{retry_num}"
        return self.worktree_base / safe_id
    
    async def _run_git(
        self,
        args: List[str],
        cwd: Path = None,
        check: bool = True,
        timeout: float = 60.0
    ) -> tuple[int, str, str]:
        """Run a git command asynchronously with timeout.

        Args:
            args: Git command arguments
            cwd: Working directory
            check: Raise exception on non-zero return
            timeout: Max seconds to wait (default 60s, prevents hangs)
        """
        cmd = ["git"] + args
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(cwd or self.repo_path)
        )

        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=timeout
            )
        except asyncio.TimeoutError:
            # Kill the hung process
            logger.error(f"⏰ Git command timed out after {timeout}s: git {' '.join(args)}")
            try:
                process.kill()
                await process.wait()
            except Exception:
                pass
            raise RuntimeError(f"Git command timed out after {timeout}s: git {' '.join(args)}")

        stdout_str = stdout.decode("utf-8", errors="replace") if stdout else ""
        stderr_str = stderr.decode("utf-8", errors="replace") if stderr else ""

        if check and process.returncode != 0:
            raise RuntimeError(f"Git command failed: {' '.join(cmd)}\n{stderr_str}")

        return process.returncode, stdout_str, stderr_str

    async def _ensure_clean_git_state(self, worktree_path: Path) -> None:
        """
        Ensure git is in a clean state before operations.
        Aborts any abandoned rebase or merge operations.

        Args:
            worktree_path: Path to the worktree to check
        """
        # Check for abandoned rebase
        rebase_dir = worktree_path / ".git" / "rebase-merge"
        rebase_apply_dir = worktree_path / ".git" / "rebase-apply"

        if rebase_dir.exists() or rebase_apply_dir.exists():
            logger.warning(f"  🧹 Cleaning abandoned rebase in {worktree_path.name}")
            await self._run_git(["rebase", "--abort"], cwd=worktree_path, check=False)

        # Check for abandoned merge
        merge_head = worktree_path / ".git" / "MERGE_HEAD"

        if merge_head.exists():
            logger.warning(f"  🧹 Cleaning abandoned merge in {worktree_path.name}")
            await self._run_git(["merge", "--abort"], cwd=worktree_path, check=False)

    async def rebase_on_main(self, task_id: str) -> MergeResult:
        """
        Rebase a task's worktree on main before merging.

        This handles concurrent edits by replaying task changes on top of latest main.
        Fails fast on conflicts - Phoenix will retry with fresh state.

        Args:
            task_id: Task whose worktree to rebase

        Returns:
            MergeResult indicating success or conflict
        """
        info = self.worktrees.get(task_id)
        if not info:
            return MergeResult(
                success=False,
                task_id=task_id,
                error_message=f"No worktree for task: {task_id}"
            )

        wt_path = info.worktree_path

        # Clean any dirty git state first
        await self._ensure_clean_git_state(wt_path)

        # Fetch latest main into the worktree
        logger.info(f"  📥 Fetching latest {self.main_branch} for rebase...")
        await self._run_git(
            ["fetch", ".", f"{self.main_branch}:{self.main_branch}"],
            cwd=wt_path,
            check=False
        )

        # Rebase task branch onto main
        logger.info(f"  🔄 Rebasing {info.branch_name} onto {self.main_branch}...")
        returncode, stdout, stderr = await self._run_git(
            ["rebase", self.main_branch],
            cwd=wt_path,
            check=False
        )

        if returncode != 0:
            # Rebase failed - likely conflicts
            # Abort the rebase to leave worktree in clean state
            logger.error(f"  ❌ Rebase failed for {task_id} - conflicts detected")
            await self._run_git(["rebase", "--abort"], cwd=wt_path, check=False)

            # Parse conflicts if possible
            conflict_files = []
            if "CONFLICT" in stdout or "CONFLICT" in stderr:
                import re
                conflict_pattern = r"CONFLICT.*?:\s+(?:Merge conflict in|add/add):\s+(.+)"
                conflicts = re.findall(conflict_pattern, stdout + stderr)
                conflict_files = list(set(conflicts))

            error_msg = f"Rebase conflicts detected. Files: {', '.join(conflict_files) if conflict_files else 'unknown'}\n{stdout}\n{stderr}"

            return MergeResult(
                success=False,
                task_id=task_id,
                conflict=True,
                conflicting_files=conflict_files,
                error_message=error_msg
            )

        logger.info(f"  ✅ Rebase successful - {task_id} synced with {self.main_branch}")
        return MergeResult(success=True, task_id=task_id)

    async def create_worktree(
        self,
        task_id: str,
        retry_number: int = 0,
        previous_branch: Optional[str] = None
    ) -> WorktreeInfo:
        """
        Create a new worktree for a task asynchronously.
        
        Args:
            task_id: Task identifier
            retry_number: Phoenix retry number (0 for first attempt)
            previous_branch: For retries, the failed branch reference
            
        Returns:
            WorktreeInfo with paths and branch
        """
        if retry_number == 0:
            branch_name = self._task_branch_name(task_id)
        else:
            branch_name = self._retry_branch_name(task_id, retry_number)
        
        wt_path = self._worktree_path(task_id, retry_number)
        
        # Check if worktree already exists and is valid
        if wt_path.exists() and (wt_path / ".git").exists():
            # Sync with main
            try:
                await self._run_git(
                    ["merge", self.main_branch, "-m", f"Sync {self.main_branch} into {branch_name}"],
                    cwd=wt_path,
                    check=False
                )
            except Exception as e:
                logger.warning(f"Failed to sync worktree with main: {e}")

            # CRITICAL: Track existing worktree (bug fix - was missing!)
            info = WorktreeInfo(
                task_id=task_id,
                branch_name=branch_name,
                worktree_path=wt_path,
                status=WorktreeStatus.ACTIVE,
                retry_number=retry_number,
                previous_branch=previous_branch
            )
            self.worktrees[task_id] = info
            return info
        
        # Cleanup existing directory if it exists but isn't a valid worktree
        if wt_path.exists():
            import shutil
            await asyncio.to_thread(shutil.rmtree, wt_path, ignore_errors=True)
        
        # Create worktree directory
        wt_path.mkdir(parents=True, exist_ok=True)
        
        # Git operations
        try:
            # CRITICAL: Delete old branch if exists (for retries)
            # This ensures retries start fresh from current main, not old conflicting state
            await self._run_git(
                ["branch", "-D", branch_name],
                check=False  # Ignore if doesn't exist
            )
            
            # Create branch from main (fresh, with latest main code)
            await self._run_git(
                ["branch", branch_name, self.main_branch],
                check=False
            )
            
            # Create worktree with --force
            await self._run_git(
                ["worktree", "add", "--force", str(wt_path), branch_name]
            )
        except Exception as e:
            # Cleanup on failure
            if wt_path.exists():
                import shutil
                await asyncio.to_thread(shutil.rmtree, wt_path, ignore_errors=True)
            raise RuntimeError(f"Failed to create worktree: {e}")
        
        # Track it
        info = WorktreeInfo(
            task_id=task_id,
            branch_name=branch_name,
            worktree_path=wt_path,
            status=WorktreeStatus.ACTIVE,
            retry_number=retry_number,
            previous_branch=previous_branch
        )
        self.worktrees[task_id] = info
        
        return info
    
    async def commit_changes(
        self,
        task_id: str,
        message: str,
        files: Optional[List[str]] = None
    ) -> str:
        """
        Commit changes in a task's worktree asynchronously.
        
        Args:
            task_id: Task whose worktree to commit in
            message: Commit message
            files: Specific files to commit (None = all changes)
            
        Returns:
            Commit hash or empty string if no changes
        """
        info = self.worktrees.get(task_id)
        if not info:
            raise ValueError(f"No worktree for task: {task_id}")
        
        wt_path = info.worktree_path
        
        import logging
        logger = logging.getLogger(__name__)
        
        # Stage files first
        if files:
            for f in files:
                await self._run_git(["add", f], cwd=wt_path)
        else:
            await self._run_git(["add", "-A"], cwd=wt_path)
        
        # Check if there are changes to commit
        returncode, _, _ = await self._run_git(
            ["diff", "--cached", "--quiet"],
            cwd=wt_path,
            check=False
        )
        
        if returncode == 0:
            return ""  # No changes

        # Commit directly to task branch
        # Rebase will happen later in strategist before merge (after QA passes)
        await self._run_git(["commit", "-m", message], cwd=wt_path)
        
        # Get commit hash
        _, stdout, _ = await self._run_git(["rev-parse", "HEAD"], cwd=wt_path)
        commit_hash = stdout.strip()
        
        # Track it
        info.commits.append(commit_hash)
        
        return commit_hash
    
    async def commit_to_main(
        self,
        message: str,
        files: List[str]
    ) -> str:
        """
        Commit files directly to the main branch (workspace root) asynchronously.
        """
        # Ensure we are on main
        await self._run_git(["checkout", self.main_branch])
        
        # Add files
        for f in files:
            await self._run_git(["add", f])
        
        # Commit
        returncode, _, _ = await self._run_git(
            ["commit", "-m", message],
            check=False
        )
        
        if returncode == 0:
            _, stdout, _ = await self._run_git(["rev-parse", "HEAD"])
            return stdout.strip()
        
        return ""
    
    async def merge_to_main(self, task_id: str) -> MergeResult:
        """
        Merge a task's branch to main asynchronously.

        Uses an asyncio lock to ensure only one merge happens at a time,
        preventing race conditions and data loss (Git Strategy 1A).

        Returns:
            MergeResult indicating success or conflict
        """
        # CRITICAL: Acquire merge lock to prevent concurrent merges
        async with self._merge_lock:
            import logging
            logger = logging.getLogger(__name__)
            logger.info(f"🔒 Acquired merge lock for task {task_id}")

            info = self.worktrees.get(task_id)
            if not info:
                raise ValueError(f"No worktree for task: {task_id}")
        
            # Check for uncommitted changes in the worktree
            # Only care about modified/staged files, NOT untracked (??) files
            _, stdout, _ = await self._run_git(
                ["status", "--porcelain"],
                cwd=info.worktree_path,
                check=False
            )
        
            # Filter out untracked files (lines starting with "??")
            if stdout.strip():
                changes = [line for line in stdout.strip().split('\n') 
                          if line and not line.startswith('??')]
                if changes:
                    error_msg = f"Uncommitted changes in worktree:\n" + '\n'.join(changes)
                    logger.error(f"❌ MERGE BLOCKED: {error_msg}")
                    return MergeResult(
                        success=False,
                        task_id=task_id,
                        conflict=False,
                        error_message=error_msg
                    )
        
            # Switch to main
            await self._run_git(["checkout", self.main_branch])
        
            # Check for uncommitted changes in main repo
            # Only care about modified/staged files, NOT untracked (??) files
            _, stdout, _ = await self._run_git(
                ["status", "--porcelain"],
                check=False
            )
        
            # Filter out untracked files (lines starting with "??")
            # Untracked files don't cause merge conflicts
            if stdout.strip():
                changes = [line for line in stdout.strip().split('\n') 
                          if line and not line.startswith('??')]
                if changes:
                    error_msg = f"Uncommitted changes in main repo:\n" + '\n'.join(changes)
                    logger.error(f"❌ MERGE BLOCKED: {error_msg}")
                    return MergeResult(
                        success=False,
                        task_id=task_id,
                        conflict=False,
                        error_message=error_msg
                    )
        
            # Attempt merge
            returncode, stdout, stderr = await self._run_git(
                ["merge", info.branch_name, "--no-ff", "-m",
                 f"Merge {info.branch_name} (task {task_id})"],
                check=False
            )
        
            if returncode == 0:
                info.status = WorktreeStatus.MERGED
                info.merged_at = datetime.now()
                return MergeResult(success=True, task_id=task_id)
            else:
                # Merge failed - capture full error info
                error_details = f"stdout: {stdout}\nstderr: {stderr}" if stdout or stderr else "No error output captured"
                logger.error(f"❌ MERGE FAILED for {task_id}: return={returncode}, {error_details}")
                
                # Abort merge if in progress
                await self._run_git(["merge", "--abort"], check=False)
            
                return MergeResult(
                    success=False,
                    task_id=task_id,
                    conflict=True,
                    error_message=f"return={returncode}: {error_details}"
                )
    
    async def cleanup_worktree(self, task_id: str) -> None:
        """Remove a worktree (but keep branch) asynchronously."""
        info = self.worktrees.get(task_id)
        if not info:
            return
        
        await self._run_git(
            ["worktree", "remove", str(info.worktree_path), "--force"],
            check=False
        )
        
        info.status = WorktreeStatus.DELETED
        info.deleted_at = datetime.now()


async def initialize_git_repo_async(repo_path: Path) -> None:
    """Initialize a git repository if it doesn't exist asynchronously."""
    git_dir = repo_path / ".git"

    async def run_git(args: List[str], check: bool = True, timeout: float = 60.0):
        process = await asyncio.create_subprocess_exec(
            "git", *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(repo_path)
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=timeout
            )
        except asyncio.TimeoutError:
            logger.error(f"⏰ Git init command timed out: git {' '.join(args)}")
            try:
                process.kill()
                await process.wait()
            except Exception:
                pass
            raise RuntimeError(f"Git init command timed out: git {' '.join(args)}")

        if check and process.returncode != 0:
            raise RuntimeError(f"Git command failed: git {' '.join(args)}")
        return stdout.decode("utf-8", errors="replace")
    
    if not git_dir.exists():
        await run_git(["init"])
        await run_git(["config", "user.name", "Agent Orchestrator"])
        await run_git(["config", "user.email", "orchestrator@agent.local"])
        
        # Create default .gitignore
        gitignore_path = repo_path / ".gitignore"
        gitignore_content = """# Agent Framework Logs (worktrees and llm_logs now stored externally)
logs/

# Git
.git/

# Python
__pycache__/
*.py[cod]
*.pyc
.venv/
venv/

# OS
.DS_Store
Thumbs.db
"""
        gitignore_path.write_text(gitignore_content, encoding="utf-8")
        
        await run_git(["add", ".gitignore"])
        await run_git(["commit", "-m", "Initial commit with .gitignore"])
        await run_git(["branch", "-M", "main"])
