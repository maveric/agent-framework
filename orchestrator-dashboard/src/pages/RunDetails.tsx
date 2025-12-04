import { useParams } from 'react-router-dom';
import { useMemo, useState, useEffect } from 'react';
import { apiClient } from '../api/client';
import { useWebSocketStore } from '../api/websocket';
import { ChevronDown, ChevronUp, LayoutGrid, List, X } from 'lucide-react';
import { formatDistanceToNow } from 'date-fns';
import { TaskGraph } from '../components/TaskGraph';
import { TaskDetailsContent } from '../components/TaskDetailsContent';
import { InterruptModal } from '../components/InterruptModal';
import { LogPanel } from '../components/LogPanel';
import { CancelRunButton } from '../components/CancelRunButton';
interface Task {
    id: string;
    description: string;
    status: 'planned' | 'ready' | 'active' | 'complete' | 'failed' | 'blocked' | 'waiting_human';
    phase: string;
    component: string;
    assigned_worker_profile?: string;
    depends_on: string[];
    acceptance_criteria?: string[];
    result_path?: string;
    retry_count?: number;
    qa_verdict?: {
        passed: boolean;
        overall_feedback: string;
    };
    aar?: {
        summary: string;
        approach: string;
        challenges: string[];
        decisions_made: string[];
        files_modified: string[];
        time_spent_estimate?: string;
    };
    escalation?: {
        type: string;
        reason: string;
        suggested_action: string;
        blocking: boolean;
    };
}

interface RunDetails {
    run_id: string;
    objective: string;
    status: string;
    created_at: string;
    updated_at: string;
    strategy_status: string;
    tasks: Task[];
    insights: any[];
    design_log: any[];
    workspace_path?: string;
    model_config?: {
        director_model: { provider: string; model_name: string; temperature: number };
        worker_model: { provider: string; model_name: string; temperature: number };
        strategist_model: { provider: string; model_name: string; temperature: number };
    };
    task_memories?: {
        [taskId: string]: any;
    };
    task_counts?: {
        completed: number;
        active: number;
        planned: number;
    };
    interrupt_data?: any;
}

const workerColors: Record<string, string> = {
    'full_stack_developer': 'bg-blue-900/20 text-blue-400 border-blue-800/50',
    'devops_engineer': 'bg-purple-900/20 text-purple-400 border-purple-800/50',
    'qa_engineer': 'bg-green-900/20 text-green-400 border-green-800/50',
    'product_manager': 'bg-orange-900/20 text-orange-400 border-orange-800/50',
    'architect': 'bg-indigo-900/20 text-indigo-400 border-indigo-800/50',
};

