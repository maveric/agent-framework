
import { AlertCircle } from 'lucide-react';

// Define the interface locally or import it if shared
interface Task {
    id: string;
    description: string;
    status: 'planned' | 'ready' | 'active' | 'complete' | 'failed' | 'blocked';
    phase: string;
    component: string;
    assigned_worker_profile?: string;
    depends_on: string[];
    acceptance_criteria?: string[];
    result_path?: string;
    qa_verdict?: {
        passed: boolean;
        overall_feedback: string;
    };
    aar?: {
        summary: string;
        approach: string;
        challenges: string[];
        decisions_made: string[];
        files_modified: string[];
        time_spent_estimate?: string;
    };
    escalation?: {
        type: string;
        reason: string;
        suggested_action: string;
    };
}

interface TaskDetailsContentProps {
    task: Task;
    logs?: any[];
}

export function TaskDetailsContent({ task, logs }: TaskDetailsContentProps) {
    return (
        <div className="space-y-4">
            {/* Description */}
            <div>
                <h4 className="text-xs font-semibold text-slate-400 mb-1">Description</h4>
                <p className="text-sm text-slate-300 whitespace-pre-wrap">{task.description}</p>
            </div>

            {/* Agent Logs */}
            {logs && logs.length > 0 && (
                <div>
                    <h4 className="text-xs font-semibold text-slate-400 mb-2">Agent Logs</h4>
                    <div className="bg-slate-950 rounded border border-slate-800 max-h-96 overflow-y-auto p-2 space-y-3 font-mono text-xs">
                        {logs.map((log, idx) => (
                            <div key={idx} className="space-y-1">
                                <div className="flex items-center gap-2">
                                    <span className={`px-1.5 py-0.5 rounded text-[10px] uppercase font-bold ${log.type === 'human' ? 'bg-blue-900/30 text-blue-400 border border-blue-800/50' :
                                        log.type === 'ai' ? 'bg-purple-900/30 text-purple-400 border border-purple-800/50' :
                                            log.type === 'tool' ? 'bg-amber-900/30 text-amber-400 border border-amber-800/50' :
                                                'bg-slate-800 text-slate-400'
                                        }`}>
                                        {log.type === 'human' ? 'USER' : log.type === 'ai' ? 'ASSISTANT' : log.type.toUpperCase()}
                                    </span>
                                    {log.name && <span className="text-slate-500 text-[10px]">{log.name}</span>}
                                </div>

                                {log.content && (
                                    <div className="pl-2 border-l-2 border-slate-800 text-slate-300 whitespace-pre-wrap break-words">
                                        {typeof log.content === 'string' ? log.content : JSON.stringify(log.content, null, 2)}
                                    </div>
                                )}

                                {log.tool_calls && log.tool_calls.length > 0 && (
                                    <div className="pl-2 space-y-2 mt-1">
                                        {log.tool_calls.map((tc: any, i: number) => (
                                            <div key={i} className="bg-slate-900/50 p-2 rounded border border-slate-800">
                                                <div className="text-cyan-400 font-semibold mb-1 flex items-center gap-2">
                                                    <span>🛠️ {tc.name}</span>
                                                </div>
                                                <pre className="text-slate-400 overflow-x-auto">
                                                    {JSON.stringify(tc.args, null, 2)}
                                                </pre>
                                            </div>
                                        ))}
                                    </div>
                                )}
                            </div>
                        ))}
                    </div>
                </div>
            )}

            {/* Acceptance Criteria */}
            {task.acceptance_criteria && task.acceptance_criteria.length > 0 && (
                <div>
                    <h4 className="text-xs font-semibold text-slate-400 mb-1">Acceptance Criteria</h4>
                    <ul className="list-disc list-inside text-xs text-slate-300 space-y-1">
                        {task.acceptance_criteria.map((criteria, idx) => (
                            <li key={idx}>{criteria}</li>
                        ))}
                    </ul>
                </div>
            )}

            {/* Result Path */}
            {task.result_path && (
                <div>
                    <h4 className="text-xs font-semibold text-slate-400 mb-1">Result Path</h4>
                    <code className="text-xs bg-slate-900 px-2 py-1 rounded text-slate-300 block overflow-x-auto">
                        {task.result_path}
                    </code>
                </div>
            )}

            {/* QA Verdict */}
            {task.qa_verdict && (
                <div>
                    <h4 className="text-xs font-semibold text-slate-400 mb-1">QA Verdict</h4>
                    <div className={`text-xs p-2 rounded ${task.qa_verdict.passed ? 'bg-green-900/20 text-green-300' : 'bg-red-900/20 text-red-300'}`}>
                        <div className="font-medium mb-1">{task.qa_verdict.passed ? 'PASSED' : 'FAILED'}</div>
                        <p>{task.qa_verdict.overall_feedback}</p>
                    </div>
                </div>
            )}

            {/* Escalation */}
            {task.escalation && (
                <div>
                    <h4 className="text-xs font-semibold text-orange-400 mb-1 flex items-center gap-2">
                        <AlertCircle className="w-3 h-3" />
                        Escalation: {task.escalation.type}
                    </h4>
                    <div className="bg-orange-900/20 p-2 rounded border border-orange-700/50 text-xs text-orange-200">
                        <p className="font-medium mb-1">{task.escalation.reason}</p>
                        <p className="text-orange-300/80">Action: {task.escalation.suggested_action}</p>
                    </div>
                </div>
            )}

            {/* After Action Report */}
            {task.aar && (
                <div className="space-y-2">
                    <h4 className="text-xs font-semibold text-slate-400 border-b border-slate-700 pb-1">After Action Report</h4>

                    <div>
                        <span className="text-xs text-slate-500 font-medium">Summary:</span>
                        <p className="text-xs text-slate-300 mt-0.5">{task.aar.summary}</p>
                    </div>

                    {task.aar.challenges && task.aar.challenges.length > 0 && (
                        <div>
                            <span className="text-xs text-slate-500 font-medium">Challenges:</span>
                            <ul className="list-disc list-inside text-xs text-slate-300 mt-0.5">
                                {task.aar.challenges.map((c, i) => <li key={i}>{c}</li>)}
                            </ul>
                        </div>
                    )}

                    {task.aar.files_modified && task.aar.files_modified.length > 0 && (
                        <div>
                            <span className="text-xs text-slate-500 font-medium">Files Modified:</span>
                            <div className="flex flex-wrap gap-1 mt-1">
                                {task.aar.files_modified.map((f, i) => (
                                    <span key={i} className="bg-slate-900 px-1.5 py-0.5 rounded text-[10px] font-mono text-slate-400 border border-slate-800">
                                        {f.split('/').pop()}
                                    </span>
                                ))}
                            </div>
                        </div>
                    )}
                </div>
            )}
        </div>
    );
}
