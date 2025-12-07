# Kanban Task Editing Implementation Plan (task_015)

Follow design_spec.md for architecture details.

## Overview
Enable inline editing of existing tasks in Kanban cards (title, description, status). Double-click card or edit icon → editable fields → save/cancel → PATCH /api/tasks/{id} → DB update → optimistic UI update + React Query invalidation for immediate reflect in board. No page reload. Validation: required title, valid status enum.

Current state (from prior tasks):
- SQLite tasks table: id (uuid), title, description, status (todo/in-progress/done).
- GET/POST /api/tasks exist.
- Frontend: KanbanBoard.tsx, TaskCard.tsx renders tasks, optimistic create works.

Scope: ONLY edit (PATCH), no delete/reorder/drag-drop (future tasks).

## Backend Changes (src/server.py or dedicated api/tasks.py)
- Add PATCH /api/tasks/{id}: {title?, description?, status?} → validate, update row → return updated task JSON.
- Add status enum validation.
- Error: 404 if not found, 400 invalid data.

## Frontend Changes (orchestrator-dashboard/src)
- TaskCard.tsx: Add edit icon, inline edit mode (inputs for title/desc, Select for status).
- useTasks.ts: Add useUpdateTask mutation (optimistic + invalidate).
- KanbanBoard.tsx: Integrate mutation.

## Acceptance (global)
- Edit controls appear on hover/dbl-click.
- Changes persist to DB, reflect instantly across columns.
- Error handling: toast on fail, revert optimistic.

## Subtasks
Granular commits below via create_subtasks.