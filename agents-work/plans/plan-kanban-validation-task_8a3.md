# Kanban Board Validation Plan (Task ID: 8a3)

## Component Overview
Plan for comprehensive testing of Kanban board features per design_spec.md (Spec/dashboard_frontend_spec.md): backend API endpoints (/api/runs/{runId}/tasks), frontend logic (TaskKanban.tsx, useTasks.ts, api/tasks.ts), workflows (add/move/delete tasks via drag-drop/status update, WS real-time updates). Unit tests for components/hooks/endpoints. E2E for full flows. No new deps: pytest/FastAPI TestClient (backend), Vitest/RTL (frontend), Playwright (E2E).

## Granularity
Commit-level: atomic test suites with 100% coverage per endpoint/component/flow.

## Tasks Overview
1. Backend pytest setup + task API unit tests (CRUD).
2. Frontend Vitest setup + hook/component unit tests.
3. Playwright E2E setup.
4. E2E tests: add task, move (drag-drop + status update), delete, WS updates.

## Dependencies
Backend tests independent. Frontend units after API stable. E2E after all implemented (depends on prior Kanban plans: foundation, creation, deletion, display, board).

Follow design_spec.md strictly - tests only, no features.

## File Changes
- src/tests/test_kanban_tasks.py (backend units)
- orchestrator-dashboard/src/__tests__/kanban.test.tsx (frontend units)
- orchestrator-dashboard/e2e/kanban.spec.ts (E2E)
- playwright.config.ts updates