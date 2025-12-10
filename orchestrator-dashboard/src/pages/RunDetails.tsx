import { useParams } from 'react-router-dom';
import { useMemo, useState, useEffect } from 'react';
import { apiClient } from '../api/client';
import { useWebSocketStore } from '../api/websocket';
import { LayoutGrid, List } from 'lucide-react';
import { TaskGraph } from '../components/TaskGraph';
import { InterruptModal } from '../components/InterruptModal';
import { LogPanel } from '../components/LogPanel';
import {
    RunHeader,
    ModelConfig,
    TaskCard,
    TaskInspector,
    InsightsPanel,
    DesignLogPanel,
    DirectorLogsModal
} from '../components/run-details';
import type { Task, RunDetails as RunDetailsType } from '../types/run';

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

    const [run, setRun] = useState<RunDetailsType | null>(null);
    const [isLoading, setIsLoading] = useState(true);
    const [error, setError] = useState<Error | null>(null);

    useEffect(() => {
        if (!runId) return;

        // Initial fetch
        apiClient<RunDetailsType>(`/api/runs/${runId}`)
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

        // Handle task-specific interrupts (run continues, only task paused)
        const removeTaskInterruptHandler = addMessageHandler('task_interrupted', (message) => {
            if (message.run_id === runId) {
                console.log('Task interrupted event received:', message.payload);
                // Show modal for the specific task
                if (message.payload.data) {
                    setInterruptData(message.payload.data);
                    setShowInterruptModal(true);
                }
                // Don't change run status - it stays running
            }
        });

        return () => {
            removeStateUpdateHandler();
            removeInterruptHandler();
            removeTaskInterruptHandler();
            unsubscribe(runId);
        };
    }, [runId, addMessageHandler, subscribe, unsubscribe]);


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

    const handleInterrupt = async (taskId: string) => {
        if (!runId) return;
        if (!confirm('Are you sure you want to force interrupt this task? This will stop the run and move the task to the Human Queue.')) return;

        try {
            await apiClient(`/api/runs/${runId}/tasks/${taskId}/interrupt`, {
                method: 'POST'
            });
            // Re-fetch run details to update UI
            const data = await apiClient<RunDetailsType>(`/api/runs/${runId}`);
            setRun(data);

            // IMPORTANT: Populate interrupt modal with task data
            const interruptedTask = data.tasks.find(t => t.id === taskId);
            if (interruptedTask) {
                // Build interrupt data from task
                const newInterruptData = {
                    task_id: interruptedTask.id,
                    task_description: interruptedTask.description,
                    failure_reason: `Manually interrupted by user from ${interruptedTask.status} status`,
                    retry_count: interruptedTask.retry_count || 0,
                    acceptance_criteria: interruptedTask.acceptance_criteria || [],
                    component: interruptedTask.component,
                    phase: interruptedTask.phase,
                    assigned_worker_profile: interruptedTask.assigned_worker_profile || 'code_worker',
                    depends_on: interruptedTask.depends_on || []
                };
                setInterruptData(newInterruptData);
                setShowInterruptModal(true);
            }
        } catch (error) {
            console.error('Failed to interrupt task:', error);
            alert('Failed to interrupt task: ' + error);
        }
    };

    // Handle clicking "Resolve" on a waiting_human task from TaskDetailsContent
    const handleResolveClick = (task: Task) => {
        // Build interrupt data from the task (same format as handleInterrupt)
        const resolveData = {
            task_id: task.id,
            task_description: task.description,
            failure_reason: task.aar?.summary || task.escalation?.reason || 'Task requires human review',
            retry_count: task.retry_count || 0,
            acceptance_criteria: task.acceptance_criteria || [],
            component: task.component,
            phase: task.phase,
            assigned_worker_profile: task.assigned_worker_profile || 'code_worker',
            depends_on: task.depends_on || []
        };
        setInterruptData(resolveData);
        setShowInterruptModal(true);
    };

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
                <RunHeader
                    run={run}
                    interruptData={interruptData}
                    isReplanning={isReplanning}
                    onReplan={handleReplan}
                    onShowInterruptModal={() => setShowInterruptModal(true)}
                />

                {/* Model Config */}
                <ModelConfig
                    modelConfig={run.model_config}
                    onViewDirectorLogs={() => setViewingDirectorLogs(true)}
                />

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
                                {sortedTasks.map((task) => (
                                    <TaskCard
                                        key={task.id}
                                        task={task}
                                        allTasks={sortedTasks}
                                        isExpanded={expandedTasks.has(task.id)}
                                        logs={run.task_memories?.[task.id]}
                                        onToggle={() => toggleTask(task.id)}
                                        onResolveClick={handleResolveClick}
                                    />
                                ))}
                                {run.tasks.length === 0 && (
                                    <div className="text-center py-8 text-slate-500 bg-slate-800/50 rounded-lg border border-slate-700 border-dashed">
                                        No tasks generated yet
                                    </div>
                                )}
                            </div>
                        )}
                    </div>

                    {/* Inspector Panel (Graph Mode) */}
                    {viewMode === 'graph' && selectedTaskId && (() => {
                        const task = run.tasks.find(t => t.id === selectedTaskId);
                        return task ? (
                            <TaskInspector
                                task={task}
                                logs={run.task_memories?.[task.id]}
                                onClose={() => setSelectedTaskId(null)}
                                onInterrupt={handleInterrupt}
                                onResolveClick={handleResolveClick}
                            />
                        ) : null;
                    })()}

                    {/* Main Content (Graph/Logs) - Sidebar */}
                    {/* Hide sidebar when Inspector is open in graph mode to make room */}
                    {(!selectedTaskId || viewMode !== 'graph') && (
                        <div className={`${viewMode === 'graph' ? 'lg:col-span-3 grid lg:grid-cols-3 gap-6' : 'lg:col-span-1'} space-y-6`}>
                            {/* Insights */}
                            <InsightsPanel insights={run.insights} />

                            {/* Design Log */}
                            <DesignLogPanel designLog={run.design_log} />

                            {/* Real-Time Logs */}
                            <LogPanel runId={runId!} />
                        </div>
                    )}
                </div>

                {/* Director Logs Modal */}
                {viewingDirectorLogs && (
                    <DirectorLogsModal
                        logs={run.task_memories?.['director']}
                        onClose={() => setViewingDirectorLogs(false)}
                    />
                )}

                {/* HITL Interrupt Modal */}
                {showInterruptModal && interruptData && (
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
                )}
            </div>
        </div>
    );
}
