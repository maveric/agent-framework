interface DesignLogPanelProps {
    designLog: any[];
}

export function DesignLogPanel({ designLog }: DesignLogPanelProps) {
    if (!designLog || designLog.length === 0) return null;

    return (
        <div className="bg-slate-800 rounded-lg p-6 border border-slate-700">
            <h2 className="text-lg font-semibold text-slate-200 mb-4">Design Decisions</h2>
            <div className="space-y-3">
                {designLog.map((log: any) => (
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
    );
}
