import { useParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { apiClient } from '../api/client';
import { Activity, CheckCircle, Clock, AlertCircle, PauseCircle, StopCircle } from 'lucide-react';
import { formatDistanceToNow } from 'date-fns';

interface Task {
    id: string;
    description: string;
    status: 'planned' | 'ready' | 'active' | 'complete' | 'failed' | 'blocked';
    phase: string;
    component: string;
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
}

export function RunDetails() {
    const { runId } = useParams<{ runId: string }>();

    const { data: run, isLoading, error } = useQuery({
        queryKey: ['run', runId],
        queryFn: () => apiClient<RunDetails>(`/api/runs/${runId}`),
        refetchInterval: 1000, // Poll every second for real-time updates
    });

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

            {/* Content Grid */}
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
                {/* Task List */}
                <div className="lg:col-span-1 space-y-4">
                    <h2 className="text-lg font-semibold text-slate-200">Tasks ({run.tasks.length})</h2>
                    <div className="space-y-3">
                        {run.tasks.map((task) => (
                            <div key={task.id} className="bg-slate-800 p-4 rounded-lg border border-slate-700 hover:border-slate-600 transition-colors">
                                <div className="flex items-start justify-between mb-2">
                                    <span className="font-mono text-xs text-slate-500">{task.id}</span>
                                    <span className={`text-xs px-2 py-0.5 rounded-full capitalize ${task.status === 'complete' ? 'bg-green-400/10 text-green-400' :
                                        task.status === 'failed' ? 'bg-red-400/10 text-red-400' :
                                            task.status === 'active' ? 'bg-blue-400/10 text-blue-400' :
                                                'bg-slate-700 text-slate-400'
                                        }`}>
                                        {task.status}
                                    </span>
                                </div>
                                <p className="text-sm text-slate-300 line-clamp-2">{task.description}</p>
                                <div className="mt-2 flex items-center gap-2 text-xs text-slate-500">
                                    <span className="bg-slate-700/50 px-1.5 py-0.5 rounded">{task.component}</span>
                                    <span className="bg-slate-700/50 px-1.5 py-0.5 rounded">{task.phase}</span>
                                </div>
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
