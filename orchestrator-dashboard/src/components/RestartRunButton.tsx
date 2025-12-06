import { RefreshCw } from 'lucide-react';
import { apiClient } from '../api/client';
import { useState } from 'react';

interface RestartRunButtonProps {
    runId: string;
    status: string;
    onRestart?: () => void;
}

export function RestartRunButton({ runId, status, onRestart }: RestartRunButtonProps) {
    const [isRestarting, setIsRestarting] = useState(false);

    // Only show for stopped/cancelled/failed runs (not running ones)
    if (['running', 'interrupted'].includes(status)) {
        return null;
    }

    const handleRestart = async () => {
        if (!confirm('Restart this run? It will resume from the last saved state.')) {
            return;
        }

        setIsRestarting(true);

        try {
            const result = await apiClient(`/api/runs/${runId}/restart`, { method: 'POST' });
            if (result.status === 'error') {
                alert(result.message || 'Failed to restart run');
            } else {
                onRestart?.();
            }
        } catch (err) {
            console.error('Failed to restart run:', err);
            alert('Failed to restart run. Check console for details.');
        } finally {
            setIsRestarting(false);
        }
    };

    return (
        <button
            onClick={handleRestart}
            disabled={isRestarting}
            className={`flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${isRestarting
                ? 'bg-gray-800 text-gray-500 cursor-not-allowed'
                : 'bg-green-900/20 text-green-400 hover:bg-green-900/40 border border-green-800/50'
                }`}
            title="Restart this run from last saved state"
        >
            <RefreshCw className={`w-3.5 h-3.5 ${isRestarting ? 'animate-spin' : ''}`} />
            {isRestarting ? 'Restarting...' : 'Restart Run'}
        </button>
    );
}
