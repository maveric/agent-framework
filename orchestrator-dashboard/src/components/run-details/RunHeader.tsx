import { useWebSocketStore } from '../../api/websocket';
import { CancelRunButton } from '../CancelRunButton';
import { RestartRunButton } from '../RestartRunButton';
import type { RunDetails } from '../../types/run';

interface RunHeaderProps {
    run: RunDetails;
    interruptData: any;
    isReplanning: boolean;
    onReplan: () => void;
    onShowInterruptModal: () => void;
}

export function RunHeader({
    run,
    interruptData,
    isReplanning,
    onReplan,
    onShowInterruptModal
}: RunHeaderProps) {
    const connected = useWebSocketStore((state) => state.connected);

    return (
        <div className="flex items-center justify-between mb-8">
            <div>
                <div className="flex items-center gap-3 mb-2">
                    <h1 className="text-3xl font-bold text-white tracking-tight">Run Details</h1>
                    <span className={`px-2 py-0.5 rounded text-xs font-medium uppercase tracking-wider ${run.status === 'running' ? 'bg-blue-500/20 text-blue-400 border border-blue-500/30' :
                            run.status === 'replanning' ? 'bg-purple-500/20 text-purple-400 border border-purple-500/30 animate-pulse' :
                                run.status === 'completed' ? 'bg-green-500/20 text-green-400 border border-green-500/30' :
                                    run.status === 'failed' ? 'bg-red-500/20 text-red-400 border border-red-500/30' :
                                        run.status === 'interrupted' || run.status === 'paused' ? 'bg-yellow-500/20 text-yellow-400 border border-yellow-500/30' :
                                            'bg-slate-700 text-slate-400'
                        }`}>

                        {run.status}
                    </span>
                    {/* Connection Status */}
                    <div
                        className={`w-2 h-2 rounded-full ${connected ? 'bg-green-500 shadow-[0_0_8px_rgba(34,197,94,0.6)]' : 'bg-red-500'}`}
                        title={connected ? 'Connected' : 'Disconnected'}
                    />
                </div>
                <div className="flex items-center gap-2 text-sm text-slate-400">
                    <span className="font-mono">{run.run_id}</span>
                    <span>•</span>
                    <span>{run.tasks.length} tasks</span>
                    {run.workspace_path && (
                        <>
                            <span>•</span>
                            <span className="font-mono">{run.workspace_path}</span>
                        </>
                    )}
                </div>
                <p className="text-lg text-slate-300 leading-relaxed mt-2">{run.objective}</p>
            </div>
            <div className="flex gap-3">
                {interruptData && (
                    <button
                        onClick={onShowInterruptModal}
                        className="px-4 py-2 bg-yellow-600 text-white rounded hover:bg-yellow-700 transition-colors flex items-center gap-2 shadow-lg shadow-yellow-900/20 animate-pulse-slow"
                    >
                        ⚠️ Resolve Intervention
                    </button>
                )}
                <button
                    onClick={onReplan}
                    disabled={isReplanning || run.status !== 'running'}
                    className="px-4 py-2 bg-slate-800 border border-slate-700 rounded hover:bg-slate-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                >
                    {isReplanning ? 'Replanning...' : 'Trigger Replan'}
                </button>
                <CancelRunButton
                    runId={run.run_id}
                    status={run.status}
                />
                <RestartRunButton
                    runId={run.run_id}
                    status={run.status}
                />
            </div>
        </div>
    );
}
