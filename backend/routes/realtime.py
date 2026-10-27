"""Real-time communication routes (WebSocket and SSE)."""
import asyncio
import json
from core.logging import get_logger
from datetime import datetime
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sse_starlette.sse import EventSourceResponse

from ingestion import get_ingestion
from utils.websocket import (
    PIN_REJECTED_CLOSE_CODE,
    PIN_REJECTED_REASON,
    REALTIME_PROTOCOL,
    PinRejected,
    scope_from_query,
    ws_manager,
)
from agent_state import agent_state_manager

router = APIRouter(tags=["realtime"])
log = get_logger(__name__)


@router.get("/api/progress")
async def get_progress_stream():
    """
    Server-sent events endpoint for ingestion progress.
    """
    async def event_generator():
        ingestion = get_ingestion()
        while True:
            progress_data = ingestion.progress.to_dict()
            yield {
                "event": "progress",
                "data": json.dumps(progress_data)
            }
            await asyncio.sleep(1)  # Update every second

    return EventSourceResponse(event_generator())


_SCOPE_MESSAGES = {
    "realtime_scope": "scope",
    "realtime_subscribe": "subscribe",
    "realtime_unsubscribe": "unsubscribe",
}


async def _handle_scope_message(websocket: WebSocket, message: dict) -> None:
    """Apply a scope message and acknowledge it with the resulting scope.

    The acknowledgement is queued behind everything broadcast before the
    change, so a client that waits for it before reading state over HTTP
    cannot miss an event for what it just subscribed to.
    """
    data = message.get("data")
    seq = data.get("seq") if isinstance(data, dict) else None
    try:
        applied = await ws_manager.apply_scope_message(websocket, _SCOPE_MESSAGES[message["event"]], data)
    except ValueError as e:
        await ws_manager.send_to(websocket, "realtime_scope_rejected", {"seq": seq, "reason": str(e)})
        return
    if applied is not None:
        # The acknowledgement names the profile but carries none of its data.
        await ws_manager.send_to(
            websocket, "realtime_scope_applied", {"seq": seq, **applied}, profile_scoped=False
        )


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """
    WebSocket endpoint for real-time updates.
    Clients can connect here to receive events about:
    - media_added: New media items indexed
    - media_updated: Media items processed/updated
    - media_deleted: Media items removed
    - progress_update: Processing progress changes

    Clients that declare the realtime capability (``?realtime=1``, see
    ``utils.websocket``) receive only their profile's events and per-entity
    detail for what they subscribe to; others receive every broadcast.
    Either way, events of a PIN-protected profile are delivered only once
    the socket proves its PIN (``?profile=P&pin=...``, or ``pin`` on a
    ``realtime_scope`` message). A wrong PIN on connect closes the socket
    with ``PIN_REJECTED_CLOSE_CODE``.
    """
    try:
        scope = scope_from_query(websocket.query_params)
    except ValueError as e:
        # Unusable scope: fall back to the legacy stream rather than refuse.
        log.warning("Ignoring invalid realtime scope on connect", error=str(e))
        scope = None
    try:
        pin_proof = await ws_manager.prove_pin(
            websocket.query_params.get("profile"), websocket.query_params.get("pin")
        )
    except PinRejected:
        # Accept first so the browser sees the close code; a refused
        # handshake surfaces only as an anonymous connection failure.
        await websocket.accept()
        await websocket.close(code=PIN_REJECTED_CLOSE_CODE, reason=PIN_REJECTED_REASON)
        return
    await ws_manager.connect(websocket, scope, pin_proof)

    try:
        # Send welcome message
        welcome = {
            "message": "Connected to Stimma WebSocket",
            "timestamp": datetime.now().isoformat(),
            "realtime_protocol": REALTIME_PROTOCOL,
        }
        client = ws_manager.client_for(websocket)
        if scope is not None and client is not None:
            welcome["realtime"] = ws_manager.describe_scope(client)
        await ws_manager.send_to(websocket, "connected", welcome)

        # Keep connection alive and handle incoming messages
        while True:
            try:
                # Wait for messages from client (e.g., subscriptions, pings)
                data = await websocket.receive_text()
                message = json.loads(data)

                # Log incoming message (skip noisy ping events)
                if message.get("event") != "ping":
                    message_data = message.get("data", {})
                    log.info(
                        "WS IN",
                        ws_event=message.get("event"),
                        data_keys=sorted(str(key) for key in message_data)
                        if isinstance(message_data, dict) else [],
                    )

                # Handle ping/pong for keep-alive
                if message.get("event") == "ping":
                    await ws_manager.send_to(websocket, "pong", {"timestamp": datetime.now().isoformat()})

                # Realtime scope: profile, entity subscriptions, preview policy
                elif message.get("event") in _SCOPE_MESSAGES:
                    await _handle_scope_message(websocket, message)

                # Handle generator instance registration (for cleanup on disconnect)
                elif message.get("event") == "register_generator_instance":
                    generator_instance_id = message.get("data", {}).get("generator_instance_id")
                    if generator_instance_id and ws_manager.register_generator_instance(
                        websocket, generator_instance_id
                    ):
                        await ws_manager.send_to(websocket, "generator_instance_registered", {
                            "generator_instance_id": generator_instance_id
                        })
                        from generation_queue import get_generation_queue
                        await get_generation_queue().generator_instance_connected(
                            generator_instance_id
                        )

                # Handle agent control messages. These only set flags that no
                # agent run reads, and a chat id alone does not name a profile
                # (ids are per-profile), so they carry no PIN check.
                elif message.get("event") == "agent_pause":
                    chat_id = message.get("data", {}).get("chat_id")
                    if chat_id:
                        agent_state_manager.request_pause(chat_id)
                        await ws_manager.send_to(websocket, "agent_paused", {"chat_id": chat_id})

                elif message.get("event") == "agent_resume":
                    chat_id = message.get("data", {}).get("chat_id")
                    if chat_id:
                        agent_state_manager.resume(chat_id)
                        await ws_manager.send_to(websocket, "agent_resumed", {"chat_id": chat_id})

                # Handle generation work request decline (frontend couldn't submit)
                elif message.get("event") == "generation_decline_work":
                    data = message.get("data", {})
                    client_id = data.get("generator_instance_id")
                    backend_name = data.get("backend_name")
                    if client_id and backend_name:
                        from generation_queue import get_generation_queue
                        queue = get_generation_queue()
                        reservation_id = data.get("reservation_id")
                        if reservation_id:
                            await queue.decline_work_reservation(
                                reservation_id, client_id, backend_name
                            )
                        else:
                            await queue.decline_work_request(client_id, backend_name)

                elif message.get("event") == "agent_cancel":
                    chat_id = message.get("data", {}).get("chat_id")
                    if chat_id:
                        agent_state_manager.request_cancel(chat_id)
                        await ws_manager.send_to(websocket, "agent_cancelled", {"chat_id": chat_id})

            except WebSocketDisconnect:
                break
            except json.JSONDecodeError:
                await ws_manager.send_to(websocket, "error", {"message": "Invalid JSON"})
            except Exception as e:
                log.error(f"Error handling WebSocket message: {e}")
                break

    except Exception as e:
        log.error(f"WebSocket error: {e}")
    finally:
        await ws_manager.disconnect(websocket)
