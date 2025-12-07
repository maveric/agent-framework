# Dashboard Items List/Grid View Implementation Plan
**Task ID:** dashboard-items-list-grid-task_a1b  
**Component:** dashboard-items-viewer  
**Follows:** Spec/dashboard_frontend_spec.md  

## Overview
Implement a toggleable list/grid view for viewing orchestrator **items** (runs/tasks) in an organized, accessible layout. Supports real-time updates via WebSocket when items are added/removed/modified.

**Acceptance Criteria (from task):**
- [ ] User can see items in list **OR** grid layout
- [ ] View auto-updates when items added/removed (via WS `state_update`/`task_update`)

**Scope Constraints (ZERO expansion):**
- ONLY list/grid toggle for existing data (runs/tasks from API/WS)
- NO new API endpoints, auth, persistence, styling beyond Tailwind, animations
- Use existing: React Query hooks, WS store, TaskGraph patterns
- Accessibility: ARIA labels, keyboard nav (WCAG 2.1 A)
- Responsive: mobile-first (Tailwind breakpoints)

**Tech Stack (per spec):**
- React 18 + TS
- TailwindCSS (grid/list flex layouts)
- React Query (polling + optimistic updates)
- Lucide icons (view toggle)
- Existing types: RunSummary, TaskSummary

## Architecture Decisions
1. **New Component:** `ItemsView.tsx` (generic for runs/tasks)
   - Props: `items: Item[]`, `viewMode: 'list'|'grid'`, `onToggleView`, `onItemClick`
   - Internal: useLayoutEffect for WS-driven re-renders
2. **Integration:** Wrap in RunDetails/Dashboard pages
3. **Real-time:** useWSMessage('state_update') → optimistic update local state
4. **Layout:**
   | View  | Mobile | Desktop |
   |-------|--------|---------|
   | List  | 1-col  | Cards   |
   | Grid  | 1-col  | 2-4 col |
5. **Accessibility:** `role="list"`, `aria-label`, `tabindex`, screenreader-only text

## File Changes (est. 200-300 LOC)
```
orchestrator-dashboard/src/components/
├── ItemsView.tsx           [NEW ~150 LOC]
└── ui/
    └── ViewToggle.tsx     [NEW ~50 LOC] (List/Grid icons)

orchestrator-dashboard/src/hooks/
└── useItemsView.ts        [NEW ~50 LOC] (WS + RQ integration)

orchestrator-dashboard/src/pages/
├── Dashboard.tsx           [+20 LOC] (use ItemsView for runs)
└── RunDetails.tsx          [+20 LOC] (use ItemsView for tasks)
```

## Dependencies
- Existing: useRuns, useTasks, useWebSocketStore
- NO new deps

## Success Metrics
- Loads 20+ items smoothly (<500ms)
- Toggle switches instantly
- WS updates reflect in <1s
- Keyboard-navigable (Tab/Enter selects item)
- Mobile: stacks vertically

## Potential Gotchas
- WS optimistic updates: use `key={item.id+timestamp}` for React re-render
- Grid responsiveness: Tailwind `grid-cols-1 md:grid-cols-2 xl:grid-cols-4`
- Accessibility: `role="grid"` for grid, `role="list"` for list

**Next:** Execute subtasks below.

---

**Subtasks will be created via `create_subtasks` tool.**
