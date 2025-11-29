"""
Agent Orchestrator — Git & Filesystem Specification
====================================================
Version 1.0 — November 2025

Git worktree management, branch conventions, and filesystem operations
for isolated task execution.

Depends on:
- orchestrator_types.py (Task, WorkerResult, AAR)
- node_contracts.py (OrchestratorConfig, worker_node integration)

Design Principles:
1. Each task works in its own git worktree (full isolation)
2. Branch from main only after dependencies are merged (simple dependency model)
3. First-to-merge wins; conflicts resolved on retry
4. Worktrees kept until user confirms run completion (debugging)
5. Phoenix retries get fresh branch with read-only reference to failed attempt
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional
import subprocess
import shutil


# =============================================================================
# CONFIGURATION
# =============================================================================

@dataclass
class GitConfig:
    """Git-specific configuration for the orchestrator."""
    
    # Base paths
    repo_path: Path = Path("./project")           # Main repository
    worktree_base: Path = Path("./worktrees")     # Where worktrees live
    
    # Branch naming
    main_branch: str = "main"
    task_branch_prefix: str = "task"              # task/{id}
    retry_branch_prefix: str = "retry"            # task/{id}/retry-{n}
    
    # Commit settings
    auto_commit_on_complete: bool = True
    commit_message_template: str = "[{task_id}] {phase}: {summary}"
    
    # Cleanup
    cleanup_on_run_complete: bool = False         # Requires user confirmation
    keep_failed_branches: bool = True             # For Phoenix reference
    
    def task_branch_name(self, task_id: str) -> str:
        """Generate branch name for a task."""
        return f"{self.task_branch_prefix}/{task_id}"
    
    def retry_branch_name(self, task_id: str, retry_num: int) -> str:
        """Generate branch name for a Phoenix retry."""
        return f"{self.task_branch_prefix}/{task_id}/{self.retry_branch_prefix}-{retry_num}"
    
    def worktree_path(self, task_id: str) -> Path:
        """Generate worktree directory path for a task."""
        # Sanitize task_id for filesystem
        safe_id = task_id.replace("/", "_").replace("\\", "_")
        return self.worktree_base / safe_id


# =============================================================================
# DIRECTORY STRUCTURE
# =============================================================================
"""
Project Layout:
---------------

./project/                          # Main repository (bare or with working tree)
├── .git/
├── src/
├── tests/
├── docs/
└── ...

./worktrees/                        # Worktree container (outside main repo)
├── db_plan_001/                    # Worktree for task db-plan-001
│   ├── .git                        # File pointing to main .git
│   ├── src/
│   └── ...
├── api_impl_002/                   # Worktree for task api-impl-002
│   └── ...
└── db_plan_001_retry_1/            # Phoenix retry worktree
    └── ...

Branch Structure:
-----------------

main                                # Stable, all completed work merged here
├── task/db-plan-001               # First attempt at db planning
├── task/db-plan-001/retry-1       # Phoenix retry (failed attempt preserved)
├── task/api-impl-002              # API implementation
└── task/ui-impl-003               # UI implementation (parallel to api)

Merge Flow:
-----------

1. Task starts → branch from main → create worktree
2. Task works → commits to task branch
3. Task completes → QA passes → merge to main → keep worktree
4. Dependent tasks → branch from updated main
5. Run completes → user confirms → delete all worktrees

