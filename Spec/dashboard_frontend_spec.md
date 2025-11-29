# Orchestrator Dashboard — Frontend Specification

Version 1.0 — November 2025

A production-ready React frontend for monitoring and controlling the agent orchestrator.

## Quick Start

```bash
# Create project
npm create vite@latest orchestrator-dashboard -- --template react-ts
cd orchestrator-dashboard

# Install dependencies
npm install @tanstack/react-query @tanstack/react-router
npm install reactflow dagre
npm install zustand
npm install tailwindcss postcss autoprefixer
npm install @radix-ui/react-dialog @radix-ui/react-tabs @radix-ui/react-select
npm install lucide-react
npm install date-fns

# Initialize Tailwind
npx tailwindcss init -p
```

---

## Directory Structure

```
src/
├── api/
│   ├── client.ts           # Fetch wrapper with auth
│   ├── runs.ts             # Run API calls
│   ├── tasks.ts            # Task API calls
│   └── websocket.ts        # WebSocket manager
├── components/
│   ├── ui/                 # Reusable UI components
│   │   ├── Badge.tsx
│   │   ├── Button.tsx
│   │   ├── Card.tsx
│   │   ├── Dialog.tsx
│   │   ├── Select.tsx
│   │   └── Tabs.tsx
│   ├── layout/
│   │   ├── Header.tsx
│   │   ├── Sidebar.tsx
│   │   └── Layout.tsx
│   ├── runs/
│   │   ├── RunList.tsx
│   │   ├── RunCard.tsx
│   │   ├── RunDetail.tsx
│   │   └── CreateRunDialog.tsx
│   ├── tasks/
│   │   ├── TaskList.tsx
│   │   ├── TaskCard.tsx
│   │   ├── TaskDetail.tsx
│   │   ├── TaskGraph.tsx
│   │   └── ArtifactViewer.tsx
│   ├── human/
│   │   ├── HumanQueue.tsx
│   │   ├── ResolveTaskDialog.tsx
│   │   └── EscalationDialog.tsx
│   └── logs/
│       └── LogStream.tsx
├── hooks/
│   ├── useRuns.ts
│   ├── useTasks.ts
│   ├── useWebSocket.ts
│   └── useHumanQueue.ts
├── stores/
│   └── websocket.ts        # Zustand store for WS state
├── types/
│   └── api.ts              # TypeScript types matching backend
├── pages/
│   ├── Dashboard.tsx
│   ├── RunsPage.tsx
│   ├── RunDetailPage.tsx
│   └── HumanQueuePage.tsx
├── App.tsx
└── main.tsx
```

---

## Types (src/types/api.ts)

