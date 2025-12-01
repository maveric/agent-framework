
import { Link, useLocation } from '@tanstack/react-router';
import { LayoutDashboard, ListTodo, Users, Activity } from 'lucide-react';

const NAV_ITEMS = [
    { label: 'Dashboard', icon: LayoutDashboard, to: '/' },
    { label: 'Runs', icon: ListTodo, to: '/runs' },
    { label: 'Human Queue', icon: Users, to: '/human' },
];

export function Sidebar() {
    const location = useLocation();

    return (
        <aside className="w-64 bg-slate-900 border-r border-slate-800 flex flex-col">
            <div className="p-6">
                <div className="flex items-center gap-2 text-blue-400">
                    <Activity className="w-6 h-6" />
                    <span className="font-bold text-lg tracking-tight">Orchestrator</span>
                </div>
            </div>

            <nav className="flex-1 px-4 space-y-1">
                {NAV_ITEMS.map((item) => (
                    <Link
                        key={item.to}
                        to={item.to}
                        className={`flex items-center gap-3 px-3 py-2 rounded-lg text-sm font-medium transition-colors ${location.pathname === item.to
                            ? 'bg-blue-500/10 text-blue-400'
                            : 'text-slate-400 hover:text-slate-100 hover:bg-slate-800'
                            }`}
                    >
                        <item.icon className="w-5 h-5" />
                        {item.label}
                    </Link>
                ))}
            </nav>

            <div className="p-4 border-t border-slate-800">
                <div className="text-xs text-slate-500">
                    v1.0.0
                </div>
            </div>
        </aside>
    );
}
