# Kanban Board Validation Tests Plan (task_0c7)

## Component Overview
Comprehensive validation of Kanban board per design_spec.md (Spec/dashboard_spec.py, Spec/dashboard_frontend_spec.md). Covers backend APIs (/api/runs/{run_id} tasks extraction), frontend components/hooks (KanbanBoard, TaskCard, useTasks), E2E user flows (view tasks grouped by status, mock WS updates shifting columns). Uses pytest (backend), Vitest/RTL (frontend units), Playwright (E2E). 100% coverage for critical paths. No new features.

## Dependencies
- Backend: src/server.py stable with task data in run responses
- Frontend: orchestrator-dashboard/src/{api/tasks.ts, hooks/useTasks.ts, components/tasks/{KanbanBoard.tsx, TaskCard.tsx}} from prior plans
- Existing: src/tests/, frontend no-tests-yet → create tests/

## Tasks (Commit-Level)
1. Backend pytest: API endpoints + task extraction
2. Frontend Vitest setup + component/hook units
3. Playwright E2E setup + core flows
4. Coverage reports + CI integration tests

Follow design_spec.md strictly—no features, tests only.

## Backend Tests (pytest)
- test_get_run_tasks: Mock DB state → verify tasks list, status counts
- test_run_status_with_tasks: interrupted → task_counts accurate
- WS mock: task_update → state_update broadcast

## Frontend Units (Vitest + RTL)
- TaskCard: renders id/phase/desc/status/retry; snapshots match STATUS_COLORS
- KanbanBoard: groups by STATUS_TO_COLUMN; empty states; responsive
- useTasks: fetches/invalidates on WS; optimistic updates (if add impl)

## E2E (Playwright)
- Navigate RunDetails → Kanban tab loads columns
- Mock WS task_update → task moves columns real-time
- Responsive: mobile viewport → h-scroll
- Perf: load <2s

## File Changes
```
src/tests/test_kanban_api.py          (pytest: endpoints, mocks)
orchestrator-dashboard/
├── vitest.config.ts                  (setup)
├── src/__tests__/
│   ├── useTasks.test.tsx             (React Query + WS)
│   ├── KanbanBoard.test.tsx          (render/grouping)
│   └── TaskCard.test.tsx             (UI/status)
└── playwright.config.ts              (update)
  └── e2e/kanban.spec.ts              (flows)
```

## Success Criteria
- Backend: 100% pass; mocks DB state → correct JSON
- Frontend: snapshots; RTL queries find 3 columns + task counts
- E2E: video record; tasks shift on mock WS
- Coverage: >90% on Kanban files