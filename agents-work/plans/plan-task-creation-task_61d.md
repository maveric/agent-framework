# Task Creation Implementation Plan (Kanban Integration)

## Component Overview
Implements task creation for the Kanban board via API and UI. New tasks are created with minimal data (title), default status 'planned' (maps to 'To Do' column), and appear immediately in the 'To Do' column. Scoped strictly to acceptance criteria—no validation, no run_id requirement (global tasks list for MVP), no edit/delete.

Follows design_spec.md (dashboard spec) for Task type (title as description), API patterns (src/api/tasks.ts), hooks (useTasks.ts). Integrates with existing/planned TaskKanban.tsx.

## Dependencies
- Backend: src/server.py (endpoints)
- Frontend: orchestrator-dashboard/src/api/tasks.ts (add create), src/hooks/useTasks.ts (add create mutation), src/components/tasks/TaskKanban.tsx (add input UI)
- Assumes GET /api/tasks exists or will be added (from prior kanban plan)

## Key Features
1. Backend POST /api/tasks {title: str} → creates {id, title (as description), status: 'planned'}
2. Frontend: Input + Add button above 'To Do' column, optimistic UI update
3. Real-time display in 'To Do' via local state/refetch

## File Changes
- src/server.py: Add global_tasks list, POST /api/tasks endpoint
- orchestrator-dashboard/src/api/tasks.ts: Add createTask(runId irrelevant, global)
- orchestrator-dashboard/src/hooks/useTasks.ts: Add useCreateTask mutation (invalidate queries)
- orchestrator-dashboard/src/components/tasks/TaskKanban.tsx: Add form in To Do header
- src/tests/test_server_tasks.py: Unit tests (new)

## Status Mapping Reminder (To Do column)
todo: ['planned', 'ready', 'blocked']

## Risks/Notes
- Global tasks (no run scoping) for MVP—fits AC without expansion
- Optimistic updates assume no conflicts (no concurrency)

