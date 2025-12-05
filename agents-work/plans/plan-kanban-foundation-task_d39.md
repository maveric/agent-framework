# Kanban Foundation Implementation Plan (task_d39)

## Overview
This plan establishes the foundational infrastructure for the Kanban board app as per the task requirements and design_spec.md reference. Scope is strictly limited to:
- Flask backend initialization
- SQLite database setup with 'tasks' table
- Single-file frontend (index.html with embedded CSS/JS)

No extras (no auth, no advanced UI, no deployment).

## Architecture
- Backend: Flask app serving API and static files
- DB: SQLite 'kanban.db' with table `tasks` (id INTEGER PRIMARY KEY, title TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'todo')
- Frontend: Single `static/index.html` with inline CSS/JS for basic board display (3 columns: Todo, In Progress, Done)

## Granularity
Commit-level tasks, each ~100-300 LOC, self-contained with verification.

## Task Breakdown
See subtasks below for atomic changes.