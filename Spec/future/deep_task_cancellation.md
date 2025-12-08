# Future Enhancement: Deep Task Cancellation

## Overview
Enable interrupt/cancel to fully terminate all resources started by a task, including:
- Child subprocesses spawned via `run_shell` or `run_python`
- Any long-running commands (servers, watchers, etc.)
- Network connections or file handles

## Current Behavior
When a task is interrupted:
1. ✅ Dispatch loop is cancelled
2. ✅ Task status set to WAITING_HUMAN
3. ❌ Subprocesses started by agent (e.g., `python app.py`) continue running as orphans

## Proposed Solution

### Phase 1: Track Subprocess PIDs
Modify `run_shell_async` and `run_python_async` to:
- Store spawned process PIDs in task-scoped storage
- Return PID alongside command output

```python
# In code_execution_async.py
async def run_shell_async(command: str, timeout: int, cwd: Path, task_id: str = None) -> dict:
    proc = await asyncio.create_subprocess_shell(...)
    
    # Track PID for later cleanup
    if task_id:
        register_task_subprocess(task_id, proc.pid)
    
    return {"output": ..., "pid": proc.pid}
```

### Phase 2: Per-Task Process Registry
Create a global registry mapping task_id → list of PIDs:

```python
# task_process_registry.py
_task_processes: Dict[str, Set[int]] = {}

def register_task_subprocess(task_id: str, pid: int):
    if task_id not in _task_processes:
        _task_processes[task_id] = set()
    _task_processes[task_id].add(pid)

def kill_task_subprocesses(task_id: str):
    for pid in _task_processes.get(task_id, []):
        try:
            os.kill(pid, signal.SIGTERM)
            # Wait briefly, then SIGKILL if still running
        except ProcessLookupError:
            pass  # Already dead
    _task_processes.pop(task_id, None)
```

### Phase 3: Integration with interrupt_task
Modify `interrupt_task` endpoint to call `kill_task_subprocesses(task_id)`:

```python
# In server.py interrupt_task()
from task_process_registry import kill_task_subprocesses

# Before cancelling the dispatch loop:
logger.info(f"Killing subprocesses for task {task_id}")
kill_task_subprocesses(task_id)
```

### Phase 4: Windows Considerations
On Windows, process tree killing requires special handling:
- Use `taskkill /F /T /PID {pid}` for tree kill
- Or use `psutil.Process(pid).children(recursive=True)` + kill each

```python
import platform
if platform.system() == "Windows":
    subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True)
else:
    os.killpg(os.getpgid(pid), signal.SIGTERM)
```

## Scope
- **run_shell**: Primary target, most likely to spawn servers
- **run_python**: Secondary, could spawn subprocesses via `subprocess.Popen`
- **Browser sessions**: Future consideration if using playwright/selenium

## Complexity Estimate
- Phase 1-2: ~2 hours
- Phase 3: ~1 hour  
- Phase 4 (Windows compat): ~2 hours
- Testing: ~2 hours

**Total: ~7 hours**

## Dependencies
- May want `psutil` for cross-platform process management
- Need to pass `task_id` through tool binding chain

## Priority
Medium - Impacts UX when agents make mistakes like running servers directly.
Workaround: User can manually kill processes via Task Manager / `kill` command.