"""


# =============================================================================
# WORKTREE LIFECYCLE
# =============================================================================

class WorktreeStatus(str, Enum):
    """Status of a git worktree."""
    CREATING = "creating"       # Being set up
    ACTIVE = "active"           # Task is working in it
    COMPLETE = "complete"       # Task done, not yet merged
    MERGED = "merged"           # Merged to main, kept for reference
    FAILED = "failed"           # Task failed, kept for Phoenix reference
    DELETED = "deleted"         # Cleaned up


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
    previous_branch: Optional[str] = None  # Reference to failed attempt
    
    # Commit tracking
    commits: List[str] = field(default_factory=list)  # Commit hashes
    files_modified: List[str] = field(default_factory=list)


@dataclass 
class WorktreeManager:
    """
    Manages git worktrees for task isolation.
    
    This is the primary interface for all git operations in the orchestrator.
    """
    config: GitConfig
    worktrees: Dict[str, WorktreeInfo] = field(default_factory=dict)
    
    # -------------------------------------------------------------------------
    # WORKTREE CREATION
    # -------------------------------------------------------------------------
    
    def create_worktree(
        self,
        task_id: str,
        retry_number: int = 0,
        previous_branch: Optional[str] = None
    ) -> WorktreeInfo:
        """
        Create a new worktree for a task.
        
        Args:
            task_id: The task identifier
            retry_number: Phoenix retry number (0 for first attempt)
            previous_branch: For retries, the branch that failed (read-only reference)
        
        Returns:
            WorktreeInfo with paths and branch info
        
        Flow:
            1. Determine branch name (new or retry)
            2. Create branch from main
            3. Create worktree directory
            4. Link worktree to branch
        """
        # Determine branch name
        if retry_number == 0:
            branch_name = self.config.task_branch_name(task_id)
        else:
            branch_name = self.config.retry_branch_name(task_id, retry_number)
        
        # Determine worktree path
        if retry_number == 0:
            wt_path = self.config.worktree_path(task_id)
        else:
            wt_path = self.config.worktree_base / f"{task_id.replace('/', '_')}_retry_{retry_number}"
        
        # Create worktree directory if needed
        wt_path.mkdir(parents=True, exist_ok=True)
        
        # Git operations
        self._git_create_branch(branch_name, self.config.main_branch)
        self._git_create_worktree(wt_path, branch_name)
        
        # Track it
        info = WorktreeInfo(
            task_id=task_id,
            branch_name=branch_name,
            worktree_path=wt_path,
            status=WorktreeStatus.ACTIVE,
            retry_number=retry_number,
            previous_branch=previous_branch,
        )
        self.worktrees[task_id] = info
        
        return info
    
    def _git_create_branch(self, branch_name: str, from_branch: str) -> None:
        """Create a new branch from another branch."""
        subprocess.run(
            ["git", "branch", branch_name, from_branch],
            cwd=self.config.repo_path,
            check=True,
            capture_output=True,
        )
    
    def _git_create_worktree(self, path: Path, branch_name: str) -> None:
        """Create a worktree at path, checking out branch."""
        subprocess.run(
            ["git", "worktree", "add", str(path), branch_name],
            cwd=self.config.repo_path,
            check=True,
            capture_output=True,
        )
    
    # -------------------------------------------------------------------------
    # WORKTREE OPERATIONS
    # -------------------------------------------------------------------------
    
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
            Commit hash
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
                    capture_output=True,
                )
        else:
            subprocess.run(
                ["git", "add", "-A"],
                cwd=wt_path,
                check=True,
                capture_output=True,
            )
        
        # Check if there are changes to commit
        result = subprocess.run(
            ["git", "diff", "--cached", "--quiet"],
            cwd=wt_path,
            capture_output=True,
        )
        
        if result.returncode == 0:
            # No changes to commit
            return ""
        
        # Commit
        subprocess.run(
            ["git", "commit", "-m", message],
            cwd=wt_path,
            check=True,
            capture_output=True,
        )
        
        # Get commit hash
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=wt_path,
            check=True,
            capture_output=True,
            text=True,
        )
        commit_hash = result.stdout.strip()
        
        # Track it
        info.commits.append(commit_hash)
        
        return commit_hash
    
    def get_changed_files(self, task_id: str) -> List[str]:
        """Get list of files modified in task's worktree since branch creation."""
        info = self.worktrees.get(task_id)
        if not info:
            raise ValueError(f"No worktree for task: {task_id}")
        
        result = subprocess.run(
            ["git", "diff", "--name-only", self.config.main_branch],
            cwd=info.worktree_path,
            check=True,
            capture_output=True,
            text=True,
        )
        
        files = [f for f in result.stdout.strip().split("\n") if f]
        info.files_modified = files
        return files
    
    def get_diff_from_failed(self, task_id: str) -> Optional[str]:
        """
        For Phoenix retries, get the diff of what was tried in the failed attempt.
        
        This lets the new worker see what didn't work.
        """
        info = self.worktrees.get(task_id)
        if not info or not info.previous_branch:
            return None
        
        result = subprocess.run(
            ["git", "diff", f"{self.config.main_branch}..{info.previous_branch}"],
            cwd=self.config.repo_path,
            check=True,
            capture_output=True,
            text=True,
        )
        
        return result.stdout
    
    def list_files_in_failed(self, task_id: str) -> Optional[List[str]]:
        """
        For Phoenix retries, list files that were modified in the failed attempt.
        """
        info = self.worktrees.get(task_id)
        if not info or not info.previous_branch:
            return None
        
        result = subprocess.run(
            ["git", "diff", "--name-only", f"{self.config.main_branch}..{info.previous_branch}"],
            cwd=self.config.repo_path,
            check=True,
            capture_output=True,
            text=True,
        )
        
        return [f for f in result.stdout.strip().split("\n") if f]
    
    # -------------------------------------------------------------------------
    # MERGE OPERATIONS
    # -------------------------------------------------------------------------
    
    def merge_to_main(self, task_id: str) -> "MergeResult":
        """
        Merge a task's branch to main.
        
        Returns:
            MergeResult indicating success or conflict details
        """
        info = self.worktrees.get(task_id)
        if not info:
            raise ValueError(f"No worktree for task: {task_id}")
        
        # Switch to main in the main repo
        subprocess.run(
            ["git", "checkout", self.config.main_branch],
            cwd=self.config.repo_path,
            check=True,
            capture_output=True,
        )
        
        # Attempt merge
        result = subprocess.run(
            ["git", "merge", info.branch_name, "--no-ff", "-m", 
             f"Merge {info.branch_name} (task {task_id})"],
            cwd=self.config.repo_path,
            capture_output=True,
            text=True,
        )
        
        if result.returncode == 0:
            info.status = WorktreeStatus.MERGED
            info.merged_at = datetime.now()
            return MergeResult(success=True, task_id=task_id)
        else:
            # Merge conflict
            # Abort the merge to leave repo in clean state
            subprocess.run(
                ["git", "merge", "--abort"],
                cwd=self.config.repo_path,
                capture_output=True,
            )
            
            # Get conflicting files
            conflicting_files = self._get_conflicting_files(info.branch_name)
            
            return MergeResult(
                success=False,
                task_id=task_id,
                conflict=True,
                conflicting_files=conflicting_files,
                error_message=result.stderr,
            )
    
    def _get_conflicting_files(self, branch_name: str) -> List[str]:
        """Identify which files would conflict in a merge."""
        # Do a dry-run merge to find conflicts
        result = subprocess.run(
            ["git", "merge", "--no-commit", "--no-ff", branch_name],
            cwd=self.config.repo_path,
            capture_output=True,
            text=True,
        )
        
        # Get list of conflicted files
        status_result = subprocess.run(
            ["git", "diff", "--name-only", "--diff-filter=U"],
            cwd=self.config.repo_path,
            capture_output=True,
            text=True,
        )
        
        # Abort to clean up
        subprocess.run(
            ["git", "merge", "--abort"],
            cwd=self.config.repo_path,
            capture_output=True,
        )
        
        return [f for f in status_result.stdout.strip().split("\n") if f]
    
    # -------------------------------------------------------------------------
    # PHOENIX RETRY SUPPORT
    # -------------------------------------------------------------------------
    
    def prepare_phoenix_retry(
        self,
        task_id: str,
        retry_number: int
    ) -> WorktreeInfo:
        """
        Prepare a fresh worktree for a Phoenix retry.
        
        The failed branch is preserved and passed as a reference.
        The new worktree branches from main (clean slate).
        
        Args:
            task_id: Task to retry
            retry_number: Which retry this is (1, 2, 3...)
        
        Returns:
            New WorktreeInfo with reference to failed branch
        """
        old_info = self.worktrees.get(task_id)
        if not old_info:
            raise ValueError(f"No existing worktree for task: {task_id}")
        
        # Mark old worktree as failed
        old_info.status = WorktreeStatus.FAILED
        failed_branch = old_info.branch_name
        
        # Remove old worktree (but keep branch)
        self._remove_worktree(old_info.worktree_path)
        
        # Create new worktree with reference to failed branch
        return self.create_worktree(
            task_id=task_id,
            retry_number=retry_number,
            previous_branch=failed_branch,
        )
    
    def _remove_worktree(self, path: Path) -> None:
        """Remove a worktree (but not its branch)."""
        subprocess.run(
            ["git", "worktree", "remove", str(path), "--force"],
            cwd=self.config.repo_path,
            capture_output=True,
        )
    
    # -------------------------------------------------------------------------
    # CLEANUP
    # -------------------------------------------------------------------------
    
    def cleanup_run(self, confirm: bool = False) -> Dict[str, Any]:
        """
        Clean up all worktrees after run completion.
        
        Args:
            confirm: Must be True to actually delete (safety)
        
        Returns:
            Summary of what was (or would be) cleaned up
        """
        summary = {
            "worktrees_to_delete": [],
            "branches_to_delete": [],
            "branches_to_keep": [],  # Failed branches for reference
            "deleted": False,
        }
        
        for task_id, info in self.worktrees.items():
            summary["worktrees_to_delete"].append(str(info.worktree_path))
            
            if info.status == WorktreeStatus.FAILED and self.config.keep_failed_branches:
                summary["branches_to_keep"].append(info.branch_name)
            else:
                summary["branches_to_delete"].append(info.branch_name)
        
        if not confirm:
            return summary
        
        # Actually delete
        for task_id, info in list(self.worktrees.items()):
            # Remove worktree
            if info.worktree_path.exists():
                self._remove_worktree(info.worktree_path)
            
            # Remove branch (unless keeping for reference)
            if info.branch_name not in summary["branches_to_keep"]:
                subprocess.run(
                    ["git", "branch", "-D", info.branch_name],
                    cwd=self.config.repo_path,
                    capture_output=True,
                )
            
            info.status = WorktreeStatus.DELETED
            info.deleted_at = datetime.now()
        
        summary["deleted"] = True
        return summary
    
    def get_worktree_status(self) -> Dict[str, Dict[str, Any]]:
        """Get status of all worktrees for debugging/display."""
        return {
            task_id: {
                "branch": info.branch_name,
                "path": str(info.worktree_path),
                "status": info.status.value,
                "retry_number": info.retry_number,
                "previous_branch": info.previous_branch,
                "commits": len(info.commits),
                "files_modified": len(info.files_modified),
            }
            for task_id, info in self.worktrees.items()
        }


