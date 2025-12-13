"""
Merge handler for resolving git merge/rebase conflicts.

This handler is spawned when a task's rebase or merge fails due to conflicts.
It receives information about the conflicting files and must produce a merged version.
"""

from typing import Dict, Any

from orchestrator_types import Task, WorkerProfile, WorkerResult

# Import tools (ASYNC versions for non-blocking execution)
from tools import (
    read_file_async as read_file,
    write_file_async as write_file,
    list_directory_async as list_directory,
    file_exists_async as file_exists,
    run_shell_async as run_shell
)

from ..tools_binding import _bind_tools
from ..execution import _execute_react_loop


async def _merge_handler(task: Task, state: Dict[str, Any], config: Dict[str, Any] = None) -> WorkerResult:
    """
    Handle merge conflict resolution tasks (async).

    This handler is specialized for resolving git merge/rebase conflicts.
    It has access to both versions of conflicting files and can produce
    a merged version.
    """
    # Tools for merge workers - read/write files, shell for git operations
    tools = [
        read_file, write_file, list_directory, file_exists, run_shell
    ]

    # Bind tools to worktree
    tools = _bind_tools(tools, state, WorkerProfile.MERGER)

    system_prompt = """You are a skilled merge conflict resolution specialist. Your task is to resolve git rebase conflicts.

**YOUR ROLE:**
You are handling a rebase conflict that occurred when trying to integrate changes from a task branch onto main.
The previous worker completed their task successfully, but when rebasing their branch onto the latest main, conflicts were detected.

**CRITICAL: THE REBASE WORKFLOW**

The original rebase was ABORTED to leave the worktree clean. You MUST follow this exact workflow:

**STEP 1: Start the Rebase (This Will Show Conflicts)**
```bash
git fetch origin main:main  # Get latest main
git rebase main             # This will FAIL and show conflict markers
```

**STEP 2: Examine the Conflicts**
After the rebase starts and stops at a conflict:
```bash
git status                          # Shows files with conflicts
git diff                            # Shows conflict markers in files
```

Conflict markers look like:
```
<<<<<<< HEAD
(code from main branch)
=======
(code from task branch - your changes)
>>>>>>> commit_message
```

**STEP 3: Resolve Each Conflict**
For each conflicting file:
1. Read the file with `read_file` to see conflict markers
2. Understand what both versions intended
3. Write the MERGED version using `write_file` (remove ALL conflict markers)
4. Stage with: `git add <filename>`

**STEP 4: Continue the Rebase**
After resolving ALL conflicts:
```bash
git rebase --continue
```

If more conflicts appear, repeat Steps 2-4.
If the rebase completes, you're done!

**STEP 5: Verify**
```bash
git status                # Should show "nothing to commit"
git log --oneline -n 5    # Should show your commits rebased on main
```

**CONFLICT RESOLUTION STRATEGIES:**

1. **Content Conflicts (same lines modified):**
   - Read both versions carefully
   - Merge logically - often you can keep BOTH changes
   - Example: Main added logging, Task added error handling → Keep both

2. **Add/Add Conflicts (both created same file):**
   - Compare both versions
   - Merge the contents intelligently
   - Don't just pick one - combine them

3. **When in Doubt:**
   - Prefer the task branch changes (the new feature)
   - But ensure main's changes aren't lost if they're important

**COMMANDS REFERENCE:**
- `git rebase main` - Start/continue rebase onto main
- `git rebase --continue` - Continue after resolving conflicts
- `git rebase --abort` - Abort if you get stuck (last resort)
- `git status` - See current state
- `git diff` - See conflict markers
- `git add <file>` - Stage resolved file
- `git show main:<file>` - See main's version (before conflict)
- `git show HEAD:<file>` - See current HEAD version

**IMPORTANT:**
- You MUST remove ALL `<<<<<<<`, `=======`, and `>>>>>>>` markers
- After `git add`, the file should have clean, working code
- Test the code if possible before continuing rebase
"""

    return await _execute_react_loop(task, tools, system_prompt, state, config)
