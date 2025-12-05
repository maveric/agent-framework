# Implementation Plan for Task Deletion (task_3b8)

## Overview
Follow design_spec.md strictly. Add delete functionality for tasks in Kanban columns. Backend Flask API DELETE /api/tasks/{id}, frontend React task card 'X' button calls API and removes from UI optimistically without page reload.

## Backend Changes (Flask/SQLite)
- Route: DELETE /api/tasks/&lt;int:id&gt;
- Delete from tasks table by id.
- Return JSON {'success': true} or 404.

## Frontend Changes (React/ReactFlow)
- TaskNode component: Add 'X' button.
- onClick: fetch DELETE, on success remove from local tasks state.
- Use useState or zustand store for tasks.

## Testing
- Backend unit test for DELETE.
- Frontend unit test for delete handler.
- E2E Playwright test for click X, verify gone.

Granularity: Atomic commits, each with verification.

