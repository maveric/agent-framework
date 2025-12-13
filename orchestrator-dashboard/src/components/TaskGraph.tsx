import { useMemo, useState, useCallback, useEffect } from 'react';
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
import { Activity, CheckCircle, Clock, AlertCircle, PauseCircle, StopCircle, RefreshCw, Link, X, Unlink } from 'lucide-react';
import { addTaskDependency, removeTaskDependency } from '../api/client';

// Reuse Task interface (or import it if we move it to a shared types file)
interface Task {
    id: string;
    title?: string;  // Task title (may not exist in old data)
    description: string;
    status: 'planned' | 'ready' | 'active' | 'complete' | 'failed' | 'blocked' | 'awaiting_qa' | 'waiting_human' | 'abandoned';
    phase: string;
    component: string;
    assigned_worker_profile?: string;
    depends_on: string[];
    retry_count?: number;
}

interface TaskGraphProps {
    tasks: Task[];
    onTaskClick?: (taskId: string) => void;
    runId?: string; // Needed for API calls
}

// Custom Node Component with link mode support
const TaskNode = ({ data }: { data: Task & { isLinkSource?: boolean; linkModeActive?: boolean } }) => {
    const statusColors = {
        complete: 'border-green-500 bg-green-900/20',
        failed: 'border-red-500 bg-red-900/20',
        active: 'border-blue-500 bg-blue-900/20',
        ready: 'border-slate-500 bg-slate-800',
        planned: 'border-slate-700 bg-slate-900',
        blocked: 'border-orange-500 bg-orange-900/20',
        awaiting_qa: 'border-orange-400 bg-orange-900/20',
        waiting_human: 'border-yellow-500 bg-yellow-900/20',
        abandoned: 'border-slate-600 bg-slate-800/50 opacity-60',
    };

    const statusIconMap: Record<string, typeof CheckCircle> = {
        complete: CheckCircle,
        failed: AlertCircle,
        active: Activity,
        ready: Clock,
        planned: PauseCircle,
        blocked: StopCircle,
        awaiting_qa: Clock,
        waiting_human: PauseCircle,
    };
    const StatusIcon = statusIconMap[data.status] || PauseCircle;

    const workerColors: Record<string, string> = {
        planner_worker: 'bg-indigo-900/30 text-indigo-300 border-indigo-800/50',
        code_worker: 'bg-emerald-900/30 text-emerald-300 border-emerald-800/50',
        test_worker: 'bg-amber-900/30 text-amber-300 border-amber-800/50',
        research_worker: 'bg-violet-900/30 text-violet-300 border-violet-800/50',
        writer_worker: 'bg-rose-900/30 text-rose-300 border-rose-800/50',
        merge_worker: 'bg-cyan-900/30 text-cyan-300 border-cyan-800/50',
    };

    const title = data.title || data.description.split('\n')[0]; // Fallback for backwards compatibility
    const isWaiting = data.status === 'failed' || data.status === 'waiting_human';
    const isLinkSource = data.isLinkSource;
    const linkModeActive = data.linkModeActive;

    return (
        <div className={`w-64 p-3 rounded-lg border-2 ${statusColors[data.status] || statusColors.planned} shadow-lg transition-all hover:shadow-xl 
            ${isWaiting ? '!border-yellow-500 shadow-[0_0_15px_rgba(234,179,8,0.3)] animate-pulse-slow' : ''}
            ${isLinkSource ? '!border-cyan-400 !border-4 shadow-[0_0_20px_rgba(34,211,238,0.5)]' : ''}
            ${linkModeActive && !isLinkSource ? 'cursor-crosshair' : ''}
        `}>
            <Handle type="target" position={Position.Top} className="!bg-slate-500" />

            <div className="flex items-start justify-between mb-2">
                <div className="flex items-center gap-2 flex-1 min-w-0">
                    <StatusIcon className={`w-4 h-4 flex-shrink-0 ${data.status === 'complete' ? 'text-green-400' :
                        data.status === 'failed' ? 'text-red-400' :
                            data.status === 'active' ? 'text-blue-400' :
                                'text-slate-400'
                        }`} />
                    <span className="text-xs text-slate-200 font-medium truncate" title={`${title} (${data.id})`}>
                        {title}
                    </span>
                </div>
                <span className="text-[10px] uppercase tracking-wider text-slate-500 font-semibold flex-shrink-0 ml-2">
                    {data.phase}
                </span>
            </div>

            <div className="text-[10px] text-slate-500 mb-2 font-mono">
                {data.id}
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

            {data.retry_count !== undefined && data.retry_count > 0 && (
                <div className="absolute -top-2 -right-2 bg-yellow-500/20 text-yellow-400 border border-yellow-500/50 rounded-md px-1.5 py-0.5 text-[10px] font-bold flex items-center gap-1 shadow-sm backdrop-blur-sm">
                    <RefreshCw size={10} />
                    {data.retry_count}
                </div>
            )}

            {isLinkSource && (
                <div className="absolute -top-3 left-1/2 -translate-x-1/2 bg-cyan-500 text-white px-2 py-0.5 rounded text-[10px] font-bold">
                    SOURCE
                </div>
            )}

            <Handle type="source" position={Position.Bottom} className="!bg-slate-500" />
        </div>
    );
};

