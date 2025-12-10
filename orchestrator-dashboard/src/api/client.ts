// In development, use relative URLs to go through Vite's proxy
// In production, or if VITE_API_URL is set, use that
const API_BASE = import.meta.env.VITE_API_URL || (import.meta.env.DEV ? '' : 'http://localhost:8085');

// API version prefix - update this to change API version globally
const API_VERSION = '/api/v1';

interface FetchOptions extends RequestInit {
    params?: Record<string, string>;
}

/**
 * Helper to build versioned API URLs
 * @param endpoint - Endpoint path (e.g., '/runs', '/runs/123')
 * @returns Full URL with version prefix
 */
export function apiUrl(endpoint: string): string {
    // If endpoint already starts with /api/v, don't add version prefix
    if (endpoint.startsWith('/api/v')) {
        return `${API_BASE}${endpoint}`;
    }
    // If endpoint starts with /api/, replace with versioned prefix
    if (endpoint.startsWith('/api/')) {
        return `${API_BASE}${endpoint.replace('/api/', API_VERSION + '/')}`;
    }
    // Otherwise, add version prefix
    return `${API_BASE}${API_VERSION}${endpoint}`;
}

export async function apiClient<T>(
    endpoint: string,
    options: FetchOptions = {}
): Promise<T> {
    const { params, ...fetchOptions } = options;

    let url = apiUrl(endpoint);
    if (params) {
        const searchParams = new URLSearchParams(params);
        url += `?${searchParams.toString()}`;
    }

    const response = await fetch(url, {
        ...fetchOptions,
        headers: {
            'Content-Type': 'application/json',
            ...fetchOptions.headers,
        },
    });

    if (!response.ok) {
        const error = await response.json().catch(() => ({ detail: 'Unknown error' }));
        throw new Error(error.detail || `HTTP ${response.status}`);
    }

    return response.json();
}

/**
 * Add a dependency between tasks
 * Makes taskId depend on dependsOnId
 */
export async function addTaskDependency(
    runId: string,
    taskId: string,
    dependsOnId: string
): Promise<{ task_id: string; depends_on: string[]; updated: boolean }> {
    return apiClient(`/runs/${runId}/tasks/${taskId}`, {
        method: 'PATCH',
        body: JSON.stringify({ add_dependency: dependsOnId }),
    });
}

/**
 * Remove a dependency between tasks
 */
export async function removeTaskDependency(
    runId: string,
    taskId: string,
    dependsOnId: string
): Promise<{ task_id: string; depends_on: string[]; updated: boolean }> {
    return apiClient(`/runs/${runId}/tasks/${taskId}`, {
        method: 'PATCH',
        body: JSON.stringify({ remove_dependency: dependsOnId }),
    });
}
