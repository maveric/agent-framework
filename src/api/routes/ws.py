"""
WebSocket Routes
================
WebSocket endpoints for real-time communication.
"""

import logging
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from api.state import manager, runs_index

logger = logging.getLogger(__name__)

router = APIRouter(tags=["websocket"])


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time updates."""
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_json()
            if data.get("type") == "subscribe":
                await manager.subscribe(websocket, data.get("run_id"), runs_index)
            elif data.get("type") == "unsubscribe":
                await manager.unsubscribe(websocket, data.get("run_id"))
    except WebSocketDisconnect:
        manager.disconnect(websocket)
