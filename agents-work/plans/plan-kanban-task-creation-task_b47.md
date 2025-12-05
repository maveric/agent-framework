# Kanban Task Creation UI Implementation Plan

## Component Overview
Implements task creation UI for Kanban board per task spec. Adds input + button at page top, POST /api/tasks backend endpoint, optimistic updates for instant 'To Do' column render. Follows design_spec.md architecture.

## Backend Changes
- src/server.py: Add POST /api/tasks endpoint using SQLite tasks table.

## Frontend Changes  
- orchestrator-dashboard/src/components/TaskInput.tsx (new)
- Update KanbanBoard.tsx to integrate input + optimistic updates via React Query
- Add useTasks hook with mutations

## Verification
- Backend unit test confirms DB insert
- Frontend E2E test verifies UI flow + column render

Granularity: 4 atomic commits (1 backend, 2 frontend build, 1 test).