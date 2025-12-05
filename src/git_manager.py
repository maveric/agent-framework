"""
Agent Orchestrator — Git Worktree Manager
==========================================
Version 1.0 — November 2025

Manages git worktrees for isolated task execution.
Based on Spec/git_filesystem_spec.py.
"""

import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional


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


@dataclass
class WorktreeManager:
    """
    Manages git worktrees for task isolation.
    
    Each task gets its own worktree branching from main.
    Workers commit to their task branch, then merge on QA approval.
    """
    repo_path: Path
    worktree_base: Path
    main_branch: str = "main"
    worktrees: Dict[str, WorktreeInfo] = field(default_factory=dict)
    
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
    
    def create_worktree(
        self,
        task_id: str,
        retry_number: int = 0,
        previous_branch: Optional[str] = None
    ) -> WorktreeInfo:
        """
        Create a new worktree for a task.
        
        Args:
            task_id: Task identifier
            retry_number: Phoenix retry number (0 for first attempt)
            previous_branch: For retries, the failed branch reference
            
        Returns:
            WorktreeInfo with paths and branch
        """
        # Determine branch and path
        if retry_number == 0:
            branch_name = self._task_branch_name(task_id)
        else:
            branch_name = self._retry_branch_name(task_id, retry_number)
        
        wt_path = self._worktree_path(task_id, retry_number)
        
        # Check if worktree already exists and is valid
        if wt_path.exists() and (wt_path / ".git").exists():
            # Sync with main to ensure we have latest fixes (e.g. from Phoenix recovery)
            try:
                subprocess.run(
                    ["git", "merge", self.main_branch, "-m", f"Sync {self.main_branch} into {branch_name}"],
                    cwd=wt_path,
                    check=False,  # Don't crash on conflict, just warn
                    capture_output=True
                )
            except Exception as e:
                print(f"  Warning: Failed to sync worktree with main: {e}")

            return WorktreeInfo(
                task_id=task_id,
                branch_name=branch_name,
                worktree_path=wt_path,
                status=WorktreeStatus.ACTIVE,
                retry_number=retry_number,
                previous_branch=previous_branch
            )
            
        # Cleanup existing directory if it exists but isn't a valid worktree
        if wt_path.exists():
            import shutil
            try:
                shutil.rmtree(wt_path)
            except Exception:
                pass
        
        # Create worktree directory
        wt_path.mkdir(parents=True, exist_ok=True)
        
        # Git operations
        try:
            # Create branch from main (ignore error if exists)
            subprocess.run(
                ["git", "branch", branch_name, self.main_branch],
                cwd=self.repo_path,
                check=False,
                capture_output=True
            )
            
            # Create worktree
            # Use --force to handle cases where git thinks the branch is already checked out
            # (e.g. from a deleted worktree that wasn't pruned)
            subprocess.run(
                ["git", "worktree", "add", "--force", str(wt_path), branch_name],
                cwd=self.repo_path,
                check=True,
                capture_output=True
            )
        except subprocess.CalledProcessError as e:
            # Cleanup on failure
            if wt_path.exists():
                import shutil
                try:
                    shutil.rmtree(wt_path)
                except Exception:
                    pass
            raise RuntimeError(f"Failed to create worktree: {e.stderr.decode() if e.stderr else str(e)}")
        
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
    
    def commit_changes(
        self,
        task_id: str,
        message: str,
        files: Optional[List[str]] = None
    ) -> str:
        """
        Commit changes in a task's worktree.
        
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
        
        # Stage files
        if files:
            for f in files:
                subprocess.run(
                    ["git", "add", f],
                    cwd=wt_path,
                    check=True,
                    capture_output=True
                )
        else:
            subprocess.run(
                ["git", "add", "-A"],
                cwd=wt_path,
                check=True,
                capture_output=True
            )
        
        # Check if there are changes
        result = subprocess.run(
            ["git", "diff", "--cached", "--quiet"],
            cwd=wt_path,
            capture_output=True
        )
        
        if result.returncode == 0:
            return ""  # No changes
        
        # Commit
        subprocess.run(
            ["git", "commit", "-m", message],
            cwd=wt_path,
            check=True,
            capture_output=True
        )
        
        # Get commit hash
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=wt_path,
            check=True,
            capture_output=True,
            text=True
        )
        commit_hash = result.stdout.strip()
        
        # Track it
        info.commits.append(commit_hash)
        
        return commit_hash

    def commit_to_main(
        self,
        message: str,
        files: List[str]
    ) -> str:
        """
        Commit files directly to the main branch (workspace root).
        Used for shared artifacts like design_spec.md.
        """
        # Ensure we are on main
        subprocess.run(
            ["git", "checkout", self.main_branch],
            cwd=self.repo_path,
            check=True,
            capture_output=True
        )
        
        # Add files
        for f in files:
            subprocess.run(
                ["git", "add", f],
                cwd=self.repo_path,
                check=True,
                capture_output=True
            )
            
        # Commit
        result = subprocess.run(
            ["git", "commit", "-m", message],
            cwd=self.repo_path,
            capture_output=True
        )
        
        if result.returncode == 0:
            # Get hash
            rev_parse = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=self.repo_path,
                capture_output=True,
                text=True
            )
            return rev_parse.stdout.strip()
            
        return ""
    
    def merge_to_main(self, task_id: str) -> MergeResult:
        """
        Merge a task's branch to main.
        
        Returns:
            MergeResult indicating success or conflict
        """
        info = self.worktrees.get(task_id)
        if not info:
            raise ValueError(f"No worktree for task: {task_id}")
        
        # CRITICAL: Check for uncommitted changes in the worktree
        # This indicates the worker didn't properly complete (crash, bug, etc.)
        status_check = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=info.worktree_path,
            capture_output=True,
            text=True
        )
        
        if status_check.stdout.strip():
            error_msg = f"Uncommitted changes in worktree - worker may have crashed or failed to complete properly:\n{status_check.stdout}"
            print(f"  ❌ MERGE BLOCKED: {error_msg}", flush=True)
            return MergeResult(
                success=False,
                task_id=task_id,
                conflict=False,
                error_message=error_msg
            )
        
        # Switch to main
        subprocess.run(
            ["git", "checkout", self.main_branch],
            cwd=self.repo_path,
            check=True,
            capture_output=True
        )
        
        # Check for uncommitted changes in main repo (should never happen with worktrees)
        status_result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=self.repo_path,
            capture_output=True,
            text=True
        )
        
        if status_result.stdout.strip():
            error_msg = f"Uncommitted changes in main repo - worktree isolation may be broken:\n{status_result.stdout}"
            print(f"  ❌ MERGE BLOCKED: {error_msg}", flush=True)
            return MergeResult(
                success=False,
                task_id=task_id,
                conflict=False,
                error_message=error_msg
            )
        
        # Attempt merge
        result = subprocess.run(
            ["git", "merge", info.branch_name, "--no-ff", "-m",
             f"Merge {info.branch_name} (task {task_id})"],
            cwd=self.repo_path,
            capture_output=True,
            text=True
        )
        
        if result.returncode == 0:
            info.status = WorktreeStatus.MERGED
            info.merged_at = datetime.now()
            return MergeResult(success=True, task_id=task_id)
        else:
            # Conflict - abort merge
            subprocess.run(
                ["git", "merge", "--abort"],
                cwd=self.repo_path,
                capture_output=True
            )
            
            return MergeResult(
                success=False,
                task_id=task_id,
                conflict=True,
                error_message=result.stderr
            )
    
    def cleanup_worktree(self, task_id: str) -> None:
        """Remove a worktree (but keep branch)."""
        info = self.worktrees.get(task_id)
        if not info:
            return
        
        subprocess.run(
            ["git", "worktree", "remove", str(info.worktree_path), "--force"],
            cwd=self.repo_path,
            capture_output=True
        )
        
        info.status = WorktreeStatus.DELETED
        info.deleted_at = datetime.now()


def initialize_git_repo(repo_path: Path) -> None:
    """Initialize a git repository if it doesn't exist."""
    git_dir = repo_path / ".git"
    
    if not git_dir.exists():
        # Initialize repo
        subprocess.run(
            ["git", "init"],
            cwd=repo_path,
            check=True,
            capture_output=True
        )
        
        # Configure git user for this repo
        subprocess.run(
            ["git", "config", "user.name", "Agent Orchestrator"],
            cwd=repo_path,
            check=True,
            capture_output=True
        )
        subprocess.run(
            ["git", "config", "user.email", "orchestrator@agent.local"],
            cwd=repo_path,
            check=True,
            capture_output=True
        )
        
        # Create default .gitignore for framework-internal directories
        gitignore_path = repo_path / ".gitignore"
        gitignore_content = """# Agent Framework Internal Directories
.llm_logs/
.worktrees/
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
        
        # Stage and commit the .gitignore
        subprocess.run(
            ["git", "add", ".gitignore"],
            cwd=repo_path,
            check=True,
            capture_output=True
        )
        
        # Create initial commit with .gitignore
        subprocess.run(
            ["git", "commit", "-m", "Initial commit with .gitignore"],
            cwd=repo_path,
            check=True,
            capture_output=True
        )
        
        # Ensure we are on 'main' branch (some systems default to master)
        subprocess.run(
            ["git", "branch", "-M", "main"],
            cwd=repo_path,
            check=True,
            capture_output=True
        )
