import { useCallback, useMemo, useEffect, type MouseEvent } from 'react';
import ReactFlow, {
    type Node,
    type Edge,
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
    useEffect(() => {
        const { nodes: newNodes, edges: newEdges } = getLayoutedElements(tasks);
        setNodes(newNodes);
        setEdges(newEdges);
    }, [tasks, setNodes, setEdges]);

    const onNodeClick = useCallback(
        (_: MouseEvent, node: Node) => {
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
