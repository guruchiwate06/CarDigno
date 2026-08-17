"""
CarDigno - Real-Time WebSockets Ingestion Broadcast Manager
Manages client WebSocket lifecycle and streams real-time decoded OBD-II telemetry
and ML subsystem health ratings to connected dashboard clients.
"""

import asyncio
import logging
from typing import Dict, List, Any, Optional
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger("WebSocketGateway")

ws_router = APIRouter()


class TelemetryConnectionManager:
    """
    Manages active client WebSocket connections and broadcasts JSON telemetry payloads.
    """

    def __init__(self):
        self.active_connections: List[WebSocket] = []
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket):
        """Accepts incoming WebSocket connection and adds client to active registry."""
        await websocket.accept()
        async with self._lock:
            self.active_connections.append(websocket)
        logger.info(f"WebSocket client connected. Active connections: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        """Removes disconnected WebSocket client from registry."""
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
            logger.info(f"WebSocket client disconnected. Active connections: {len(self.active_connections)}")

    async def broadcast(self, payload: Dict[str, Any]):
        """
        Broadcasts JSON payload to all connected clients concurrently.
        Gracefully removes clients that experience socket errors or disconnects.
        """
        if not self.active_connections:
            return

        stale_connections = []
        async with self._lock:
            connections = list(self.active_connections)

        for connection in connections:
            try:
                await connection.send_json(payload)
            except Exception as e:
                logger.debug(f"Failed to send WebSocket payload: {e}")
                stale_connections.append(connection)

        if stale_connections:
            async with self._lock:
                for dead_ws in stale_connections:
                    if dead_ws in self.active_connections:
                        self.active_connections.remove(dead_ws)

    def get_client_count(self) -> int:
        """Returns the current number of connected WebSocket clients."""
        return len(self.active_connections)


# Global singleton connection manager instance
manager = TelemetryConnectionManager()


@ws_router.websocket("/ws/telemetry")
async def websocket_telemetry_endpoint(websocket: WebSocket):
    """
    WebSocket Endpoint: /ws/telemetry
    Streams live 10 Hz telemetry data frames, feature vectors, and ML health evaluations.
    """
    await manager.connect(websocket)
    try:
        # Keep connection open and listen for any incoming client messages / ping-pongs
        while True:
            data = await websocket.receive_text()
            # Respond to client ping or custom queries if necessary
            if data.strip() == "ping":
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        logger.warning(f"WebSocket error: {e}")
        manager.disconnect(websocket)