```typescript
// =============================================================================
// ENUMS
// =============================================================================

export type RunStatus = 
  | 'running' 
  | 'paused' 
  | 'completed' 
  | 'failed' 
  | 'waiting_human';

export type TaskStatus = 
  | 'planned'
  | 'ready'
  | 'blocked'
  | 'active'
  | 'awaiting_qa'
  | 'failed_qa'
  | 'complete'
  | 'waiting_human'
  | 'abandoned';

export type TaskPhase = 'plan' | 'build' | 'test';

export type HumanAction = 
  | 'approve' 
  | 'reject' 
  | 'modify' 
  | 'retry' 
  | 'escalate' 
  | 'provide_input';

// =============================================================================
// RUN TYPES
// =============================================================================

export interface RunSummary {
  run_id: string;
  objective: string;
  status: RunStatus;
  created_at: string;
  updated_at: string;
  task_counts: Record<TaskStatus, number>;
  tags: string[];
}

export interface RunDetail extends RunSummary {
  spec: Record<string, any>;
  strategy_status: string;
  tasks: Task[];
  insights: Insight[];
  design_log: DesignDecision[];
  guardian: Record<string, any>;
}

export interface CreateRunRequest {
  objective: string;
  spec?: Record<string, any>;
  tags?: string[];
}

// =============================================================================
// TASK TYPES
// =============================================================================

export interface Task {
  id: string;
  component: string;
  phase: TaskPhase;
  description: string;
  status: TaskStatus;
  priority: number;
  assigned_worker_profile?: string;
  depends_on: string[];
  acceptance_criteria: string[];
  retry_count: number;
  result_path?: string;
  qa_verdict?: QAVerdict;
  aar?: AAR;
  escalation?: Escalation;
  blocked_reason?: BlockedReason;
  created_at?: string;
  started_at?: string;
  completed_at?: string;
}

export interface TaskSummary {
  id: string;
  component: string;
  phase: TaskPhase;
  description: string;
  status: TaskStatus;
  priority: number;
  assigned_worker_profile?: string;
  retry_count: number;
  has_escalation: boolean;
  needs_human: boolean;
}

export interface QAVerdict {
  passed: boolean;
  criterion_results: CriterionResult[];
  overall_feedback: string;
  suggested_focus?: string;
}

export interface CriterionResult {
  criterion: string;
  passed: boolean;
  reasoning: string;
  suggestions?: string;
}

export interface AAR {
  summary: string;
  approach: string;
  challenges: string[];
  decisions_made: string[];
  files_modified: string[];
  time_spent_estimate: string;
}

export interface Escalation {
  type: string;
  reason: string;
  context: Record<string, any>;
  blocking: boolean;
}

export interface BlockedReason {
  type: string;
  reason: string;
  blocked_since: string;
}

// =============================================================================
// HUMAN RESOLUTION TYPES
// =============================================================================

export interface HumanResolution {
  action: HumanAction;
  feedback?: string;
  modified_criteria?: string[];
  modified_description?: string;
  input_data?: Record<string, any>;
}

export interface EscalationResolution {
  action: 'resolve' | 'dismiss' | 'reassign';
  resolution_notes: string;
  new_task_description?: string;
  spec_clarification?: Record<string, any>;
}

// =============================================================================
// OTHER TYPES
// =============================================================================

export interface Insight {
  topic: string[];
  summary: string;
  source_task?: string;
  added_at: string;
}

export interface DesignDecision {
  id: string;
  area: string;
  applies_to: string[];
  summary: string;
  reason: string;
  timestamp: string;
}

// =============================================================================
// WEBSOCKET TYPES
// =============================================================================

export type WSMessageType = 
  | 'state_update'
  | 'task_update'
  | 'log_message'
  | 'human_needed'
  | 'run_complete'
  | 'error'
  | 'heartbeat'
  | 'subscribe'
  | 'unsubscribe'
  | 'subscribed'
  | 'unsubscribed'
  | 'ping'
  | 'pong';

export interface WSMessage {
  type: WSMessageType;
  run_id?: string;
  payload: Record<string, any>;
  timestamp: string;
}
```

---

## API Client (src/api/client.ts)

```typescript
const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000';

interface FetchOptions extends RequestInit {
  params?: Record<string, string>;
}

export async function apiClient<T>(
  endpoint: string,
  options: FetchOptions = {}
): Promise<T> {
  const { params, ...fetchOptions } = options;
  
  let url = `${API_BASE}${endpoint}`;
  if (params) {
    const searchParams = new URLSearchParams(params);
    url += `?${searchParams.toString()}`;
  }

  const response = await fetch(url, {
    ...fetchOptions,
    headers: {
      'Content-Type': 'application/json',
      ...fetchOptions.headers,
    },
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Unknown error' }));
    throw new Error(error.detail || `HTTP ${response.status}`);
  }

  return response.json();
}
```

---

## API Hooks (src/api/runs.ts)

```typescript
import { apiClient } from './client';
import type { RunSummary, RunDetail, CreateRunRequest } from '../types/api';

export const runsApi = {
  list: (params?: { status?: string; tag?: string; limit?: number }) =>
    apiClient<RunSummary[]>('/api/runs', { params: params as Record<string, string> }),

  get: (runId: string) =>
    apiClient<RunDetail>(`/api/runs/${runId}`),

  create: (request: CreateRunRequest) =>
    apiClient<{ run_id: string }>('/api/runs', {
      method: 'POST',
      body: JSON.stringify(request),
    }),

  pause: (runId: string) =>
    apiClient<{ status: string }>(`/api/runs/${runId}/pause`, { method: 'POST' }),

  resume: (runId: string) =>
    apiClient<{ status: string }>(`/api/runs/${runId}/resume`, { method: 'POST' }),
};
```

---