@dataclass
class MergeResult:
    """Result of attempting to merge a task branch to main."""
    success: bool
    task_id: str
    conflict: bool = False
    conflicting_files: List[str] = field(default_factory=list)
    error_message: str = ""
    
    def needs_retry(self) -> bool:
        """Should this task be retried due to merge conflict?"""
        return self.conflict


# =============================================================================
# FILESYSTEM INDEX
# =============================================================================

@dataclass
class FilesystemIndex:
    """
    Tracks which branch/task owns which files.
    
    This helps detect potential conflicts before they happen and
    provides context about file ownership.
    """
    # path -> task_id that last modified it
    file_owners: Dict[str, str] = field(default_factory=dict)
    
    # path -> list of task_ids that have modified it
    file_history: Dict[str, List[str]] = field(default_factory=dict)
    
    def record_modification(self, path: str, task_id: str) -> None:
        """Record that a task modified a file."""
        self.file_owners[path] = task_id
        if path not in self.file_history:
            self.file_history[path] = []
        if task_id not in self.file_history[path]:
            self.file_history[path].append(task_id)
    
    def get_owner(self, path: str) -> Optional[str]:
        """Get the task that last modified a file."""
        return self.file_owners.get(path)
    
    def get_potential_conflicts(
        self, 
        task_id: str, 
        files_to_modify: List[str]
    ) -> List[Dict[str, Any]]:
        """
        Check if modifying these files might conflict with other tasks.
        
        This is advisory only - actual conflicts are detected at merge time.
        """
        conflicts = []
        for path in files_to_modify:
            owner = self.file_owners.get(path)
            if owner and owner != task_id:
                conflicts.append({
                    "path": path,
                    "current_owner": owner,
                    "requesting_task": task_id,
                })
        return conflicts
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "file_owners": self.file_owners,
            "file_history": self.file_history,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "FilesystemIndex":
        return cls(
            file_owners=data.get("file_owners", {}),
            file_history=data.get("file_history", {}),
        )


