"""
Test runner utilities for agent testing.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


class NoOpWebSocketManager:
    """
    Mock WebSocket manager that captures broadcasts without sending.

    Used for testing to avoid actual WebSocket connections while
    still recording what would have been broadcast.
    """

    def __init__(self):
        self.broadcasts: List[tuple] = []

    async def broadcast(self, event: str, data: Dict[str, Any]):
        """Record the broadcast without sending."""
        self.broadcasts.append((event, data))

    def get_broadcasts(self, event: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get recorded broadcasts, optionally filtered by event type."""
        if event:
            return [d for e, d in self.broadcasts if e == event]
        return [d for _, d in self.broadcasts]

    def clear(self):
        """Clear recorded broadcasts."""
        self.broadcasts.clear()
