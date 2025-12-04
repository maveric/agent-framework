import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Play, FolderOpen, AlertCircle } from 'lucide-react';

interface CreateRunRequest {
    objective: string;
    workspace_path?: string;
}

export function NewRun() {
    const navigate = useNavigate();
    const [objective, setObjective] = useState('');
    const [workspacePath, setWorkspacePath] = useState('');
    const [isSubmitting, setIsSubmitting] = useState(false);
    const [error, setError] = useState<string | null>(null);

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault();

        if (!objective.trim()) {
            setError('Objective is required');
            return;
        }

        setIsSubmitting(true);
        setError(null);

        try {
            const payload: CreateRunRequest = {
                objective: objective.trim(),
            };

            if (workspacePath.trim()) {
                payload.workspace_path = workspacePath.trim();
            }

            const response = await fetch('http://localhost:8085/api/runs', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify(payload),
            });

            if (!response.ok) {
                const errorData = await response.json().catch(() => ({}));
                throw new Error(errorData.detail || `HTTP error! status: ${response.status}`);
            }

            const data = await response.json();
            const runId = data.run_id;

            // Navigate to the run details page
            navigate(`/runs/${runId}`);
        } catch (err) {
            console.error('Failed to create run:', err);
            setError(err instanceof Error ? err.message : 'Failed to create run');
        } finally {
            setIsSubmitting(false);
        }
    };

    return (
        <div className="min-h-screen bg-slate-950 text-slate-200 p-8">
            <div className="max-w-4xl mx-auto space-y-8">
                {/* Header */}
                <div>
                    <h1 className="text-3xl font-bold text-white mb-2">Create New Run</h1>
                    <p className="text-slate-400">
                        Define an objective and let the orchestrator break it down into executable tasks
                    </p>
                </div>

                {/* Form Card */}
                <div className="bg-slate-900 rounded-lg border border-slate-800 p-8">
                    <form onSubmit={handleSubmit} className="space-y-6">
                        {/* Objective Field */}
                        <div>
                            <label htmlFor="objective" className="block text-sm font-semibold text-slate-200 mb-2">
                                Objective <span className="text-red-400">*</span>
                            </label>
                            <textarea
                                id="objective"
                                value={objective}
                                onChange={(e) => setObjective(e.target.value)}
                                placeholder="E.g., Create a REST API with user authentication, or Build a React dashboard with real-time updates"
                                rows={6}
                                className="w-full bg-slate-800 border border-slate-700 rounded-lg px-4 py-3 text-slate-200 placeholder-slate-500 focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 focus:outline-none transition-colors resize-none"
                                disabled={isSubmitting}
                            />
                            <p className="mt-2 text-xs text-slate-500">
                                Describe what you want to build. Be specific about features, technologies, and requirements.
                            </p>
                        </div>

                        {/* Workspace Path Field */}
                        <div>
                            <label htmlFor="workspace" className="block text-sm font-semibold text-slate-200 mb-2 flex items-center gap-2">
                                <FolderOpen className="w-4 h-4" />
                                Workspace Path <span className="text-slate-500 font-normal">(optional)</span>
                            </label>
                            <input
                                id="workspace"
                                type="text"
                                value={workspacePath}
                                onChange={(e) => setWorkspacePath(e.target.value)}
                                placeholder="E.g., ./my-project or leave blank for auto-generated"
                                className="w-full bg-slate-800 border border-slate-700 rounded-lg px-4 py-3 text-slate-200 placeholder-slate-500 focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 focus:outline-none transition-colors font-mono text-sm"
                                disabled={isSubmitting}
                            />
                            <p className="mt-2 text-xs text-slate-500">
                                Directory where the orchestrator will create files. If not specified, a unique workspace will be generated.
                            </p>
                        </div>

                        {/* Error Alert */}
                        {error && (
                            <div className="bg-red-900/20 border border-red-500/50 rounded-lg p-4 flex items-start gap-3">
                                <AlertCircle className="w-5 h-5 text-red-400 flex-shrink-0 mt-0.5" />
                                <div>
                                    <p className="text-sm font-semibold text-red-400">Error Creating Run</p>
                                    <p className="text-sm text-red-300 mt-1">{error}</p>
                                </div>
                            </div>
                        )}

                        {/* Submit Button */}
                        <div className="flex items-center justify-between pt-4 border-t border-slate-800">
                            <button
                                type="button"
                                onClick={() => navigate('/')}
                                className="px-4 py-2 text-slate-400 hover:text-slate-200 transition-colors"
                                disabled={isSubmitting}
                            >
                                Cancel
                            </button>
                            <button
                                type="submit"
                                disabled={isSubmitting || !objective.trim()}
                                className="flex items-center gap-2 px-6 py-3 bg-blue-600 hover:bg-blue-700 disabled:bg-slate-700 disabled:text-slate-500 disabled:cursor-not-allowed text-white font-semibold rounded-lg transition-colors shadow-lg shadow-blue-900/50"
                            >
                                <Play className={`w-5 h-5 ${isSubmitting ? 'animate-pulse' : ''}`} />
                                {isSubmitting ? 'Creating Run...' : 'Start Run'}
                            </button>
                        </div>
                    </form>
                </div>

                {/* Info Panel */}
                <div className="bg-blue-900/10 border border-blue-500/30 rounded-lg p-6">
                    <h3 className="text-sm font-semibold text-blue-400 mb-3 flex items-center gap-2">
                        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                        </svg>
                        What happens next?
                    </h3>
                    <ul className="space-y-2 text-sm text-slate-300">
                        <li className="flex items-start gap-2">
                            <span className="text-blue-400 font-bold mt-0.5">1.</span>
                            <span>The <strong className="text-white">Director</strong> analyzes your objective and creates a design specification</span>
                        </li>
                        <li className="flex items-start gap-2">
                            <span className="text-blue-400 font-bold mt-0.5">2.</span>
                            <span>Tasks are decomposed and assigned to specialized worker agents (planner, coder, tester)</span>
                        </li>
                        <li className="flex items-start gap-2">
                            <span className="text-blue-400 font-bold mt-0.5">3.</span>
                            <span>The <strong className="text-white">Strategist</strong> performs QA validation on completed tasks</span>
                        </li>
                        <li className="flex items-start gap-2">
                            <span className="text-blue-400 font-bold mt-0.5">4.</span>
                            <span>If any task exceeds retry limits, you'll be prompted for <strong className="text-yellow-400">human intervention</strong></span>
                        </li>
                    </ul>
                </div>

                {/* Examples */}
                <div className="bg-slate-900/50 border border-slate-800 rounded-lg p-6">
                    <h3 className="text-sm font-semibold text-slate-200 mb-4">Example Objectives</h3>
                    <div className="grid gap-3">
                        {[
                            'Build a kanban board with drag-and-drop functionality using React and FastAPI',
                            'Create a CLI tool in Python that analyzes git repositories and generates commit statistics',
                            'Implement a REST API with JWT authentication, user management, and PostgreSQL database',
                        ].map((example, idx) => (
                            <button
                                key={idx}
                                type="button"
                                onClick={() => setObjective(example)}
                                className="text-left p-3 bg-slate-800/50 hover:bg-slate-800 border border-slate-700 rounded text-sm text-slate-300 hover:text-slate-100 transition-colors"
                                disabled={isSubmitting}
                            >
                                {example}
                            </button>
                        ))}
                    </div>
                </div>
            </div>
        </div>
    );
}
