# Concurrent Git Operations: Complete Strategy Guide

**Problem Statement**: Multiple worker agents complete tasks simultaneously and attempt to merge their branches to `main` concurrently, causing race conditions, merge conflicts, and git state corruption.

**Current State**: No synchronization → Lost commits, corrupted repos, merge failures

---

## Table of Contents

1. [Current Architecture Analysis](#current-architecture-analysis)
2. [Strategy 1: Pessimistic Locking](#strategy-1-pessimistic-locking)
3. [Strategy 2: Optimistic Concurrency with Retry](#strategy-2-optimistic-concurrency-with-retry)
4. [Strategy 3: Rebase-Based Workflow](#strategy-3-rebase-based-workflow)
5. [Strategy 4: Sequential Merge Queue](#strategy-4-sequential-merge-queue)
6. [Strategy 5: Per-Component Branch Strategy](#strategy-5-per-component-branch-strategy)
7. [Strategy 6: Deferred Batch Merges](#strategy-6-deferred-batch-merges)
8. [Strategy 7: Eliminate Git During Execution](#strategy-7-eliminate-git-during-execution)
9. [Hybrid Approaches](#hybrid-approaches)
10. [Recommendation Matrix](#recommendation-matrix)

---

## Current Architecture Analysis

### What Happens Now

```python
# git_manager.py:439
async def merge_to_main(self, task_id: str) -> MergeResult:
    # Worker A and Worker B can both enter here simultaneously
    subprocess.run(["git", "checkout", self.main_branch], ...)  # RACE!
    result = subprocess.run(["git", "merge", info.branch_name, ...])  # RACE!
```

### Race Condition Timeline

```
Time  | Worker A (task_001)           | Worker B (task_002)           | Main Branch State
------|-------------------------------|-------------------------------|------------------
T0    | complete, start merge         |                               | commit C0
T1    | checkout main (C0)            | complete, start merge         | commit C0
T2    | merge task_001 branch         | checkout main (C0)            | commit C0
T3    | creating merge commit...      | merge task_002 branch         | DIRTY (A writing)
T4    | commit C1 (A's merge)         | ERROR: main has changed!      | commit C1
T5    | success                       | FAIL or CONFLICT              | commit C1
```

**Result**: Worker B fails, or worse, creates a broken merge.

### Current Failure Modes

1. **Concurrent Checkout**: Both workers checkout `main` at same commit, unaware of each other
2. **Dirty Working Tree**: Worker A's merge leaves uncommitted changes, Worker B sees dirty state
3. **Lost Commits**: Worker B's changes get discarded when merge fails
4. **Corrupt State**: Partial merges, detached HEAD, or stale worktree references

---

## Strategy 1: Pessimistic Locking

**Concept**: Only one worker can merge at a time. Use locks to serialize access to `main`.

### 1A: Asyncio Lock (In-Process)

**How It Works**:

```python
# git_manager.py - add class-level lock
class WorktreeManager:
    def __init__(self, ...):
        self._merge_lock = asyncio.Lock()

    async def merge_to_main(self, task_id: str) -> MergeResult:
        async with self._merge_lock:  # Only one merge at a time
            # Checkout main
            subprocess.run(["git", "checkout", self.main_branch], ...)

            # Merge (no concurrent access possible)
            result = subprocess.run(["git", "merge", info.branch_name, ...])

            return MergeResult(success=True, ...)
```

**Timeline with Lock**:

```
Time  | Worker A              | Worker B              | Lock State
------|----------------------|----------------------|------------
T0    | acquire lock         |                      | A holds lock
T1    | checkout main        | tries to acquire... | A holds lock
T2    | merge task_001       | WAITING...          | A holds lock
T3    | commit C1            | WAITING...          | A holds lock
T4    | release lock         | acquired lock!      | B holds lock
T5    | done                 | checkout main (C1)  | B holds lock
T6    |                      | merge task_002      | B holds lock
T7    |                      | commit C2           | B holds lock
T8    |                      | release lock        | Free
```

**Pros**:
- ✅ Simple to implement (5 lines of code)
- ✅ Guarantees serialization
- ✅ Works with existing merge logic
- ✅ No external dependencies

**Cons**:
- ❌ Only works for single-process (not multi-server)
- ❌ If lock holder crashes, lock is released (could be mid-merge)
- ❌ No visibility into who holds lock or why waiting

**Implementation**:

```python
# git_manager.py
import asyncio
from contextlib import asynccontextmanager

class WorktreeManager:
    def __init__(self, repo_path: Path, worktree_base: Path, ...):
        self.repo_path = repo_path
        self.worktree_base = worktree_base
        self._merge_lock = asyncio.Lock()  # NEW

    async def merge_to_main(self, task_id: str) -> MergeResult:
        logger.info(f"Task {task_id} waiting for merge lock...")

        async with self._merge_lock:
            logger.info(f"Task {task_id} acquired merge lock")

            # Original merge logic here (unchanged)
            info = self.worktrees.get(task_id)
            # ... checkout, merge, etc ...

            logger.info(f"Task {task_id} releasing merge lock")
            return result
```

**Migration Effort**: ⭐ (15 minutes)

**Best For**:
- Single-server deployments
- Quick fix to test if locking solves the problem
- Development/testing environments

---

### 1B: File-Based Lock (Cross-Process)

**How It Works**:

Use a lock file in the repo to coordinate across processes/servers.

```python
import fcntl  # Unix file locking
from pathlib import Path

class FileLock:
    def __init__(self, lock_file: Path):
        self.lock_file = lock_file
        self.fd = None

    async def acquire(self, timeout: float = 60.0):
        """Acquire exclusive lock on file"""
        self.lock_file.parent.mkdir(parents=True, exist_ok=True)
        self.fd = open(self.lock_file, 'w')

        start = time.time()
        while time.time() - start < timeout:
            try:
                fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                # Write PID for debugging
                self.fd.write(f"{os.getpid()}\n{datetime.now().isoformat()}\n")
                self.fd.flush()
                return True
            except IOError:
                await asyncio.sleep(0.1)

        raise TimeoutError(f"Could not acquire lock after {timeout}s")

    async def release(self):
        if self.fd:
            fcntl.flock(self.fd, fcntl.LOCK_UN)
            self.fd.close()

# Usage in WorktreeManager
async def merge_to_main(self, task_id: str) -> MergeResult:
    lock = FileLock(self.repo_path / ".git" / "merge.lock")

    try:
        await lock.acquire(timeout=120.0)  # Wait up to 2 minutes

        # Original merge logic
        # ...

    finally:
        await lock.release()
```

**Pros**:
- ✅ Works across processes/servers (if on shared filesystem)
- ✅ Lock persists in filesystem (can inspect `.git/merge.lock` to see who has it)
- ✅ Automatic release on process crash (OS cleans up file locks)
- ✅ Built into OS kernel (reliable)

**Cons**:
- ❌ Requires shared filesystem (NFS, EFS, etc.) for multi-server
- ❌ File locking on NFS can be unreliable
- ❌ Lock file can become stale if not cleaned up
- ❌ Platform-specific (fcntl is Unix-only, need different approach for Windows)

**Implementation**: See code above

**Migration Effort**: ⭐⭐ (1-2 hours)

**Best For**:
- Multi-process on same server
- Shared filesystem deployments

---

### 1C: Database Lock

**How It Works**:

Use PostgreSQL advisory locks or a lock table.

```python
# Approach 1: PostgreSQL Advisory Locks
async def merge_to_main(self, task_id: str) -> MergeResult:
    async with self.db.acquire() as conn:
        # Acquire advisory lock (ID = hash of repo path)
        lock_id = hash(str(self.repo_path)) % (2**31)
        await conn.execute("SELECT pg_advisory_lock($1)", lock_id)

        try:
            # Merge logic
            result = self._do_merge(task_id)
        finally:
            await conn.execute("SELECT pg_advisory_unlock($1)", lock_id)

    return result

# Approach 2: Lock Table
# CREATE TABLE merge_locks (
#   repo_path VARCHAR PRIMARY KEY,
#   holder VARCHAR,
#   acquired_at TIMESTAMP
# );

async def acquire_lock(repo_path: str, holder: str, timeout: float = 60.0):
    start = time.time()
    while time.time() - start < timeout:
        try:
            # Try to insert lock record
            await conn.execute("""
                INSERT INTO merge_locks (repo_path, holder, acquired_at)
                VALUES ($1, $2, NOW())
                ON CONFLICT DO NOTHING
                RETURNING repo_path
            """, repo_path, holder)

            # If insert succeeded, we got the lock
            return True
        except:
            await asyncio.sleep(0.5)

    raise TimeoutError("Could not acquire lock")
```

**Pros**:
- ✅ Works across servers (shared database)
- ✅ Can query lock state (who holds it, when acquired)
- ✅ PostgreSQL advisory locks are very reliable
- ✅ Automatic cleanup on connection close

**Cons**:
- ❌ Requires database (added dependency)
- ❌ Database becomes single point of contention
- ❌ Network latency for lock acquisition
- ❌ Overkill for single-server deployments

**Migration Effort**: ⭐⭐⭐ (4-6 hours, includes DB setup)

**Best For**:
- Multi-server production deployments
- When you already have PostgreSQL

---

### 1D: Redis Lock (Distributed)

**How It Works**:

Use Redis SET with NX (not exists) and EX (expiry) for distributed locking.

```python
import aioredis

class RedisLock:
    def __init__(self, redis_client, key: str, ttl: int = 120):
        self.redis = redis_client
        self.key = key
        self.ttl = ttl
        self.token = str(uuid.uuid4())

    async def acquire(self, timeout: float = 60.0):
        start = time.time()
        while time.time() - start < timeout:
            # SET key value NX EX ttl
            # NX = only set if not exists
            # EX = expiry time (prevents stuck locks)
            result = await self.redis.set(
                self.key,
                self.token,
                nx=True,  # Only if not exists
                ex=self.ttl  # Auto-expire after 120s
            )

            if result:
                return True

            await asyncio.sleep(0.1)

        raise TimeoutError("Could not acquire lock")

    async def release(self):
        # Only release if we own it (check token)
        script = """
        if redis.call("get", KEYS[1]) == ARGV[1] then
            return redis.call("del", KEYS[1])
        else
            return 0
        end
        """
        await self.redis.eval(script, keys=[self.key], args=[self.token])

# Usage
async def merge_to_main(self, task_id: str) -> MergeResult:
    lock = RedisLock(
        self.redis_client,
        key=f"merge_lock:{self.repo_path}",
        ttl=120  # Auto-expire after 2 minutes
    )

    try:
        await lock.acquire(timeout=60.0)

        # Merge logic
        result = self._do_merge(task_id)

    finally:
        await lock.release()

    return result
```

**Pros**:
- ✅ Distributed (works across servers)
- ✅ Auto-expiry prevents stuck locks
- ✅ High performance (in-memory)
- ✅ Can monitor lock state in real-time
- ✅ Battle-tested pattern (used by Celery, etc.)

**Cons**:
- ❌ Requires Redis (added dependency)
- ❌ Redis becomes single point of failure (use Redis Sentinel/Cluster)
- ❌ Clock skew issues with expiry
- ❌ Complex failure modes (split brain, network partitions)

**Implementation**: See code above + Redis setup

**Migration Effort**: ⭐⭐⭐ (4-6 hours, includes Redis setup)

**Best For**:
- Multi-server production deployments
- High-concurrency scenarios (50+ concurrent workers)
- When you already have Redis infrastructure

---

## Strategy 2: Optimistic Concurrency with Retry

**Concept**: Don't lock. Try to merge, and if it fails due to concurrent modification, retry.

### How It Works

```python
async def merge_to_main_optimistic(self, task_id: str, max_retries: int = 5) -> MergeResult:
    """Optimistic merge with exponential backoff retry"""

    for attempt in range(max_retries):
        try:
            # Get current main commit BEFORE checkout
            main_commit_before = subprocess.run(
                ["git", "rev-parse", self.main_branch],
                cwd=self.repo_path,
                capture_output=True,
                text=True
            ).stdout.strip()

            # Checkout main
            subprocess.run(["git", "checkout", self.main_branch],
                          cwd=self.repo_path, check=True)

            # Verify main hasn't changed (compare-and-swap)
            main_commit_after = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=self.repo_path,
                capture_output=True,
                text=True
            ).stdout.strip()

            if main_commit_before != main_commit_after:
                # Someone else merged while we were checking out!
                logger.warning(f"Attempt {attempt + 1}: Main changed, retrying...")
                await asyncio.sleep(2 ** attempt + random.uniform(0, 1))
                continue

            # Try to merge
            result = subprocess.run(
                ["git", "merge", info.branch_name, "--no-ff", "-m", f"Merge {task_id}"],
                cwd=self.repo_path,
                capture_output=True
            )

            if result.returncode == 0:
                # Success!
                return MergeResult(success=True, task_id=task_id)
            else:
                # Merge conflict - handle separately
                return self._handle_conflict(task_id, info.branch_name)

        except subprocess.CalledProcessError as e:
            # Checkout or other git error
            logger.warning(f"Attempt {attempt + 1}: Git error: {e}, retrying...")
            await asyncio.sleep(2 ** attempt + random.uniform(0, 1))

    # All retries exhausted
    return MergeResult(
        success=False,
        task_id=task_id,
        error_message=f"Failed after {max_retries} retries"
    )
```

**Timeline**:

```
Time  | Worker A              | Worker B              | Main
------|----------------------|----------------------|------
T0    | read main = C0       |                      | C0
T1    | checkout main        | read main = C0       | C0
T2    | verify main = C0 ✓   | checkout main        | C0
T3    | merge task_001       | verify main = C0 ✓   | C0
T4    | commit C1            | merge task_002       | C1 (A merged!)
T5    | done                 | ERROR: main changed! | C1
T6    |                      | sleep 2s, retry...   | C1
T7    |                      | read main = C1       | C1
T8    |                      | checkout main        | C1
T9    |                      | verify main = C1 ✓   | C1
T10   |                      | merge task_002       | C1
T11   |                      | commit C2            | C2
```

**Pros**:
- ✅ No locks needed (no deadlocks)
- ✅ Works across servers without coordination
- ✅ Automatic retry handles transient conflicts
- ✅ Better throughput under low contention

**Cons**:
- ❌ Wasted work on retry (checkout, merge attempt)
- ❌ High contention = many retries (performance degrades)
- ❌ Exponential backoff can delay merges significantly
- ❌ Still requires some form of conflict detection

**Migration Effort**: ⭐⭐ (2-3 hours)

**Best For**:
- Low to medium concurrency (< 10 concurrent merges)
- When you can't add external dependencies (Redis, DB)
- Brownfield codebases where adding locks is hard

---

## Strategy 3: Rebase-Based Workflow

**Concept**: Instead of merging branches into main, rebase task branches onto main and fast-forward.

### How It Works

```python
async def integrate_to_main_rebase(self, task_id: str) -> MergeResult:
    """Rebase task branch onto main, then fast-forward merge"""

    info = self.worktrees.get(task_id)
    if not info:
        raise ValueError(f"No worktree for task: {task_id}")

    # Step 1: Update main to latest
    subprocess.run(
        ["git", "checkout", self.main_branch],
        cwd=self.repo_path,
        check=True
    )
    subprocess.run(
        ["git", "pull"],
        cwd=self.repo_path,
        check=True
    )

    # Step 2: Rebase task branch onto main (in worktree)
    try:
        subprocess.run(
            ["git", "rebase", self.main_branch],
            cwd=info.worktree_path,
            check=True,
            capture_output=True
        )
    except subprocess.CalledProcessError:
        # Rebase conflict - need to resolve
        return await self._resolve_rebase_conflict(task_id, info.worktree_path)

    # Step 3: Switch to main and fast-forward merge
    subprocess.run(
        ["git", "checkout", self.main_branch],
        cwd=self.repo_path,
        check=True
    )

    result = subprocess.run(
        ["git", "merge", "--ff-only", info.branch_name],
        cwd=self.repo_path,
        capture_output=True
    )

    if result.returncode == 0:
        return MergeResult(success=True, task_id=task_id)
    else:
        # Fast-forward failed (shouldn't happen if rebase succeeded)
        return MergeResult(
            success=False,
            task_id=task_id,
            error_message=f"Fast-forward failed: {result.stderr.decode()}"
        )
```

**Git History Comparison**:

```
MERGE WORKFLOW (current):
  A --- B --- C --- D (main)
   \         /     /
    E --- F     G --- H
    (task1)     (task2)

Result: Merge commits D and later, non-linear history

REBASE WORKFLOW:
  A --- B --- C (main)
   \
    E --- F (task1 branch)

After rebase task1:
  A --- B --- C --- E' --- F' (main + task1 rebased)

After rebase task2:
  A --- B --- C --- E' --- F' --- G' --- H' (main)

Result: Linear history, no merge commits
```

**Pros**:
- ✅ Linear history (easier to bisect, cleaner git log)
- ✅ No merge commits (simpler history)
- ✅ Fast-forward merges are atomic (all-or-nothing)
- ✅ Easier to see what each task did (commits grouped)

**Cons**:
- ❌ Rewrites commit history (SHAs change after rebase)
- ❌ More complex conflict resolution (rebase --continue)
- ❌ Can't preserve original commit timestamps
- ❌ Still needs locking or retry for concurrent rebases
- ❌ Dangerous if branches are shared (shouldn't be in your case)

**Conflict Resolution**:

```python
async def _resolve_rebase_conflict(self, task_id: str, worktree_path: Path):
    """Resolve rebase conflicts using LLM (similar to merge conflicts)"""

    # Get list of conflicted files
    status = subprocess.run(
        ["git", "diff", "--name-only", "--diff-filter=U"],
        cwd=worktree_path,
        capture_output=True,
        text=True
    )
    conflicted_files = status.stdout.strip().split('\n')

    # Use LLM to resolve each file
    for file_path in conflicted_files:
        await self._llm_resolve_conflict(worktree_path, [file_path])

    # Continue rebase
    subprocess.run(
        ["git", "rebase", "--continue"],
        cwd=worktree_path,
        check=True
    )
```

**Migration Effort**: ⭐⭐⭐ (4-6 hours, need to update conflict resolution)

**Best For**:
- Teams that prefer linear history
- When you want clean git log for debugging
- Combined with locking or retry strategy

---

## Strategy 4: Sequential Merge Queue

**Concept**: Workers don't merge directly. They enqueue merge requests, and a single background task processes the queue sequentially.

### How It Works

```python
# New module: merge_queue.py
import asyncio
from dataclasses import dataclass
from typing import Dict
from pathlib import Path

@dataclass
class MergeRequest:
    task_id: str
    branch_name: str
    priority: int = 5
    submitted_at: datetime = field(default_factory=datetime.now)

class MergeQueue:
    def __init__(self, wt_manager: WorktreeManager):
        self.wt_manager = wt_manager
        self.queue: asyncio.Queue = asyncio.Queue()
        self.results: Dict[str, MergeResult] = {}
        self._processor_task = None

    def start(self):
        """Start background processor"""
        self._processor_task = asyncio.create_task(self._process_queue())

    async def stop(self):
        """Stop processor gracefully"""
        await self.queue.put(None)  # Sentinel
        if self._processor_task:
            await self._processor_task

    async def enqueue(self, task_id: str, branch_name: str) -> MergeResult:
        """Submit merge request and wait for result"""
        request = MergeRequest(task_id=task_id, branch_name=branch_name)
        await self.queue.put(request)

        # Wait for result (poll every 0.5s)
        while task_id not in self.results:
            await asyncio.sleep(0.5)

        return self.results.pop(task_id)

    async def _process_queue(self):
        """Background task that processes merges sequentially"""
        logger.info("Merge queue processor started")

        while True:
            request = await self.queue.get()

            if request is None:
                # Sentinel value, shutdown
                break

            logger.info(f"Processing merge for task {request.task_id}")

            try:
                # Execute merge WITHOUT locks (queue serializes)
                result = await self.wt_manager._do_merge_unlocked(request.task_id)
                self.results[request.task_id] = result
            except Exception as e:
                logger.error(f"Merge failed for {request.task_id}: {e}")
                self.results[request.task_id] = MergeResult(
                    success=False,
                    task_id=request.task_id,
                    error_message=str(e)
                )
            finally:
                self.queue.task_done()

        logger.info("Merge queue processor stopped")

# In WorktreeManager:
class WorktreeManager:
    def __init__(self, ...):
        self.merge_queue = MergeQueue(self)
        self.merge_queue.start()

    async def merge_to_main(self, task_id: str) -> MergeResult:
        """Public API - enqueues merge request"""
        return await self.merge_queue.enqueue(task_id, self.worktrees[task_id].branch_name)

    async def _do_merge_unlocked(self, task_id: str) -> MergeResult:
        """Internal method - does actual merge (called by queue processor)"""
        # Original merge logic here (no locks needed)
        # ...
```

**Timeline**:

```
Time  | Worker A         | Worker B         | Merge Queue      | Main
------|------------------|------------------|------------------|------
T0    | complete task    |                  | idle             | C0
T1    | enqueue merge    |                  | processing A...  | C0
T2    | waiting...       | complete task    | merging A        | C0
T3    | waiting...       | enqueue merge    | merging A        | C0
T4    | waiting...       | waiting...       | A done! (C1)     | C1
T5    | got result: ✓    | waiting...       | processing B...  | C1
T6    | done             | waiting...       | merging B        | C1
T7    |                  | got result: ✓    | B done! (C2)     | C2
T8    |                  | done             | idle             | C2
```

**Pros**:
- ✅ Guaranteed sequential processing (no races)
- ✅ No explicit locks needed
- ✅ Queue can be prioritized (high-priority tasks first)
- ✅ Easy to add observability (queue depth, processing time)
- ✅ Can retry failed merges automatically
- ✅ Clean separation of concerns

**Cons**:
- ❌ Adds latency (workers wait in queue)
- ❌ Single-threaded bottleneck (queue processor)
- ❌ Queue can grow unbounded if merges are slow
- ❌ More complex code (background task, queue management)

**Enhancements**:

```python
# Priority queue (high priority first)
class MergeQueue:
    def __init__(self, wt_manager: WorktreeManager):
        self.queue: asyncio.PriorityQueue = asyncio.PriorityQueue()
        # ...

    async def enqueue(self, task_id: str, branch_name: str, priority: int = 5):
        request = MergeRequest(task_id, branch_name, priority)
        # Lower priority value = processed first
        await self.queue.put((priority, request))

# Persistent queue (survives restarts)
class PersistentMergeQueue:
    def __init__(self, db_path: Path):
        # Store queue in SQLite
        self.db = await aiosqlite.connect(db_path)
        await self.db.execute("""
            CREATE TABLE IF NOT EXISTS merge_queue (
                id INTEGER PRIMARY KEY,
                task_id TEXT,
                branch_name TEXT,
                priority INTEGER,
                submitted_at TIMESTAMP,
                status TEXT DEFAULT 'pending'
            )
        """)
```

**Migration Effort**: ⭐⭐⭐ (6-8 hours)

**Best For**:
- High-concurrency scenarios (many simultaneous completions)
- When you want centralized merge control
- Production systems that need observability

---

## Strategy 5: Per-Component Branch Strategy

**Concept**: Instead of merging everything to `main`, create per-component integration branches.

### How It Works

```
Traditional:
  main (all code)
    ├── task_001 (api changes)
    ├── task_002 (frontend changes)
    └── task_003 (database changes)

All merge to main → high conflict potential

Per-Component:
  main (stable releases only)
    ├── integration/api
    │   ├── task_001
    │   └── task_004
    ├── integration/frontend
    │   ├── task_002
    │   └── task_005
    └── integration/database
        └── task_003

Tasks merge to component branch → periodic merge component→main
```

**Implementation**:

```python
class WorktreeManager:
    def __init__(self, ...):
        # Component-level locks (one lock per component)
        self.component_locks: Dict[str, asyncio.Lock] = {}

    def get_integration_branch(self, task: Task) -> str:
        """Determine which branch to merge to based on component"""
        # Map component to integration branch
        component_branches = {
            "api": "integration/api",
            "frontend": "integration/frontend",
            "database": "integration/db",
            "shared": "integration/shared"
        }
        return component_branches.get(task.component, "main")

    async def merge_to_integration(self, task_id: str, task: Task) -> MergeResult:
        """Merge to component-specific integration branch"""
        target_branch = self.get_integration_branch(task)

        # Get or create lock for this component
        if target_branch not in self.component_locks:
            self.component_locks[target_branch] = asyncio.Lock()

        async with self.component_locks[target_branch]:
            # Merge to integration branch (low conflict rate)
            subprocess.run(["git", "checkout", target_branch], ...)
            subprocess.run(["git", "merge", info.branch_name, ...], ...)

            return MergeResult(success=True, task_id=task_id)

    async def merge_integrations_to_main(self):
        """Periodic job: merge all integration branches to main"""
        integration_branches = [
            "integration/api",
            "integration/frontend",
            "integration/db"
        ]

        subprocess.run(["git", "checkout", "main"], ...)

        for branch in integration_branches:
            result = subprocess.run(
                ["git", "merge", branch, "--no-ff", "-m", f"Integrate {branch}"],
                cwd=self.repo_path,
                capture_output=True
            )

            if result.returncode != 0:
                # Conflict between components - needs manual resolution
                logger.error(f"Integration conflict: {branch}")
                # Could use LLM resolution here too
```

**Timeline**:

```
Workers complete in parallel:
  Task A (api) → integration/api (✓ no conflict with frontend)
  Task B (frontend) → integration/frontend (✓ no conflict with api)
  Task C (api) → integration/api (serialized with Task A only)

Periodic integration (every 10 tasks or hourly):
  integration/api → main
  integration/frontend → main
  integration/db → main
```

**Pros**:
- ✅ Dramatically reduces merge conflicts (isolated by component)
- ✅ Parallel merges for different components
- ✅ Easier to test component changes before main merge
- ✅ Rollback entire component if something breaks
- ✅ Scales well (10+ components = 10x throughput)

**Cons**:
- ❌ More complex branching strategy
- ❌ Cross-component changes need special handling
- ❌ Periodic integration can still have conflicts
- ❌ `main` is not always up-to-date (delayed integration)
- ❌ Requires good component boundaries (not always clear)

**Migration Effort**: ⭐⭐⭐⭐ (2-3 days - needs component mapping, integration job)

**Best For**:
- Large projects with clear component boundaries
- High concurrency (50+ concurrent workers)
- Microservices architectures

---

## Strategy 6: Deferred Batch Merges

**Concept**: Workers commit to their branches but DON'T merge. Merge everything at the end in a batch.

### How It Works

```python
class WorktreeManager:
    def __init__(self, ...):
        self.pending_merges: List[str] = []  # Task IDs waiting to merge

    async def commit_only(self, task_id: str) -> str:
        """Commit to branch but don't merge"""
        info = self.worktrees.get(task_id)

        # Stage and commit as usual
        subprocess.run(["git", "add", "-A"], cwd=info.worktree_path)
        commit_hash = subprocess.run(
            ["git", "commit", "-m", f"Task {task_id} complete"],
            cwd=info.worktree_path,
            capture_output=True,
            text=True
        ).stdout

        # Track for later merge
        self.pending_merges.append(task_id)

        logger.info(f"Task {task_id} committed ({commit_hash[:8]}), queued for merge")
        return commit_hash

    async def batch_merge_all(self):
        """Merge all pending branches in dependency order"""
        logger.info(f"Batch merging {len(self.pending_merges)} branches")

        # Sort by dependency order (tasks that depend on fewer things first)
        # This minimizes conflicts
        sorted_tasks = self._topological_sort(self.pending_merges)

        for task_id in sorted_tasks:
            try:
                result = await self._merge_single(task_id)
                if result.success:
                    logger.info(f"  ✓ Merged {task_id}")
                else:
                    logger.error(f"  ✗ Failed to merge {task_id}: {result.error_message}")
            except Exception as e:
                logger.error(f"  ✗ Exception merging {task_id}: {e}")

        self.pending_merges.clear()
        logger.info("Batch merge complete")

    def _topological_sort(self, task_ids: List[str]) -> List[str]:
        """Sort tasks by dependency order (Kahn's algorithm)"""
        # Get task objects
        tasks = {tid: self._get_task(tid) for tid in task_ids}

        # Build in-degree map
        in_degree = {tid: 0 for tid in task_ids}
        for tid, task in tasks.items():
            for dep in task.depends_on:
                if dep in in_degree:
                    in_degree[tid] += 1

        # Process queue
        queue = [tid for tid, deg in in_degree.items() if deg == 0]
        result = []

        while queue:
            current = queue.pop(0)
            result.append(current)

            # Decrease in-degree for dependents
            for tid, task in tasks.items():
                if current in task.depends_on and tid in in_degree:
                    in_degree[tid] -= 1
                    if in_degree[tid] == 0:
                        queue.append(tid)

        return result
```

**Usage in Dispatch Loop**:

```python
# dispatch.py - modify worker completion handling
if result.status == "complete" and result.aar and result.aar.files_modified:
    if wt_manager:
        # Commit but don't merge yet
        commit_hash = await wt_manager.commit_only(task_id)
        logger.info(f"  Task {task_id} committed, pending merge")

# At end of run or periodically
if all_tasks_complete:
    logger.info("All tasks complete, starting batch merge...")
    await wt_manager.batch_merge_all()
```

**Timeline**:

```
Phase 1: Execution (parallel)
  Worker A → commit to branch (no merge)
  Worker B → commit to branch (no merge)
  Worker C → commit to branch (no merge)
  ...all workers commit independently

Phase 2: Batch Merge (sequential, at end)
  Merge task_001 → main
  Merge task_002 → main
  Merge task_003 → main
  ...all merged in dependency order
```

**Pros**:
- ✅ Zero contention during execution (workers don't block each other)
- ✅ Merge in dependency order (reduces conflicts)
- ✅ Can optimize merge order (minimize conflicts)
- ✅ Can test all branches before merging
- ✅ Easy to rollback individual tasks

**Cons**:
- ❌ Tasks don't see each other's changes during execution
- ❌ Delays integration (subsequent tasks can't depend on uncommitted work)
- ❌ Large batch merges can take a long time
- ❌ If batch merge fails partway, need recovery logic
- ❌ Not suitable for incremental/streaming use cases

**Migration Effort**: ⭐⭐⭐ (4-6 hours)

**Best For**:
- Batch processing workflows (all tasks known upfront)
- High parallelism, low inter-task dependencies
- When you can afford delayed integration

---

## Strategy 7: Eliminate Git During Execution

**Concept**: Don't use git worktrees during execution. Use simple filesystem isolation, then commit everything at the end.

### How It Works

```python
class FilesystemIsolation:
    """Replaces WorktreeManager - simple directory isolation"""

    def __init__(self, workspace_root: Path):
        self.workspace_root = workspace_root
        self.task_dirs: Dict[str, Path] = {}

    def create_task_workspace(self, task_id: str) -> Path:
        """Create isolated directory for task"""
        task_dir = self.workspace_root / ".task_workspaces" / task_id
        task_dir.mkdir(parents=True, exist_ok=True)

        # Copy current main state to task directory
        main_dir = self.workspace_root
        shutil.copytree(
            main_dir,
            task_dir,
            ignore=shutil.ignore_patterns('.git', '.task_workspaces', '__pycache__'),
            dirs_exist_ok=True
        )

        self.task_dirs[task_id] = task_dir
        return task_dir

    def get_modified_files(self, task_id: str) -> List[Path]:
        """Detect files changed by worker"""
        task_dir = self.task_dirs[task_id]
        main_dir = self.workspace_root

        modified = []
        for task_file in task_dir.rglob('*'):
            if task_file.is_file():
                rel_path = task_file.relative_to(task_dir)
                main_file = main_dir / rel_path

                # Compare content
                if not main_file.exists() or not filecmp.cmp(task_file, main_file):
                    modified.append(rel_path)

        return modified

    def apply_changes_to_main(self, task_id: str):
        """Copy changed files from task workspace to main"""
        task_dir = self.task_dirs[task_id]
        main_dir = self.workspace_root

        modified = self.get_modified_files(task_id)

        for rel_path in modified:
            src = task_dir / rel_path
            dst = main_dir / rel_path

            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)

        return modified

# After all tasks complete, commit to git once
async def finalize_run(fs_manager: FilesystemIsolation, task_ids: List[str]):
    """Commit all changes to git in one shot"""

    all_modified = []
    for task_id in task_ids:
        modified = fs_manager.apply_changes_to_main(task_id)
        all_modified.extend(modified)

    # Now commit everything to git
    subprocess.run(["git", "add", "-A"], cwd=fs_manager.workspace_root)
    subprocess.run(
        ["git", "commit", "-m", f"Agent run complete: {len(task_ids)} tasks"],
        cwd=fs_manager.workspace_root
    )
```

**Pros**:
- ✅ Simple (no git during execution)
- ✅ Zero git-related race conditions
- ✅ Fast (no git overhead per task)
- ✅ Easy to debug (just directories)

**Cons**:
- ❌ No version history during execution
- ❌ Can't see intermediate commits
- ❌ Large disk usage (full copy per task)
- ❌ File conflicts detected late (at apply time)
- ❌ Loses all git benefits during execution

**Migration Effort**: ⭐⭐⭐⭐ (1-2 days - major refactor)

**Best For**:
- Prototyping/testing
- When git overhead is too high
- Small workspaces (< 100MB per task)

---

## Hybrid Approaches

### Hybrid 1: Lock + Optimistic Retry

Combine locking for common case, retry for edge cases.

```python
async def merge_to_main(self, task_id: str) -> MergeResult:
    # Try to acquire lock (short timeout)
    try:
        async with asyncio.timeout(5.0):
            async with self._merge_lock:
                return await self._do_merge(task_id)
    except asyncio.TimeoutError:
        # Lock held too long, fall back to optimistic retry
        logger.warning("Lock timeout, switching to optimistic retry")
        return await self._merge_optimistic_retry(task_id)
```

**Best For**: Production systems that need reliability + performance

---

### Hybrid 2: Queue + Priority Lanes

Fast lane for critical tasks, queue for normal tasks.

```python
class MergeQueue:
    def __init__(self):
        self.fast_lane = asyncio.Lock()  # For critical tasks
        self.queue = asyncio.Queue()  # For normal tasks

    async def merge(self, task_id: str, priority: str = "normal"):
        if priority == "critical":
            # Use lock (faster)
            async with self.fast_lane:
                return await self._do_merge(task_id)
        else:
            # Use queue (serialized)
            return await self._enqueue_and_wait(task_id)
```

**Best For**: When some tasks need low-latency merges

---

### Hybrid 3: Component Branches + Queue

Per-component queues for fine-grained parallelism.

```python
class ComponentMergeManager:
    def __init__(self):
        self.queues: Dict[str, MergeQueue] = {}

    async def merge(self, task_id: str, component: str):
        if component not in self.queues:
            self.queues[component] = MergeQueue()

        # Each component has independent queue
        return await self.queues[component].enqueue(task_id)
```

**Best For**: Large projects with many components

---

## Recommendation Matrix

| Scenario | Recommended Strategy | Alternative | Why |
|----------|---------------------|-------------|-----|
| **Single server, < 10 workers** | Asyncio Lock (1A) | Optimistic Retry (2) | Simple, sufficient |
| **Single server, 10-50 workers** | Merge Queue (4) | Component Branches (5) | Better throughput |
| **Multi-server, shared FS** | File Lock (1B) | Redis Lock (1D) | Cross-process coordination |
| **Multi-server, no shared FS** | Redis Lock (1D) | DB Lock (1C) | Distributed locking |
| **Very high concurrency (50+)** | Component Branches (5) | Queue + Priority (Hybrid 2) | Maximize parallelism |
| **Batch workflows** | Deferred Merge (6) | Queue (4) | Optimize merge order |
| **Prefer linear history** | Rebase (3) + Lock (1A) | Rebase (3) + Queue (4) | Clean git log |
| **Quick fix for testing** | Optimistic Retry (2) | Asyncio Lock (1A) | No dependencies |
| **Production, high reliability** | Queue (4) + Monitoring | Redis Lock (1D) | Observability |

---

## Implementation Roadmap

### Phase 1: Quick Fix (Week 1)
**Goal**: Stop the bleeding, prevent data loss

1. Implement **Asyncio Lock (1A)**
   - Add `self._merge_lock = asyncio.Lock()` to WorktreeManager
   - Wrap merge_to_main with `async with self._merge_lock:`
   - Test with 10 concurrent workers
   - **Effort**: 1-2 hours

2. Add monitoring
   - Log lock wait times
   - Alert if lock held > 60s
   - **Effort**: 1 hour

**Total**: 3-4 hours, 90% of race conditions eliminated

---

### Phase 2: Production Hardening (Week 2-3)
**Goal**: Scalable, observable solution

1. Implement **Merge Queue (4)**
   - Background processor task
   - Priority queue support
   - Persistent queue (SQLite)
   - **Effort**: 6-8 hours

2. Add metrics
   - Queue depth gauge
   - Merge duration histogram
   - Conflict rate counter
   - **Effort**: 2-3 hours

3. Testing
   - Unit tests for queue
   - Integration tests with 50 concurrent workers
   - Chaos testing (kill processor mid-merge)
   - **Effort**: 4-6 hours

**Total**: 12-17 hours, production-ready

---

### Phase 3: Optimize (Month 2)
**Goal**: Maximum throughput

1. Implement **Component Branches (5)**
   - Define component boundaries
   - Create integration branches
   - Periodic integration job
   - **Effort**: 2-3 days

2. Add **Rebase Workflow (3)**
   - Switch from merge to rebase
   - Update conflict resolution
   - Test with linear history
   - **Effort**: 1 day

**Total**: 3-4 days, 5-10x throughput improvement

---

## Quick Decision Tree

```
START
  ↓
  Are you running multi-server?
  ├─ NO → Can you tolerate queue latency?
  │       ├─ NO → Use Asyncio Lock (1A)
  │       └─ YES → Use Merge Queue (4)
  │
  └─ YES → Do you have Redis?
          ├─ YES → Use Redis Lock (1D)
          └─ NO → Do you have shared filesystem?
                  ├─ YES → Use File Lock (1B)
                  └─ NO → Use DB Lock (1C) or add Redis
```

---

## Appendix: Testing Concurrent Merges

### Test Harness

```python
# tests/test_concurrent_merges.py
import asyncio
import pytest
from git_manager import WorktreeManager

@pytest.mark.asyncio
async def test_concurrent_merges_no_conflict():
    """10 workers merge different files simultaneously"""

    wt_manager = WorktreeManager(...)

    async def worker(worker_id: int):
        task_id = f"task_{worker_id:03d}"

        # Create worktree
        wt_manager.create_worktree(task_id)

        # Write unique file
        (wt_manager.worktrees[task_id].worktree_path / f"file_{worker_id}.txt").write_text(
            f"Worker {worker_id} was here"
        )

        # Commit
        wt_manager.commit_changes(task_id, f"Worker {worker_id}")

        # Merge (concurrent!)
        result = await wt_manager.merge_to_main(task_id)
        assert result.success, f"Worker {worker_id} merge failed"

    # Run 10 workers in parallel
    await asyncio.gather(*[worker(i) for i in range(10)])

    # Verify all files present in main
    main_files = list((wt_manager.repo_path).glob("file_*.txt"))
    assert len(main_files) == 10

@pytest.mark.asyncio
async def test_concurrent_merges_with_conflict():
    """10 workers modify same file → test conflict resolution"""

    # Similar setup, but all workers modify "shared.txt"
    # Should trigger LLM conflict resolution
    ...
```

Run with: `pytest tests/test_concurrent_merges.py -v -s`

---

## Conclusion

**My Recommendation for You**:

**Phase 1 (This Week)**: Implement **Asyncio Lock (1A)** immediately. It's 3 hours of work and eliminates 90% of your pain.

**Phase 2 (Next Month)**: Migrate to **Merge Queue (4)** for production. It's more robust, observable, and scales better.

**Future (If needed)**: Add **Component Branches (5)** when you hit 50+ concurrent workers.

This gives you an incremental path from broken → working → scalable.

Want me to implement any of these strategies for you?
