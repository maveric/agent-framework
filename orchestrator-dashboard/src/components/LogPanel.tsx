import { useState, useEffect } from 'react';
import { useWebSocketStore } from '../api/websocket';

interface LogEntry {
    message: string;
    level: string;
    node?: string;
    timestamp: string;
}

interface LogPanelProps {
    runId: string;
}

export function LogPanel({ runId }: LogPanelProps) {
    const [logs, setLogs] = useState<LogEntry[]>([]);
    const addMessageHandler = useWebSocketStore((state) => state.addMessageHandler);

    useEffect(() => {
        const unsubscribe = addMessageHandler('log_message', (msg) => {
            if (msg.run_id === runId) {
                setLogs(prev => [...prev, msg.payload as LogEntry]);
            }
        });

        return unsubscribe;
    }, [runId, addMessageHandler]);

    const getLevelColor = (level: string) => {
        switch (level) {
            case 'success': return 'text-green-400';
            case 'error': return 'text-red-400';
            case 'warning': return 'text-yellow-400';
            default: return 'text-slate-300';
        }
    };

    const getNodeColor = (node?: string) => {
        if (!node) return '';
        switch (node) {
            case 'director': return 'text-purple-400';
            case 'worker': return 'text-blue-400';
            case 'strategist': return 'text-green-400';
            default: return 'text-slate-400';
        }
    };

    return (
        <div className="bg-slate-900 rounded-lg border border-slate-800 p-4 h-96 overflow-y-auto">
            <h3 className="text-sm font-semibold text-slate-200 mb-3 flex items-center gap-2">
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5 .414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                </svg>
                Real-Time Logs
            </h3>

            {logs.length === 0 ? (
                <div className="text-center text-slate-500 py-8 font-mono text-xs">
                    Waiting for log messages...
                </div>
            ) : (
                <div className="space-y-1 font-mono text-xs">
                    {logs.map((log, i) => (
                        <div key={i} className={`${getLevelColor(log.level)} border-l-2 border-slate-700 pl-3 py-1`}>
                            <span className="text-slate-500">
                                [{new Date(log.timestamp).toLocaleTimeString()}]
                            </span>
                            {log.node && (
                                <span className={`ml-2 ${getNodeColor(log.node)}`}>
                                    [{log.node}]
                                </span>
                            )}
                            <span className="ml-2">{log.message}</span>
                        </div>
                    ))}
                </div>
            )}
        </div>
    );
}
