import { X } from 'lucide-react';
import { TaskDetailsContent } from '../TaskDetailsContent';

interface DirectorLogsModalProps {
    logs?: any;
    onClose: () => void;
}

export function DirectorLogsModal({ logs, onClose }: DirectorLogsModalProps) {
    return (
        <div className="fixed inset-0 bg-black/50 backdrop-blur-sm flex items-center justify-center z-50 p-4">
            <div className="bg-slate-900 rounded-xl border border-slate-700 w-full max-w-4xl max-h-[90vh] flex flex-col shadow-2xl">
                <div className="flex items-center justify-between p-4 border-b border-slate-800">
                    <div className="flex items-center gap-3">
                        <h2 className="text-lg font-bold text-white">Director System Logs</h2>
                        <span className="bg-indigo-900/30 text-indigo-300 px-2 py-0.5 rounded text-xs border border-indigo-800/50">
                            GLOBAL VIEW
                        </span>
                    </div>
                    <button
                        onClick={onClose}
                        className="text-slate-400 hover:text-white p-1 rounded hover:bg-slate-800 transition-colors"
                    >
                        <X className="w-5 h-5" />
                    </button>
                </div>
                <div className="p-6 overflow-y-auto">
                    <TaskDetailsContent
                        task={{
                            id: 'director-system',
                            description: 'Global orchestration logs. Shows high-level planning, decomposition, and integration decisions.',
                            status: 'active',
                            phase: 'orchestration',
                            component: 'director',
                            depends_on: []
                        }}
                        logs={logs}
                    />
                </div>
            </div>
        </div>
    );
}
