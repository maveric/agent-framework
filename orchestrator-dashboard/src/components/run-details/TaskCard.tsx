import { ChevronDown, ChevronUp } from 'lucide-react';
import { TaskDetailsContent } from '../TaskDetailsContent';
import type { Task } from '../../types/run';
import { workerColors } from '../../types/run';

interface TaskCardProps {
    task: Task;
    allTasks: Task[];
    isExpanded: boolean;
    logs?: any;
    isLoadingLogs?: boolean;
    onToggle: () => void;
    onResolveClick: (task: Task) => void;
}

export function TaskCard({
    task,
    allTasks,
    isExpanded,
    logs,
    isLoadingLogs,
    onToggle,
    onResolveClick
}: TaskCardProps) {
    const isWaiting = task.status === 'failed' || task.status === 'waiting_human';

    return (
        <div
            className={`bg-slate-800 p-4 rounded-lg border transition-all ${isWaiting
                ? 'border-yellow-500 shadow-[0_0_15px_rgba(234,179,8,0.3)] animate-pulse-slow'
                : 'border-slate-700 hover:border-slate-600'
                }`}
        >
            <div
                className="flex items-start justify-between mb-2 cursor-pointer"
                onClick={onToggle}
            >
                <div className="flex items-center gap-2">
                    {isExpanded ? (
                        <ChevronUp className="w-4 h-4 text-slate-500" />
                    ) : (
                        <ChevronDown className="w-4 h-4 text-slate-500" />
                    )}
                    <span className="font-mono text-xs text-slate-500">{task.id}</span>
                </div>
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
            </div>

            <p className={`text-sm text-slate-300 ${isExpanded ? '' : 'line-clamp-2'}`}>
                {task.description}
            </p>

            <div className="mt-2 flex items-center gap-2 text-xs text-slate-500">
                <span className="bg-slate-700/50 px-1.5 py-0.5 rounded">{task.component}</span>
                <span className="bg-slate-700/50 px-1.5 py-0.5 rounded">{task.phase}</span>
                {task.assigned_worker_profile && (
                    <span className={`px-1.5 py-0.5 rounded border ${workerColors[task.assigned_worker_profile] || 'bg-slate-800 text-slate-400 border-slate-700'
                        }`}>
                        {task.assigned_worker_profile}
                    </span>
                )}
                {task.retry_count !== undefined && task.retry_count > 0 && (
                    <span className="px-1.5 py-0.5 rounded bg-yellow-900/20 text-yellow-400 border border-yellow-700/50 font-semibold">
                        ↻ {task.retry_count}
                    </span>
                )}
            </div>

            {task.depends_on && task.depends_on.length > 0 && (
                <div className="mt-2 text-xs text-slate-500">
                    <span className="mr-1">Depends on:</span>
                    {task.depends_on.map(dep => {
                        const depTask = allTasks.find(t => t.id === dep);
                        const isComplete = depTask?.status === 'complete';
                        return (
                            <span
                                key={dep}
                                className={`px-1 rounded mr-1 font-mono ${isComplete
                                    ? 'bg-green-900/30 border border-green-700/50 text-green-400'
                                    : 'bg-slate-800 border border-slate-700 text-slate-400'
                                    }`}
                            >
                                {dep}
                            </span>
                        );
                    })}
                </div>
            )}

            {isExpanded && (
                <div className="mt-4 pt-4 border-t border-slate-700">
                    {isLoadingLogs ? (
                        <div className="flex items-center gap-2 text-slate-400 text-sm py-4">
                            <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-blue-500"></div>
                            Loading conversation...
                        </div>
                    ) : (
                        <TaskDetailsContent
                            task={task}
                            logs={logs}
                            onResolveClick={onResolveClick}
                        />
                    )}
                </div>
            )}
        </div>
    );
}
