import { useParams } from 'react-router-dom';
import { useMemo, useState, useEffect } from 'react';  // Add useEffect
import { useQuery } from '@tanstack/react-query';
import { apiClient } from '../api/client';
import { Clock, ChevronDown, ChevronUp, LayoutGrid, List, X, RefreshCw } from 'lucide-react';
import { formatDistanceToNow } from 'date-fns';
import { TaskGraph } from '../components/TaskGraph';
import { TaskDetailsContent } from '../components/TaskDetailsContent';
import { InterruptModal } from '../components/InterruptModal';  // Add this line

interface Task {
    id: string;
    description: string;
    status: 'planned' | 'ready' | 'active' | 'complete' | 'failed' | 'blocked';
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
}

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

    useEffect(() => {
        if (!runId) return;

        const checkInterrupts = async () => {
            try {
                const response = await fetch(`http://localhost:8085/api/runs/${runId}/interrupts`);
                const data = await response.json();
                if (data.interrupted && data.data) {
                    setInterruptData(data.data);
                    setShowInterruptModal(true);
                }
            } catch (error) {
                console.error('Failed to check for interrupts:', error);
            }
        };

        checkInterrupts(); // Check immediately
        const interval = setInterval(checkInterrupts, 2000);

        return () => clearInterval(interval);
    }, [runId]);

    const { data: run, isLoading, error } = useQuery({
        queryKey: ['run', runId],
        queryFn: () => apiClient<RunDetails>(`/api/runs/${runId}`),
        refetchInterval: 1000, // Poll every second for real-time updates
    });

    const handleReplan = async () => {
        if (!runId) return;
        try {
            setIsReplanning(true);
            await apiClient(`/api/runs/${runId}/replan`, { method: 'POST' });
            // We don't need to manually refetch because the query invalidation or polling will pick it up
            // But we can show a toast or just rely on the button state
        } catch (err) {
            console.error('Failed to trigger replan:', err);
            alert('Failed to trigger replan. Check console for details.');
        } finally {
            // Keep loading state for a moment to show feedback
            setTimeout(() => setIsReplanning(false), 1000);
        }
    };

    const sortedTasks = useMemo(() => {
        if (!run?.tasks) return [];

        const taskMap = new Map(run.tasks.map(t => [t.id, t]));
        const visited = new Set<string>();
        const visiting = new Set<string>();
        const result: Task[] = [];

        const visit = (taskId: string) => {
            if (visited.has(taskId)) return;
            if (visiting.has(taskId)) {
                console.warn(`Cycle detected involving task ${taskId}`);
                return;
            }

            const task = taskMap.get(taskId);
            if (!task) return;

            visiting.add(taskId);

            if (task.depends_on && Array.isArray(task.depends_on)) {
                task.depends_on.forEach(depId => visit(depId));
            }

            visiting.delete(taskId);
            visited.add(taskId);
            result.push(task);
        };

        run.tasks.forEach(t => visit(t.id));
        return result;
    }, [run?.tasks]);

    // Define workerColors here or import them if they are from another file
    const workerColors: { [key: string]: string } = {
        'planner_worker': 'bg-purple-900/30 text-purple-300 border border-purple-800/50',
        'code_worker': 'bg-blue-900/30 text-blue-300 border border-blue-800/50',
        'test_worker': 'bg-green-900/30 text-green-300 border border-green-800/50',
        'research_worker': 'bg-amber-900/30 text-amber-300 border border-amber-800/50',
        'writer_worker': 'bg-pink-900/30 text-pink-300 border border-pink-800/50',
        'default': 'bg-slate-800 text-slate-400 border-slate-700'
    };

    if (isLoading) {
        return (
            <div className="flex items-center justify-center min-h-screen">
                <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-500"></div>
            </div>
        );
    }

    if (error || !run) {
        return (
            <div className="flex items-center justify-center min-h-screen text-red-400">
                Error loading run details
            </div>
        );
    }

    return (
        <div className="min-h-screen bg-slate-950 text-slate-200 p-8">
            <div className="w-full px-8 space-y-8">
                {/* Header */}
                <div className="bg-slate-900 rounded-lg p-6 border border-slate-800">
                    <div className="flex items-start justify-between mb-4">
                        <div className="flex items-center gap-3">
                            <h1 className="text-xl font-bold text-white">Run Details</h1>
                            <span className={`px-2 py-0.5 rounded text-xs font-medium uppercase tracking-wider ${run.status === 'completed' ? 'bg-green-500/20 text-green-400' :
                                run.status === 'failed' ? 'bg-red-500/20 text-red-400' :
                                    run.status === 'paused' ? 'bg-yellow-500/20 text-yellow-400' :
                                        'bg-blue-500/20 text-blue-400'
                                }`}>
                                {run.status}
                            </span>
                        </div>
                        <div className="flex items-center gap-2 text-sm text-slate-400">
                            <span className="flex items-center gap-1">
                                <Clock className="w-4 h-4" />
                                Started {formatDistanceToNow(new Date(run.created_at))} ago
                            </span>
                        </div>
                    </div>

                    <div className="mb-4">
                        <div className="text-sm font-mono text-slate-500 mb-2">{run.run_id}</div>
                        <p className="text-lg text-slate-300 leading-relaxed">{run.objective}</p>
                    </div>

                    <div className="flex items-center gap-4 text-xs text-slate-500 pt-4 border-t border-slate-800">
                        <span className="flex items-center gap-1">
                            <span className={`w-2 h-2 rounded-full ${run.status === 'active' ? 'bg-blue-400 animate-pulse' : 'bg-slate-600'}`}></span>
                            {run.status}
                        </span>
                        <span>•</span>
                        <span>{run.tasks.length} tasks</span>
                        {run.workspace_path && (
                            <>
                                <span>•</span>
                                <span className="font-mono">{run.workspace_path}</span>
                            </>
                        )}
                    </div>
                </div>

                {/* Model Config */}
                {run.model_config && (
                    <div className="bg-slate-900 rounded-lg p-6 border border-slate-800">
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
                )}

                {/* Content Grid */}
                <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
                    {/* Task List / Graph */}
                    {/* Task List / Graph */}
                    <div className={`${!selectedTaskId ? 'lg:col-span-3' : 'lg:col-span-2'} space-y-4 transition-all duration-300`}>
                        <div className="flex items-center justify-between">
                            <h2 className="text-xl font-semibold text-slate-200">Tasks ({run.tasks.length})</h2>
                            <div className="flex items-center gap-2">
                                <button
                                    onClick={handleReplan}
                                    disabled={isReplanning}
                                    className={`flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${isReplanning
                                        ? 'bg-slate-800 text-slate-500 cursor-not-allowed'
                                        : 'bg-slate-800 text-slate-300 hover:bg-slate-700 hover:text-white border border-slate-700'
                                        }`}
                                    title="Trigger a re-planning of pending tasks"
                                >
                                    <RefreshCw className={`w-3.5 h-3.5 ${isReplanning ? 'animate-spin' : ''}`} />
                                    {isReplanning ? 'Replanning...' : 'Replan'}
                                </button>
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
                                    <div key={task.id} className="bg-slate-800 p-4 rounded-lg border border-slate-700 hover:border-slate-600 transition-colors">
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
                        </div>
                    )}
                    {/* Director Logs Modal */}
                    {viewingDirectorLogs && (
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
                    )}
                </div>
            </div>
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
    );
}
