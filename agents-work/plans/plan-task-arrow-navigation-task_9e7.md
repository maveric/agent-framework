# Task Arrow Navigation Implementation Plan (task_9e7)

## Component Overview
Implement left/right arrow buttons on task cards in the dashboard's Kanban view (orchestrator-dashboard). Buttons cycle tasks between 3 columns: **To Do** (planned/ready/blocked), **In Progress** (active/awaiting_qa), **Done** (complete/failed_qa/abandoned). 

- Left (←): Previous column
- Right (→): Next column (wraps around)
- Backend: PUT /api/tasks/{id} with {status: newStatus}
- UI: Optimistic update, no reload, React Query invalidation + WS sync
- Follow design_spec.md and Spec/dashboard_frontend_spec.md for TaskGraph/TaskList integration.

**Strict Scope:** Only arrow buttons + status mapping. No drag-drop, editing, auth, new columns, validation beyond enum.

## Files
- Frontend: orchestrator-dashboard/src/utils/taskColumns.ts (new)
- Frontend: orchestrator-dashboard/src/api/tasks.ts (add updateTaskStatus)
- Frontend: orchestrator-dashboard/src/hooks/useTasks.ts (add useUpdateTaskStatus)
- Frontend: orchestrator-dashboard/src/components/tasks/TaskCard.tsx (add buttons)
- Frontend: orchestrator-dashboard/src/components/tasks/TaskList.tsx or TaskGraph.tsx (Kanban layout grouping)
- Backend: Assume /src/server.py or tasks router extended (if needed)

## Success Criteria
- Arrows on cards cycle status/column instantly
- Backend DB updated
- Multi-client sync via WS

