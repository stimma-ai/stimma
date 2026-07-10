"""In-process permission gate for STP tool calls made from inside run_code.

Generation now happens via the agent's Python (``from stimma.tools.* import ...;
await tool(...)``), which routes through ``StimmaSDK._dispatch_tool``. That path is
NOT the top-level ``call_tool`` function call, so the legacy pause-and-replay HITL
(``_needs_permission`` / ``_pause_for_permission`` in service.py) never fires for it.

The legacy HITL cannot be reused here: it works by persisting pending state and
``raise HumanActionRequired`` to unwind the whole turn, then replaying the loop on
resume. Mid-``run_code`` that would re-execute the agent's program from the top and
re-run every tool call before the gated one → double-spend.

So this gate is an **in-process async block**: the sandbox coroutine ``await``s a
future that the ``/human-response`` endpoint resolves in the same process/event loop.
The coroutine suspends cleanly (sibling ``gather`` branches suspend too); approve
resolves the future and execution continues exactly where it paused; deny raises
``ToolPermissionDenied`` inside that one coroutine (surfaces as a normal tool failure).

The run_code executor is already a timeout-free 0.5s poll loop that tolerates an
arbitrarily long inner ``await`` (every multi-minute generation parks it the same way)
and cancels the inner task on interrupt — so parking here needs no special handling
beyond registry cleanup.
"""

from __future__ import annotations

import asyncio
import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from core.logging import get_logger
from database import Chat, ChatItem

from .permissions import get_stp_permission_decision

log = get_logger(__name__)


class ToolPermissionDenied(Exception):
    """Raised inside the sandbox when the user denies (or has denied) a tool.

    Surfaces to the agent as a normal tool failure so it can adapt or stop.
    """


# request_id -> Future[{"approved": bool, "scope": str}]. Single backend process,
# single event loop → a module-level dict is a safe in-process registry.
_PENDING: dict[str, asyncio.Future] = {}


def _request_id(chat_id: int, tool_id: str) -> str:
    return f"{chat_id}:{tool_id}"


def is_pending_permission(request_id: str) -> bool:
    fut = _PENDING.get(request_id)
    return fut is not None and not fut.done()


def resolve_pending_permission(request_id: str, result: dict) -> bool:
    """Resolve a parked permission gate. Returns True if one was waiting."""
    fut = _PENDING.get(request_id)
    if fut is None or fut.done():
        return False
    fut.set_result(result)
    return True


async def _create_permission_card(
    *,
    session_maker: async_sessionmaker,
    chat_id: int,
    tool_id: str,
    request_id: str,
    display_name: str,
    provider_name: str | None,
    task_type: str | None,
    inputs: dict,
) -> None:
    """Persist + broadcast the v2_tool_permission HITL card (reuses the existing
    frontend card via V2PermissionPrompt)."""
    from utils.websocket import ws_manager

    v2_tool_args = {
        "tool_id": tool_id,
        "_v2_tool_name": "call_tool",
        "_display_name": display_name,
        "_provider_name": provider_name,
        "_task_type": task_type,
        "inputs": inputs,
        "_inprocess_request_id": request_id,
    }
    prompt = f"Generate with {display_name}" if display_name else f"Generate with {tool_id}"
    hitl_action = {
        "type": "v2_tool_permission",
        "prompt": prompt,
        "node_id": request_id,
        "tool_call_id": request_id,
        "v2_tool_args": v2_tool_args,
    }
    async with session_maker() as session:
        item = ChatItem(
            chat_id=chat_id,
            item_type="hitl_request",
            item_metadata=json.dumps(hitl_action),
        )
        session.add(item)
        await session.commit()
        item_dict = item.to_dict()
    await ws_manager.broadcast("chat_item_created", {"chat_id": chat_id, "item": item_dict})