export function RunDetails() {
    const { runId } = useParams<{ runId: string }>();
    const [viewMode, setViewMode] = useState<'list' | 'graph'>('list');
    const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null);
    const [expandedTasks, setExpandedTasks] = useState<Set<string>>(new Set());
    const [viewingDirectorLogs, setViewingDirectorLogs] = useState(false);
    const [isReplanning, setIsReplanning] = useState(false);
    const [interruptData, setInterruptData] = useState<any>(null);
    const [showInterruptModal, setShowInterruptModal] = useState(false);

    const toggleTask = (taskId: string) => {
        setExpandedTasks(prev => {
            const next = new Set(prev);
            if (next.has(taskId)) {
                next.delete(taskId);
            } else {
                next.add(taskId);
            }
            return next;
        });
    };

    // WebSocket: Subscribe to run updates and interrupts
    const addMessageHandler = useWebSocketStore((state) => state.addMessageHandler);
    const subscribe = useWebSocketStore((state) => state.subscribe);
    const unsubscribe = useWebSocketStore((state) => state.unsubscribe);

    const [run, setRun] = useState<RunDetails | null>(null);
    const [isLoading, setIsLoading] = useState(true);
    const [error, setError] = useState<Error | null>(null);

    useEffect(() => {
        if (!runId) return;

        // Initial fetch
        apiClient<RunDetails>(`/api/runs/${runId}`)
            .then(data => {
                console.log('RunDetails fetched:', data);
                setRun(data);
                if (data.interrupt_data) {
                    console.log('Interrupt data found:', data.interrupt_data);
                    setInterruptData(data.interrupt_data);
                } else {
                    console.log('No interrupt data in response');
                }
            })
            .catch(err => setError(err))
            .finally(() => setIsLoading(false));

        // Subscribe to updates
        subscribe(runId);

        // Handle real-time updates
        const removeStateUpdateHandler = addMessageHandler('state_update', (message) => {
            if (message.run_id === runId) {
                console.log('State update received:', message.payload);
                setRun(prev => {
                    if (!prev) return prev;
                    return {
                        ...prev,
                        status: message.payload.status || prev.status,
                        tasks: message.payload.tasks || prev.tasks,
                        task_counts: message.payload.task_counts || prev.task_counts,
                        insights: message.payload.insights || prev.insights,
                        design_log: message.payload.design_log || prev.design_log,
                        task_memories: message.payload.task_memories
                            ? { ...prev.task_memories, ...message.payload.task_memories }
                            : prev.task_memories
                    };
                });
            }
        });

        const removeInterruptHandler = addMessageHandler('interrupted', (message) => {
            if (message.run_id === runId) {
                console.log('Interrupted event received:', message.payload);
                // Show modal immediately on interrupt
                // The payload from server is { status: 'interrupted', data: { ... } }
                if (message.payload.data) {
                    setInterruptData(message.payload.data);
                    setShowInterruptModal(true);
                }
                // Also update run status
                setRun(prev => prev ? { ...prev, status: 'interrupted' } : null);
            }
        });

        return () => {
            removeStateUpdateHandler();
            removeInterruptHandler();
            unsubscribe(runId);
        };
    }, [runId, addMessageHandler, subscribe, unsubscribe]);

    const handleReplan = async () => {
        if (!runId) return;
        setIsReplanning(true);
        try {
            await apiClient(`/api/runs/${runId}/replan`, { method: 'POST' });
        } catch (error) {
            console.error('Failed to trigger replan:', error);
        } finally {
            setIsReplanning(false);
        }
    };

    const sortedTasks = useMemo(() => {
        if (!run?.tasks) return [];
        // Sort by status priority then ID
        const statusPriority: Record<string, number> = {
            'active': 0,
            'failed': 1,
            'waiting_human': 1,
            'ready': 2,
            'blocked': 3,
            'planned': 4,
            'complete': 5
        };
        return [...run.tasks].sort((a, b) => {
            const priorityA = statusPriority[a.status] ?? 99;
            const priorityB = statusPriority[b.status] ?? 99;
            if (priorityA !== priorityB) return priorityA - priorityB;
            return a.id.localeCompare(b.id);
        });
    }, [run?.tasks]);

    if (isLoading) {
        return (
            <div className="min-h-screen bg-slate-950 flex items-center justify-center">
                <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-500"></div>
            </div>
        );
    }

    if (error || !run) {
        return (
            <div className="min-h-screen bg-slate-950 flex items-center justify-center text-red-400">
                Error loading run details: {error?.message || 'Run not found'}
            </div>
        );
    }

    return (
        <div className="min-h-screen bg-slate-950 text-slate-200 font-sans selection:bg-blue-500/30">
            <div className="w-full px-6 py-8">
                {/* Header */}
                <div className="flex items-center justify-between mb-8">
                    <div>
                        <div className="flex items-center gap-3 mb-2">
                            <h1 className="text-3xl font-bold text-white tracking-tight">Run Details</h1>
                            <span className={`px-2 py-0.5 rounded text-xs font-medium uppercase tracking-wider ${run.status === 'running' ? 'bg-blue-500/20 text-blue-400 border border-blue-500/30' :
                                run.status === 'completed' ? 'bg-green-500/20 text-green-400 border border-green-500/30' :
                                    run.status === 'failed' ? 'bg-red-500/20 text-red-400 border border-red-500/30' :
                                        run.status === 'interrupted' || run.status === 'paused' ? 'bg-yellow-500/20 text-yellow-400 border border-yellow-500/30' :
                                            'bg-slate-700 text-slate-400'
                                }`}>
                                {run.status}
                            </span>
                            {/* Connection Status */}
                            <div className={`w-2 h-2 rounded-full ${useWebSocketStore.getState().connected ? 'bg-green-500 shadow-[0_0_8px_rgba(34,197,94,0.6)]' : 'bg-red-500'}`} title={useWebSocketStore.getState().connected ? 'Connected' : 'Disconnected'} />
                        </div>
                        <div className="flex items-center gap-2 text-sm text-slate-400">
                            <span className="font-mono">{run.run_id}</span>
                            <span>•</span>
                            <span>{run.tasks.length} tasks</span>
                            {run.workspace_path && (
                                <>
                                    <span>•</span>
                                    <span className="font-mono">{run.workspace_path}</span>
                                </>
                            )}
                        </div>
                        <p className="text-lg text-slate-300 leading-relaxed mt-2">{run.objective}</p>
                    </div>
                    <div className="flex gap-3">
                        {interruptData && (
                            <button
                                onClick={() => setShowInterruptModal(true)}
                                className="px-4 py-2 bg-yellow-600 text-white rounded hover:bg-yellow-700 transition-colors flex items-center gap-2 shadow-lg shadow-yellow-900/20 animate-pulse-slow"
                            >
                                ⚠️ Resolve Intervention
                            </button>
                        )}
                        <button
                            onClick={handleReplan}
                            disabled={isReplanning || run.status !== 'running'}
                            className="px-4 py-2 bg-slate-800 border border-slate-700 rounded hover:bg-slate-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                        >
                            {isReplanning ? 'Replanning...' : 'Trigger Replan'}
                        </button>
                        <CancelRunButton
                            runId={runId!}
                            status={run?.status || ''}
                        />
                    </div>
                </div >

                {/* Model Config */}
                {
                    run.model_config && (
                        <div className="bg-slate-900 rounded-lg p-6 border border-slate-800 mb-8">
                            <h3 className="text-sm font-semibold text-slate-200 mb-4">Model Configuration</h3>
                            <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
                                <div
                                    className="space-y-1 cursor-pointer hover:bg-slate-800/50 p-2 -m-2 rounded transition-colors"
                                    onClick={() => setViewingDirectorLogs(true)}
                                    title="View Director Logs"
                                >
                                    <div className="text-xs font-bold text-purple-400 uppercase tracking-wider mb-1">DIRECTOR</div>
                                    <div className="text-sm font-medium text-white">{run.model_config.director_model.model_name}</div>
                                    <div className="text-xs text-slate-500">{run.model_config.director_model.provider}</div>
                                    <div className="text-xs text-slate-600">temp: {run.model_config.director_model.temperature}</div>
                                </div>
                                <div className="space-y-1">
                                    <div className="text-xs font-bold text-blue-400 uppercase tracking-wider mb-1">WORKER</div>
                                    <div className="text-sm font-medium text-white">{run.model_config.worker_model.model_name}</div>
                                    <div className="text-xs text-slate-500">{run.model_config.worker_model.provider}</div>
                                    <div className="text-xs text-slate-600">temp: {run.model_config.worker_model.temperature}</div>
                                </div>
                                <div className="space-y-1">
                                    <div className="text-xs font-bold text-green-400 uppercase tracking-wider mb-1">STRATEGIST</div>
                                    <div className="text-sm font-medium text-white">{run.model_config.strategist_model.model_name}</div>
                                    <div className="text-xs text-slate-500">{run.model_config.strategist_model.provider}</div>
                                    <div className="text-xs text-slate-600">temp: {run.model_config.strategist_model.temperature}</div>
                                </div>
                            </div>
                        </div>
                    )
                }

                {/* Content Grid */}
                <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
                    {/* Task List / Graph */}
                    <div className={`${!selectedTaskId ? 'lg:col-span-3' : 'lg:col-span-2'} space-y-4 transition-all duration-300`}>
                        <div className="flex items-center justify-between">
                            <h2 className="text-xl font-semibold text-slate-200">Tasks ({run.tasks.length})</h2>
                            <div className="flex bg-slate-800 p-1 rounded-lg border border-slate-700">
                                <button
                                    onClick={() => {
                                        setViewMode('list');
                                        setSelectedTaskId(null);
                                    }}
                                    className={`p-1.5 rounded ${viewMode === 'list' ? 'bg-slate-600 text-white shadow' : 'text-slate-400 hover:text-slate-200'}`}
                                    title="List View"
                                >
                                    <List className="w-4 h-4" />
                                </button>
                                <button
                                    onClick={() => setViewMode('graph')}
                                    className={`p-1.5 rounded ${viewMode === 'graph' ? 'bg-slate-600 text-white shadow' : 'text-slate-400 hover:text-slate-200'}`}
                                    title="Graph View"
                                >
                                    <LayoutGrid className="w-4 h-4" />
                                </button>
                            </div>
                        </div>

                        {viewMode === 'graph' ? (
                            <div className="bg-slate-900 rounded-lg border border-slate-800 h-[1170px] overflow-hidden relative">
                                <TaskGraph tasks={sortedTasks} onTaskClick={(id) => {
                                    setSelectedTaskId(id);
                                }} />
                            </div>
                        ) : (
                            <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
                                {sortedTasks.map((task) => {
                                    const isWaiting = task.status === 'failed' || task.status === 'waiting_human';
                                    return (
                                        <div
                                            key={task.id}
                                            className={`bg-slate-800 p-4 rounded-lg border transition-all ${isWaiting
                                                ? 'border-yellow-500 shadow-[0_0_15px_rgba(234,179,8,0.3)] animate-pulse-slow'
                                                : 'border-slate-700 hover:border-slate-600'
                                                }`}
                                        >
                                            <div
                                                className="flex items-start justify-between mb-2 cursor-pointer"
                                                onClick={() => toggleTask(task.id)}
                                            >
                                                <div className="flex items-center gap-2">
                                                    {expandedTasks.has(task.id) ? <ChevronUp className="w-4 h-4 text-slate-500" /> : <ChevronDown className="w-4 h-4 text-slate-500" />}
                                                    <span className="font-mono text-xs text-slate-500">{task.id}</span>
                                                </div>
                                                <span className={`text-xs px-2 py-0.5 rounded-full capitalize ${task.status === 'complete' ? 'bg-green-400/10 text-green-400' :
                                                    task.status === 'failed' ? 'bg-red-400/10 text-red-400' :
                                                        task.status === 'active' ? 'bg-blue-400/10 text-blue-400' :
                                                            'bg-slate-700 text-slate-400'
                                                    }`}>
                                                    {task.status}
                                                </span>
                                            </div>

                                            <p className={`text-sm text-slate-300 ${expandedTasks.has(task.id) ? '' : 'line-clamp-2'}`}>{task.description}</p>

                                            <div className="mt-2 flex items-center gap-2 text-xs text-slate-500">
                                                <span className="bg-slate-700/50 px-1.5 py-0.5 rounded">{task.component}</span>
                                                <span className="bg-slate-700/50 px-1.5 py-0.5 rounded">{task.phase}</span>
                                                {task.assigned_worker_profile && (
                                                    <span className={`px-1.5 py-0.5 rounded border ${workerColors[task.assigned_worker_profile] || 'bg-slate-800 text-slate-400 border-slate-700'}`}>
                                                        {task.assigned_worker_profile}
                                                    </span>
                                                )}
                                                {task.retry_count !== undefined && task.retry_count > 0 && (
                                                    <span className="px-1.5 py-0.5 rounded bg-yellow-900/20 text-yellow-400 border border-yellow-700/50 font-semibold">
                                                        ↻ {task.retry_count}
                                                    </span>
                                                )}
                                            </div>

                                            {task.depends_on && task.depends_on.length > 0 && (
                                                <div className="mt-2 text-xs text-slate-500">
                                                    <span className="mr-1">Depends on:</span>
                                                    {task.depends_on.map(dep => {
                                                        const depTask = sortedTasks.find(t => t.id === dep);
                                                        const isComplete = depTask?.status === 'complete';
                                                        return (
                                                            <span
                                                                key={dep}
                                                                className={`px-1 rounded mr-1 font-mono ${isComplete
                                                                    ? 'bg-green-900/30 border border-green-700/50 text-green-400'
                                                                    : 'bg-slate-800 border border-slate-700 text-slate-400'
                                                                    }`}
                                                            >
                                                                {dep}
                                                            </span>
                                                        );
                                                    })}
                                                </div>
                                            )}

                                            {expandedTasks.has(task.id) && (
                                                <div className="mt-4 pt-4 border-t border-slate-700">
                                                    <TaskDetailsContent task={task} logs={run.task_memories?.[task.id]} />
                                                </div>
                                            )}
                                        </div>
                                    );
                                })}
                                {run.tasks.length === 0 && (
                                    <div className="text-center py-8 text-slate-500 bg-slate-800/50 rounded-lg border border-slate-700 border-dashed">
                                        No tasks generated yet
                                    </div>
                                )}
                            </div>
                        )}
                    </div>

                    {/* Inspector Panel (Graph Mode) */}
                    {viewMode === 'graph' && selectedTaskId && (
                        <div className="lg:col-span-1 border-l border-slate-800 bg-slate-900/50 -my-8 py-8 px-6 overflow-y-auto h-screen sticky top-0">
                            <div className="space-y-6">
                                {(() => {
                                    const task = run.tasks.find(t => t.id === selectedTaskId);
                                    if (!task) return null;
                                    return (
                                        <>
                                            <div className="flex items-start justify-between">
                                                <div>
                                                    <div className="flex items-center gap-2 mb-1">
                                                        <span className={`text-xs px-2 py-0.5 rounded-full capitalize ${task.status === 'complete' ? 'bg-green-400/10 text-green-400' :
                                                            task.status === 'failed' ? 'bg-red-400/10 text-red-400' :
                                                                task.status === 'active' ? 'bg-blue-400/10 text-blue-400' :
                                                                    'bg-slate-700 text-slate-400'
                                                            }`}>
                                                            {task.status}
                                                        </span>
                                                        <span className="font-mono text-xs text-slate-500">{task.id}</span>
                                                    </div>
                                                    <div className="flex items-center gap-2 text-xs text-slate-500">
                                                        <span className="bg-slate-700/50 px-1.5 py-0.5 rounded">{task.component}</span>
                                                        <span className="bg-slate-700/50 px-1.5 py-0.5 rounded">{task.phase}</span>
                                                    </div>
                                                </div>
                                                <button
                                                    onClick={() => setSelectedTaskId(null)}
                                                    className="text-slate-400 hover:text-slate-200 p-1 hover:bg-slate-700 rounded"
                                                >
                                                    <X className="w-4 h-4" />
                                                </button>
                                            </div>
                                            <div className="p-4 overflow-y-auto flex-1">
                                                <TaskDetailsContent task={task} logs={run.task_memories?.[task.id]} />
                                            </div>
                                        </>
                                    );
                                })()}
                            </div>
                        </div>
                    )}

                    {/* Main Content (Graph/Logs) - Sidebar */}
                    {/* Hide sidebar when Inspector is open in graph mode to make room */}
                    {(!selectedTaskId || viewMode !== 'graph') && (
                        <div className={`${viewMode === 'graph' ? 'lg:col-span-3 grid lg:grid-cols-3 gap-6' : 'lg:col-span-1'} space-y-6`}>
                            {/* Insights */}
                            {run.insights && run.insights.length > 0 && (
                                <div className="bg-slate-800 rounded-lg p-6 border border-slate-700">
                                    <h2 className="text-lg font-semibold text-slate-200 mb-4">Insights</h2>
                                    <div className="space-y-3">
                                        {run.insights.map((insight: any) => (
                                            <div key={insight.id} className="bg-slate-900/50 p-3 rounded border border-slate-700/50">
                                                <div className="flex items-center gap-2 mb-1">
                                                    <span className="text-xs font-mono text-purple-400">INSIGHT</span>
                                                    <span className="text-xs text-slate-500">{formatDistanceToNow(new Date(insight.created_at))} ago</span>
                                                </div>
                                                <p className="text-sm text-slate-300">{insight.summary}</p>
                                            </div>
                                        ))}
                                    </div>
                                </div>
                            )}

                            {/* Design Log */}
                            {run.design_log && run.design_log.length > 0 && (
                                <div className="bg-slate-800 rounded-lg p-6 border border-slate-700">
                                    <h2 className="text-lg font-semibold text-slate-200 mb-4">Design Decisions</h2>
                                    <div className="space-y-3">
                                        {run.design_log.map((log: any) => (
                                            <div key={log.id} className="bg-slate-900/50 p-3 rounded border border-slate-700/50">
                                                <div className="flex items-center gap-2 mb-1">
                                                    <span className="text-xs font-mono text-cyan-400">DECISION</span>
                                                    <span className="text-xs text-slate-500">{log.area}</span>
                                                </div>
                                                <p className="text-sm text-slate-300 font-medium">{log.summary}</p>
                                                <p className="text-sm text-slate-400 mt-1">{log.reason}</p>
                                            </div>
                                        ))}
                                    </div>
                                </div>
                            )}

                            {/* Real-Time Logs */}
                            <LogPanel runId={runId!} />
                        </div>
                    )}
                </div>

                {/* Director Logs Modal */}
                {
                    viewingDirectorLogs && (
                        <div className="fixed inset-0 bg-black/50 backdrop-blur-sm flex items-center justify-center z-50 p-4">
                            <div className="bg-slate-900 rounded-xl border border-slate-700 w-full max-w-4xl max-h-[90vh] flex flex-col shadow-2xl">
                                <div className="flex items-center justify-between p-4 border-b border-slate-800">
                                    <div className="flex items-center gap-3">
                                        <h2 className="text-lg font-bold text-white">Director System Logs</h2>
                                        <span className="bg-indigo-900/30 text-indigo-300 px-2 py-0.5 rounded text-xs border border-indigo-800/50">
                                            GLOBAL VIEW
                                        </span>
                                    </div>
                                    <button
                                        onClick={() => setViewingDirectorLogs(false)}
                                        className="text-slate-400 hover:text-white p-1 rounded hover:bg-slate-800 transition-colors"
                                    >
                                        <X className="w-5 h-5" />
                                    </button>
                                </div>
                                <div className="p-6 overflow-y-auto">
                                    <TaskDetailsContent
                                        task={{
                                            id: 'director-system',
                                            description: 'Global orchestration logs. Shows high-level planning, decomposition, and integration decisions.',
                                            status: 'active',
                                            phase: 'orchestration',
                                            component: 'director',
                                            depends_on: []
                                        }}
                                        logs={run.task_memories?.['director']}
                                    />
                                </div>
                            </div>
                        </div>
                    )
                }

                {/* HITL Interrupt Modal */}
                {
                    showInterruptModal && interruptData && (
                        <InterruptModal
                            runId={runId!}
                            interruptData={interruptData}
                            onResolve={() => {
                                setShowInterruptModal(false);
                                setInterruptData(null);
                            }}
                            onClose={() => {
                                setShowInterruptModal(false);
                            }}
                        />
                    )
                }
            </div >
        </div >
    );
}
