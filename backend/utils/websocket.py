"""WebSocket connection management for real-time updates."""
import asyncio
import json
from core.logging import get_logger
from typing import List, Dict, Optional, Callable, Awaitable
from fastapi import WebSocket

from core.profile_context import get_current_profile

log = get_logger(__name__)


class WebSocketManager:
    """Manages WebSocket connections and broadcasts events to connected clients."""

    def __init__(self):
        self.active_connections: List[WebSocket] = []
        # Track generator_instance_id -> websocket mapping for cleanup on disconnect
        self._generator_instance_websockets: Dict[str, WebSocket] = {}
        # Callback for when a generator instance disconnects
        self._on_generator_disconnect: Optional[Callable[[str], Awaitable[None]]] = None
        # Event set whenever at least one client is connected; cleared when none
        self._client_present = asyncio.Event()

    def set_on_generator_disconnect(self, callback: Callable[[str], Awaitable[None]]):
        """Set callback to be called when a generator instance disconnects."""
        self._on_generator_disconnect = callback

    async def connect(self, websocket: WebSocket):
        """Accept a new WebSocket connection."""
        await websocket.accept()
        self.active_connections.append(websocket)
        self._client_present.set()
        log.info(f"WebSocket connected. Total connections: {len(self.active_connections)}")

    def register_generator_instance(self, websocket: WebSocket, generator_instance_id: str):
        """Associate a generator instance ID with a WebSocket connection."""
        self._generator_instance_websockets[generator_instance_id] = websocket
        log.info(f"Registered generator instance {generator_instance_id} with WebSocket")

    async def disconnect(self, websocket: WebSocket):
        """Remove a disconnected WebSocket and clean up associated generator instances."""
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

        if not self.active_connections:
            self._client_present.clear()

        # Find and clean up any generator instances associated with this websocket
        disconnected_instances = [
            gid for gid, ws in self._generator_instance_websockets.items()
            if ws == websocket
        ]
        for gid in disconnected_instances:
            del self._generator_instance_websockets[gid]
            log.info(f"Generator instance {gid} disconnected")
            # Call the cleanup callback
            if self._on_generator_disconnect:
                try:
                    await self._on_generator_disconnect(gid)
                except Exception as e:
                    log.error(f"Error in generator disconnect callback: {e}")

        log.info(f"WebSocket disconnected. Total connections: {len(self.active_connections)}")

    async def broadcast(self, event: str, data: dict, include_profile: bool = True):
        """Broadcast an event to all connected clients.

        Args:
            event: The event name
            data: The event data
            include_profile: If True, automatically adds profile_id to the data
                            for client-side filtering. Set to False for truly
                            global events (like processing_stats).
        """
        if not self.active_connections:
            log.debug(f"No active WebSocket connections to broadcast '{event}' to")
            return

        # Automatically include profile_id for profile-specific events
        if include_profile and 'profile_id' not in data:
            try:
                data = {**data, 'profile_id': get_current_profile()}
            except Exception:
                # If we can't get profile, send without it (worker threads, etc.)
                pass

        message = json.dumps({"event": event, "data": data})
        # Log outgoing broadcast (truncate data for readability)
        # Skip noisy high-frequency events
        if event not in ("processing_stats",):
            # For generation job events, log key fields for debugging
            if event.startswith("generation_job_"):
                job_id = data.get('job', {}).get('id')
                gen_inst_id = data.get('generator_instance_id')
                profile_id = data.get('profile_id') or data.get('job', {}).get('profile_id')
                log.info(f"WS OUT (broadcast): {event} - job_id={job_id}, generator_instance_id={gen_inst_id}, profile_id={profile_id}")
            else:
                data_preview = json.dumps(data)[:200]
                log.info(f"WS OUT (broadcast): {event} - {data_preview}")

        # Send to all connected clients
        disconnected = []
        for connection in self.active_connections:
            try:
                await connection.send_text(message)
            except Exception as e:
                log.error(f"Error broadcasting to client: {e}", exc_info=True)
                disconnected.append(connection)

        # Remove disconnected clients
        for connection in disconnected:
            await self.disconnect(connection)

    async def send_to(self, websocket: WebSocket, event: str, data: dict):
        """Send an event to a specific client."""
        message = json.dumps({"event": event, "data": data})
        # Log outgoing message (skip noisy pong events, truncate data)
        if event != "pong":
            data_preview = json.dumps(data)[:200]
            log.info(f"WS OUT (direct): {event} - {data_preview}")
        try:
            await websocket.send_text(message)
        except Exception as e:
            log.error(f"Error sending to client: {e}")
            await self.disconnect(websocket)

    async def send_to_any(self, event: str, data: dict) -> bool:
        """Send to the first available client. Returns True on success, False if no clients.

        Used for backend→frontend RPC where any connected UI can service the
        request (e.g. layout rendering). Tries each connection in turn; if a send
        fails the connection is dropped and the next is tried.
        """
        message = json.dumps({"event": event, "data": data})
        # Snapshot the list — disconnect() mutates active_connections.
        for connection in list(self.active_connections):
            try:
                await connection.send_text(message)
                if event not in ("pong",):
                    log.info(f"WS OUT (any): {event} - request_id={data.get('request_id')}")
                return True
            except Exception as e:
                log.error(f"send_to_any: failed to send to a client, trying next: {e}")
                await self.disconnect(connection)
        return False

    async def wait_for_client(self, timeout: Optional[float] = None) -> bool:
        """Block until at least one client is connected. Returns True if a client
        is (or becomes) present, False on timeout.
        """
        if self.active_connections:
            return True
        try:
            if timeout is None:
                await self._client_present.wait()
            else:
                await asyncio.wait_for(self._client_present.wait(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            return False


# Global WebSocket manager instance
ws_manager = WebSocketManager()


async def broadcast_media_updated(media_items, fields: list[str], session=None, include_ephemeral: bool = False):
    """
    Broadcast media_updated event for one or more media items.

    Args:
        media_items: Single MediaItem or list of MediaItems (must have to_dict method)
        fields: List of field names that changed (e.g., ["markers"], ["tags"], ["caption", "prompt"])
        session: Optional database session for refreshing items
        include_ephemeral: When False (default), media tagged with ephemeral_run_id (one-shot
            flow-as-tool run intermediates) are silently skipped so no media_updated event ever
            surfaces them. One guard here covers every caller.
    """
    from sqlalchemy import select

    # Normalize to list
    if not isinstance(media_items, list):
        media_items = [media_items]

    if not media_items:
        return

    # Drop ephemeral one-shot-run intermediates before they can reach any client.
    # getattr guard: callers may pass lightweight objects, but real MediaItems carry the field.
    if not include_ephemeral:
        media_items = [
            item for item in media_items
            if getattr(item, "ephemeral_run_id", None) is None
        ]
        if not media_items:
            return

    # If session provided, refresh items to get latest data with relationships
    if session:
        from database import MediaItem
        from asset_association_service import media_compatibility_projections
        media_ids = [item.id for item in media_items]
        # Use populate_existing=True to force refresh from DB, bypassing identity map cache
        result = await session.execute(
            select(MediaItem)
            .where(MediaItem.id.in_(media_ids))
            .execution_options(populate_existing=True)
        )
        media_items = result.scalars().all()

    projections = (
        await media_compatibility_projections(session, media_items)
        if session
        else [item.to_dict() for item in media_items]
    )

    # Broadcast update for each item
    for item in projections:
        await ws_manager.broadcast("media_updated", {
            "media_id": item.get("media_id", item["id"]),
            "asset_id": item.get("asset_id"),
            "fields": fields,
            "media": item,
        })
