import React from 'react';
import { NavLink, Outlet } from 'react-router-dom';
import { LayoutDashboard, Play, Users, Settings } from 'lucide-react';
import { useWebSocketStore } from '../../api/websocket';

export function Layout() {
    const connect = useWebSocketStore((state) => state.connect);
    const connected = useWebSocketStore((state) => state.connected);

    React.useEffect(() => {
        connect();
    }, [connect]);

    return (
        <div className="flex h-screen bg-background">
            {/* Sidebar */}
            <aside className="w-64 border-r bg-card">
                <div className="p-6">
                    <h1 className="text-xl font-bold">Orchestrator</h1>
                    <div className="mt-2 flex items-center gap-2 text-sm text-muted-foreground">
                        <div className={`w-2 h-2 rounded-full ${connected ? 'bg-green-500' : 'bg-red-500'}`} />
                        {connected ? 'Connected' : 'Disconnected'}
                    </div>
                </div>

                <nav className="px-4 space-y-2">
                    <NavLink
                        to="/"
                        className={({ isActive }) =>
                            `flex items-center gap-3 px-4 py-2 rounded-md transition-colors ${isActive ? 'bg-primary text-primary-foreground' : 'hover:bg-accent'
                            }`
                        }
                    >
                        <LayoutDashboard size={20} />
                        Dashboard
                    </NavLink>
                    <NavLink
                        to="/runs"
                        className={({ isActive }) =>
                            `flex items-center gap-3 px-4 py-2 rounded-md transition-colors ${isActive ? 'bg-primary text-primary-foreground' : 'hover:bg-accent'
                            }`
                        }
                    >
                        <Play size={20} />
                        Runs
                    </NavLink>
                    <NavLink
                        to="/queue"
                        className={({ isActive }) =>
                            `flex items-center gap-3 px-4 py-2 rounded-md transition-colors ${isActive ? 'bg-primary text-primary-foreground' : 'hover:bg-accent'
                            }`
                        }
                    >
                        <Users size={20} />
                        Human Queue
                    </NavLink>
                </nav>
            </aside>

            {/* Main Content */}
            <main className="flex-1 overflow-auto">
                <header className="h-16 border-b flex items-center px-8 bg-card">
                    <div className="ml-auto">
                        <button className="p-2 hover:bg-accent rounded-full">
                            <Settings size={20} />
                        </button>
                    </div>
                </header>
                <div className="p-8">
                    <Outlet />
                </div>
            </main>
        </div>
    );
}
