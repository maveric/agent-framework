# Kanban Task Editing Implementation Plan (task_c80)

Follow design_spec.md for architecture details (cross-referenced with Spec/dashboard_frontend_spec.md for task model: id, title, description, status).

## Overview
Enable users to edit properties of existing tasks (title, description, status) directly in Kanban cards. 
- Double-click card or edit icon triggers inline editable fields (title input, description textarea, status select).
- On blur/Enter/click save: PATCH /api/tasks/{id}, optimistic UI update via React Query mutation + invalidation.
- Changes persist to SQLite DB and reflect instantly across all columns without reload.
- Validation: title required (min 1 char), status enum ['todo','in-progress','done'], desc optional.
- Error: toast notification, revert optimistic update.

Current assumed state (from prior components):
- SQLite DB: tasks table (id UUID PK, title TEXT NOT NULL, description TEXT, status ENUM('todo','in-progress','done'), updated_at TIMESTAMP).
- Backend: GET/POST /api/tasks/{id} implemented.
- Frontend: KanbanBoard.tsx renders columns with TaskCard.tsx from useTasks query.

Scope: STRICTLY editing (PATCH + UI). No create/delete/drag-drop/reorder (scoped to other tasks). No auth/rate-limit.

## Backend Changes (src/server.py)
- PATCH /api/tasks/{id}: Accept partial {title?, description?, status?}, validate Pydantic, UPDATE query, return updated task JSON.
- Add Pydantic TaskUpdate model.
- 404 if id not found, 400 invalid (title empty, invalid status).
- Update updated_at.

## Frontend Changes (orchestrator-dashboard/src)
- hooks/useTasks.ts: Add useUpdateTask mutation (optimistic update task in query cache, invalidateQueries on success).
- components/TaskCard.tsx: Add editMode state, PencilIcon button/dblclick toggle, inputs/select bound to task data, onSave mutation, onCancel revert.
- KanbanBoard.tsx: Ensure query invalidation propagates to re-fetch/re-render columns.

## Acceptance Criteria (global, per design_spec.md)
1. Edit icon appears on TaskCard hover.
2. Dbl-click title toggles edit mode.
3. Title input required, status select limited to enum.
4. Save sends PATCH, shows loading spinner, success → optimistic reflect + toast, error → revert + toast.
5. Changes appear instantly in source/target columns (query invalidation).
6. Cancel/Esc discards changes.
7. Responsive on mobile (full-width edit).

## Subtasks
Granular commit-level tasks defined via create_subtasks below.