# =============================================================================
# INTEGRATION WITH ORCHESTRATOR
# =============================================================================

def setup_task_worktree(
    manager: WorktreeManager,
    task: Dict[str, Any]
) -> str:
    """
    Set up a worktree for a task.
    
    Called by worker_node before task execution.
    
    Returns:
        Path to worktree directory
    """
    task_id = task["id"]
    retry_count = task.get("retry_count", 0)
    
    # Check if this is a Phoenix retry
    if retry_count > 0:
        # Get reference to previous failed branch
        existing = manager.worktrees.get(task_id)
        previous_branch = existing.branch_name if existing else None
        
        info = manager.prepare_phoenix_retry(task_id, retry_count)
    else:
        info = manager.create_worktree(task_id)
    
    return str(info.worktree_path)


def commit_task_work(
    manager: WorktreeManager,
    task: Dict[str, Any],
    aar_summary: str,
    files_modified: List[str]
) -> str:
    """
    Commit a task's work to its branch.
    
    Called by worker_node after task completes.
    
    Returns:
        Commit hash
    """
    task_id = task["id"]
    phase = task.get("phase", "work")
    
    message = manager.config.commit_message_template.format(
        task_id=task_id,
        phase=phase,
        summary=aar_summary[:50],  # Truncate for commit message
    )
    
    return manager.commit_changes(task_id, message, files_modified)