## React Query Hooks (src/hooks/useRuns.ts)

```typescript
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { runsApi } from '../api/runs';
import type { CreateRunRequest } from '../types/api';

export function useRuns(params?: { status?: string; tag?: string }) {
  return useQuery({
    queryKey: ['runs', params],
    queryFn: () => runsApi.list(params),
    refetchInterval: 10000, // Poll every 10s
  });
}

export function useRun(runId: string) {
  return useQuery({
    queryKey: ['runs', runId],
    queryFn: () => runsApi.get(runId),
    refetchInterval: 5000, // Poll every 5s
    enabled: !!runId,
  });
}

export function useCreateRun() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (request: CreateRunRequest) => runsApi.create(request),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['runs'] });
    },
  });
}

export function usePauseRun() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (runId: string) => runsApi.pause(runId),
    onSuccess: (_, runId) => {
      queryClient.invalidateQueries({ queryKey: ['runs', runId] });
    },
  });
}

export function useResumeRun() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (runId: string) => runsApi.resume(runId),
    onSuccess: (_, runId) => {
      queryClient.invalidateQueries({ queryKey: ['runs', runId] });
    },
  });
}
```

---

## WebSocket Manager (src/api/websocket.ts)

```typescript
import { create } from 'zustand';
import type { WSMessage, WSMessageType } from '../types/api';

const WS_URL = import.meta.env.VITE_WS_URL || 'ws://localhost:8000/ws';

interface WebSocketState {
  socket: WebSocket | null;
  connected: boolean;
  subscribedRuns: Set<string>;
  messages: WSMessage[];
  connect: () => void;
  disconnect: () => void;
  subscribe: (runId: string) => void;
  unsubscribe: (runId: string) => void;
  addMessageHandler: (type: WSMessageType, handler: (msg: WSMessage) => void) => () => void;
}

type MessageHandler = (msg: WSMessage) => void;
const messageHandlers = new Map<WSMessageType, Set<MessageHandler>>();

export const useWebSocketStore = create<WebSocketState>((set, get) => ({
  socket: null,
  connected: false,
  subscribedRuns: new Set(),
  messages: [],

  connect: () => {
    const socket = new WebSocket(WS_URL);

    socket.onopen = () => {
      set({ connected: true });
      console.log('WebSocket connected');
      
      // Re-subscribe to runs
      const { subscribedRuns } = get();
      subscribedRuns.forEach((runId) => {
        socket.send(JSON.stringify({ type: 'subscribe', run_id: runId }));
      });
    };

    socket.onclose = () => {
      set({ connected: false });
      console.log('WebSocket disconnected');
      
      // Reconnect after delay
      setTimeout(() => get().connect(), 3000);
    };

    socket.onerror = (error) => {
      console.error('WebSocket error:', error);
    };

    socket.onmessage = (event) => {
      const msg: WSMessage = JSON.parse(event.data);
      
      // Add to message history (keep last 100)
      set((state) => ({
        messages: [...state.messages.slice(-99), msg],
      }));

      // Call registered handlers
      const handlers = messageHandlers.get(msg.type);
      if (handlers) {
        handlers.forEach((handler) => handler(msg));
      }
    };

    set({ socket });
  },

  disconnect: () => {
    const { socket } = get();
    if (socket) {
      socket.close();
      set({ socket: null, connected: false });
    }
  },

  subscribe: (runId: string) => {
    const { socket, subscribedRuns } = get();
    
    if (!subscribedRuns.has(runId)) {
      subscribedRuns.add(runId);
      set({ subscribedRuns: new Set(subscribedRuns) });
      
      if (socket?.readyState === WebSocket.OPEN) {
        socket.send(JSON.stringify({ type: 'subscribe', run_id: runId }));
      }
    }
  },

  unsubscribe: (runId: string) => {
    const { socket, subscribedRuns } = get();
    
    if (subscribedRuns.has(runId)) {
      subscribedRuns.delete(runId);
      set({ subscribedRuns: new Set(subscribedRuns) });
      
      if (socket?.readyState === WebSocket.OPEN) {
        socket.send(JSON.stringify({ type: 'unsubscribe', run_id: runId }));
      }
    }
  },

  addMessageHandler: (type: WSMessageType, handler: MessageHandler) => {
    if (!messageHandlers.has(type)) {
      messageHandlers.set(type, new Set());
    }
    messageHandlers.get(type)!.add(handler);

    // Return cleanup function
    return () => {
      messageHandlers.get(type)?.delete(handler);
    };
  },
}));

// Hook for easy WebSocket message subscription
export function useWSMessage(type: WSMessageType, handler: (msg: WSMessage) => void) {
  const addMessageHandler = useWebSocketStore((s) => s.addMessageHandler);

  React.useEffect(() => {
    return addMessageHandler(type, handler);
  }, [type, handler, addMessageHandler]);
}
```

