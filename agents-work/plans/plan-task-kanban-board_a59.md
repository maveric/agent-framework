# Task Kanban Board Implementation Plan

## Component Overview
This component implements a Kanban board displaying tasks fetched from the backend API, organized into three columns: 'To Do', 'In Progress', and 'Done'. Tasks are grouped by status mapping:
- **To Do**: 'planned', 'ready', 'blocked'
- **In Progress**: 'active', 'awaiting_qa', 'waiting_human'
- **Done**: 'complete', 'failed_qa', 'abandoned'

Follows Spec/dashboard_frontend_spec.md for architecture, types, API (src/api/tasks.ts), hooks (useTasks.ts), and WebSocket integration.

## Dependencies
- Existing: src/api/client.ts, src/types/api.ts (Task type), src/api/websocket.ts
- Run-scoped: Assumes runId prop or context from RunDetailPage.

## Key Features
1. Fetch tasks on mount via GET /api/runs/{runId}/tasks
2. Render tasks in columns with drag-drop reordering (no backend move yet, UI only)
3. Real-time updates via WebSocket 'task_update' events
4. Responsive grid layout with TailwindCSS

## File Changes
- src/components/tasks/TaskKanban.tsx (new)
- src/hooks/useTasks.ts (new)
- src/api/tasks.ts (add listTasks)
- Update RunDetailPage.tsx to use TaskKanban in 'list' tab

## Status Mapping
const columnMap = {
  todo: ['planned', 'ready', 'blocked'],
  progress: ['active', 'awaiting_qa', 'waiting_human'],
  done: ['complete', 'failed_qa', 'abandoned']
};