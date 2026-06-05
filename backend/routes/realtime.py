"""Real-time communication routes (WebSocket and SSE)."""
import asyncio
import json
from core.logging import get_logger
from datetime import datetime
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sse_starlette.sse import EventSourceResponse

from ingestion import get_ingestion
from utils.websocket import ws_manager
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


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """
    WebSocket endpoint for real-time updates.
    Clients can connect here to receive events about:
    - media_added: New media items indexed
    - media_updated: Media items processed/updated
    - media_deleted: Media items removed
    - progress_update: Processing progress changes
    """
    await ws_manager.connect(websocket)

    try:
        # Send welcome message
        await ws_manager.send_to(websocket, "connected", {
            "message": "Connected to Stimma WebSocket",
            "timestamp": datetime.now().isoformat()
        })

        # Keep connection alive and handle incoming messages
        while True:
            try:
                # Wait for messages from client (e.g., subscriptions, pings)
                data = await websocket.receive_text()
                message = json.loads(data)

                # Log incoming message (skip noisy ping events)
                if message.get("event") != "ping":
                    log.info(f"WS IN: {message.get('event')} - {json.dumps(message.get('data', {}))[:200]}")

                # Handle ping/pong for keep-alive
                if message.get("event") == "ping":
                    await ws_manager.send_to(websocket, "pong", {"timestamp": datetime.now().isoformat()})

                # Handle generator instance registration (for cleanup on disconnect)
                elif message.get("event") == "register_generator_instance":
                    generator_instance_id = message.get("data", {}).get("generator_instance_id")
                    if generator_instance_id:
                        ws_manager.register_generator_instance(websocket, generator_instance_id)
                        await ws_manager.send_to(websocket, "generator_instance_registered", {
                            "generator_instance_id": generator_instance_id
                        })

                # Handle agent control messages
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
                        await queue.decline_work_request(client_id, backend_name)

                elif message.get("event") == "agent_cancel":
                    chat_id = message.get("data", {}).get("chat_id")
                    if chat_id:
                        agent_state_manager.request_cancel(chat_id)
                        await ws_manager.send_to(websocket, "agent_cancelled", {"chat_id": chat_id})

                elif message.get("event") == "render_layout_response":
                    from utils.ui_render import complete_request
                    data = message.get("data", {})
                    complete_request(
                        request_id=data.get("request_id", ""),
                        png_b64=data.get("png_b64"),
                        error=data.get("error"),
                    )

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