---

## Task Graph Component (src/components/tasks/TaskGraph.tsx)

```typescript
import React, { useCallback, useMemo } from 'react';
import ReactFlow, {
  Node,
  Edge,
  Background,
  Controls,
  MiniMap,
  useNodesState,
  useEdgesState,
} from 'reactflow';
import dagre from 'dagre';
import 'reactflow/dist/style.css';
import type { Task, TaskStatus } from '../../types/api';

// Status colors
const STATUS_COLORS: Record<TaskStatus, string> = {
  planned: '#94a3b8',
  ready: '#3b82f6',
  blocked: '#f59e0b',
  active: '#8b5cf6',
  awaiting_qa: '#06b6d4',
  failed_qa: '#ef4444',
  complete: '#22c55e',
  waiting_human: '#f97316',
  abandoned: '#6b7280',
};

interface TaskGraphProps {
  tasks: Task[];
  onTaskClick?: (taskId: string) => void;
}

// Layout using dagre
function getLayoutedElements(tasks: Task[]) {
  const dagreGraph = new dagre.graphlib.Graph();
  dagreGraph.setDefaultEdgeLabel(() => ({}));
  dagreGraph.setGraph({ rankdir: 'LR', nodesep: 50, ranksep: 100 });

  const nodeWidth = 200;
  const nodeHeight = 80;

  // Add nodes
  tasks.forEach((task) => {
    dagreGraph.setNode(task.id, { width: nodeWidth, height: nodeHeight });
  });

  // Add edges
  tasks.forEach((task) => {
    task.depends_on.forEach((dep) => {
      if (tasks.find((t) => t.id === dep)) {
        dagreGraph.setEdge(dep, task.id);
      }
    });
  });

  dagre.layout(dagreGraph);

  const nodes: Node[] = tasks.map((task) => {
    const nodeWithPosition = dagreGraph.node(task.id);
    return {
      id: task.id,
      type: 'taskNode',
      position: {
        x: nodeWithPosition.x - nodeWidth / 2,
        y: nodeWithPosition.y - nodeHeight / 2,
      },
      data: { task },
    };
  });

  const edges: Edge[] = [];
  tasks.forEach((task) => {
    task.depends_on.forEach((dep) => {
      if (tasks.find((t) => t.id === dep)) {
        edges.push({
          id: `${dep}-${task.id}`,
          source: dep,
          target: task.id,
          animated: task.status === 'active',
        });
      }
    });
  });

  return { nodes, edges };
}

// Custom node component
function TaskNode({ data }: { data: { task: Task } }) {
  const { task } = data;
  const color = STATUS_COLORS[task.status];

  return (
    <div
      className="px-3 py-2 rounded-lg border-2 bg-white shadow-sm"
      style={{ borderColor: color, minWidth: 180 }}
    >
      <div className="flex items-center gap-2 mb-1">
        <div
          className="w-2 h-2 rounded-full"
          style={{ backgroundColor: color }}
        />
        <span className="text-xs font-medium text-gray-500 uppercase">
          {task.phase}
        </span>
      </div>
      <div className="text-sm font-medium truncate" title={task.id}>
        {task.id}
      </div>
      <div className="text-xs text-gray-500 truncate" title={task.description}>
        {task.description.slice(0, 40)}...
      </div>
      <div className="mt-1 flex items-center gap-2">
        <span
          className="text-xs px-1.5 py-0.5 rounded"
          style={{ backgroundColor: `${color}20`, color }}
        >
          {task.status}
        </span>
        {task.retry_count > 0 && (
          <span className="text-xs text-orange-600">
            ↻{task.retry_count}
          </span>
        )}
      </div>
    </div>
  );
}

const nodeTypes = {
  taskNode: TaskNode,
};

export function TaskGraph({ tasks, onTaskClick }: TaskGraphProps) {
  const { nodes: initialNodes, edges: initialEdges } = useMemo(
    () => getLayoutedElements(tasks),
    [tasks]
  );

  const [nodes, setNodes, onNodesChange] = useNodesState(initialNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(initialEdges);

  // Update when tasks change
  React.useEffect(() => {
    const { nodes: newNodes, edges: newEdges } = getLayoutedElements(tasks);
    setNodes(newNodes);
    setEdges(newEdges);
  }, [tasks, setNodes, setEdges]);

  const onNodeClick = useCallback(
    (_: React.MouseEvent, node: Node) => {
      onTaskClick?.(node.id);
    },
    [onTaskClick]
  );

  return (
    <div className="w-full h-[500px] border rounded-lg">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onNodeClick={onNodeClick}
        nodeTypes={nodeTypes}
        fitView
      >
        <Background />
        <Controls />
        <MiniMap />
      </ReactFlow>
    </div>
  );
}
```

