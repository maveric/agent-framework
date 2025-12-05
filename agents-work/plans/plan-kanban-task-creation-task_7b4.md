# Kanban Task Creation Feature Plan

Follow design_spec.md for architecture (FastAPI backend, SQLite tasks table, React frontend).

## Overview
Implements task creation per acceptance criteria: UI input/button → POST /api/tasks → DB store → instant 'To Do' render (optimistic update, no reload).

## Assumptions from Prior Work
- Backend: src/server.py exists with /api/runs, SQLite DB with tasks(id, title, status, column, created_at) from kanban-foundation.
- Frontend: orchestrator-dashboard/src has KanbanBoard from plan-task-kanban-board_a59.md.

## Subtasks (4 Atomic Commits)

1. **Backend API endpoint** (build): POST /api/tasks → DB insert → JSON response.
2. **TaskInput UI component** (build): Input + Add button.
3. **Kanban integration + optimistic** (build): Add to board top, React Query mutation.
4. **E2E test** (test): Playwright verifies full flow.

Granularity ensures reviewable PRs with inline verification.