# Task Kanban Display Implementation Plan (task_02a)

## Component Overview
Implements Kanban board for viewing tasks organized in 'To Do', 'In Progress', 'Done' columns. Fetches from backend GET /api/runs/{runId}/tasks (per Spec/dashboard_spec.py). Groups tasks by status:
- **To Do**: planned, ready, blocked
- **In Progress**: active, awaiting_qa, waiting_human  
- **Done**: complete, failed_qa, abandoned

Follows design_spec.md (Spec/dashboard_frontend_spec.md) for types (TaskSummary), API structure (src/api/tasks.ts), hooks (useTasks.ts), UI (TaskCard in src/components/tasks/).

## Dependencies
- Backend: Existing GET /api/runs/{runId}/tasks endpoint (confirmed in src/server.py)
- Frontend: src/types/api.ts (Task), src/api/client.ts, TailwindCSS setup
- Scoped to run: Requires runId prop (from RunDetailPage)

## Key Features (MVP - per acceptance criteria)
1. Fetch all tasks on load via GET /api/runs/{runId}/tasks
2. Group into 3 columns by status mapping
3. Render distinct TaskCard per task (id, description, status badge, phase)
4. Responsive horizontal scroll on mobile
5. No drag-drop (UI preview only, no backend persistence)

## File Changes (minimal, atomic)
```
orchestrator-dashboard/
├── src/api/tasks.ts          (new: listTasks)
├── src/hooks/useTasks.ts     (new: React Query hook)
├── src/components/tasks/
│   ├── TaskKanban.tsx        (new: board + columns)
│   └── TaskCard.tsx          (new: card UI)
└── src/pages/RunDetailPage.tsx (update: replace TaskList tab with TaskKanban)
```

## Status-to-Column Mapping
```ts
const COLUMNS = {
  todo: ['planned', 'ready', 'blocked'],
  progress: ['active', 'awaiting_qa', 'waiting_human'],
  done: ['complete', 'failed_qa', 'abandoned']
} as const;
```

## Visual Design (Tailwind)
- Columns: flex min-w-[320px], gap-4, h-[600px], scroll-x
- Cards: shadow-md, p-4, rounded-lg, hover:lift
- Status badge: color-coded per TaskStatus (reuse TaskStatusBadge if exists)
- Empty state: \"No tasks in this column\"

## Integration
- Mount in RunDetailPage 'list' tab: &lt;TaskKanban runId={runId} /&gt;
- Real-time: useWSMessage('task_update') to refetch/invalidate query

## Success Criteria
- Loads 10+ tasks → correct column placement (manual verify)
- Status colors match spec STATUS_COLORS
- Responsive: stacks vertical on mobile
- No console errors, fast mount (&lt;500ms)

## Risks/Blockers
- API returns full TaskDetail? Use TaskSummary slicing if needed
- No /api/tasks global → run-scoped only (per spec)

## Next (out-of-scope)
- Drag-drop (requires PUT /tasks/{id}/move)
- Filtering/sorting
- Bulk actions
