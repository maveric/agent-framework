# Task Kanban Display Implementation Plan (task_4d3)

## Component Overview
Implements a responsive Kanban board displaying tasks in three columns: 'To Do', 'In Progress', 'Done'. Tasks fetched dynamically from backend GET /api/runs/{runId} (tasks array in response, per current server.py; aligns with Spec/dashboard_spec.py /runs/{run_id}/tasks). Groups by status mapping. Updates on page load and via WebSocket 'task_update' events.

Follows Spec/dashboard_frontend_spec.md for architecture: React Query (useQuery refetchInterval + invalidation), Zustand WS store, Task types, Tailwind UI, TaskCard/TaskList patterns. Run-scoped (requires runId prop).

## Dependencies
- Backend: /api/runs/{runId} returns 'tasks' array with TaskStatus
- Frontend: orchestrator-dashboard/src/api/client.ts, websocket.ts exist; types/api.ts (Task); Tailwind setup
- Previous: RunDetailPage tabs (graph/list); WS subscription in RunDetailPage

## Key Features (MVP per acceptance criteria)
1. Fetch tasks via GET /api/runs/{runId} → extract .tasks
2. Group/render in columns by status:
   - To Do: 'planned', 'ready', 'blocked'
   - In Progress: 'active', 'awaiting_qa', 'waiting_human'
   - Done: 'complete', 'failed_qa', 'abandoned'
3. Each task: TaskCard (id, phase badge, description truncate, status badge, retry count)
4. Dynamic: React Query auto-refetch (5s); invalidate on WS 'task_update'/'state_update'
5. Responsive: horizontal scroll mobile; empty states
6. No interactions (view-only; drag-drop out-of-scope)

## File Changes (atomic commits)
```
orchestrator-dashboard/src/
├── api/tasks.ts              (new: tasksApi.list(runId))
├── hooks/useTasks.ts         (new: useTasks(runId) React Query + WS invalidation)
├── components/tasks/
│   ├── TaskCard.tsx          (new: reusable card UI)
│   └── KanbanBoard.tsx       (new: columns + TaskCard grid)
└── pages/RunDetailPage.tsx   (update: &lt;KanbanBoard runId={runId} /&gt; in 'list' TabsContent)
```

## Status-to-Column Mapping
```ts
const STATUS_TO_COLUMN: Record<TaskStatus, keyof typeof COLUMNS> = {
  planned: 'todo', ready: 'todo', blocked: 'todo',
  active: 'progress', awaiting_qa: 'progress', waiting_human: 'progress',
  complete: 'done', failed_qa: 'done', abandoned: 'done'
};
const COLUMNS = { todo: 'To Do', progress: 'In Progress', done: 'Done' } as const;
```

## Visual Design (Tailwind + spec STATUS_COLORS)
- Board: flex gap-6 overflow-x-auto h-[600px] pb-6
- Column: min-w-[350px] bg-gray-50 rounded-xl p-6 shadow-lg
  - Header: font-bold text-xl flex justify-between (count badge)
  - Tasks: grid grid-cols-1 gap-4 (cards hover:shadow-xl transition-all)
- Card: bg-white p-4 rounded-lg border shadow-md h-[120px]
  - Header: flex id + phase badge (small colored pill)
  - Body: description (2-line truncate)
  - Footer: status badge (colored per STATUS_COLORS) + retry icon if >0
- Empty: text-gray-500 text-center py-12 'No tasks here yet...'

## Integration
- In RunDetailPage 'list' tab: replace TaskList with &lt;KanbanBoard runId={runId} /&gt;
- WS: useWSMessage('task_update', 'state_update') → queryClient.invalidateQueries(['tasks', runId])
- Reuse: STATUS_COLORS from TaskGraph; types from api.ts

## Success Criteria (3-6 per task)
- Loads run with 10+ tasks → correct column counts (manual: To Do=3, Progress=4, Done=3)
- Status badges match colors (planned=gray, active=purple, complete=green)
- WS update: simulate task status change → column shift + refetch <1s
- Responsive: mobile viewport → horizontal scroll works, cards stack
- Perf: initial load <1s; no hydration mismatch
- Accessibility: keyboard nav, ARIA labels on cards/columns

## Risks/Blockers
- Backend /runs/{runId} tasks format mismatch → use task_to_dict util if needed
- WS not firing task_update → fallback to refetchInterval:5000
- No /runs/{runId}/tasks → extract from get_run response (current impl)

## Next (out-of-scope per spec)
- Drag-drop (POST /tasks/{id}/status)
- Filters/search
- Bulk actions
- Task detail modals