def _resolve_display_meta(tool_id: str, kwargs: dict, task_type: str | None) -> dict:
    """Best-effort tool name / provider / task type for the card. Never raises."""
    display_name = tool_id
    provider_name = None
    try:
        from providers.registry import ProviderRegistry

        pt = ProviderRegistry().get_tool(tool_id)
        if pt:
            provider, descriptor = pt
            display_name = descriptor.name or tool_id
            provider_name = provider.provider_name
    except Exception:
        pass

    inputs: dict = {}
    if isinstance(kwargs, dict):
        if isinstance(kwargs.get("prompt"), str):
            inputs["prompt"] = kwargs["prompt"]
        imgs = [i for i in (kwargs.get("input_images") or []) if isinstance(i, int)]
        if imgs:
            inputs["input_images"] = imgs
    return {
        "display_name": display_name,
        "provider_name": provider_name,
        "task_type": task_type if isinstance(task_type, str) else None,
        "inputs": inputs,
    }


async def _configured_decision(
    chat_id: int, tool_id: str, session_maker: async_sessionmaker
) -> str:
    """Resolve the persisted decision (allow/deny/ask) against a fresh session.

    Fresh session, never the SDK's own session — the caller may park after this and
    must not hold a transaction across the wait, and concurrent gather branches gate
    concurrently. Returns "allow" if the chat can't be loaded (fail open: never block
    generation on a lookup miss).
    """
    async with session_maker() as session:
        chat = (
            await session.execute(select(Chat).where(Chat.id == chat_id))
        ).scalar_one_or_none()
        if chat is None:
            return "allow"
        return await get_stp_permission_decision(tool_id, chat, session)


async def ensure_tool_permission(
    *,
    chat_id: int,
    tool_id: str,
    kwargs: dict,
    task_type: str | None = None,
    run_cache: dict[str, bool],
    session_maker: async_sessionmaker | None = None,
) -> None:
    """Gate an STP tool call. Returns when allowed; raises ToolPermissionDenied when denied.

    ``session_maker`` must produce sessions on the same database as the run (the SDK
    derives one from its own session's engine) — the gate never resolves a database
    through the global profile registry. On "ask", blocks (cleanly) on the user
    resolving the permission card. Persistence of chat/always grants happens in the
    /human-response handler using its own request session — this coroutine never
    holds a write transaction across the wait.
    """
    if not tool_id:
        return

    # Per-run cache: a decision reached earlier in this same run wins immediately
    # (also covers "approve for chat/always" that got persisted; re-reading below
    # would catch those too, but the cache avoids the DB round-trip and re-prompt).
    cached = run_cache.get(tool_id)
    if cached is True:
        return
    if cached is False:
        raise ToolPermissionDenied(f"Tool '{tool_id}' was denied for this session.")

    decision = await _configured_decision(chat_id, tool_id, session_maker)

    if decision == "allow":
        run_cache[tool_id] = True
        return
    if decision == "deny":
        run_cache[tool_id] = False
        raise ToolPermissionDenied(f"Tool '{tool_id}' is blocked in tool permissions.")

    # decision == "ask": block on the card
    request_id = _request_id(chat_id, tool_id)
    fut = _PENDING.get(request_id)
    if fut is None or fut.done():
        # We are the first (or a new) request for this tool in this run — create the card.
        fut = asyncio.get_event_loop().create_future()
        _PENDING[request_id] = fut
        meta = _resolve_display_meta(tool_id, kwargs, task_type)
        await _create_permission_card(
            session_maker=session_maker,
            chat_id=chat_id,
            tool_id=tool_id,
            request_id=request_id,
            display_name=meta["display_name"],
            provider_name=meta["provider_name"],
            task_type=meta["task_type"],
            inputs=meta["inputs"],
        )
    # else: a concurrent gather branch already raised the card — await the same future.

    try:
        result = await fut
    finally:
        # Cancellation (interrupt/stop) unwinds here — clean up so a later run re-asks.
        if _PENDING.get(request_id) is fut:
            _PENDING.pop(request_id, None)

    approved = bool(result.get("approved"))
    run_cache[tool_id] = approved
    if not approved:
        raise ToolPermissionDenied(f"Tool '{tool_id}' was denied by the user.")