def merge_completed_task(
    manager: WorktreeManager,
    task_id: str,
    fs_index: FilesystemIndex
) -> MergeResult:
    """
    Merge a completed task's branch to main.
    
    Called by director_node after QA passes.
    
    Updates filesystem_index with merged files.
    """
    result = manager.merge_to_main(task_id)
    
    if result.success:
        # Update filesystem index
        info = manager.worktrees[task_id]
        for path in info.files_modified:
            fs_index.record_modification(path, task_id)
    
    return result


def get_phoenix_context(
    manager: WorktreeManager,
    task_id: str
) -> Dict[str, Any]:
    """
    Get context about the failed attempt for Phoenix retry.
    
    Returns:
        Dict with diff, modified files, and branch reference
    """
    info = manager.worktrees.get(task_id)
    if not info or not info.previous_branch:
        return {}
    
    return {
        "failed_branch": info.previous_branch,
        "failed_diff": manager.get_diff_from_failed(task_id),
        "failed_files": manager.list_files_in_failed(task_id),
    }


# =============================================================================
# CONFLICT RESOLUTION
# =============================================================================

@dataclass
class ConflictResolutionStrategy:
    """
    How to handle merge conflicts.
    
    Current strategy: First-to-merge wins, second task retries.
    The retry will branch from updated main (with first task's changes).
    """
    
    @staticmethod
    def handle_conflict(
        merge_result: MergeResult,
        task: Dict[str, Any],
        manager: WorktreeManager
    ) -> Dict[str, Any]:
        """
        Handle a merge conflict by preparing task for retry.
        
        Returns:
            State update dict for the task
        """
        if not merge_result.conflict:
            raise ValueError("No conflict to handle")
        
        # Task needs to retry with fresh branch from updated main
        # This is effectively a Phoenix retry, but due to conflict not QA failure
        
        return {
            "id": task["id"],
            "status": "ready",  # Back to ready for re-execution
            "retry_count": task.get("retry_count", 0) + 1,
            "blocked_reason": None,
            # Store conflict info for worker context
            "conflict_info": {
                "conflicting_files": merge_result.conflicting_files,
                "reason": "merge_conflict",
                "message": f"Files {merge_result.conflicting_files} were modified by another task. Retrying with updated main.",
            },
        }


