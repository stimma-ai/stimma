"""
WebSocket test client for verifying event broadcasts.

Provides utilities for connecting to the app's WebSocket endpoint
and waiting for specific events with timeout.
"""

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any, Optional

from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect


@dataclass
class ReceivedEvent:
    """A WebSocket event received from the server."""
    event: str
    data: dict[str, Any]
    raw: str


@dataclass
class WebSocketTestClient:
    """Test client for WebSocket event verification.

    Usage:
        async with WebSocketTestClient(app) as ws:
            # Trigger some action that emits an event
            await client.post("/api/media/1/markers", json={"marker_id": 1})

            # Wait for the event
            event = await ws.wait_for_event("markers_updated", timeout=5.0)
            assert event is not None
            assert event.data["media_id"] == 1
    """

    app: Any
    received_events: list[ReceivedEvent] = field(default_factory=list)
    _websocket: Any = None
    _receive_task: Optional[asyncio.Task] = None
    _connected: bool = False

    async def connect(self, path: str = "/ws", headers: Optional[dict] = None):
        """Connect to the WebSocket endpoint.

        Note: This uses Starlette's TestClient which handles the connection
        synchronously. For async WebSocket testing, we use a background task.
        """
        # For integration tests, we'll use a simpler approach
        # The actual WebSocket testing will be done differently
        pass

    async def disconnect(self):
        """Disconnect from the WebSocket."""
        if self._receive_task:
            self._receive_task.cancel()
            try:
                await self._receive_task
            except asyncio.CancelledError:
                pass
        self._connected = False

    async def wait_for_event(
        self,
        event_name: str,
        timeout: float = 5.0,
        match: Optional[dict] = None,
    ) -> Optional[ReceivedEvent]:
        """Wait for a specific event to be received.

        Args:
            event_name: The event type to wait for
            timeout: Maximum time to wait in seconds
            match: Optional dict of data fields that must match

        Returns:
            The matching event, or None if timeout
        """
        # Check already received events first
        for event in self.received_events:
            if event.event == event_name:
                if match is None or self._matches(event.data, match):
                    self.received_events.remove(event)
                    return event

        # Wait for new events
        deadline = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < deadline:
            await asyncio.sleep(0.1)
            for event in self.received_events:
                if event.event == event_name:
                    if match is None or self._matches(event.data, match):
                        self.received_events.remove(event)
                        return event

        return None

    def _matches(self, data: dict, match: dict) -> bool:
        """Check if data contains all key-value pairs in match."""
        for key, value in match.items():
            if key not in data or data[key] != value:
                return False
        return True

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.disconnect()


class MockWebSocketManager:
    """Mock WebSocket manager that captures broadcasts for testing.

    Use this when you want to verify events are broadcast without
    actually connecting a WebSocket client.
    """

    def __init__(self):
        self.broadcasts: list[tuple[str, dict]] = []
        self.connections: list = []

    async def broadcast(self, event: str, data: dict, include_profile: bool = True):
        """Capture a broadcast event."""
        self.broadcasts.append((event, data))

    async def connect(self, websocket):
        """Track a connection."""
        self.connections.append(websocket)

    async def disconnect(self, websocket):
        """Track a disconnection."""
        if websocket in self.connections:
            self.connections.remove(websocket)

    def get_broadcasts(self, event_name: Optional[str] = None) -> list[tuple[str, dict]]:
        """Get captured broadcasts, optionally filtered by event name."""
        if event_name is None:
            return self.broadcasts.copy()
        return [(e, d) for e, d in self.broadcasts if e == event_name]

    def clear(self):
        """Clear all captured broadcasts."""
        self.broadcasts.clear()

    def assert_broadcast(self, event_name: str, data_match: Optional[dict] = None):
        """Assert that a specific event was broadcast.

        Args:
            event_name: Expected event type
            data_match: Optional dict of data fields that must match

        Raises:
            AssertionError if event was not found
        """
        for event, data in self.broadcasts:
            if event == event_name:
                if data_match is None:
                    return
                if all(data.get(k) == v for k, v in data_match.items()):
                    return

        broadcast_events = [e for e, _ in self.broadcasts]
        raise AssertionError(
            f"Expected broadcast '{event_name}' not found. "
            f"Received: {broadcast_events}"
        )
