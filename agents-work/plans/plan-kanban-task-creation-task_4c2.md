# Kanban Task Creation Implementation Plan

Follow design_spec.md for architecture details.

## Overview
Enable UI task creation: input+button → POST /api/tasks → instant To Do column render (no reload).

## Backend Changes (src/server.py)
- Add POST /api/tasks: {title} → insert SQLite tasks (id=uuid, title, status='todo', column='To Do') → return task.
- Unit test verifies DB insert/response.

## Frontend Changes (orchestrator-dashboard)
Assume existing KanbanBoard component from prior plans (plan-task-kanban-board_a59.md).
- New TaskInput.tsx: input field + Add button.
- Integrate into KanbanBoard top: useMutation optimistic update → add to 'To Do' state instantly → replace on success.
- useTasks hook with invalidateQueries.

## Atomic Commits
1. Backend endpoint + test
2. TaskInput component
3. Integrate + optimistic updates
4. E2E test (Playwright)