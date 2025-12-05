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
    llm_resolved: bool = False  # True if LLM resolved the conflict


def _llm_resolve_conflict(repo_path: Path, conflicted_files: List[str]) -> bool:
    """
    Use LLM to resolve merge conflicts.
    
    Args:
        repo_path: Path to git repository (main worktree)
        conflicted_files: List of files with conflicts
        
    Returns:
        True if all conflicts were resolved, False otherwise
    """
    from llm_client import get_llm
    from config import OrchestratorConfig
    from langchain_core.messages import HumanMessage, SystemMessage
    
    print(f"  🤖 LLM attempting to resolve {len(conflicted_files)} conflict(s)...", flush=True)
    
    try:
        # Get coder model config for merge resolution
        orch_config = OrchestratorConfig()
        model_config = orch_config.coder_model or orch_config.worker_model
        model = get_llm(model_config)
        
        for file_path in conflicted_files:
            full_path = repo_path / file_path
            
            if not full_path.exists():
                print(f"  ⚠️ Conflicted file not found: {file_path}", flush=True)
                continue
            
            # Read the conflicted file (has <<<<<<, =======, >>>>>> markers)
            with open(full_path, "r", encoding="utf-8", errors="replace") as f:
                conflicted_content = f.read()
            
            # Check if it actually has conflict markers
            if "<<<<<<" not in conflicted_content:
                print(f"  ⚠️ No conflict markers in {file_path}, skipping", flush=True)
                continue
            
            print(f"  🔧 Resolving: {file_path}", flush=True)
            
            # Create merge resolution prompt
            system_prompt = """You are a code merge expert. You will receive a file with git merge conflict markers.
Your job is to intelligently merge the code by combining both versions.

RULES:
1. Output ONLY the resolved file content, nothing else
2. Remove all conflict markers (<<<<<<, =======, >>>>>>)
3. Combine both versions logically - don't just pick one
4. For code files (like app.py), combine all functions/endpoints from both versions
5. Preserve proper syntax and formatting
6. Do NOT add any explanation or markdown - just the resolved code"""

            user_prompt = f"""Resolve this merge conflict by combining both versions:

FILE: {file_path}

{conflicted_content}

Output the resolved file content:"""

            # Call LLM
            messages = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_prompt)
            ]
            
            response = model.invoke(messages)
            resolved_content = response.content.strip()
            
            # Remove any markdown code blocks if LLM added them
            if resolved_content.startswith("```"):
                lines = resolved_content.split("\n")
                # Remove first and last lines (```python and ```)
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].strip() == "```":
                    lines = lines[:-1]
                resolved_content = "\n".join(lines)
            
            # Verify no conflict markers remain
            if "<<<<<<" in resolved_content or "=======" in resolved_content or ">>>>>>" in resolved_content:
                print(f"  ❌ LLM resolution still has conflict markers, aborting", flush=True)
                return False
            
            # Write resolved content
            with open(full_path, "w", encoding="utf-8") as f:
                f.write(resolved_content)
            
            # Stage the resolved file
            subprocess.run(
                ["git", "add", file_path],
                cwd=repo_path,
                check=True,
                capture_output=True
            )
            
            print(f"  ✅ Resolved: {file_path}", flush=True)
        
        return True
        
    except Exception as e:
        print(f"  ❌ LLM merge resolution failed: {e}", flush=True)
        import traceback
        traceback.print_exc()
        return False


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
        # NOTE: We only care about modified/staged files, NOT untracked files (??)
        status_check = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=info.worktree_path,
            capture_output=True,
            text=True
        )
        
        # Filter out untracked files (??) - only block on actual uncommitted changes
        uncommitted_lines = [
            line for line in status_check.stdout.strip().split('\n')
            if line and not line.startswith('??')
        ]
        
        if uncommitted_lines:
            error_msg = f"Uncommitted changes in worktree - worker may have crashed or failed to complete properly:\n" + "\n".join(uncommitted_lines)
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
        # NOTE: We only care about modified/staged files, NOT untracked files (??)
        # Untracked directories like .llm_logs/, .worktrees/, logs/ are fine
        status_result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=self.repo_path,
            capture_output=True,
            text=True
        )
        
        # Filter out untracked files (??) - only block on actual changes
        uncommitted_lines = [
            line for line in status_result.stdout.strip().split('\n')
            if line and not line.startswith('??')
        ]
        
        if uncommitted_lines:
            error_msg = f"Uncommitted changes in main repo - worktree isolation may be broken:\n" + "\n".join(uncommitted_lines)
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
            # Merge conflict detected - try LLM resolution before aborting
            print(f"  ⚠️ Merge conflict detected for {task_id}", flush=True)
            
            # Get list of conflicted files
            status_result = subprocess.run(
                ["git", "diff", "--name-only", "--diff-filter=U"],
                cwd=self.repo_path,
                capture_output=True,
                text=True
            )
            conflicted_files = [f for f in status_result.stdout.strip().split('\n') if f]
            
            if conflicted_files:
                print(f"  📝 Conflicted files: {conflicted_files}", flush=True)
                
                # Try LLM-assisted resolution
                if _llm_resolve_conflict(self.repo_path, conflicted_files):
                    # LLM resolved the conflicts - complete the merge
                    commit_result = subprocess.run(
                        ["git", "commit", "-m", f"Merge {info.branch_name} (task {task_id}) - LLM resolved conflicts"],
                        cwd=self.repo_path,
                        capture_output=True,
                        text=True
                    )
                    
                    if commit_result.returncode == 0:
                        print(f"  ✅ LLM successfully resolved merge conflict for {task_id}", flush=True)
                        info.status = WorktreeStatus.MERGED
                        info.merged_at = datetime.now()
                        return MergeResult(
                            success=True, 
                            task_id=task_id, 
                            llm_resolved=True,
                            conflicting_files=conflicted_files
                        )
                    else:
                        print(f"  ❌ Failed to commit LLM resolution: {commit_result.stderr}", flush=True)
            
            # LLM resolution failed or no conflicted files - abort merge
            subprocess.run(
                ["git", "merge", "--abort"],
                cwd=self.repo_path,
                capture_output=True
            )
            
            # Git can output errors to stderr OR stdout, so capture both
            error_output = result.stderr.strip() or result.stdout.strip() or "Merge conflict (no details available)"
            
            return MergeResult(
                success=False,
                task_id=task_id,
                conflict=True,
                conflicting_files=conflicted_files,
                error_message=error_output
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
