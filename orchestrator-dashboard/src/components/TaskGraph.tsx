import { useMemo, useState, useCallback } from 'react';
import ReactFlow, {
    Node,
    Edge,
    Position,
    MarkerType,
    Background,
    Controls,
    Handle,
} from 'reactflow';
import dagre from 'dagre';
import 'reactflow/dist/style.css';
import { Activity, CheckCircle, Clock, AlertCircle, PauseCircle, StopCircle } from 'lucide-react';

// Reuse Task interface (or import it if we move it to a shared types file)
interface Task {
    id: string;
    description: string;
    status: 'planned' | 'ready' | 'active' | 'complete' | 'failed' | 'blocked';
    phase: string;
    component: string;
    assigned_worker_profile?: string;
    depends_on: string[];
}

interface TaskGraphProps {
    tasks: Task[];
    onTaskClick?: (taskId: string) => void;
}

// Custom Node Component
const TaskNode = ({ data }: { data: Task }) => {
    const statusColors = {
        complete: 'border-green-500 bg-green-900/20',
        failed: 'border-red-500 bg-red-900/20',
        active: 'border-blue-500 bg-blue-900/20',
        ready: 'border-slate-500 bg-slate-800',
        planned: 'border-slate-700 bg-slate-900',
        blocked: 'border-orange-500 bg-orange-900/20',
    };

    const StatusIcon = {
        complete: CheckCircle,
        failed: AlertCircle,
        active: Activity,
        ready: Clock,
        planned: PauseCircle,
        blocked: StopCircle,
    }[data.status] || PauseCircle;

    const workerColors: Record<string, string> = {
        planner_worker: 'bg-indigo-900/30 text-indigo-300 border-indigo-800/50',
        code_worker: 'bg-emerald-900/30 text-emerald-300 border-emerald-800/50',
        test_worker: 'bg-amber-900/30 text-amber-300 border-amber-800/50',
        research_worker: 'bg-violet-900/30 text-violet-300 border-violet-800/50',
        writer_worker: 'bg-rose-900/30 text-rose-300 border-rose-800/50',
    };

    return (
        <div className={`w-64 p-3 rounded-lg border-2 ${statusColors[data.status] || statusColors.planned} shadow-lg transition-all hover:shadow-xl`}>
            <Handle type="target" position={Position.Top} className="!bg-slate-500" />

            <div className="flex items-start justify-between mb-2">
                <div className="flex items-center gap-2">
                    <StatusIcon className={`w-4 h-4 ${data.status === 'complete' ? 'text-green-400' :
                        data.status === 'failed' ? 'text-red-400' :
                            data.status === 'active' ? 'text-blue-400' :
                                'text-slate-400'
                        }`} />
                    <span className="font-mono text-xs text-slate-300 truncate w-32" title={data.id}>
                        {data.id}
                    </span>
                </div>
                <span className="text-[10px] uppercase tracking-wider text-slate-500 font-semibold">
                    {data.phase}
                </span>
            </div>

            <div className="text-xs text-slate-200 line-clamp-2 mb-2 font-medium">
                {data.description.split('\n')[0]}
            </div>

            <div className="flex items-center justify-between mt-2">
                <span className="text-[10px] text-slate-500 bg-slate-800/50 px-1.5 py-0.5 rounded">
                    {data.component}
                </span>
                {data.assigned_worker_profile && (
                    <span className={`text-[10px] px-1.5 py-0.5 rounded border ${workerColors[data.assigned_worker_profile] || 'bg-slate-800 text-slate-400 border-slate-700'}`}>
                        {data.assigned_worker_profile}
                    </span>
                )}
            </div>

            <Handle type="source" position={Position.Bottom} className="!bg-slate-500" />
        </div>
    );
};

const nodeTypes = {
    taskNode: TaskNode,
};

