# Testing Plan for Orchestrator Dashboard (Backend + Frontend)
Task ID: 2d7

## Overview
Follow design_spec.md (Spec/dashboard_spec.py and Spec/dashboard_frontend_spec.md). Create comprehensive unit tests for all REST API endpoints (backend) and frontend JS logic. Add E2E tests for critical flows: create run/add task, task status changes (move), abandon task (delete).

**Backend Testing**: pytest + FastAPI TestClient for API endpoints.
**Frontend Testing**: Vitest + React Testing Library for components/hooks.
**E2E Testing**: Playwright for user flows.

**No new deps beyond pytest (backend), vitest/react-testing-library/playwright (frontend).**

## Backend Structure
```
src/tests/
├── test_api_endpoints.py     # Unit tests for all FastAPI routes
└── conftest.py               # Test fixtures (app, client, mock orchestrator)
```

## Frontend Structure  
```
orchestrator-dashboard/
├── src/__tests__/
│   ├── api.test.ts          # API client tests
│   ├── hooks.test.ts        # Custom hooks
│   ├── components.test.tsx  # Key components (TaskGraph, HumanQueue, etc.)
└── e2e/
    └── dashboard.spec.ts    # Playwright E2E flows
```

## Critical Coverage
- **Backend**: 100% endpoints (/runs, /tasks, /hitl, /ws health checks)
- **Frontend**: Hooks (useRuns, useWebSocket), Components (TaskGraph, ResolutionModal)
- **E2E**: Create run → View tasks → Resolve HITL (retry/abandon) → Task status updates