# =============================================================================
# INITIALIZATION
# =============================================================================

def initialize_git_repo(config: GitConfig) -> None:
    """
    Initialize git repository for a new run.
    
    Called once at the start of a run if repo doesn't exist.
    """
    repo_path = config.repo_path
    
    if not repo_path.exists():
        repo_path.mkdir(parents=True)
    
    git_dir = repo_path / ".git"
    if not git_dir.exists():
        subprocess.run(
            ["git", "init"],
            cwd=repo_path,
            check=True,
            capture_output=True,
        )
        
        # Create initial commit so we have a main branch
        (repo_path / ".gitkeep").touch()
        subprocess.run(
            ["git", "add", ".gitkeep"],
            cwd=repo_path,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "Initial commit"],
            cwd=repo_path,
            check=True,
            capture_output=True,
        )
        
        # Ensure we're on main branch
        subprocess.run(
            ["git", "branch", "-M", config.main_branch],
            cwd=repo_path,
            check=True,
            capture_output=True,
        )
    
    # Create worktree base directory
    config.worktree_base.mkdir(parents=True, exist_ok=True)


def cleanup_orphaned_worktrees(config: GitConfig) -> List[str]:
    """
    Clean up any orphaned worktrees from crashed runs.
    
    Called at startup to ensure clean state.
    """
    result = subprocess.run(
        ["git", "worktree", "list", "--porcelain"],
        cwd=config.repo_path,
        capture_output=True,
        text=True,
    )
    
    cleaned = []
    # Parse worktree list and remove any in our worktree_base that aren't tracked
    # (Implementation would parse porcelain output and reconcile)
    
    return cleaned


# =============================================================================
# USAGE EXAMPLE
# =============================================================================

if __name__ == "__main__":
    # Example usage
    
    config = GitConfig(
        repo_path=Path("./my_project"),
        worktree_base=Path("./my_project_worktrees"),
    )
    
    # Initialize
    initialize_git_repo(config)
    
    # Create manager
    manager = WorktreeManager(config=config)
    fs_index = FilesystemIndex()
    
    # Simulate task workflow
    task = {"id": "db-plan-001", "phase": "plan", "retry_count": 0}
    
    # 1. Create worktree
    wt_path = setup_task_worktree(manager, task)
    print(f"Created worktree at: {wt_path}")
    
    # 2. Worker does work... (files modified in wt_path)
    
    # 3. Commit work
    commit_hash = commit_task_work(
        manager, task,
        aar_summary="Designed database schema with users and todos tables",
        files_modified=["src/db/schema.sql", "docs/db_design.md"]
    )
    print(f"Committed: {commit_hash}")
    
    # 4. After QA passes, merge
    result = merge_completed_task(manager, "db-plan-001", fs_index)
    if result.success:
        print("Merged to main!")
    else:
        print(f"Conflict in: {result.conflicting_files}")
        # Would trigger retry...
    
    # 5. At end of run (with user confirmation)
    summary = manager.cleanup_run(confirm=False)  # Dry run
    print(f"Would clean up: {summary}")
