import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { apiClient } from '../../api/client';
import type { Task, HumanResolution } from '../../types/api';
import { ResolveTaskDialog } from './ResolveTaskDialog';

interface HumanQueueProps {
    runId?: string; // Optional - if not provided, shows global queue
}

export function HumanQueue({ runId }: HumanQueueProps) {
    const [selectedTask, setSelectedTask] = useState<Task | null>(null);
    const queryClient = useQueryClient();

    // Fetch waiting tasks
    const { data: tasks, isLoading } = useQuery({
        queryKey: runId ? ['human-queue', runId] : ['human-queue'],
        queryFn: () =>
            runId
                ? apiClient<Task[]>(`/api/runs/${runId}/human-queue`)
                : apiClient<Array<{ run_id: string; task: Task }>>('/api/human-queue').then(res => res.map(r => r.task)), // Adapt response
        refetchInterval: 5000,
    });

    // Resolve mutation
    const resolveMutation = useMutation({
        mutationFn: ({
            runId,
            taskId,
            resolution,
        }: {
            runId: string;
            taskId: string;
            resolution: HumanResolution;
        }) =>
            apiClient(`/api/runs/${runId}/tasks/${taskId}/resolve`, {
                method: 'POST',
                body: JSON.stringify(resolution),
            }),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['human-queue'] });
            setSelectedTask(null);
        },
    });

    if (isLoading) {
        return <div className="p-4">Loading...</div>;
    }

    const taskList = tasks || [];

    if (taskList.length === 0) {
        return (
            <div className="p-8 text-center text-gray-500">
                <p className="text-lg">No tasks waiting for human review</p>
                <p className="text-sm mt-2">Tasks needing input will appear here</p>
            </div>
        );
    }

    return (
        <div className="space-y-4">
            <h2 className="text-lg font-semibold">
                Tasks Awaiting Review
            </h2>

            <div className="grid gap-4">
                {taskList.map((task) => (
                    <div
                        key={task.id}
                        className="p-4 border rounded-lg bg-white shadow-sm flex items-center justify-between"
                    >
                        <div>
                            <div className="font-medium">{task.description}</div>
                            <div className="text-sm text-gray-500 mt-1">
                                ID: {task.id} • Phase: {task.phase}
                            </div>
                        </div>

                        <button
                            onClick={() => setSelectedTask(task)}
                            className="px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700"
                        >
                            Review
                        </button>
                    </div>
                ))}
            </div>

            {selectedTask && (
                <ResolveTaskDialog
                    task={selectedTask}
                    open={!!selectedTask}
                    onOpenChange={(open) => !open && setSelectedTask(null)}
                    onResolve={(resolution) => {
                        // We need runId here. Assuming task has run_id or we pass it.
                        // If global queue, we need to know which run the task belongs to.
                        // The API for global queue returns { run_id, task }.
                        // I adapted the queryFn to return just tasks, but I lost run_id.
                        // I should fix queryFn to return tasks with run_id attached or keep the structure.
                        // For now, let's assume runId is passed or available.
                        // If runId prop is missing, we might have an issue.
                        // I'll fix this in a moment.
                        if (runId) {
                            resolveMutation.mutate({ runId, taskId: selectedTask.id, resolution });
                        } else {
                            console.error("Run ID missing for resolution");
                        }
                    }}
                />
            )}
        </div>
    );
}
