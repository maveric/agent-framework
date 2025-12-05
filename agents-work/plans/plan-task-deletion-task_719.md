# Task Deletion Feature Implementation Plan - Task ID 719

## Overview
This plan implements task deletion functionality as specified in the task description, referencing the dashboard architecture in Spec/dashboard_frontend_spec.md and backend in Spec/dashboard_spec.py and src/server.py.

**Core Requirements (from acceptance criteria):**
- Each task card displays an 'X' delete button
- DELETE /api/tasks/&lt;id&gt; removes task from database (LangGraph state)
- Deleted task is removed from UI without page reload (optimistic update + WS broadcast)

**Assumptions from codebase exploration:**
- Tasks displayed in TaskGraph.tsx (TaskNode acts as task card), RunDetailPage.tsx list, and potentially Kanban-style columns (status-based).
- Backend state managed in LangGraph checkpoints (orchestrator.db).
- Real-time updates via WebSocket (state_update events).
- No existing TaskCard; TaskNode in TaskGraph.tsx serves as card. Will add to TaskNode and any list views.
- Task IDs are globally unique.
- Frontend uses React Query for data fetching, Zustand/WS for real-time.

**Architecture Decisions (no scope expansion):**
- Backend: New DELETE /api/tasks/{task_id} scans runs to find task, removes from state, broadcasts via WS.
- Frontend API: New src/api/tasks.ts with deleteTask(taskId: string).
- UI: 'X' button in TaskNode (graph) and any task lists. Confirm delete modal? No - direct delete per AC.
- Updates: Optimistic removal from local state, React Query invalidate ['runs', runId], rely on WS for sync.
- No auth, error handling minimal (per MVP spec).
- Tests: Unit for endpoint/hook, Playwright E2E for flow.

**Risks/Mitigations:**
- Task not found: 404 response.
- Concurrent edits: WS overrides optimistic.
- Graph layout: Deleting node auto-recalculates via useMemo.

## High-Level Steps
1. Backend endpoint + broadcast.
2. Frontend API + hook.
3. UI integration (TaskNode + lists).
4. Optimistic updates + tests.

## Dependencies
- Existing WS for state_update.
- React Query for invalidation.

## Success Criteria
- Delete button visible on task cards.
- Click → API call → task gone from UI/DB.
- Real-time sync across clients.
- E2E test passes.

See subtasks for atomic commits.