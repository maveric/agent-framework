import { useState } from 'react';
import { X } from 'lucide-react';
import { apiClient } from '../api/client';

interface InterruptData {
    task_id: string;
    task_description: string;
    failure_reason: string;
    retry_count: number;
    acceptance_criteria: string[];
    component: string;
    phase: string;
    assigned_worker_profile: string;
    depends_on: string[];
}

interface InterruptModalProps {
    runId: string;
    interruptData: InterruptData;
    onResolve: () => void;
    onClose: () => void;
}

export function InterruptModal({ runId, interruptData, onResolve, onClose }: InterruptModalProps) {
    const [action, setAction] = useState<'retry' | 'abandon' | 'spawn_new_task'>('retry');
    const [modifiedDescription, setModifiedDescription] = useState(interruptData.task_description);
    const [modifiedCriteria, setModifiedCriteria] = useState(interruptData.acceptance_criteria || []);

    // Fields for new task spawning
    const [newDescription, setNewDescription] = useState(interruptData.task_description);
    const [newComponent, setNewComponent] = useState(interruptData.component);
    const [newPhase, setNewPhase] = useState(interruptData.phase);
    const [newWorkerProfile, setNewWorkerProfile] = useState(interruptData.assigned_worker_profile);
    const [newCriteria, setNewCriteria] = useState(interruptData.acceptance_criteria || []);
    const [newDependencies, setNewDependencies] = useState<string[]>(interruptData.depends_on || []);
    const [isSubmitting, setIsSubmitting] = useState(false);

    const handleSubmit = async () => {
        setIsSubmitting(true);
        let resolution;

        if (action === 'retry') {
            resolution = {
                task_id: interruptData.task_id,
                action: 'retry',
                modified_description: modifiedDescription !== interruptData.task_description ? modifiedDescription : null,
                modified_criteria: JSON.stringify(modifiedCriteria) !== JSON.stringify(interruptData.acceptance_criteria) ? modifiedCriteria : null
            };
        } else if (action === 'spawn_new_task') {
            resolution = {
                task_id: interruptData.task_id,
                action: 'spawn_new_task',
                new_description: newDescription,
                new_component: newComponent,
                new_phase: newPhase,
                new_worker_profile: newWorkerProfile,
                new_criteria: newCriteria,
                new_dependencies: newDependencies
            };
        } else {
            resolution = {
                task_id: interruptData.task_id,
                action: 'abandon'
            };
        }

        try {
            await apiClient(`/api/runs/${runId}/resolve`, {
                method: 'POST',
                body: JSON.stringify(resolution)
            });

            onResolve();
        } catch (error) {
            console.error('Failed to submit resolution:', error);
            alert('Failed to submit resolution. Please try again.');
        } finally {
            setIsSubmitting(false);
        }
    };

    const addCriterion = (criteriaList: string[], setCriteria: (c: string[]) => void) => {
        setCriteria([...criteriaList, '']);
    };

    const removeCriterion = (index: number, criteriaList: string[], setCriteria: (c: string[]) => void) => {
        const updated = criteriaList.filter((_, i) => i !== index);
        setCriteria(updated);
    };

    const updateCriterion = (index: number, value: string, criteriaList: string[], setCriteria: (c: string[]) => void) => {
        const updated = [...criteriaList];
        updated[index] = value;
        setCriteria(updated);
    };

    return (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
            <div className="bg-slate-900 border border-yellow-500/50 rounded-lg shadow-2xl max-w-4xl w-full max-h-[90vh] overflow-y-auto m-4">
                <div className="sticky top-0 bg-slate-900 border-b border-yellow-500/50 p-4 flex items-center justify-between">
                    <h2 className="text-xl font-bold text-yellow-400 flex items-center gap-2">
                        ⚠️ Task Requires Human Review
                    </h2>
                    <button
                        onClick={onClose}
                        className="text-slate-400 hover:text-slate-200 transition-colors"
                    >
                        <X className="w-6 h-6" />
                    </button>
                </div>

                <div className="p-6 space-y-6">
                    {/* Alert Banner */}
                    <div className="bg-yellow-900/20 border border-yellow-500 rounded-lg p-4">
                        <p className="text-yellow-200 font-medium">
                            Task <span className="font-mono text-yellow-400">{interruptData.task_id}</span> exceeded max retries ({interruptData.retry_count})
                        </p>
                    </div>

                    {/* Failure Reason */}
                    <div>
                        <h4 className="text-sm font-semibold text-slate-300 mb-2">Failure Reason:</h4>
                        <pre className="bg-slate-800 border border-slate-700 rounded p-3 text-xs text-slate-300 overflow-x-auto whitespace-pre-wrap">
                            {interruptData.failure_reason}
                        </pre>
                    </div>

                    {/* Option 1: Retry Task */}
                    <div className="border-t border-slate-700 pt-4">
                        <label className="flex items-center gap-3 mb-3 cursor-pointer">
                            <input
                                type="radio"
                                checked={action === 'retry'}
                                onChange={() => setAction('retry')}
                                className="w-4 h-4"
                            />
                            <strong className="text-slate-200">Retry Task (with modifications)</strong>
                        </label>

                        {action === 'retry' && (
                            <div className="ml-7 space-y-4">
                                <div>
                                    <label className="block text-sm font-medium text-slate-300 mb-1">Task Description</label>
                                    <textarea
                                        value={modifiedDescription}
                                        onChange={(e) => setModifiedDescription(e.target.value)}
                                        rows={6}
                                        className="w-full bg-slate-800 border border-slate-600 rounded px-3 py-2 text-slate-200 focus:border-blue-500 focus:outline-none"
                                    />
                                </div>

                                <div>
                                    <div className="flex items-center justify-between mb-1">
                                        <label className="block text-sm font-medium text-slate-300">Acceptance Criteria</label>
                                        <button
                                            onClick={() => addCriterion(modifiedCriteria, setModifiedCriteria)}
                                            className="text-xs text-blue-400 hover:text-blue-300"
                                        >
                                            + Add Criterion
                                        </button>
                                    </div>
                                    {modifiedCriteria.map((criterion, i) => (
                                        <div key={i} className="flex gap-2 mb-2">
                                            <input
                                                value={criterion}
                                                onChange={(e) => updateCriterion(i, e.target.value, modifiedCriteria, setModifiedCriteria)}
                                                className="flex-1 bg-slate-800 border border-slate-600 rounded px-3 py-2 text-slate-200 focus:border-blue-500 focus:outline-none"
                                                placeholder={`Criterion ${i + 1}`}
                                            />
                                            <button
                                                onClick={() => removeCriterion(i, modifiedCriteria, setModifiedCriteria)}
                                                className="px-3 py-2 bg-red-900/20 border border-red-500/50 text-red-400 rounded hover:bg-red-900/40"
                                            >
                                                Remove
                                            </button>
                                        </div>
                                    ))}
                                </div>
                            </div>
                        )}
                    </div>

                    {/* Option 2: Create New Task */}
                    <div className="border-t border-slate-700 pt-4">
                        <label className="flex items-center gap-3 mb-3 cursor-pointer">
                            <input
                                type="radio"
                                checked={action === 'spawn_new_task'}
                                onChange={() => setAction('spawn_new_task')}
                                className="w-4 h-4"
                            />
                            <strong className="text-slate-200">Create New Task (replaces failed task)</strong>
                        </label>

                        {action === 'spawn_new_task' && (
                            <div className="ml-7 space-y-4">
                                <div className="grid grid-cols-2 gap-4">
                                    <div>
                                        <label className="block text-sm font-medium text-slate-300 mb-1">Component</label>
                                        <input
                                            value={newComponent}
                                            onChange={(e) => setNewComponent(e.target.value)}
                                            className="w-full bg-slate-800 border border-slate-600 rounded px-3 py-2 text-slate-200 focus:border-blue-500 focus:outline-none"
                                        />
                                    </div>
                                    <div>
                                        <label className="block text-sm font-medium text-slate-300 mb-1">Phase</label>
                                        <select
                                            value={newPhase}
                                            onChange={(e) => setNewPhase(e.target.value)}
                                            className="w-full bg-slate-800 border border-slate-600 rounded px-3 py-2 text-slate-200 focus:border-blue-500 focus:outline-none"
                                        >
                                            <option value="plan">Plan</option>
                                            <option value="build">Build</option>
                                            <option value="test">Test</option>
                                        </select>
                                    </div>
                                </div>

                                <div>
                                    <label className="block text-sm font-medium text-slate-300 mb-1">Worker Profile</label>
                                    <select
                                        value={newWorkerProfile}
                                        onChange={(e) => setNewWorkerProfile(e.target.value)}
                                        className="w-full bg-slate-800 border border-slate-600 rounded px-3 py-2 text-slate-200 focus:border-blue-500 focus:outline-none"
                                    >
                                        <option value="planner_worker">Planner</option>
                                        <option value="code_worker">Coder</option>
                                        <option value="test_worker">Tester</option>
                                        <option value="research_worker">Researcher</option>
                                        <option value="writer_worker">Writer</option>
                                    </select>
                                </div>

                                <div>
                                    <label className="block text-sm font-medium text-slate-300 mb-1">Description</label>
                                    <textarea
                                        value={newDescription}
                                        onChange={(e) => setNewDescription(e.target.value)}
                                        rows={6}
                                        className="w-full bg-slate-800 border border-slate-600 rounded px-3 py-2 text-slate-200 focus:border-blue-500 focus:outline-none"
                                    />
                                </div>

                                <div>
                                    <div className="flex items-center justify-between mb-1">
                                        <label className="block text-sm font-medium text-slate-300">Acceptance Criteria</label>
                                        <button
                                            onClick={() => addCriterion(newCriteria, setNewCriteria)}
                                            className="text-xs text-blue-400 hover:text-blue-300"
                                        >
                                            + Add Criterion
                                        </button>
                                    </div>
                                    {newCriteria.map((criterion, i) => (
                                        <div key={i} className="flex gap-2 mb-2">
                                            <input
                                                value={criterion}
                                                onChange={(e) => updateCriterion(i, e.target.value, newCriteria, setNewCriteria)}
                                                className="flex-1 bg-slate-800 border border-slate-600 rounded px-3 py-2 text-slate-200 focus:border-blue-500 focus:outline-none"
                                                placeholder={`Criterion ${i + 1}`}
                                            />
                                            <button
                                                onClick={() => removeCriterion(i, newCriteria, setNewCriteria)}
                                                className="px-3 py-2 bg-red-900/20 border border-red-500/50 text-red-400 rounded hover:bg-red-900/40"
                                            >
                                                Remove
                                            </button>
                                        </div>
                                    ))}
                                </div>
                            </div>
                        )}
                    </div>

                    {/* Option 3: Abandon Task */}
                    <div className="border-t border-slate-700 pt-4">
                        <label className="flex items-center gap-3 cursor-pointer">
                            <input
                                type="radio"
                                checked={action === 'abandon'}
                                onChange={() => setAction('abandon')}
                                className="w-4 h-4"
                            />
                            <strong className="text-slate-200">Abandon Task</strong>
                        </label>
                    </div>

                    {/* Submit Button */}
                    <div className="flex gap-3 justify-end pt-4 border-t border-slate-700">
                        <button
                            onClick={onClose}
                            className="px-4 py-2 bg-slate-700 text-slate-200 rounded hover:bg-slate-600 transition-colors"
                            disabled={isSubmitting}
                        >
                            Cancel
                        </button>
                        <button
                            onClick={handleSubmit}
                            className="px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700 transition-colors disabled:bg-blue-800 disabled:cursor-not-allowed"
                            disabled={isSubmitting}
                        >
                            {isSubmitting ? 'Submitting...' : 'Submit'}
                        </button>
                    </div>
                </div>
            </div>
        </div>
    );
}
