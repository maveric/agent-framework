import { useEffect, useState, useRef } from 'react';
import { useWSMessage } from '../../stores/websocket';

export function LogStream() {
    const [logs, setLogs] = useState<string[]>([]);
    const bottomRef = useRef<HTMLDivElement>(null);

    useWSMessage('log_message', (msg) => {
        setLogs((prev) => [...prev.slice(-999), msg.payload.message]);
    });

    useEffect(() => {
        bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
    }, [logs]);

    return (
        <div className="h-64 overflow-auto bg-black text-green-400 font-mono text-xs p-4 rounded border border-slate-800">
            {logs.map((log, i) => (
                <div key={i} className="whitespace-pre-wrap break-all border-b border-slate-900/50 py-0.5">
                    {log}
                </div>
            ))}
            <div ref={bottomRef} />
        </div>
    );
}
