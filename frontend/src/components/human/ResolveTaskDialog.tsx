
import type { Task, HumanResolution } from '../../types/api';
import * as Dialog from '@radix-ui/react-dialog';

interface ResolveTaskDialogProps {
    task: Task;
    open: boolean;
    onOpenChange: (open: boolean) => void;
    onResolve: (resolution: HumanResolution) => void;
}

export function ResolveTaskDialog({ task, open, onOpenChange, onResolve }: ResolveTaskDialogProps) {
    return (
        <Dialog.Root open={open} onOpenChange={onOpenChange}>
            <Dialog.Portal>
                <Dialog.Overlay className="fixed inset-0 bg-black/50" />
                <Dialog.Content className="fixed top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 bg-white p-6 rounded-lg w-[500px]">
                    <Dialog.Title className="text-lg font-bold mb-4">Resolve Task: {task.id}</Dialog.Title>
                    <Dialog.Description className="mb-4">
                        {task.description}
                    </Dialog.Description>

                    <div className="flex gap-2 justify-end">
                        <button
                            onClick={() => onResolve({ action: 'approve' })}
                            className="px-4 py-2 bg-green-600 text-white rounded hover:bg-green-700"
                        >
                            Approve
                        </button>
                        <button
                            onClick={() => onResolve({ action: 'reject', feedback: 'Rejected by user' })}
                            className="px-4 py-2 bg-red-600 text-white rounded hover:bg-red-700"
                        >
                            Reject
                        </button>
                    </div>

                    <Dialog.Close className="absolute top-4 right-4 text-gray-500 hover:text-gray-700">
                        ✕
                    </Dialog.Close>
                </Dialog.Content>
            </Dialog.Portal>
        </Dialog.Root>
    );
}
