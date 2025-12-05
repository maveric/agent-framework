# Kanban Task Creation Implementation Plan (task_d85)

Follow design_spec.md for architecture details.

## Overview
Enable users to create new tasks via UI: input field + 'Add' button at page top → POST /api/tasks → backend stores in DB → optimistic render in 'To Do' column (no reload). Matches exact acceptance criteria.

## Backend Changes (src/server.py)
- POST /api/tasks accepts {title:string} → insert tasks table (id=uuid, title, status='todo', column='To Do') → return JSON.

## Frontend Changes (orchestrator-dashboard)
- New TaskInput.tsx: input + button.
- Integrate into KanbanBoard.tsx top with React Query mutation + optimistic update to 'To Do' column state.

## Subtasks (4 Atomic Commits)
1. Backend endpoint + unit test.
2. TaskInput component + test.
3. Kanban integration + optimistic UI.
4. Playwright E2E test.

Sequential deps ensure backend ready before UI. Each self-contained with verification.