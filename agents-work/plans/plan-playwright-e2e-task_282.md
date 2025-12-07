# Playwright E2E Tests Implementation Plan - Task 282

## Overview
End-to-end validation of core dashboard features using Playwright. Tests cover the full user flows for managing orchestrator runs and tasks as specified in Spec/dashboard_frontend_spec.md and Spec/dashboard_spec.py. Tests run against a running dev server (frontend: localhost:5173, backend: localhost:8000).

## Scope (Strictly from Spec)
- Dashboard: View runs list, create new run
- Run Detail: View task graph, task list, insights, design log
- Human Queue: View pending tasks, approve/reject/modify
- Controls: Pause/resume runs
- Real-time: WebSocket updates reflected in UI
- NO: Backend unit tests, component unit tests, deployment tests

## Prerequisites
- Backend running: `uvicorn main:app --port 8000 --reload`
- Frontend dev server: `npm run dev`
- Playwright installed: `npx playwright install`

## Test Strategy
1. **Smoke tests**: Core pages load without errors
2. **Happy path**: Create run → View details → Interact with tasks/HITL
3. **Real-time**: Verify WS updates change UI state
4. **Error states**: Invalid actions show errors gracefully
5. **Cross-browser**: Chrome, Firefox, WebKit

## File Structure
```
e2e/
├── playwright.config.ts
├── tests/
│   ├── dashboard.spec.ts     # Homepage + create run
│   ├── run-detail.spec.ts   # Run details + graph
│   ├── human-queue.spec.ts  # HITL resolution
│   └── real-time.spec.ts    # WS updates
└── fixtures/
    └── runs.ts              # API state setup
```

## Success Metrics
- 100% pass rate on CI
- Covers all acceptance criteria
- <30s total test runtime
- Visual regression snapshots

Follow Spec/dashboard_frontend_spec.md for UI structure and Spec/dashboard_spec.py for API contracts.
