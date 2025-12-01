
import { useRuns } from '../hooks/useRuns';
import { Link } from '@tanstack/react-router';

export function RunsPage() {
    const { data: runs, isLoading } = useRuns();

    if (isLoading) return <div>Loading...</div>;

    return (
        <div className="space-y-6">
            <div className="flex justify-between items-center">
                <h2 className="text-2xl font-bold">Runs</h2>
                <button className="px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700">
                    New Run
                </button>
            </div>

            <div className="bg-slate-900 rounded-lg border border-slate-800 overflow-hidden">
                <table className="w-full text-left">
                    <thead className="bg-slate-800/50">
                        <tr>
                            <th className="p-4 font-medium text-slate-400">ID</th>
                            <th className="p-4 font-medium text-slate-400">Objective</th>
                            <th className="p-4 font-medium text-slate-400">Status</th>
                            <th className="p-4 font-medium text-slate-400">Created</th>
                        </tr>
                    </thead>
                    <tbody>
                        {runs?.map((run) => (
                            <tr key={run.run_id} className="border-t border-slate-800 hover:bg-slate-800/30">
                                <td className="p-4 font-mono text-sm text-blue-400">
                                    <Link to="/runs/$runId" params={{ runId: run.run_id }}>{run.run_id.slice(0, 8)}</Link>
                                </td>
                                <td className="p-4">{run.objective}</td>
                                <td className="p-4">
                                    <span className={`px-2 py-1 rounded text-xs ${run.status === 'running' ? 'bg-blue-500/20 text-blue-400' :
                                        run.status === 'completed' ? 'bg-green-500/20 text-green-400' :
                                            run.status === 'failed' ? 'bg-red-500/20 text-red-400' :
                                                'bg-slate-700 text-slate-300'
                                        }`}>
                                        {run.status}
                                    </span>
                                </td>
                                <td className="p-4 text-slate-400">
                                    {new Date(run.created_at).toLocaleDateString()}
                                </td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>
        </div>
    );
}