---

## Human Queue Component (src/components/human/HumanQueue.tsx)

```typescript
import React, { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { apiClient } from '../../api/client';
import type { Task, HumanResolution, HumanAction } from '../../types/api';
import { ResolveTaskDialog } from './ResolveTaskDialog';

interface HumanQueueProps {
  runId?: string; // Optional - if not provided, shows global queue
}

export function HumanQueue({ runId }: HumanQueueProps) {
  const [selectedTask, setSelectedTask] = useState<Task | null>(null);
  const queryClient = useQueryClient();

  // Fetch waiting tasks
  const { data: tasks, isLoading } = useQuery({
    queryKey: runId ? ['human-queue', runId] : ['human-queue'],
    queryFn: () =>
      runId
        ? apiClient<Task[]>(`/api/runs/${runId}/human-queue`)
        : apiClient<Array<{ run_id: string; task: Task }>>('/api/human-queue'),
    refetchInterval: 5000,
  });

  // Resolve mutation
  const resolveMutation = useMutation({
    mutationFn: ({
      runId,
      taskId,
      resolution,
    }: {
      runId: string;
      taskId: string;
      resolution: HumanResolution;
    }) =>
      apiClient(`/api/runs/${runId}/tasks/${taskId}/resolve`, {
        method: 'POST',
        body: JSON.stringify(resolution),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['human-queue'] });
      setSelectedTask(null);
    },
  });

  if (isLoading) {
    return <div className="p-4">Loading...</div>;
  }

  const taskList = tasks || [];

  if (taskList.length === 0) {
    return (
      <div className="p-8 text-center text-gray-500">
        <p className="text-lg">No tasks waiting for human review</p>
        <p className="text-sm mt-2">Tasks needing input will appear here</p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <h2 className="text-lg font-semibold">
        Human Review Queue ({taskList.length})
      </h2>

      <div className="space-y-3">
        {taskList.map((item) => {
          const task = 'task' in item ? item.task : item;
          const itemRunId = 'run_id' in item ? item.run_id : runId!;

          return (
            <div
              key={task.id}
              className="p-4 border rounded-lg bg-white shadow-sm"
            >
              <div className="flex items-start justify-between">
                <div className="flex-1">
                  <div className="flex items-center gap-2">
                    <span className="font-medium">{task.id}</span>
                    <span className="text-xs px-2 py-0.5 bg-orange-100 text-orange-700 rounded">
                      Needs Human
                    </span>
                  </div>
                  <p className="text-sm text-gray-600 mt-1">
                    {task.description}
                  </p>
                  {task.escalation && (
                    <div className="mt-2 p-2 bg-yellow-50 border border-yellow-200 rounded text-sm">
                      <span className="font-medium">Escalation: </span>
                      {task.escalation.reason}
                    </div>
                  )}
                </div>

                <div className="flex gap-2 ml-4">
                  <button
                    onClick={() =>
                      resolveMutation.mutate({
                        runId: itemRunId,
                        taskId: task.id,
                        resolution: { action: 'approve' },
                      })
                    }
                    className="px-3 py-1.5 bg-green-600 text-white text-sm rounded hover:bg-green-700"
                  >
                    Approve
                  </button>
                  <button
                    onClick={() =>
                      resolveMutation.mutate({
                        runId: itemRunId,
                        taskId: task.id,
                        resolution: { action: 'reject' },
                      })
                    }
                    className="px-3 py-1.5 bg-red-600 text-white text-sm rounded hover:bg-red-700"
                  >
                    Reject
                  </button>
                  <button
                    onClick={() => setSelectedTask(task)}
                    className="px-3 py-1.5 bg-gray-200 text-gray-700 text-sm rounded hover:bg-gray-300"
                  >
                    More Options
                  </button>
                </div>
              </div>

              {/* Acceptance Criteria */}
              {task.acceptance_criteria.length > 0 && (
                <div className="mt-3 border-t pt-3">
                  <p className="text-xs font-medium text-gray-500 mb-1">
                    Acceptance Criteria:
                  </p>
                  <ul className="text-sm text-gray-600 list-disc list-inside">
                    {task.acceptance_criteria.map((c, i) => (
                      <li key={i}>{c}</li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* Resolve Dialog */}
      {selectedTask && (
        <ResolveTaskDialog
          task={selectedTask}
          onClose={() => setSelectedTask(null)}
          onResolve={(resolution) => {
            // Find run_id for this task
            const item = taskList.find((t) =>
              'task' in t ? t.task.id === selectedTask.id : t.id === selectedTask.id
            );
            const itemRunId = item && 'run_id' in item ? item.run_id : runId!;

            resolveMutation.mutate({
              runId: itemRunId,
              taskId: selectedTask.id,
              resolution,
            });
          }}
          isLoading={resolveMutation.isPending}
        />
      )}
    </div>
  );
}
```

