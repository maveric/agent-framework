# Kanban Task Creation Implementation Plan

Follow design_spec.md for architecture details.

## Overview
Enable users to create new task entries through the frontend UI form/button, persist via POST /api/tasks API endpoint to SQLite backend, and instantly display in the 'To Do' column of the Kanban board (optimistic UI update with React Query).

**Acceptance Criteria (from task):**
- Frontend contains UI for adding new entries (title input + Add button).
- API supports POST /api/tasks for new data {title: string}.
- New entries appear in the data view (Kanban 'To Do' column) after creation.

**Assumptions (from prior plans):**
- SQLite DB with `tasks` table: id (UUID), title (str), status (str, default 'todo').
- Backend: Flask in src/server.py with existing GET /api/tasks.
- Frontend: React/Vite in orchestrator-dashboard/src, with KanbanBoard component using React Query useTasks hook.
- Columns: 'To Do', 'In Progress', 'Done'.

## Backend Changes (src/server.py)
- Add `@app.route('/api/tasks', methods=['POST'])`: Parse JSON {title}, generate uuid, status='todo', INSERT to DB, return 201 JSON {id, title, status}.
- Error handling: 400 if no title.
- Unit test: test_post_task() verifies insert, response shape.

## Frontend Changes (orchestrator-dashboard/src)
- New: src/components/tasks/TaskInput.tsx: Form with <input title>, <Button Add>, useCreateTaskMutation (optimistic update invalidates useTasks).
- Update: KanbanBoard.tsx: Render <TaskInput /> at top, filter tasks by status for columns.
- Hooks: src/hooks/useTasks.ts add useMutation for POST.
- Types: Update Task type if needed.

## Database
No schema change - use existing tasks table.

## Testing Strategy
- Backend unit tests in same commit.
- Frontend unit test for TaskInput form.
- E2E Playwright: UI create → API → visual confirm in column.

## Risks/Mitigations
- DB exists: Verify via prior foundation tasks.
- Optimistic update rollback on error.

## Subtasks
Commit-level tasks emitted via create_subtasks tool.
