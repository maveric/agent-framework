import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { apiClient } from '../api/client';
import { Play, CheckCircle, XCircle, Clock } from 'lucide-react';

interface RunSummary {
    run_id: string;
    objective: string;
    status: string;
    created_at: string;
    task_counts: Record<string, number>;
    workspace_path?: string;
}

export function Dashboard() {
    const { data: runs, isLoading } = useQuery({
        queryKey: ['runs'],
        queryFn: () => apiClient<RunSummary[]>('/api/runs'),
        refetchInterval: 5000,
    });

    if (isLoading) {
        return <div>Loading...</div>;
    }

    const activeRuns = runs?.filter(r => r.status === 'running') || [];
    const completedRuns = runs?.filter(r => r.status === 'completed') || [];
    const failedRuns = runs?.filter(r => r.status === 'failed') || [];

    return (
        <div className="space-y-8">
            <h1 className="text-3xl font-bold">Dashboard</h1>

            {/* Stats */}
            <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
                <div className="p-6 rounded-lg border bg-card text-card-foreground shadow-sm">
                    <div className="flex items-center justify-between">
                        <div>
                            <p className="text-sm font-medium text-muted-foreground">Active Runs</p>
                            <h3 className="text-2xl font-bold">{activeRuns.length}</h3>
                        </div>
                        <Play className="text-blue-500" />
                    </div>
                </div>
                <div className="p-6 rounded-lg border bg-card text-card-foreground shadow-sm">
                    <div className="flex items-center justify-between">
                        <div>
                            <p className="text-sm font-medium text-muted-foreground">Completed</p>
                            <h3 className="text-2xl font-bold">{completedRuns.length}</h3>
                        </div>
                        <CheckCircle className="text-green-500" />
                    </div>
                </div>
                <div className="p-6 rounded-lg border bg-card text-card-foreground shadow-sm">
                    <div className="flex items-center justify-between">
                        <div>
                            <p className="text-sm font-medium text-muted-foreground">Failed</p>
                            <h3 className="text-2xl font-bold">{failedRuns.length}</h3>
                        </div>
                        <XCircle className="text-red-500" />
                    </div>
                </div>
                <div className="p-6 rounded-lg border bg-card text-card-foreground shadow-sm">
                    <div className="flex items-center justify-between">
                        <div>
                            <p className="text-sm font-medium text-muted-foreground">Total Runs</p>
                            <h3 className="text-2xl font-bold">{runs?.length || 0}</h3>
                        </div>
                        <Clock className="text-gray-500" />
                    </div>
                </div>
            </div>

            {/* Recent Runs */}
            <div className="rounded-lg border bg-card text-card-foreground shadow-sm">
                <div className="p-6 border-b">
                    <h3 className="font-semibold">Recent Runs</h3>
                </div>
                <div className="p-6">
                    {runs?.length === 0 ? (
                        <p className="text-muted-foreground">No runs found.</p>
                    ) : (
                        <div className="space-y-4">
                            {runs?.slice(0, 5).map((run) => (
                                <Link key={run.run_id} to={`/runs/${run.run_id}`} className="block">
                                    <div className="flex items-center justify-between p-4 border rounded-lg hover:bg-slate-50 transition-colors">
                                        <div className="space-y-1">
                                            <p className="font-medium">{run.objective}</p>
                                            <div className="flex items-center gap-2">
                                                <p className="text-sm text-muted-foreground">{run.run_id}</p>
                                                {run.workspace_path && (
                                                    <code className="text-xs bg-slate-100 text-slate-500 px-1.5 py-0.5 rounded font-mono">
                                                        {run.workspace_path}
                                                    </code>
                                                )}
                                            </div>
                                        </div>
                                        <div className="flex items-center gap-4">
                                            <span className={`px-2 py-1 rounded text-xs font-medium ${run.status === 'running' ? 'bg-blue-100 text-blue-700' :
                                                run.status === 'completed' ? 'bg-green-100 text-green-700' :
                                                    run.status === 'failed' ? 'bg-red-100 text-red-700' :
                                                        'bg-gray-100 text-gray-700'
                                                }`}>
                                                {run.status}
                                            </span>
                                            <span className="text-sm text-muted-foreground">
                                                {new Date(run.created_at).toLocaleDateString()}
                                            </span>
                                        </div>
                                    </div>
                                </Link>
                            ))}
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
}
