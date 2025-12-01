import { useParams } from '@tanstack/react-router';
import { useRun } from '../hooks/useRuns';

export function RunDetailPage() {
    const { runId } = useParams({ from: '/runs/$runId' });
    const { data: run, isLoading } = useRun(runId);

    if (isLoading) return <div>Loading...</div>;
    if (!run) return <div>Run not found</div>;

    return (
        <div className="space-y-6">
            <h2 className="text-2xl font-bold">Run: {run.run_id}</h2>
            <div className="bg-slate-900 p-6 rounded-lg border border-slate-800">
                <h3 className="text-lg font-medium mb-4">Objective</h3>
                <p className="text-slate-300">{run.objective}</p>
            </div>
        </div>
    );
}
