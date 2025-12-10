import type { RunDetails } from '../../types/run';

interface ModelConfigProps {
    modelConfig: RunDetails['model_config'];
    onViewDirectorLogs: () => void;
}

export function ModelConfig({ modelConfig, onViewDirectorLogs }: ModelConfigProps) {
    if (!modelConfig) return null;

    return (
        <div className="bg-slate-900 rounded-lg p-6 border border-slate-800 mb-8">
            <h3 className="text-sm font-semibold text-slate-200 mb-4">Model Configuration</h3>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
                <div
                    className="space-y-1 cursor-pointer hover:bg-slate-800/50 p-2 -m-2 rounded transition-colors"
                    onClick={onViewDirectorLogs}
                    title="View Director Logs"
                >
                    <div className="text-xs font-bold text-purple-400 uppercase tracking-wider mb-1">DIRECTOR</div>
                    <div className="text-sm font-medium text-white">{modelConfig.director_model.model_name}</div>
                    <div className="text-xs text-slate-500">{modelConfig.director_model.provider}</div>
                    <div className="text-xs text-slate-600">temp: {modelConfig.director_model.temperature}</div>
                </div>
                <div className="space-y-1">
                    <div className="text-xs font-bold text-blue-400 uppercase tracking-wider mb-1">WORKER</div>
                    <div className="text-sm font-medium text-white">{modelConfig.worker_model.model_name}</div>
                    <div className="text-xs text-slate-500">{modelConfig.worker_model.provider}</div>
                    <div className="text-xs text-slate-600">temp: {modelConfig.worker_model.temperature}</div>
                </div>
                <div className="space-y-1">
                    <div className="text-xs font-bold text-green-400 uppercase tracking-wider mb-1">STRATEGIST</div>
                    <div className="text-sm font-medium text-white">{modelConfig.strategist_model.model_name}</div>
                    <div className="text-xs text-slate-500">{modelConfig.strategist_model.provider}</div>
                    <div className="text-xs text-slate-600">temp: {modelConfig.strategist_model.temperature}</div>
                </div>
            </div>
        </div>
    );
}
