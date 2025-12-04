import { Power } from 'lucide-react';
import { apiClient } from '../api/client';
import { useState } from 'react';

export function ShutdownButton() {
    const [isShuttingDown, setIsShuttingDown] = useState(false);

    const handleShutdown = async () => {
        if (!confirm('Are you sure you want to shut down the server? All running tasks will be paused.')) {
            return;
        }

        setIsShuttingDown(true);

        try {
            await apiClient('/api/shutdown', { method: 'POST' });
            // Server will shut down, connection will drop
        } catch (err) {
            // Expected - server shuts down immediately
            console.log('Server shutdown initiated');
        }
    };

    return (
        <button
            onClick={handleShutdown}
            disabled={isShuttingDown}
            className={`flex items-center gap-2 px-3 py-2 rounded-lg text-sm font-medium transition-colors ${isShuttingDown
                    ? 'bg-gray-700 text-gray-500 cursor-not-allowed'
                    : 'bg-red-900/20 text-red-400 hover:bg-red-900/40 border border-red-800/50'
                }`}
            title="Shutdown server (all runs will pause)"
        >
            <Power className="w-4 h-4" />
            {isShuttingDown ? 'Shutting down...' : 'Stop Server'}
        </button>
    );
}
