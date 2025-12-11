import { create } from 'zustand';

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
    | 'pong'
    | 'run_list_update'
    | 'interrupted'
    | 'task_interrupted'
    | 'status';


export interface WSMessage {
    type: WSMessageType;
    run_id?: string;
    payload: Record<string, any>;
    timestamp: string;
}

// WebSocket connects directly to the FastAPI backend on port 8085
// Can be overridden with VITE_WS_URL environment variable
// Use 127.0.0.1 to avoid IPv6 resolution issues with localhost
const WS_URL = import.meta.env.VITE_WS_URL || 'ws://127.0.0.1:8085/ws';

interface WebSocketState {
    socket: WebSocket | null;
    connected: boolean;
    subscribedRuns: Set<string>;
    messages: WSMessage[];
    connect: () => void;
    disconnect: () => void;
    subscribe: (runId: string) => void;
    unsubscribe: (runId: string) => void;
    addMessageHandler: (type: WSMessageType, handler: (msg: WSMessage) => void) => () => void;
}

type MessageHandler = (msg: WSMessage) => void;
const messageHandlers = new Map<WSMessageType, Set<MessageHandler>>();

export const useWebSocketStore = create<WebSocketState>((set, get) => ({
    socket: null,
    connected: false,
    subscribedRuns: new Set(),
    messages: [],

    connect: () => {
        const socket = new WebSocket(WS_URL);

        socket.onopen = () => {
            set({ connected: true });
            console.log('WebSocket connected');

            // Re-subscribe to runs
            const { subscribedRuns } = get();
            subscribedRuns.forEach((runId) => {
                socket.send(JSON.stringify({ type: 'subscribe', run_id: runId }));
            });
        };

        socket.onclose = () => {
            set({ connected: false });
            console.log('WebSocket disconnected');

            // Reconnect after delay
            setTimeout(() => get().connect(), 3000);
        };

        socket.onerror = (error) => {
            console.error('WebSocket error:', error);
        };

        socket.onmessage = (event) => {
            const msg: WSMessage = JSON.parse(event.data);
            console.log('WS Message received:', msg.type, msg);

            // Add to message history (keep last 100)
            set((state) => ({
                messages: [...state.messages.slice(-99), msg],
            }));

            // Call registered handlers
            const handlers = messageHandlers.get(msg.type);
            if (handlers) {
                handlers.forEach((handler) => handler(msg));
            }
        };

        set({ socket });
    },

    disconnect: () => {
        const { socket } = get();
        if (socket) {
            socket.close();
            set({ socket: null, connected: false });
        }
    },

    subscribe: (runId: string) => {
        const { socket, subscribedRuns } = get();

        if (!subscribedRuns.has(runId)) {
            subscribedRuns.add(runId);
            set({ subscribedRuns: new Set(subscribedRuns) });

            if (socket?.readyState === WebSocket.OPEN) {
                socket.send(JSON.stringify({ type: 'subscribe', run_id: runId }));
            }
        }
    },

    unsubscribe: (runId: string) => {
        const { socket, subscribedRuns } = get();

        if (subscribedRuns.has(runId)) {
            subscribedRuns.delete(runId);
            set({ subscribedRuns: new Set(subscribedRuns) });

            if (socket?.readyState === WebSocket.OPEN) {
                socket.send(JSON.stringify({ type: 'unsubscribe', run_id: runId }));
            }
        }
    },

    addMessageHandler: (type: WSMessageType, handler: MessageHandler) => {
        if (!messageHandlers.has(type)) {
            messageHandlers.set(type, new Set());
        }
        messageHandlers.get(type)!.add(handler);

        // Return cleanup function
        return () => {
            messageHandlers.get(type)?.delete(handler);
        };
    },
}));