---

## Resolve Task Dialog (src/components/human/ResolveTaskDialog.tsx)

```typescript
import React, { useState } from 'react';
import type { Task, HumanResolution, HumanAction } from '../../types/api';

interface ResolveTaskDialogProps {
  task: Task;
  onClose: () => void;
  onResolve: (resolution: HumanResolution) => void;
  isLoading: boolean;
}

export function ResolveTaskDialog({
  task,
  onClose,
  onResolve,
  isLoading,
}: ResolveTaskDialogProps) {
  const [action, setAction] = useState<HumanAction>('approve');
  const [feedback, setFeedback] = useState('');
  const [modifiedCriteria, setModifiedCriteria] = useState(
    task.acceptance_criteria.join('\n')
  );
  const [modifiedDescription, setModifiedDescription] = useState(task.description);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();

    const resolution: HumanResolution = {
      action,
      feedback: feedback || undefined,
    };

    if (action === 'modify') {
      resolution.modified_criteria = modifiedCriteria
        .split('\n')
        .filter((c) => c.trim());
      resolution.modified_description = modifiedDescription;
    }

    onResolve(resolution);
  };

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-white rounded-lg shadow-xl max-w-2xl w-full max-h-[90vh] overflow-auto">
        <div className="p-6 border-b">
          <h2 className="text-xl font-semibold">Resolve Task</h2>
          <p className="text-sm text-gray-500 mt-1">{task.id}</p>
        </div>

        <form onSubmit={handleSubmit} className="p-6 space-y-4">
          {/* Task Info */}
          <div className="p-4 bg-gray-50 rounded-lg">
            <p className="font-medium">{task.description}</p>
            {task.escalation && (
              <div className="mt-2 p-2 bg-yellow-100 rounded">
                <span className="font-medium">Escalation: </span>
                {task.escalation.reason}
              </div>
            )}
          </div>

          {/* Action Selection */}
          <div>
            <label className="block text-sm font-medium mb-2">Action</label>
            <select
              value={action}
              onChange={(e) => setAction(e.target.value as HumanAction)}
              className="w-full border rounded-lg px-3 py-2"
            >
              <option value="approve">Approve - Continue with current criteria</option>
              <option value="reject">Reject - Abandon this task</option>
              <option value="modify">Modify - Update criteria and retry</option>
              <option value="retry">Retry - Fresh attempt, same criteria</option>
              <option value="provide_input">Provide Input - Give specific data</option>
            </select>
          </div>

          {/* Feedback */}
          <div>
            <label className="block text-sm font-medium mb-2">
              Feedback / Notes
            </label>
            <textarea
              value={feedback}
              onChange={(e) => setFeedback(e.target.value)}
              className="w-full border rounded-lg px-3 py-2 h-24"
              placeholder="Optional feedback for the agent..."
            />
          </div>

          {/* Modify Options */}
          {action === 'modify' && (
            <>
              <div>
                <label className="block text-sm font-medium mb-2">
                  Modified Description
                </label>
                <textarea
                  value={modifiedDescription}
                  onChange={(e) => setModifiedDescription(e.target.value)}
                  className="w-full border rounded-lg px-3 py-2 h-20"
                />
              </div>
              <div>
                <label className="block text-sm font-medium mb-2">
                  Modified Acceptance Criteria (one per line)
                </label>
                <textarea
                  value={modifiedCriteria}
                  onChange={(e) => setModifiedCriteria(e.target.value)}
                  className="w-full border rounded-lg px-3 py-2 h-32 font-mono text-sm"
                />
              </div>
            </>
          )}

          {/* Buttons */}
          <div className="flex justify-end gap-3 pt-4 border-t">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 border rounded-lg hover:bg-gray-50"
              disabled={isLoading}
            >
              Cancel
            </button>
            <button
              type="submit"
              className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50"
              disabled={isLoading}
            >
              {isLoading ? 'Submitting...' : 'Submit Resolution'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
```

