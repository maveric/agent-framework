import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { apiClient } from '../api/client';
import { useWebSocketStore } from '../api/websocket';
import { Clock, ArrowRight, AlertCircle, UserCheck } from 'lucide-react';

interface Task {
    id: string;
    description: string;
    status: string;
    phase: string;
    component: string;
    assigned_worker_profile?: string;
    failure_reason?: string;
    retry_count?: number;
}

interface RunSummary {
    run_id: string;
    objective: string;
    status: string;
    created_at: string;
    task_counts: Record<string, number>;
    workspace_path?: string;
    tasks?: Task[];
}

interface WaitingTask {
    run_id: string;
    run_objective: string;
    task: Task;
}

interface PaginatedResponse<T> {
    items: T[];
    total: number;
    limit: number;
    offset: number;
    has_more: boolean;
}

export function HumanQueue() {
    const [waitingTasks, setWaitingTasks] = useState<WaitingTask[]>([]);
    const [isLoading, setIsLoading] = useState(true);
    const addMessageHandler = useWebSocketStore((state) => state.addMessageHandler);

    const fetchWaitingTasks = async () => {
        try {
            const response = await apiClient<PaginatedResponse<RunSummary>>('/api/runs');
            const runs = response.items;
            const allWaiting: WaitingTask[] = [];

            // Filter for runs that might have waiting_human tasks
            const interruptedRuns = runs.filter(r =>
                r.status === 'interrupted' ||
                r.status === 'paused' ||
                r.status === 'waiting_human'
            );

            // Fetch full details for each interrupted run to get tasks
            for (const run of interruptedRuns) {
                try {
                    const details = await apiClient<RunSummary>(`/api/runs/${run.run_id}`);
                    if (details.tasks) {
                        const waitingFromRun = details.tasks
                            .filter(t => t.status === 'waiting_human')
                            .map(t => ({
                                run_id: run.run_id,
                                run_objective: run.objective,
                                task: t
                            }));
                        allWaiting.push(...waitingFromRun);
                    }
                } catch (e) {
                    console.error(`Failed to fetch details for run ${run.run_id}:`, e);
                }
            }

            setWaitingTasks(allWaiting);
        } catch (e) {
            console.error('Failed to fetch waiting tasks:', e);
        } finally {
            setIsLoading(false);
        }
    };

    useEffect(() => {
        // Initial fetch
        fetchWaitingTasks();

        // Subscribe to real-time updates - refetch on any state change
        const unsubscribe = addMessageHandler('state_update', () => {
            fetchWaitingTasks();
        });

        return unsubscribe;
    }, [addMessageHandler]);

    if (isLoading) {
        return <div className="p-8 text-center text-muted-foreground">Loading queue...</div>;
    }

    return (
        <div className="space-y-8">
            <div className="flex items-center justify-between">
                <div>
                    <h1 className="text-3xl font-bold">Human Queue</h1>
                    <p className="text-muted-foreground mt-2">
                        Tasks waiting for your input or approval.
                    </p>
                </div>
                <div className="bg-blue-500/10 text-blue-400 px-4 py-2 rounded-full font-mono text-sm font-bold flex items-center gap-2">
                    <AlertCircle size={16} />
                    {waitingTasks.length} Pending Tasks
                </div>
            </div>

            <div className="rounded-lg border bg-card text-card-foreground shadow-sm">
                <div className="p-6">
                    {waitingTasks.length === 0 ? (
                        <div className="text-center py-12">
                            <div className="w-16 h-16 bg-slate-800 rounded-full flex items-center justify-center mx-auto mb-4">
                                <Clock className="text-slate-500" size={32} />
                            </div>
                            <h3 className="text-lg font-medium">All Caught Up!</h3>
                            <p className="text-muted-foreground mt-1">
                                No tasks are currently waiting for human intervention.
                            </p>
                        </div>
                    ) : (
                        <div className="space-y-4">
                            {waitingTasks.map((item) => (
                                <div key={`${item.run_id}-${item.task.id}`} className="flex items-center justify-between p-6 border rounded-lg bg-slate-900/50 hover:bg-slate-900 transition-colors border-l-4 border-l-yellow-500">
                                    <div className="space-y-2 flex-1 min-w-0">
                                        <div className="flex items-center gap-3 flex-wrap">
                                            <span className="px-2 py-0.5 rounded text-xs font-bold bg-yellow-500/20 text-yellow-400 uppercase tracking-wide flex items-center gap-1">
                                                <UserCheck size={12} />
                                                Needs Input
                                            </span>
                                            <span className="text-xs text-slate-500 bg-slate-800 px-2 py-0.5 rounded">
                                                {item.task.phase}
                                            </span>
                                            <span className="text-xs text-slate-500 bg-slate-800 px-2 py-0.5 rounded">
                                                {item.task.component}
                                            </span>
                                            {item.task.retry_count !== undefined && item.task.retry_count > 0 && (
                                                <span className="text-xs text-orange-400 bg-orange-900/20 px-2 py-0.5 rounded border border-orange-500/30">
                                                    Retry #{item.task.retry_count}
                                                </span>
                                            )}
                                        </div>
                                        <h3 className="font-semibold text-lg truncate">
                                            {item.task.description.split('\n')[0].replace(/^Title:\s*/i, '').slice(0, 80)}
                                        </h3>
                                        <div className="flex items-center gap-2 text-xs text-muted-foreground font-mono">
                                            <span className="text-slate-500">Task: {item.task.id.slice(0, 12)}</span>
                                            <span>•</span>
                                            <span className="text-slate-600">Run: {item.run_objective.slice(0, 40)}...</span>
                                        </div>
                                        {item.task.failure_reason && (
                                            <p className="text-xs text-red-400/80 mt-1 bg-red-900/10 px-2 py-1 rounded line-clamp-2">
                                                {item.task.failure_reason.slice(0, 150)}...
                                            </p>
                                        )}
                                    </div>

                                    <Link
                                        to={`/runs/${item.run_id}?task=${item.task.id}`}
                                        className="flex items-center gap-2 px-4 py-2 bg-yellow-600 hover:bg-yellow-500 text-white rounded-md font-medium transition-colors ml-4 flex-shrink-0"
                                    >
                                        Resolve
                                        <ArrowRight size={16} />
                                    </Link>
                                </div>
                            ))}
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
}
