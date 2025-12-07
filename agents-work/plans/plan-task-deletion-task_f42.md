# Task Deletion Implementation Plan

## Component Overview
Implement user-facing deletion of tasks within orchestrator runs via frontend UI and backend API. Tasks are data entries displayed in RunDetail/TaskList. Deletion removes task from run state, persists via LangGraph checkpoint, and updates UI via React Query invalidation + WS broadcast.

**Scope Boundaries (per design_spec.md):**
- DELETE single task by ID within a run
- Frontend: Delete button per task card/list item
- Backend: FastAPI DELETE /api/runs/{run_id}/tasks/{task_id}
- Persist: Update LangGraph state (remove task from tasks[] array)
- Verification: Deleted task absent from GET /api/runs/{run_id}, UI refresh
- NO: Bulk delete, run delete, undo, soft-delete, authz

**Architecture Alignment (Spec/dashboard_spec.py + Spec/dashboard_frontend_spec.md):**
- Backend: Extend src/server.py with task DELETE router
- Frontend: src/api/tasks.ts (add deleteTask), useDeleteTask hook, TaskList/TaskCard delete button
- WS: Broadcast state_update on delete for real-time sync
- Types: Reuse Task from src/types/api.ts

**Risks/Blockers:**
- LangGraph state mutation: Use aupdate_state to remove task
- Dependencies: Deleting task with depends_on[]? Remove anyway (Director re-plans)
- Concurrency: Use optimistic update + error rollback

## High-Level Flow
1. User clicks "Delete" on task → optimistic UI remove → API call
2. Backend: aget_state → filter tasks (remove by ID) → aupdate_state
3. Broadcast state_update via WS
4. Frontend: Invalidate queries + optimistic success/error handling

## Success Metrics (Acceptance Criteria)
- [ ] Frontend delete button renders on tasks
- [ ] DELETE API 200 on valid task_id, 404 otherwise
- [ ] Deleted task gone from GET /api/runs/{run_id} response
- [ ] UI auto-refreshes (Query + WS), no manual refresh needed

## Subtasks
See create_subtasks output for atomic commits.