const nodeTypes = {
    taskNode: TaskNode,
};

const getLayoutedElements = (tasks: Task[], linkingFrom: string | null, linkModeActive: boolean) => {
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
            data: {
                ...task,
                isLinkSource: linkingFrom === task.id,
                linkModeActive: linkModeActive,
            },
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

function ConfirmDialog({
    isOpen,
    sourceTask,
    targetTask,
    isExistingLink,
    onConfirm,
    onCancel,
    isSubmitting
}: {
    isOpen: boolean;
    sourceTask: Task | null;
    targetTask: Task | null;
    isExistingLink: boolean;
    onConfirm: () => void;
    onCancel: () => void;
    isSubmitting: boolean;
}) {
    if (!isOpen || !sourceTask || !targetTask) return null;

    const sourceTitle = sourceTask.title || sourceTask.description.split('\n')[0];
    const targetTitle = targetTask.title || targetTask.description.split('\n')[0];

    return (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
            <div className="bg-slate-800 border border-slate-700 rounded-lg p-6 max-w-md mx-4 shadow-xl">
                <h3 className="text-lg font-semibold text-white mb-4 flex items-center gap-2">
                    {isExistingLink ? (
                        <><Unlink size={20} className="text-red-400" /> Remove Dependency</>
                    ) : (
                        <><Link size={20} className="text-cyan-400" /> Add Dependency</>
                    )}
                </h3>
                <p className="text-slate-300 mb-6">
                    {isExistingLink ? (
                        <>Remove the dependency from <span className="text-cyan-400 font-medium">"{targetTitle}"</span> to <span className="text-green-400 font-medium">"{sourceTitle}"</span>?</>
                    ) : (
                        <>Make <span className="text-cyan-400 font-medium">"{targetTitle}"</span> depend on <span className="text-green-400 font-medium">"{sourceTitle}"</span>?</>
                    )}
                </p>
                <p className="text-sm text-slate-500 mb-6">
                    {isExistingLink
                        ? `"${targetTitle}" will no longer wait for "${sourceTitle}" to complete.`
                        : `"${targetTitle}" will wait for "${sourceTitle}" to complete before it can start.`
                    }
                </p>
                <div className="flex gap-3 justify-end">
                    <button
                        onClick={onCancel}
                        className="px-4 py-2 text-slate-300 hover:text-white transition-colors"
                    >
                        Cancel
                    </button>
                    <button
                        onClick={onConfirm}
                        disabled={isSubmitting}
                        className={`px-4 py-2 text-white rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed ${isExistingLink
                            ? 'bg-red-600 hover:bg-red-500'
                            : 'bg-cyan-600 hover:bg-cyan-500'
                            }`}
                    >
                        {isSubmitting
                            ? (isExistingLink ? 'Removing...' : 'Adding...')
                            : (isExistingLink ? 'Remove Dependency' : 'Add Dependency')
                        }
                    </button>
                </div>
            </div>
        </div>
    );
}

export function TaskGraph({ tasks, onTaskClick, runId }: TaskGraphProps) {
    const [hoveredNode, setHoveredNode] = useState<string | null>(null);
    const [connectedEdges, setConnectedEdges] = useState<Set<string>>(new Set());
    const [connectedNodes, setConnectedNodes] = useState<Set<string>>(new Set());

    // Link mode state
    const [linkModeActive, setLinkModeActive] = useState(false);
    const [linkingFrom, setLinkingFrom] = useState<string | null>(null);
    const [pendingLink, setPendingLink] = useState<{ from: string; to: string } | null>(null);
    const [isSubmitting, setIsSubmitting] = useState(false);

    // Escape key handler
    useEffect(() => {
        const handleKeyDown = (e: KeyboardEvent) => {
            if (e.key === 'Escape' && linkModeActive) {
                setLinkModeActive(false);
                setLinkingFrom(null);
                setPendingLink(null);
            }
        };
        window.addEventListener('keydown', handleKeyDown);
        return () => window.removeEventListener('keydown', handleKeyDown);
    }, [linkModeActive]);

    const { nodes: initialNodes, edges: initialEdges } = useMemo(
        () => getLayoutedElements(tasks, linkingFrom, linkModeActive),
        [tasks, linkingFrom, linkModeActive]
    );

    const handleNodeClick = useCallback((_: React.MouseEvent, node: Node) => {
        if (!linkModeActive) {
            // Normal mode - show task details
            onTaskClick?.(node.id);
            return;
        }

        // Link mode
        if (!linkingFrom) {
            // First click - set source
            setLinkingFrom(node.id);
        } else if (linkingFrom === node.id) {
            // Clicked same node - deselect
            setLinkingFrom(null);
        } else {
            // Second click - show confirmation
            setPendingLink({ from: linkingFrom, to: node.id });
        }
    }, [linkModeActive, linkingFrom, onTaskClick]);

    const handleConfirmLink = useCallback(async () => {
        if (!pendingLink || !runId) return;

        // Check if link already exists (for toggle behavior)
        const targetTask = tasks.find(t => t.id === pendingLink.to);
        const isExisting = targetTask?.depends_on?.includes(pendingLink.from) ?? false;

        setIsSubmitting(true);
        try {
            if (isExisting) {
                await removeTaskDependency(runId, pendingLink.to, pendingLink.from);
            } else {
                await addTaskDependency(runId, pendingLink.to, pendingLink.from);
            }
            // Reset state
            setPendingLink(null);
            setLinkingFrom(null);
            // Stay in link mode for more links
        } catch (error) {
            console.error('Failed to modify dependency:', error);
            alert('Failed to modify dependency: ' + (error as Error).message);
        } finally {
            setIsSubmitting(false);
        }
    }, [pendingLink, runId, tasks]);

    const handleCancelLink = useCallback(() => {
        setPendingLink(null);
    }, []);

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

    const sourceTask = linkingFrom ? tasks.find(t => t.id === linkingFrom) || null : null;
    const targetTask = pendingLink ? tasks.find(t => t.id === pendingLink.to) || null : null;

    return (
        <div className="h-full w-full bg-slate-950 rounded-lg border border-slate-800 overflow-hidden relative">
            {/* Toolbar */}
            <div className="absolute top-4 left-4 z-20 flex gap-2">
                <button
                    onClick={() => {
                        setLinkModeActive(!linkModeActive);
                        if (linkModeActive) {
                            setLinkingFrom(null);
                            setPendingLink(null);
                        }
                    }}
                    className={`flex items-center gap-2 px-3 py-2 rounded-lg text-sm font-medium transition-all ${linkModeActive
                        ? 'bg-cyan-600 text-white shadow-lg shadow-cyan-500/30'
                        : 'bg-slate-800 text-slate-300 hover:bg-slate-700'
                        }`}
                >
                    <Link size={16} />
                    {linkModeActive ? 'Exit Link Mode' : 'Link Mode'}
                </button>
                {linkModeActive && (
                    <button
                        onClick={() => {
                            setLinkModeActive(false);
                            setLinkingFrom(null);
                            setPendingLink(null);
                        }}
                        className="flex items-center gap-1 px-3 py-2 rounded-lg text-sm bg-slate-800 text-slate-300 hover:bg-slate-700"
                    >
                        <X size={16} />
                        Cancel
                    </button>
                )}
            </div>

            {/* Link mode instructions */}
            {linkModeActive && (
                <div className="absolute top-4 left-1/2 -translate-x-1/2 z-20 bg-slate-800/90 backdrop-blur-sm border border-slate-700 px-4 py-2 rounded-lg text-sm text-slate-300">
                    {!linkingFrom
                        ? '👆 Click a task to select it as the dependency source'
                        : '👆 Click another task to make it depend on the selected task'
                    }
                </div>
            )}

            <ReactFlow
                nodes={nodes}
                edges={edges}
                nodeTypes={nodeTypes}
                fitView
                minZoom={0.2}
                maxZoom={2.0}
                attributionPosition="bottom-right"
                onNodeClick={handleNodeClick}
                onNodeMouseEnter={onNodeMouseEnter}
                onNodeMouseLeave={onNodeMouseLeave}
            >
                <Background color="#1e293b" gap={16} />
                <Controls className="bg-slate-800 border-slate-700 text-slate-200" />
            </ReactFlow>

            {/* Confirmation Dialog */}
            <ConfirmDialog
                isOpen={!!pendingLink}
                sourceTask={sourceTask}
                targetTask={targetTask}
                isExistingLink={targetTask?.depends_on?.includes(pendingLink?.from ?? '') ?? false}
                onConfirm={handleConfirmLink}
                onCancel={handleCancelLink}
                isSubmitting={isSubmitting}
            />
        </div>
    );
}

