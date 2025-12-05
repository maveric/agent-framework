# Task Creation Implementation Plan (task_c4b)

## Overview
Enables UI task creation per spec: input+button → POST /api/tasks → instant To Do render. 4 atomic commits.

## Backend (1 commit)
src/server.py: POST /api/tasks → SQLite insert → return ID.

## Frontend (2 commits)
1. TaskInput.tsx: Form + API call + states.
2. KanbanBoard.tsx: Integrate w/ optimistic React Query mutation.

## Test (1 commit)
E2E Playwright: full flow verification.

Follows design_spec.md architecture. Dependencies sequential.