---

## Run Detail Page (src/pages/RunDetailPage.tsx)

```typescript
import React, { useEffect } from 'react';
import { useParams } from '@tanstack/react-router';
import { useRun, usePauseRun, useResumeRun } from '../hooks/useRuns';
import { useWebSocketStore } from '../api/websocket';
import { TaskGraph } from '../components/tasks/TaskGraph';
import { TaskList } from '../components/tasks/TaskList';
import { HumanQueue } from '../components/human/HumanQueue';

export function RunDetailPage() {
  const { runId } = useParams({ from: '/runs/$runId' });
  const { data: run, isLoading, error } = useRun(runId);
  const pauseMutation = usePauseRun();
  const resumeMutation = useResumeRun();

  // Subscribe to WebSocket updates
  const { subscribe, unsubscribe, connected } = useWebSocketStore();

  useEffect(() => {
    if (connected && runId) {
      subscribe(runId);
      return () => unsubscribe(runId);
    }
  }, [connected, runId, subscribe, unsubscribe]);

  if (isLoading) return <div className="p-8">Loading...</div>;
  if (error) return <div className="p-8 text-red-600">Error: {error.message}</div>;
  if (!run) return <div className="p-8">Run not found</div>;

  const isPaused = run.status === 'paused';
  const isRunning = run.status === 'running';

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold">{run.objective}</h1>
          <p className="text-sm text-gray-500">
            Run ID: {run.run_id}
          </p>
        </div>
        <div className="flex items-center gap-3">
          <StatusBadge status={run.status} />
          {isRunning && (
            <button
              onClick={() => pauseMutation.mutate(runId)}
              className="px-4 py-2 bg-yellow-500 text-white rounded-lg"
              disabled={pauseMutation.isPending}
            >
              Pause
            </button>
          )}
          {isPaused && (
            <button
              onClick={() => resumeMutation.mutate(runId)}
              className="px-4 py-2 bg-green-600 text-white rounded-lg"
              disabled={resumeMutation.isPending}
            >
              Resume
            </button>
          )}
        </div>
      </div>

      {/* Task Counts */}
      <div className="grid grid-cols-4 gap-4">
        {Object.entries(run.task_counts).map(([status, count]) => (
          <div key={status} className="p-4 bg-white rounded-lg border">
            <div className="text-2xl font-bold">{count}</div>
            <div className="text-sm text-gray-500 capitalize">{status}</div>
          </div>
        ))}
      </div>

      {/* Human Queue (if any waiting) */}
      {run.task_counts.waiting_human > 0 && (
        <div className="p-4 bg-orange-50 border border-orange-200 rounded-lg">
          <HumanQueue runId={runId} />
        </div>
      )}

      {/* Tabs */}
      <div className="bg-white rounded-lg border">
        <Tabs defaultValue="graph">
          <TabsList>
            <TabsTrigger value="graph">Task Graph</TabsTrigger>
            <TabsTrigger value="list">Task List</TabsTrigger>
            <TabsTrigger value="insights">Insights</TabsTrigger>
            <TabsTrigger value="decisions">Design Log</TabsTrigger>
          </TabsList>

          <TabsContent value="graph" className="p-4">
            <TaskGraph
              tasks={run.tasks}
              onTaskClick={(taskId) => {
                // Navigate to task detail
              }}
            />
          </TabsContent>

          <TabsContent value="list" className="p-4">
            <TaskList tasks={run.tasks} />
          </TabsContent>

          <TabsContent value="insights" className="p-4">
            {run.insights.length === 0 ? (
              <p className="text-gray-500">No insights yet</p>
            ) : (
              <ul className="space-y-2">
                {run.insights.map((insight, i) => (
                  <li key={i} className="p-3 bg-blue-50 rounded-lg">
                    <div className="text-xs text-blue-600 mb-1">
                      {insight.topic.join(', ')}
                    </div>
                    <p>{insight.summary}</p>
                  </li>
                ))}
              </ul>
            )}
          </TabsContent>

          <TabsContent value="decisions" className="p-4">
            {run.design_log.length === 0 ? (
              <p className="text-gray-500">No design decisions yet</p>
            ) : (
              <ul className="space-y-2">
                {run.design_log.map((decision) => (
                  <li key={decision.id} className="p-3 border rounded-lg">
                    <div className="flex items-center gap-2 mb-1">
                      <span className="font-medium">{decision.area}</span>
                      <span className="text-xs text-gray-500">
                        {decision.timestamp}
                      </span>
                    </div>
                    <p className="text-sm">{decision.summary}</p>
                    <p className="text-xs text-gray-500 mt-1">
                      Reason: {decision.reason}
                    </p>
                  </li>
                ))}
              </ul>
            )}
          </TabsContent>
        </Tabs>
      </div>
    </div>
  );
}

// Simple status badge component
function StatusBadge({ status }: { status: string }) {
  const colors: Record<string, string> = {
    running: 'bg-blue-100 text-blue-800',
    paused: 'bg-yellow-100 text-yellow-800',
    completed: 'bg-green-100 text-green-800',
    failed: 'bg-red-100 text-red-800',
    waiting_human: 'bg-orange-100 text-orange-800',
  };

  return (
    <span className={`px-3 py-1 rounded-full text-sm font-medium ${colors[status] || 'bg-gray-100'}`}>
      {status}
    </span>
  );
}
```

