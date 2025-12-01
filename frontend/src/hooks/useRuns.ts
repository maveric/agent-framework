import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { runsApi } from '../api/runs';
import type { CreateRunRequest } from '../types/api';

export function useRuns(params?: { status?: string; tag?: string }) {
    return useQuery({
        queryKey: ['runs', params],
        queryFn: () => runsApi.list(params),
        refetchInterval: 10000, // Poll every 10s
    });
}

export function useRun(runId: string) {
    return useQuery({
        queryKey: ['runs', runId],
        queryFn: () => runsApi.get(runId),
        refetchInterval: 5000, // Poll every 5s
        enabled: !!runId,
    });
}

export function useCreateRun() {
    const queryClient = useQueryClient();

    return useMutation({
        mutationFn: (request: CreateRunRequest) => runsApi.create(request),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['runs'] });
        },
    });
}

export function usePauseRun() {
    const queryClient = useQueryClient();

    return useMutation({
        mutationFn: (runId: string) => runsApi.pause(runId),
        onSuccess: (_, runId) => {
            queryClient.invalidateQueries({ queryKey: ['runs', runId] });
        },
    });
}

export function useResumeRun() {
    const queryClient = useQueryClient();

    return useMutation({
        mutationFn: (runId: string) => runsApi.resume(runId),
        onSuccess: (_, runId) => {
            queryClient.invalidateQueries({ queryKey: ['runs', runId] });
        },
    });
}
