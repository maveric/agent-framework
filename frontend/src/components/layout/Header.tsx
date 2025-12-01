
import { useWebSocketStore } from '../../stores/websocket';

export function Header() {
    const connected = useWebSocketStore((state) => state.connected);

    return (
        <header className="h-16 border-b border-slate-800 flex items-center justify-between px-6 bg-slate-900/50 backdrop-blur">
            <h1 className="text-xl font-semibold text-slate-100">
                Dashboard
            </h1>

            <div className="flex items-center gap-4">
                <div className="flex items-center gap-2 text-sm">
                    <div className={`w-2 h-2 rounded-full ${connected ? 'bg-green-500' : 'bg-red-500'}`} />
                    <span className="text-slate-400">{connected ? 'Connected' : 'Disconnected'}</span>
                </div>
            </div>
        </header>
    );
}
