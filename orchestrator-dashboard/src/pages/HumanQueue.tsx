import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { apiClient } from '../api/client';
import { useWebSocketStore } from '../api/websocket';
import { Clock, ArrowRight, AlertCircle } from 'lucide-react';

interface RunSummary {
    run_id: string;
    objective: string;
    status: string;
    created_at: string;
    task_counts: Record<string, number>;
    workspace_path?: string;
}

export function HumanQueue() {
    const [runs, setRuns] = useState<RunSummary[]>([]);
    const [isLoading, setIsLoading] = useState(true);
    const addMessageHandler = useWebSocketStore((state) => state.addMessageHandler);

    useEffect(() => {
        // Initial fetch
        apiClient<RunSummary[]>('/api/runs')
            .then(data => {
                console.log('HumanQueue: Fetched runs:', data);
                setRuns(data);
            })
            .finally(() => setIsLoading(false));

        // Subscribe to real-time updates
        const unsubscribe = addMessageHandler('run_list_update', (msg) => {
            console.log('HumanQueue: Received update:', msg.payload);
            setRuns(msg.payload as RunSummary[]);
        });

        return unsubscribe;
    }, [addMessageHandler]);

    if (isLoading) {
        return <div className="p-8 text-center text-muted-foreground">Loading queue...</div>;
    }

    // Filter for runs that need human attention
    const queueRuns = runs.filter(r =>
        r.status === 'interrupted' ||
        r.status === 'paused' ||
        r.status === 'waiting_human'
    );

    return (
        <div className="space-y-8">
            <div className="flex items-center justify-between">
                <div>
                    <h1 className="text-3xl font-bold">Human Queue</h1>
                    <p className="text-muted-foreground mt-2">
                        Runs waiting for your input or approval.
                    </p>
                </div>
                <div className="bg-blue-500/10 text-blue-400 px-4 py-2 rounded-full font-mono text-sm font-bold flex items-center gap-2">
                    <AlertCircle size={16} />
                    {queueRuns.length} Pending
                </div>
            </div>

            <div className="rounded-lg border bg-card text-card-foreground shadow-sm">
                <div className="p-6">
                    {queueRuns.length === 0 ? (
                        <div className="text-center py-12">
                            <div className="w-16 h-16 bg-slate-800 rounded-full flex items-center justify-center mx-auto mb-4">
                                <Clock className="text-slate-500" size={32} />
                            </div>
                            <h3 className="text-lg font-medium">All Caught Up!</h3>
                            <p className="text-muted-foreground mt-1">
                                No runs are currently waiting for human intervention.
                            </p>
                        </div>
                    ) : (
                        <div className="space-y-4">
                            {queueRuns.map((run) => (
                                <div key={run.run_id} className="flex items-center justify-between p-6 border rounded-lg bg-slate-900/50 hover:bg-slate-900 transition-colors border-l-4 border-l-yellow-500">
                                    <div className="space-y-1">
                                        <div className="flex items-center gap-3">
                                            <span className="px-2 py-0.5 rounded text-xs font-bold bg-yellow-500/20 text-yellow-400 uppercase tracking-wide">
                                                Needs Input
                                            </span>
                                            <span className="text-xs text-slate-500 font-mono">
                                                {new Date(run.created_at).toLocaleString()}
                                            </span>
                                        </div>
                                        <h3 className="font-semibold text-lg">{run.objective}</h3>
                                        <div className="flex items-center gap-2 text-sm text-muted-foreground font-mono">
                                            <span>ID: {run.run_id}</span>
                                            {run.workspace_path && (
                                                <>
                                                    <span>•</span>
                                                    <span>{run.workspace_path}</span>
                                                </>
                                            )}
                                        </div>
                                    </div>

                                    <Link
                                        to={`/runs/${run.run_id}`}
                                        className="flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white rounded-md font-medium transition-colors"
                                    >
                                        Review
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
