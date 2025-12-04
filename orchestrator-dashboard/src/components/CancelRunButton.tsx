import { XCircle } from 'lucide-react';
import { apiClient } from '../api/client';
import { useState } from 'react';

interface CancelRunButtonProps {
    runId: string;
    status: string;
    onCancel?: () => void;
}

export function CancelRunButton({ runId, status, onCancel }: CancelRunButtonProps) {
    const [isCancelling, setIsCancelling] = useState(false);

    // Only show for running/interrupted runs
    if (!['running', 'interrupted'].includes(status)) {
        return null;
    }

    const handleCancel = async () => {
        if (!confirm('Cancel this run? The graph will stop executing and the run will be marked as cancelled.')) {
            return;
        }

        setIsCancelling(true);

        try {
            await apiClient(`/api/runs/${runId}/cancel`, { method: 'POST' });
            onCancel?.();
        } catch (err) {
            console.error('Failed to cancel run:', err);
            alert('Failed to cancel run. Check console for details.');
        } finally {
            setIsCancelling(false);
        }
    };

    return (
        <button
            onClick={handleCancel}
            disabled={isCancelling}
            className={`flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${isCancelling
                    ? 'bg-gray-800 text-gray-500 cursor-not-allowed'
                    : 'bg-red-900/20 text-red-400 hover:bg-red-900/40 border border-red-800/50'
                }`}
            title="Cancel this run"
        >
            <XCircle className="w-3.5 h-3.5" />
            {isCancelling ? 'Cancelling...' : 'Cancel Run'}
        </button>
    );
}
