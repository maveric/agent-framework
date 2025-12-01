// =============================================================================
// ENUMS
// =============================================================================

export type RunStatus =
    | 'running'
    | 'paused'
    | 'completed'
    | 'failed'
    | 'waiting_human';

export type TaskStatus =
    | 'planned'
    | 'ready'
    | 'blocked'
    | 'active'
    | 'awaiting_qa'
    | 'failed_qa'
    | 'complete'
    | 'waiting_human'
    | 'abandoned';

export type TaskPhase = 'plan' | 'build' | 'test';

export type HumanAction =
    | 'approve'
    | 'reject'
    | 'modify'
    | 'retry'
    | 'escalate'
    | 'provide_input';

// =============================================================================
// RUN TYPES
// =============================================================================

export interface RunSummary {
    run_id: string;
    objective: string;
    status: RunStatus;
    created_at: string;
    updated_at: string;
    task_counts: Record<TaskStatus, number>;
    tags: string[];
}

export interface RunDetail extends RunSummary {
    spec: Record<string, any>;
    strategy_status: string;
    tasks: Task[];
    insights: Insight[];
    design_log: DesignDecision[];
    guardian: Record<string, any>;
}

export interface CreateRunRequest {
    objective: string;
    spec?: Record<string, any>;
    tags?: string[];
}

// =============================================================================
// TASK TYPES
// =============================================================================

export interface Task {
    id: string;
    component: string;
    phase: TaskPhase;
    description: string;
    status: TaskStatus;
    priority: number;
    assigned_worker_profile?: string;
    depends_on: string[];
    acceptance_criteria: string[];
    retry_count: number;
    result_path?: string;
    qa_verdict?: QAVerdict;
    aar?: AAR;
    escalation?: Escalation;
    blocked_reason?: BlockedReason;
    created_at?: string;
    started_at?: string;
    completed_at?: string;
}

export interface TaskSummary {
    id: string;
    component: string;
    phase: TaskPhase;
    description: string;
    status: TaskStatus;
    priority: number;
    assigned_worker_profile?: string;
    retry_count: number;
    has_escalation: boolean;
    needs_human: boolean;
}

export interface QAVerdict {
    passed: boolean;
    criterion_results: CriterionResult[];
    overall_feedback: string;
    suggested_focus?: string;
}

export interface CriterionResult {
    criterion: string;
    passed: boolean;
    reasoning: string;
    suggestions?: string;
}

export interface AAR {
    summary: string;
    approach: string;
    challenges: string[];
    decisions_made: string[];
    files_modified: string[];
    time_spent_estimate: string;
}

export interface Escalation {
    type: string;
    reason: string;
    context: Record<string, any>;
    blocking: boolean;
}

export interface BlockedReason {
    type: string;
    reason: string;
    blocked_since: string;
}

// =============================================================================
// HUMAN RESOLUTION TYPES
// =============================================================================

export interface HumanResolution {
    action: HumanAction;
    feedback?: string;
    modified_criteria?: string[];
    modified_description?: string;
    input_data?: Record<string, any>;
}

export interface EscalationResolution {
    action: 'resolve' | 'dismiss' | 'reassign';
    resolution_notes: string;
    new_task_description?: string;
    spec_clarification?: Record<string, any>;
}

// =============================================================================
// OTHER TYPES
// =============================================================================

export interface Insight {
    topic: string[];
    summary: string;
    source_task?: string;
    added_at: string;
}

export interface DesignDecision {
    id: string;
    area: string;
    applies_to: string[];
    summary: string;
    reason: string;
    timestamp: string;
}

// =============================================================================
// WEBSOCKET TYPES
// =============================================================================

export type WSMessageType =
    | 'state_update'
    | 'task_update'
    | 'log_message'
    | 'human_needed'
    | 'run_complete'
    | 'error'
    | 'heartbeat'
    | 'subscribe'
    | 'unsubscribe'
    | 'subscribed'
    | 'unsubscribed'
    | 'ping'
    | 'pong';

export interface WSMessage {
    type: WSMessageType;
    run_id?: string;
    payload: Record<string, any>;
    timestamp: string;
}
