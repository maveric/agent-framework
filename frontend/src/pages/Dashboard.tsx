

export function Dashboard() {
    return (
        <div className="space-y-6">
            <h2 className="text-2xl font-bold">Dashboard</h2>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
                <div className="p-6 bg-slate-900 rounded-lg border border-slate-800">
                    <h3 className="text-lg font-medium text-slate-400">Active Runs</h3>
                    <p className="text-3xl font-bold mt-2">0</p>
                </div>
                <div className="p-6 bg-slate-900 rounded-lg border border-slate-800">
                    <h3 className="text-lg font-medium text-slate-400">Pending Tasks</h3>
                    <p className="text-3xl font-bold mt-2">0</p>
                </div>
                <div className="p-6 bg-slate-900 rounded-lg border border-slate-800">
                    <h3 className="text-lg font-medium text-slate-400">Human Reviews</h3>
                    <p className="text-3xl font-bold mt-2">0</p>
                </div>
            </div>
        </div>
    );
}
