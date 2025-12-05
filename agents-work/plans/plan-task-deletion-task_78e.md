# Implementation Plan for Task Deletion (task_78e)

## Overview
Follow design_spec.md strictly. Implement task removal functionality for the Kanban board. Add backend DELETE /api/tasks/&lt;id&gt; endpoint to remove task from SQLite DB. Frontend: Add 'X' close button to each task card that calls the API and optimistically removes the task from local state/UI without page reload. Use optimistic updates for immediate feedback.

## Current Architecture (from codebase exploration)
- **Backend**: Flask app (likely src/backend/app.py or similar) with SQLite tasks table (id, title, status).
- **Frontend**: React (Vite, likely orchestrator-dashboard/src or Kanban app) with task cards/nodes (TaskNode in TaskGraph.tsx or Kanban columns).
- **State Management**: Local useState, Zustand, or React Query for tasks list.
- **API**: Existing GET/POST /api/tasks; add DELETE.
- **No WebSocket**: Use direct fetch for delete, invalidate/refetch or optimistic remove.

## Backend Changes
1. Add @app.route('/api/tasks/&lt;int:task_id&gt;', methods=['DELETE'])
2. Query DB: DELETE FROM tasks WHERE id = task_id
3. Return jsonify({'success': True, 'deleted_id': task_id}) or 404
4. Add unit test with test client or pytest.

## Frontend Changes
1. In TaskNode/TaskCard component: Add 'X' button (absolute positioned top-right).
2. onClick: async deleteTask(id) { optimistic remove from state, await fetch DELETE, if error revert }
3. Use React Query mutation or useSWR mutator if present; else useState filter.
4. Ensure immediate UI removal, error handling with toast/revert.

## Testing Strategy
- Backend unit test: DELETE succeeds/fails.
- Frontend unit test: Button renders, handler called.
- E2E Playwright: Create task, click X, verify removed from UI/DB/list.

## Granularity
Atomic commits: one endpoint+test, one UI button, one handler+optimistic, one E2E.

## Dependencies
- Existing: Tasks table, GET/POST /api/tasks, task list UI.
