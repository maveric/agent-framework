# Kanban Task Creation Implementation Plan

Follow design_spec.md for architecture details.

## Overview
Enable users to create tasks via UI input/button at page top → POST /api/tasks → DB store → instant render in 'To Do' column (optimistic update, no reload).

## Backend (src/server.py)
Add POST /api/tasks: accept {title:string} → insert tasks table (id=uuid, title, status='todo', column='To Do') → return task JSON.

## Frontend (orchestrator-dashboard)
- TaskInput.tsx: input + Add button.
- Integrate to KanbanBoard top with React Query optimistic mutation.
- useTasks hook.

## Tasks
4 atomic commits with verification. Sequential deps: backend → UI → integration → test.