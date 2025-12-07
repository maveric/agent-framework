# Dashboard Data Viewing Implementation Plan
## Component: Data Viewing (Runs List + Run Detail)
**Task ID:** cf6  
**Spec Reference:** Spec/dashboard_frontend_spec.md + Spec/dashboard_spec.py  
**Current State:** Backend APIs exist (/api/runs, /api/runs/{id}, WS /ws). Frontend skeleton present (App.tsx, api/, components/). Need UI for run list/detail, polling/WS auto-updates.

## Architecture Overview
- **Backend:** Use existing FastAPI endpoints + WebSocket for real-time.
- **Frontend:** React + TanStack Query (polling) + Zustand WS store.
- **Data Flow:** Query /api/runs → RunList; /api/runs/{id} → RunDetail; WS subscribe → auto-refresh.
- **Auto-Updates:** React Query refetchInterval (10s runs, 5s detail) + WS invalidates queries.
- **Types:** Match backend Pydantic (RunSummary, RunDetail, Task).

## MVP Scope (Strictly Spec)
1. Runs list page (table/cards).
2. Run detail: task list/graph, status, task counts.
3. Real-time updates via WS.
4. Responsive Tailwind UI.
**NO:** HITL queue, create/pause/resume (out of scope).

## File Changes
```
orchestrator-dashboard/src/
├── types/api.ts          # RunSummary, RunDetail, Task (from spec)
├── api/
│   ├── client.ts         # Fetch wrapper
│   └── runs.ts           # runsApi.list/get
├── hooks/
│   └── useRuns.ts        # useQuery for list/detail + WS integration
├── components/runs/
│   ├── RunList.tsx
│   └── RunCard.tsx
├── components/tasks/
│   └── TaskList.tsx      # Simple table (no graph for MVP)
├── pages/
│   ├── RunsPage.tsx
│   └── RunDetailPage.tsx
└── App.tsx               # Router setup
```

## Dependencies
- Backend endpoints (exists).
- Tailwind (exists).

## Risks/Blockers
- WS message format mismatch → align with server.py broadcasts.
- DB state serialization → handle task_memories messages.

## Success Criteria
- View /runs → list updates every 10s + WS.
- Click run → detail with tasks, updates 5s/WS.
- E2E: Create run via curl → appears + updates.

## Subtasks
(Defined via create_subtasks tool)