const getLayoutedElements = (tasks: Task[]) => {
    const dagreGraph = new dagre.graphlib.Graph();
    dagreGraph.setDefaultEdgeLabel(() => ({}));

    const nodeWidth = 280;
    const nodeHeight = 120;

    dagreGraph.setGraph({ rankdir: 'TB', nodesep: 100, ranksep: 100 });

    tasks.forEach((task) => {
        dagreGraph.setNode(task.id, { width: nodeWidth, height: nodeHeight });
    });

    tasks.forEach((task) => {
        if (task.depends_on) {
            task.depends_on.forEach((depId) => {
                // Only add edge if dependency exists in the task list
                if (tasks.find(t => t.id === depId)) {
                    dagreGraph.setEdge(depId, task.id);
                }
            });
        }
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
            data: task,
            style: { zIndex: 10 }, // Ensure nodes are above edges
        };
    });

    const edges: Edge[] = [];
    tasks.forEach((task) => {
        if (task.depends_on) {
            task.depends_on.forEach((depId) => {
                if (tasks.find(t => t.id === depId)) {
                    edges.push({
                        id: `${depId}-${task.id}`,
                        source: depId,
                        target: task.id,
                        type: 'default', // Bezier curve
                        animated: task.status === 'active',
                        style: { stroke: '#64748b', strokeWidth: 2, opacity: 0.6 },
                        markerEnd: {
                            type: MarkerType.ArrowClosed,
                            color: '#64748b',
                        },
                    });
                }
            });
        }
    });

    return { nodes, edges };
};

export function TaskGraph({ tasks, onTaskClick }: TaskGraphProps) {
    const [hoveredNode, setHoveredNode] = useState<string | null>(null);
    const [connectedEdges, setConnectedEdges] = useState<Set<string>>(new Set());
    const [connectedNodes, setConnectedNodes] = useState<Set<string>>(new Set());

    const { nodes: initialNodes, edges: initialEdges } = useMemo(() => getLayoutedElements(tasks), [tasks]);

    const onNodeMouseEnter = useCallback((_: React.MouseEvent, node: Node) => {
        setHoveredNode(node.id);

        const connectedEdgeIds = new Set<string>();
        const connectedNodeIds = new Set<string>();
        connectedNodeIds.add(node.id);

        initialEdges.forEach((edge) => {
            if (edge.source === node.id || edge.target === node.id) {
                connectedEdgeIds.add(edge.id);
                connectedNodeIds.add(edge.source);
                connectedNodeIds.add(edge.target);
            }
        });

        setConnectedEdges(connectedEdgeIds);
        setConnectedNodes(connectedNodeIds);
    }, [initialEdges]);

    const onNodeMouseLeave = useCallback(() => {
        setHoveredNode(null);
        setConnectedEdges(new Set());
        setConnectedNodes(new Set());
    }, []);

    // Apply styles based on hover state
    const nodes = useMemo(() => {
        return initialNodes.map(node => ({
            ...node,
            style: {
                ...node.style,
                opacity: hoveredNode && !connectedNodes.has(node.id) ? 0.3 : 1,
                transition: 'opacity 0.2s',
            }
        }));
    }, [initialNodes, hoveredNode, connectedNodes]);

    const edges = useMemo(() => {
        return initialEdges.map(edge => ({
            ...edge,
            type: 'smoothstep', // Revert to orthogonal lines
            style: {
                ...edge.style,
                stroke: connectedEdges.has(edge.id) ? '#3b82f6' : '#475569', // Blue if connected, slate if not
                strokeWidth: connectedEdges.has(edge.id) ? 3 : 2,
                opacity: hoveredNode && !connectedEdges.has(edge.id) ? 0.1 : (connectedEdges.has(edge.id) ? 1 : 0.6),
                zIndex: connectedEdges.has(edge.id) ? 20 : 0,
                transition: 'all 0.2s',
            },
            markerEnd: {
                type: MarkerType.ArrowClosed,
                color: connectedEdges.has(edge.id) ? '#3b82f6' : '#475569',
            },
        }));
    }, [initialEdges, hoveredNode, connectedEdges]);

    return (
        <div className="h-[800px] w-full bg-slate-950 rounded-lg border border-slate-800 overflow-hidden">
            <ReactFlow
                nodes={nodes}
                edges={edges}
                nodeTypes={nodeTypes}
                fitView
                minZoom={0.2}
                maxZoom={2.0}
                attributionPosition="bottom-right"
                onNodeClick={(_, node) => onTaskClick?.(node.id)}
                onNodeMouseEnter={onNodeMouseEnter}
                onNodeMouseLeave={onNodeMouseLeave}
            >
                <Background color="#1e293b" gap={16} />
                <Controls className="bg-slate-800 border-slate-700 text-slate-200" />
            </ReactFlow>
        </div>
    );
}
