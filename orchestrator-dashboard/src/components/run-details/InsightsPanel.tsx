import { formatDistanceToNow } from 'date-fns';

interface InsightsPanelProps {
    insights: any[];
}

export function InsightsPanel({ insights }: InsightsPanelProps) {
    if (!insights || insights.length === 0) return null;

    return (
        <div className="bg-slate-800 rounded-lg p-6 border border-slate-700">
            <h2 className="text-lg font-semibold text-slate-200 mb-4">Insights</h2>
            <div className="space-y-3">
                {insights.map((insight: any) => (
                    <div key={insight.id} className="bg-slate-900/50 p-3 rounded border border-slate-700/50">
                        <div className="flex items-center gap-2 mb-1">
                            <span className="text-xs font-mono text-purple-400">INSIGHT</span>
                            <span className="text-xs text-slate-500">
                                {formatDistanceToNow(new Date(insight.created_at))} ago
                            </span>
                        </div>
                        <p className="text-sm text-slate-300">{insight.summary}</p>
                    </div>
                ))}
            </div>
        </div>
    );
}
