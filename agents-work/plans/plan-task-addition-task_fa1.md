# Task Addition Capability Implementation Plan

## Component Overview
Implements user capability to add new tasks/items to an orchestrator run via UI form. Tasks are persisted by calling backend POST /api/runs/{run_id}/tasks endpoint, which updates the orchestrator state. Follows Spec/dashboard_frontend_spec.md for types (AddTaskRequest, Task), API structure, and UI patterns (similar to CreateRunDialog).

## Dependencies
- Backend: Existing OrchestratorService.get_instance(), models.requests.AddTaskRequest, /api/runs/{run_id} exists.
- Frontend: src/api/client.ts, src/types/api.ts (Task, TaskPhase), src/hooks/useRuns.ts pattern.
- Existing: RunDetailPage.tsx or TaskList.tsx for integration point.

## Key Features
1. UI Dialog with form: component, phase (plan/build/test), description, acceptance_criteria (textarea), priority slider.
2. Validation: Required fields, phase enum dropdown.
3. On submit: POST to /api/runs/{run_id}/tasks, optimistic update via React Query invalidate.
4. Real-time: WebSocket updates reflect new task.
5. Responsive Tailwind UI matching spec (Radix Dialog, Select).

## Backend Changes
- Add POST /runs/{run_id}/tasks endpoint in backend/api/tasks.py
- OrchestratorService.add_task(run_id, task_data) → append to state.tasks, conditional ready if no deps.

## Frontend Changes
- src/api/tasks.ts: add createTask(runId, data)
- src/hooks/useCreateTask.ts: React Query mutation
- src/components/tasks/AddTaskDialog.tsx: New component
- src/pages/RunDetailPage.tsx: Add button → open dialog
- src/components/tasks/TaskList.tsx: Button to add

## Acceptance Criteria (from task)
- UI allows adding new items (form + submit)
- Items persisted (backend state update, query invalidation)

## Risks/Notes
- Ensure new task status='planned', phase validated.
- No auth yet, per spec.
- Test: Verify task appears in list/graph after add.

## Subtask Breakdown
See create_subtasks output for atomic commits.