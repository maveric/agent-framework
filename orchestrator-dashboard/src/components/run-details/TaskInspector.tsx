import { X, Hand } from 'lucide-react';
import { TaskDetailsContent } from '../TaskDetailsContent';
import type { Task } from '../../types/run';

interface TaskInspectorProps {
    task: Task;
    logs?: any;
    onClose: () => void;
    onInterrupt: (taskId: string) => void;
    onResolveClick: (task: Task) => void;
}

export function TaskInspector({
    task,
    logs,
    onClose,
    onInterrupt,
    onResolveClick
}: TaskInspectorProps) {
    return (
        <div className="lg:col-span-1 border-l border-slate-800 bg-slate-900/50 -my-8 py-8 px-6 overflow-y-auto h-screen sticky top-0">
            <div className="space-y-6">
                <div className="flex items-start justify-between">
                    <div>
                        <div className="flex items-center gap-2 mb-1">
                            <span className={`text-xs px-2 py-0.5 rounded-full capitalize ${task.status === 'complete' ? 'bg-green-400/10 text-green-400' :
                                    task.status === 'failed' ? 'bg-red-400/10 text-red-400' :
                                        task.status === 'active' ? 'bg-blue-400/10 text-blue-400' :
                                            task.status?.startsWith('pending_') ? 'bg-yellow-400/10 text-yellow-400 animate-pulse' :
                                                'bg-slate-700 text-slate-400'
                                }`}>
                                {task.status?.startsWith('pending_')
                                    ? task.status.replace('pending_', '') + ' (syncing)'
                                    : task.status}
                            </span>
                            <span className="font-mono text-xs text-slate-500">{task.id}</span>
                        </div>
                        <div className="flex items-center gap-2 text-xs text-slate-500">
                            <span className="bg-slate-700/50 px-1.5 py-0.5 rounded">{task.component}</span>
                            <span className="bg-slate-700/50 px-1.5 py-0.5 rounded">{task.phase}</span>
                        </div>
                    </div>
                    <div className="flex items-center gap-2">
                        {task.status === 'active' && (
                            <button
                                onClick={() => onInterrupt(task.id)}
                                className="flex items-center gap-1.5 px-2 py-1 bg-red-900/20 hover:bg-red-900/40 text-red-400 text-xs rounded border border-red-800/50 transition-colors"
                                title="Force Interrupt Task"
                            >
                                <Hand className="w-3 h-3" />
                                Interrupt
                            </button>
                        )}
                        <button
                            onClick={onClose}
                            className="text-slate-400 hover:text-slate-200 p-1 hover:bg-slate-700 rounded"
                        >
                            <X className="w-4 h-4" />
                        </button>
                    </div>
                </div>
                <div className="p-4 overflow-y-auto flex-1">
                    <TaskDetailsContent
                        task={task}
                        logs={logs}
                        onResolveClick={onResolveClick}
                    />
                </div>
            </div>
        </div>
    );
}
