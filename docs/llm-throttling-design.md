# LLM Request Throttling Design

> **Status**: Design Complete - Ready for Implementation

## Goal
Run multiple projects/runs simultaneously without overwhelming LLM providers.

## Current State
- Every worker creates its own LLM instance via `get_llm()`
- No awareness of other concurrent requests
- No global rate limiting

## Proposed Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                      LLM Request Pool                           │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  Global Semaphore: max_concurrent = 5 (configurable)    │   │
│  │  In-flight counter: 3/5                                 │   │
│  │  Queue depth: 2 waiting                                 │   │
│  └─────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
         ▲                    ▲                    ▲
         │                    │                    │
    ┌────┴────┐          ┌────┴────┐          ┌────┴────┐
    │ Run A   │          │ Run B   │          │ Run C   │
    │ Worker1 │          │ Worker2 │          │ Worker3 │
    └─────────┘          └─────────┘          └─────────┘
```

---

## Recommended: Wrapper in `llm_client.py`

**Lift: ~50 lines in 1 file**

```python
# llm_client.py - add this

import asyncio
from contextlib import asynccontextmanager

class LLMPool:
    """Global pool managing concurrent LLM requests."""
    
    _instance = None
    
    def __init__(self, max_concurrent: int = 5):
        self.semaphore = asyncio.Semaphore(max_concurrent)
        self.in_flight = 0
        self.total_requests = 0
        self.lock = asyncio.Lock()
    
    @classmethod
    def get_instance(cls, max_concurrent: int = 5) -> "LLMPool":
        if cls._instance is None:
            cls._instance = cls(max_concurrent)
        return cls._instance
    
    @asynccontextmanager
    async def acquire(self, run_id: str = None, task_id: str = None):
        """Acquire a slot in the pool (blocks if at capacity)."""
        await self.semaphore.acquire()
        async with self.lock:
            self.in_flight += 1
            self.total_requests += 1
            logger.debug(f"LLM slot acquired ({self.in_flight}/{self.semaphore._value + self.in_flight})")
        try:
            yield
        finally:
            async with self.lock:
                self.in_flight -= 1
            self.semaphore.release()
    
    def get_stats(self) -> dict:
        return {
            "in_flight": self.in_flight,
            "max_concurrent": self.semaphore._value + self.in_flight,
            "total_requests": self.total_requests
        }

# Modify existing wrapper:
async def throttled_ainvoke(llm, messages, run_id=None, task_id=None, **kwargs):
    """Throttled LLM invocation - respects global concurrency limit."""
    pool = LLMPool.get_instance()
    async with pool.acquire(run_id, task_id):
        return await llm.ainvoke(messages, **kwargs)
```

**Changes needed elsewhere:**
- Replace `llm.ainvoke()` with `throttled_ainvoke(llm, ...)`
- ~6 files, ~1 line change each

---

## Files to Modify

| File | Change |
|------|--------|
| `llm_client.py` | Add `LLMPool` class + `throttled_ainvoke()` |
| `execution.py` | Use `throttled_ainvoke()` for agent loop |
| `director_main.py` | Use `throttled_ainvoke()` for fix task creation |
| `decomposition.py` | Use `throttled_ainvoke()` for spec/planners |
| `integration.py` | Use `throttled_ainvoke()` for dependency resolution |
| `strategist.py` | Use `throttled_ainvoke()` for merge decisions |
| `config.py` | Add `max_concurrent_llm_calls: int = 5` |

---

## Configuration

```python
# config.py
class OrchestratorConfig:
    # ... existing fields ...
    
    # LLM throttling
    max_concurrent_llm_calls: int = 5  # Global limit across all runs
```

### Dashboard Integration (Optional)
Could expose stats via WebSocket:
```json
{"type": "llm_stats", "in_flight": 3, "max": 5, "queued": 2}
```

---

## Per-Provider Limits (Future Enhancement)

```python
class LLMPool:
    def __init__(self):
        self.provider_limits = {
            "anthropic": asyncio.Semaphore(5),
            "openai": asyncio.Semaphore(10),
            "glm": asyncio.Semaphore(3),
        }
```

---

## Summary

| Metric | Value |
|--------|-------|
| **Implementation time** | ~30 min |
| **Lines of code** | ~60 new, ~10 modified |
| **Risk level** | Low |
| **Testing** | Run 2+ concurrent runs, verify throttling |
