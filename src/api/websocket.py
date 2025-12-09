"""
WebSocket Connection Manager
=============================
Manages WebSocket connections and broadcasting for the orchestrator dashboard.
"""

import logging
from typing import List, Dict
from datetime import datetime
from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    """Manages WebSocket connections and message broadcasting."""

    def __init__(self):
        self.active_connections: List[WebSocket] = []
        self.subscriptions: Dict[str, List[WebSocket]] = {}  # run_id -> [websockets]

    async def connect(self, websocket: WebSocket):
        """Accept a new WebSocket connection."""
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"WebSocket connected. Total active: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        """Remove a WebSocket connection."""
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

        # Remove from subscriptions
        for run_id in list(self.subscriptions.keys()):
            if websocket in self.subscriptions[run_id]:
                self.subscriptions[run_id].remove(websocket)
                if not self.subscriptions[run_id]:
                    del self.subscriptions[run_id]
        logger.info(f"WebSocket disconnected. Total active: {len(self.active_connections)}")

    async def subscribe(self, websocket: WebSocket, run_id: str, runs_index: Dict):
        """Subscribe a WebSocket to updates for a specific run."""
        if run_id not in self.subscriptions:
            self.subscriptions[run_id] = []
        if websocket not in self.subscriptions[run_id]:
            self.subscriptions[run_id].append(websocket)
            logger.info(f"Subscribed to {run_id}. Total subscribers: {len(self.subscriptions[run_id])}")

            # IMMEDIATELY send current state so client doesn't have to wait for next task update
            if run_id in runs_index:
                run_data = runs_index[run_id]
                try:
                    await websocket.send_json({
                        "type": "state_update",
                        "run_id": run_id,
                        "timestamp": datetime.now().isoformat(),
                        "payload": {
                            "status": run_data.get("status", "running"),
                            "task_counts": run_data.get("task_counts", {}),
                            "objective": run_data.get("objective", ""),
                        }
                    })
                except Exception as e:
                    logger.error(f"Error sending initial state: {e}")

    async def unsubscribe(self, websocket: WebSocket, run_id: str):
        """Unsubscribe a WebSocket from updates for a specific run."""
        if run_id in self.subscriptions and websocket in self.subscriptions[run_id]:
            self.subscriptions[run_id].remove(websocket)
            if not self.subscriptions[run_id]:
                del self.subscriptions[run_id]
            logger.info(f"Unsubscribed from {run_id}")

    async def broadcast(self, message: dict):
        """Broadcast a message to all connected WebSocket clients."""
        # Inject timestamp if missing
        if "timestamp" not in message:
            message["timestamp"] = datetime.now().isoformat()

        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception as e:
                logger.error(f"Error broadcasting message: {e}")

    async def broadcast_to_run(self, run_id: str, message: dict):
        """Broadcast a message to all WebSocket clients subscribed to a specific run."""
        # Inject run_id and timestamp if missing
        if "run_id" not in message:
            message["run_id"] = run_id
        if "timestamp" not in message:
            message["timestamp"] = datetime.now().isoformat()

        if run_id in self.subscriptions:
            for connection in self.subscriptions[run_id]:
                try:
                    await connection.send_json(message)
                except Exception as e:
                    logger.error(f"Error broadcasting to run {run_id}: {e}")
