# Task Deletion Implementation Plan (ID: 2e4)

## Component Overview
Add user ability to delete individual tasks from a run in the orchestrator dashboard. Deletion removes the task from LangGraph state (tasks[] array), persists via checkpoint, broadcasts state_update via WebSocket, and updates frontend UI via React Query invalidation. Ensures deleted tasks no longer appear in TaskGraph, TaskList, or RunDetail views.

**Scope Boundaries (per Spec/dashboard_spec.py and Spec/dashboard_frontend_spec.md):**
- DELETE /api/runs/{run_id}/tasks/{task_id} endpoint (backend: src/server.py)
- Frontend: Delete button in TaskDetailsContent.tsx or new TaskCard in TaskList (if missing, minimal addition)
- State update: aget_state → filter out task_id → aupdate_state(config, {'tasks': new_tasks})
- Real-time: WS 'state_update' broadcast to subscribed clients
- Error handling: 404 if run/task not found; 409 if task active/in-progress
- NO: Bulk delete, undo/restore, soft-delete, auth, run deletion, dependency handling (simple remove)

**Architecture Alignment:**
- Backend: Extend FastAPI router in src/server.py; use Orchestrator graph from langgraph_definition.py
- Frontend: src/api/tasks.ts (create if missing) → useDeleteTask hook; integrate in TaskDetailsContent.tsx + TaskGraph onNodeClick
- Types: Extend Task from Spec/dashboard_frontend_spec.md types/api.ts
- WS: Leverage existing websocket.ts for state_update handling (invalidateQueries)

**Risks/Blockers:**
- State mutation safety: Use immutable filter + aupdate_state
- Concurrency: Optimistic UI + WS sync prevents stale views
- Dependencies: Deleting task with depends_on? Remove regardless (Director replans if needed)
- Active tasks: Block delete if status != planned|ready|blocked

## High-Level Flow
1. User clicks Delete in TaskDetails or TaskCard → optimistic remove from local tasks[] → mutation
2. Backend: Validate run/task exists + inactive → aget_state → new_tasks = [t for t in tasks if t.id != task_id] → aupdate_state
3. WS: Broadcast {'type': 'state_update', 'run_id': run_id, 'payload': {'tasks': new_tasks}}
4. Frontend: Mutation success → invalidate ['runs', runId]; WS handler refetches/invalidates

## Success Metrics (Acceptance Criteria)
- [ ] Delete button visible on eligible tasks (planned/ready/blocked)
- [ ] DELETE API returns 200, removes task from GET /api/runs/{run_id}
- [ ] UI optimistic remove + auto-refresh via Query/WS; deleted task gone from graph/list
- [ ] Error states: 404/409 handled with toast/user feedback
- [ ] Playwright E2E: Create run → view tasks → delete → verify absent

## Subtasks
See create_subtasks output for atomic commits.
