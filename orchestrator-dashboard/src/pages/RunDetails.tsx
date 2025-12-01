import { useParams } from 'react-router-dom';
import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { apiClient } from '../api/client';
import { Activity, CheckCircle, Clock, AlertCircle, PauseCircle, StopCircle, ChevronDown, ChevronUp } from 'lucide-react';
import { formatDistanceToNow } from 'date-fns';

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
}

export function RunDetails() {
    const { runId } = useParams<{ runId: string }>();

    const [expandedTasks, setExpandedTasks] = useState<Set<string>>(new Set());

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

    const { data: run, isLoading, error } = useQuery({
        queryKey: ['run', runId],
        queryFn: () => apiClient<RunDetails>(`/api/runs/${runId}`),
        refetchInterval: 1000, // Poll every second for real-time updates
    });

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

    if (isLoading) {
        return (
            <div className="flex items-center justify-center h-full">
                <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary-500"></div>
            </div>
        );
    }

    if (error || !run) {
        return (
            <div className="flex flex-col items-center justify-center h-full text-slate-400">
                <AlertCircle className="w-12 h-12 mb-4" />
                <p>Failed to load run details</p>
            </div>
        );
    }

    const getStatusColor = (status: string) => {
        switch (status) {
            case 'completed': return 'text-green-400 bg-green-400/10';
            case 'failed': return 'text-red-400 bg-red-400/10';
            case 'paused': return 'text-yellow-400 bg-yellow-400/10';
            case 'blocked': return 'text-orange-400 bg-orange-400/10';
            default: return 'text-blue-400 bg-blue-400/10';
        }
    };

    const getStatusIcon = (status: string) => {
        switch (status) {
            case 'completed': return <CheckCircle className="w-5 h-5" />;
            case 'failed': return <AlertCircle className="w-5 h-5" />;
            case 'paused': return <PauseCircle className="w-5 h-5" />;
            case 'blocked': return <StopCircle className="w-5 h-5" />;
            default: return <Activity className="w-5 h-5" />;
        }
    };

    return (
        <div className="space-y-6">
            {/* Header */}
            <div className="bg-slate-800 rounded-lg p-6 border border-slate-700">
                <div className="flex items-start justify-between">
                    <div>
                        <div className="flex items-center gap-3 mb-2">
                            <h1 className="text-2xl font-bold text-slate-100">Run Details</h1>
                            <span className={`px-3 py-1 rounded-full text-sm font-medium flex items-center gap-2 ${getStatusColor(run.status)}`}>
                                {getStatusIcon(run.status)}
                                <span className="capitalize">{run.status}</span>
                            </span>
                        </div>
                        <p className="text-slate-400 font-mono text-sm mb-4">{run.run_id}</p>
                        <div className="prose prose-invert max-w-none">
                            <p className="text-lg text-slate-300">{run.objective}</p>
                        </div>
                        <div className="flex items-center gap-4 text-sm text-slate-400 mt-1">
                            <div className="flex items-center gap-1">
                                <Activity className="w-4 h-4" />
                                <span>{run.strategy_status}</span>
                            </div>
                            <div>•</div>
                            <div>{run.tasks.length} tasks</div>
                            {run.workspace_path && (
                                <>
                                    <div>•</div>
                                    <div className="font-mono text-xs bg-slate-800 px-2 py-0.5 rounded border border-slate-700 select-all">
                                        {run.workspace_path}
                                    </div>
                                </>
                            )}
                        </div>
                    </div>
                    <div className="flex flex-col items-end text-sm text-slate-500">
                        <div className="flex items-center gap-2 mb-1">
                            <Clock className="w-4 h-4" />
                            <span>Started {formatDistanceToNow(new Date(run.created_at))} ago</span>
                        </div>
                        <div>Last updated {formatDistanceToNow(new Date(run.updated_at))} ago</div>
                    </div>
                </div>
            </div>

            {/* Model Configuration */}
            {run.model_config && (
                <div className="bg-slate-800 rounded-lg p-6 border border-slate-700">
                    <h2 className="text-lg font-semibold text-slate-200 mb-4">Model Configuration</h2>
                    <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                        <div className="bg-slate-900/50 p-4 rounded border border-slate-700/50">
                            <div className="text-xs font-semibold text-purple-400 mb-2">DIRECTOR</div>
                            <div className="space-y-1">
                                <div className="text-sm text-slate-300 font-mono">{run.model_config.director_model.model_name}</div>
                                <div className="text-xs text-slate-500">{run.model_config.director_model.provider}</div>
                                <div className="text-xs text-slate-500">temp: {run.model_config.director_model.temperature}</div>
                            </div>
                        </div>
                        <div className="bg-slate-900/50 p-4 rounded border border-slate-700/50">
                            <div className="text-xs font-semibold text-blue-400 mb-2">WORKER</div>
                            <div className="space-y-1">
                                <div className="text-sm text-slate-300 font-mono">{run.model_config.worker_model.model_name}</div>
                                <div className="text-xs text-slate-500">{run.model_config.worker_model.provider}</div>
                                <div className="text-xs text-slate-500">temp: {run.model_config.worker_model.temperature}</div>
                            </div>
                        </div>
                        <div className="bg-slate-900/50 p-4 rounded border border-slate-700/50">
                            <div className="text-xs font-semibold text-green-400 mb-2">STRATEGIST</div>
                            <div className="space-y-1">
                                <div className="text-sm text-slate-300 font-mono">{run.model_config.strategist_model.model_name}</div>
                                <div className="text-xs text-slate-500">{run.model_config.strategist_model.provider}</div>
                                <div className="text-xs text-slate-500">temp: {run.model_config.strategist_model.temperature}</div>
                            </div>
                        </div>
                    </div>
                </div>
            )}

            {/* Content Grid */}
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
                {/* Task List */}
                <div className="lg:col-span-1 space-y-4">
                    <h2 className="text-lg font-semibold text-slate-200">Tasks ({run.tasks.length})</h2>
                    <div className="space-y-3">
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
                                        <span className="bg-purple-900/30 text-purple-300 px-1.5 py-0.5 rounded border border-purple-800/50">
                                            {task.assigned_worker_profile}
                                        </span>
                                    )}
                                </div>

                                {task.depends_on && task.depends_on.length > 0 && (
                                    <div className="mt-2 text-xs text-slate-500">
                                        <span className="mr-1">Depends on:</span>
                                        {task.depends_on.map(dep => (
                                            <span key={dep} className="bg-slate-800 border border-slate-700 px-1 rounded mr-1 font-mono">
                                                {dep}
                                            </span>
                                        ))}
                                    </div>
                                )}

                                {expandedTasks.has(task.id) && (
                                    <div className="mt-4 pt-4 border-t border-slate-700/50 space-y-3">
                                        {task.acceptance_criteria && task.acceptance_criteria.length > 0 && (
                                            <div>
                                                <h4 className="text-xs font-semibold text-slate-400 mb-1">Acceptance Criteria</h4>
                                                <ul className="list-disc list-inside text-xs text-slate-300 space-y-1">
                                                    {task.acceptance_criteria.map((criteria, idx) => (
                                                        <li key={idx}>{criteria}</li>
                                                    ))}
                                                </ul>
                                            </div>
                                        )}

                                        {task.result_path && (
                                            <div>
                                                <h4 className="text-xs font-semibold text-slate-400 mb-1">Result Path</h4>
                                                <code className="text-xs bg-slate-900 px-2 py-1 rounded text-slate-300 block overflow-x-auto">
                                                    {task.result_path}
                                                </code>
                                            </div>
                                        )}

                                        {task.qa_verdict && (
                                            <div>
                                                <h4 className="text-xs font-semibold text-slate-400 mb-1">QA Verdict</h4>
                                                <div className={`text-xs p-2 rounded ${task.qa_verdict.passed ? 'bg-green-900/20 text-green-300' : 'bg-red-900/20 text-red-300'}`}>
                                                    <div className="font-medium mb-1">{task.qa_verdict.passed ? 'PASSED' : 'FAILED'}</div>
                                                    <p>{task.qa_verdict.overall_feedback}</p>
                                                </div>
                                            </div>
                                        )}

                                        {task.escalation && (
                                            <div>
                                                <h4 className="text-xs font-semibold text-orange-400 mb-1 flex items-center gap-2">
                                                    <AlertCircle className="w-3 h-3" />
                                                    Escalation: {task.escalation.type}
                                                </h4>
                                                <div className="bg-orange-900/20 p-2 rounded border border-orange-700/50 text-xs text-orange-200">
                                                    <p className="font-medium mb-1">{task.escalation.reason}</p>
                                                    <p className="text-orange-300/80">Action: {task.escalation.suggested_action}</p>
                                                </div>
                                            </div>
                                        )}

                                        {task.aar && (
                                            <div className="space-y-2">
                                                <h4 className="text-xs font-semibold text-slate-400 border-b border-slate-700 pb-1">After Action Report</h4>

                                                <div>
                                                    <span className="text-xs text-slate-500 font-medium">Summary:</span>
                                                    <p className="text-xs text-slate-300 mt-0.5">{task.aar.summary}</p>
                                                </div>

                                                {task.aar.challenges && task.aar.challenges.length > 0 && (
                                                    <div>
                                                        <span className="text-xs text-slate-500 font-medium">Challenges:</span>
                                                        <ul className="list-disc list-inside text-xs text-slate-300 mt-0.5">
                                                            {task.aar.challenges.map((c, i) => <li key={i}>{c}</li>)}
                                                        </ul>
                                                    </div>
                                                )}

                                                {task.aar.files_modified && task.aar.files_modified.length > 0 && (
                                                    <div>
                                                        <span className="text-xs text-slate-500 font-medium">Files Modified:</span>
                                                        <div className="flex flex-wrap gap-1 mt-1">
                                                            {task.aar.files_modified.map((f, i) => (
                                                                <span key={i} className="bg-slate-900 px-1.5 py-0.5 rounded text-[10px] font-mono text-slate-400 border border-slate-800">
                                                                    {f.split('/').pop()}
                                                                </span>
                                                            ))}
                                                        </div>
                                                    </div>
                                                )}
                                            </div>
                                        )}
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
                </div>

                {/* Main Content (Graph/Logs) */}
                <div className="lg:col-span-2 space-y-6">
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
            </div>
        </div>
    );
}
