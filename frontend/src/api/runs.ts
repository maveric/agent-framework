import { apiClient } from './client';
import type { RunSummary, RunDetail, CreateRunRequest } from '../types/api';

export const runsApi = {
    list: (params?: { status?: string; tag?: string; limit?: number }) =>
        apiClient<RunSummary[]>('/api/runs', { params: params as Record<string, string> }),

    get: (runId: string) =>
        apiClient<RunDetail>(`/api/runs/${runId}`),

    create: (request: CreateRunRequest) =>
        apiClient<{ run_id: string }>('/api/runs', {
            method: 'POST',
            body: JSON.stringify(request),
        }),

    pause: (runId: string) =>
        apiClient<{ status: string }>(`/api/runs/${runId}/pause`, { method: 'POST' }),

    resume: (runId: string) =>
        apiClient<{ status: string }>(`/api/runs/${runId}/resume`, { method: 'POST' }),
};
