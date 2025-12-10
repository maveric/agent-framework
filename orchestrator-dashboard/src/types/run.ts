/**
 * Shared types for Run Details
 */

export interface Task {
    id: string;
    description: string;
    status: 'planned' | 'ready' | 'active' | 'complete' | 'failed' | 'blocked' | 'waiting_human' | 'awaiting_qa' | 'abandoned';
    phase: string;
    component: string;
    assigned_worker_profile?: string;
    depends_on: string[];
    acceptance_criteria?: string[];
    result_path?: string;
    retry_count?: number;
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
        blocking?: boolean;
    };
}

export interface RunDetails {
    run_id: string;
    objective: string;
    status: string;
    created_at: string;
    updated_at: string;
    strategy_status: string;
    tasks: Task[];
    insights: any[];
    design_log: any[];
    workspace_path?: string;
    model_config?: {
        director_model: { provider: string; model_name: string; temperature: number };
        worker_model: { provider: string; model_name: string; temperature: number };
        strategist_model: { provider: string; model_name: string; temperature: number };
    };
    task_memories?: {
        [taskId: string]: any;
    };
    task_counts?: {
        completed: number;
        active: number;
        planned: number;
    };
    interrupt_data?: any;
}

export const workerColors: Record<string, string> = {
    'full_stack_developer': 'bg-blue-900/20 text-blue-400 border-blue-800/50',
    'devops_engineer': 'bg-purple-900/20 text-purple-400 border-purple-800/50',
    'qa_engineer': 'bg-green-900/20 text-green-400 border-green-800/50',
    'product_manager': 'bg-orange-900/20 text-orange-400 border-orange-800/50',
    'architect': 'bg-indigo-900/20 text-indigo-400 border-indigo-800/50',
};