---

## Production Considerations

### Authentication
```typescript
// Add to api/client.ts
const getAuthToken = () => localStorage.getItem('auth_token');

export async function apiClient<T>(endpoint: string, options: FetchOptions = {}): Promise<T> {
  const token = getAuthToken();
  
  const response = await fetch(url, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...(token && { 'Authorization': `Bearer ${token}` }),
      ...options.headers,
    },
  });
  // ...
}
```

### Error Handling
```typescript
// Add error boundary and toast notifications
import { toast } from 'sonner';

// In mutations
onError: (error) => {
  toast.error(`Failed: ${error.message}`);
},
```

### Environment Config
```bash
# .env.production
VITE_API_URL=https://api.yoursite.com
VITE_WS_URL=wss://api.yoursite.com/ws
```

### Docker
```dockerfile
# Dockerfile
FROM node:20-slim AS builder
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:alpine
COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
```

---

## Summary

This spec provides:

1. **Backend API** (`dashboard_spec.py`)
   - FastAPI with full REST endpoints
   - WebSocket for real-time updates
   - Human-in-the-loop resolution endpoints
   - Proper typing with Pydantic

2. **Frontend** (this document)
   - React + TypeScript + Vite
   - React Query for data fetching
   - Zustand for WebSocket state
   - ReactFlow for task DAG visualization
   - Complete type definitions

3. **Key Features**
   - Real-time task updates via WebSocket
   - Human review queue with approve/reject/modify
   - Task graph visualization
   - Run pause/resume controls
   - Escalation handling

Copy both files to your `/specs` folder and use them as implementation guides.
