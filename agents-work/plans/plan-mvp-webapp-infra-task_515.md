# MVP Web App Infrastructure Implementation Plan (Task 515)

## Component Overview
This component establishes the foundational infrastructure for the MVP web application dashboard as specified in Spec/dashboard_spec.py (backend API) and Spec/dashboard_frontend_spec.md (frontend). The current codebase has partial scaffolding (src/server.py FastAPI, orchestrator-dashboard Vite React, orchestrator.db SQLite), but needs structured backend per spec, full frontend setup, and verification of integration.

**Scope Constraints (Strictly Enforced):**
- Backend: Structured FastAPI with routers, Pydantic models, SQLite checkpointer integration (NO new features like auth, Docker).
- Frontend: Vite + React-TS + TanStack Query + Tailwind + ReactFlow (per spec deps/structure, NO routing/auth yet).
- Persistence: Leverage existing orchestrator.db (LangGraph checkpointer), init any custom tables.
- Integration: CORS, API client fetches /api/runs, basic WebSocket connect.
- NO: Full dashboard pages, E2E features, deployment, extras.

## Architecture Alignment
- Backend: backend/main.py → api/runs.py → services/orchestrator.py → models/
- Frontend: orchestrator-dashboard/src/api/client.ts → hooks/useRuns.ts → pages/Dashboard.tsx
- DB: orchestrator.db (existing)

## Implementation Phases
1. **Backend Scaffold** (structured dirs/files per spec)
2. **DB Init** (custom tables if needed)
3. **Basic API** (runs list/create stub)
4. **Frontend Scaffold** (deps, types, api client)
5. **Integration** (frontend fetches backend)
6. **Verification** (unit/integration tests)

## Risks/Mitigations
- Existing server.py monolithic → Restructure minimally, preserve endpoints.
- DB conflicts → Use existing checkpointer.
- Windows paths → Relative paths only.

## Success Metrics (Acceptance Criteria)
- Backend: `uvicorn backend.main:app` runs, /health, /api/runs returns JSON.
- Frontend: `npm run dev`, page loads, fetches /api/runs.
- DB: Tables exist, writable.
- Tests: 100% pass.

## Task Breakdown
See subtasks below (commit-level). Each build task includes unit tests inline.

**Total LOC estimate:** ~1500 (scaffolds + stubs + tests)
**Timeline:** 4-6 worker cycles (parallel frontend/backend possible after DB).