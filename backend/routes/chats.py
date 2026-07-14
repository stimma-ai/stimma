"""API routes for chat system."""
import asyncio
from core.logging import get_logger
from datetime import datetime
from typing import Any, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func, or_, and_, desc, delete, update
from sqlalchemy.ext.asyncio import AsyncSession
import json

from database import Chat, ChatItem, GenerationJob, LLMTrace, UserPreference, MediaItem
from core.dependencies import get_db_session
from models.api_models import BaseModel
from pydantic import BaseModel as PydanticBaseModel
from project_service import get_project_or_404
from utils.websocket import ws_manager
from config import get_settings
from llm_resolver import (
    get_effective_llm_config,
    LLMInsufficientBalanceError,
    LLMNotConfiguredError,
    normalize_model_slug,
)
from llm_correlation import llm_correlation_context

log = get_logger(__name__)


# Request/Response models
class BatchDeleteRequest(PydanticBaseModel):
    ids: List[int]


class ChatCreateRequest(PydanticBaseModel):
    name: Optional[str] = None
    original_chatitem_id: Optional[int] = None
    project_id: Optional[int] = None
    flow_id: Optional[int] = None
    model_slug: Optional[str] = None


class ChatUpdateRequest(PydanticBaseModel):
    name: Optional[str] = None
    throttle: Optional[str] = None
    generation_settings: Optional[str] = None  # JSON string
    project_id: Optional[int] = None
    flow_id: Optional[int] = None
    model_slug: Optional[str] = None


class AttachmentInfo(PydanticBaseModel):
    media_id: Optional[int] = None  # For images from library
    path: Optional[str] = None  # For uploaded files
    filename: Optional[str] = None


class ChatItemCreateRequest(PydanticBaseModel):
    item_type: str
    message_text: Optional[str] = None
    tool_name: Optional[str] = None
    tool_call_id: Optional[str] = None
    tool_args: Optional[str] = None
    tool_result: Optional[str] = None
    tool_error: Optional[str] = None
    media_id: Optional[int] = None
    media_ids: Optional[str] = None
    grid_layout: Optional[str] = None
    parent_item_id: Optional[int] = None
    item_metadata: Optional[str] = None
    selected_media_ids: Optional[List[int]] = None  # Media IDs user selected before sending
    attachments: Optional[List[AttachmentInfo]] = None  # Images attached to message


class ChatResponse(PydanticBaseModel):
    id: int
    name: str
    created_at: str
    updated_at: str
    deleted_at: Optional[str]
    original_chatitem_id: Optional[int]
    project_id: Optional[int]
    flow_id: Optional[int] = None
    throttle: Optional[str]
    generation_settings: Optional[dict]
    model_slug: Optional[str] = None


class ChatListResponse(PydanticBaseModel):
    items: List[ChatResponse]
    total: int
    page: int
    page_size: int


class MediaPreview(PydanticBaseModel):
    media_id: int
    file_hash: str


class ChatPreview(PydanticBaseModel):
    id: int
    name: str
    created_at: str
    updated_at: str
    project_id: Optional[int]
    message_count: int
    generated_count: int
    recent_media: List[MediaPreview]
    last_message: str = ''


class ChatPreviewListResponse(PydanticBaseModel):
    items: List[ChatPreview]
    total: int
    page: int
    page_size: int


class ChatItemResponse(PydanticBaseModel):
    id: int
    chat_id: int
    created_at: str
    item_type: str
    message_text: Optional[str]
    tool_name: Optional[str]
    tool_call_id: Optional[str]
    tool_args: Optional[dict]
    # Tool results can be object/array/string depending on tool and legacy rows.
    tool_result: Optional[Any]
    tool_error: Optional[str]
    media_id: Optional[int]
    media_ids: Optional[list]
    grid_layout: Optional[dict]
    parent_item_id: Optional[int]
    item_metadata: Optional[dict]


class ChatItemListResponse(PydanticBaseModel):
    items: List[ChatItemResponse]
    has_more: bool


router = APIRouter(prefix="/api/chats", tags=["chats"])


async def collect_chat_media(session, chat_ids):
    """Generated media per chat, newest first, parsed from media_display items.

    Media references live in item_metadata.display_data.rows[].output.media_id
    (media_items.chat_item_id is not populated by the agent pipeline). Returns
    (media_ids_by_chat, media_info) where media_info maps id -> file_hash for
    all referenced, non-deleted media. Shared by chat previews and global
    search thumbnails.
    """
    if not chat_ids:
        return {}, {}

    media_display_query = (
        select(ChatItem.chat_id, ChatItem.item_metadata)
        .where(
            ChatItem.chat_id.in_(chat_ids),
            ChatItem.item_type == 'media_display',
            ChatItem.item_metadata.isnot(None),
        )
        .order_by(desc(ChatItem.id))
    )
    media_display_rows = (await session.execute(media_display_query)).all()

    media_ids_by_chat = {}  # chat_id -> [media_id, ...] ordered newest first
    all_media_ids = set()
    for chat_id_val, metadata_raw in media_display_rows:
        if chat_id_val not in media_ids_by_chat:
            media_ids_by_chat[chat_id_val] = []

        try:
            metadata = json.loads(metadata_raw) if isinstance(metadata_raw, str) else metadata_raw
            if not metadata:
                continue
            display_data = metadata.get('display_data', {})
            if not isinstance(display_data, dict):
                continue
            for media_row in display_data.get('rows', []):
                if not isinstance(media_row, dict):
                    continue
                output = media_row.get('output', {})
                if isinstance(output, dict) and output.get('status') == 'complete':
                    mid = output.get('media_id')
                    if mid and isinstance(mid, int):
                        media_ids_by_chat[chat_id_val].append(mid)
                        all_media_ids.add(mid)
        except (json.JSONDecodeError, TypeError):
            continue

    media_info = {}
    if all_media_ids:
        media_query = (
            select(MediaItem.id, MediaItem.file_hash)
            .where(
                MediaItem.id.in_(list(all_media_ids)),
                MediaItem.deleted_at.is_(None),
            )
        )
        media_info = {row[0]: row[1] for row in (await session.execute(media_query)).all()}

    return media_ids_by_chat, media_info


def generate_unique_chat_name(existing_names: List[str]) -> str:
    """Generate a unique 'Untitled' or 'Untitled N' name."""
    if "Untitled" not in existing_names:
        return "Untitled"

    # Find the highest number
    max_num = 1
    for name in existing_names:
        if name.startswith("Untitled "):
            try:
                num = int(name.split(" ")[1])
                max_num = max(max_num, num)
            except (IndexError, ValueError):
                continue

    return f"Untitled {max_num + 1}"


def is_auto_generated_name(name: str) -> bool:
    """Check if a chat name is auto-generated (empty, Untitled, or Untitled N)."""
    if not name:  # Empty string counts as auto-generated
        return True
    if name == "Untitled":
        return True
    if name.startswith("Untitled "):
        try:
            int(name.split(" ")[1])
            return True
        except (IndexError, ValueError):
            return False
    return False


async def auto_name_chat(
    chat_id: int,
    user_message: Optional[str],
    profile_id: Optional[str] = None,
    selected_media_ids: Optional[List[int]] = None,
    user_messages: Optional[List[str]] = None,
    current_name: Optional[str] = None,
):
    """
    Use LLM to generate a short name for the chat based on user messages.
    Runs in background with its own database session.

    Called on messages 1-3. On message 1 it always generates a name. On messages
    2-3 it asks the LLM whether the existing title is still good or should be
    replaced now that more context is available.

    If selected_media_ids are provided, queries for extracted_prompt to give
    the LLM more context about what the user is working with.
    """
    from llm import llm_complete_text
    from database_registry import get_database_registry
    from core.profile_context import set_current_profile, get_current_profile

    if profile_id is None:
        profile_id = get_current_profile()

    # Set profile context for this background task so broadcasts include profile_id
    set_current_profile(profile_id)

    log.info(f"auto_name_chat started for chat {chat_id}")

    registry = get_database_registry()
    db = registry.get_database(profile_id)

    try:
        async with db.async_session_maker() as session:
            # Get the chat
            result = await session.execute(select(Chat).where(Chat.id == chat_id))
            chat = result.scalar_one_or_none()

            if not chat:
                log.warning(f"Chat {chat_id}: Chat not found in database")
                return

            # If caller told us there's a current name from a prior auto-name pass,
            # allow re-evaluation. Otherwise only auto-name if still Untitled.
            has_prior_auto_name = current_name and not is_auto_generated_name(current_name)
            if not has_prior_auto_name and not is_auto_generated_name(chat.name):
                log.info(f"Chat {chat_id} already has custom name '{chat.name}', skipping auto-name")
                return

            log.info(f"Chat {chat_id} name='{chat.name}', proceeding with LLM call")

            # Query for media context if media IDs were provided
            media_context = ""
            if selected_media_ids:
                result = await session.execute(
                    select(MediaItem.extracted_prompt)
                    .where(MediaItem.id.in_(selected_media_ids))
                )
                media_info = result.fetchall()

                # Collect unique prompts
                prompts = []
                for row in media_info:
                    if row.extracted_prompt and row.extracted_prompt.strip():
                        prompts.append(row.extracted_prompt.strip())

                # Build media context string
                context_parts = []
                if prompts:
                    # Dedupe and truncate prompts
                    unique_prompts = list(dict.fromkeys(prompts))[:3]
                    context_parts.append("Generation prompts: " + "; ".join(p[:100] for p in unique_prompts))

                if context_parts:
                    media_context = "\n" + "\n".join(context_parts) + "\n"
                    log.info(f"Chat {chat_id}: Added media context from {len(selected_media_ids)} images")

            request_text = (user_message or "").strip()
            if not request_text and not media_context:
                log.info(f"Chat {chat_id}: No text or media context for auto-name, skipping")
                return

            # Resolve the effective agent-fast LLM so Stimma Cloud and endpoint
            # configs both work here.
            llm_config = await get_effective_llm_config("agent-fast")

            # Build conversation context from all user messages if available
            if user_messages and len(user_messages) > 1:
                msgs_text = "\n".join(f"- {m[:200]}" for m in user_messages if m and m.strip())
                conversation_context = msgs_text
            else:
                conversation_context = request_text[:200] if request_text else "[Image attachments only]"

            # If we already have a real title from a prior pass, ask LLM to evaluate
            if has_prior_auto_name:
                system_prompt = (
                    "You evaluate chat titles. Given a conversation and its current title, "
                    "decide if the title is still accurate or should be replaced. "
                    "Reply with ONLY the title (either the same one or a better one). "
                    "Titles should be 4-5 words max."
                )
                user_prompt = f"""Current title: {current_name}

Messages so far:
{conversation_context}{media_context}

If the current title is still a good fit, reply with it exactly. Otherwise reply with a better 4-5 word title.
Title:"""
            else:
                system_prompt = "You generate short titles (4-5 words max). Reply with ONLY the title."
                user_prompt = f"""Generate a 4-5 word title for this chat.

Good: "Golden Retriever Variations", "Beach Sunset Edit", "Company Logo"
Bad: "Generating Variations of Golden Retriever Photo", "Editing the Beautiful Beach Sunset Image"

Request: {conversation_context}{media_context}
Title:"""

            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ]

            api_base = llm_config.get_api_base()
            log.info(f"Chat {chat_id}: Calling LLM with model={llm_config.get_model()}, api_base={api_base}")
            log.info(f"Chat {chat_id}: Messages: {messages}")

            with llm_correlation_context("title", chat_id=chat_id):
                new_name = await llm_complete_text(
                    config=llm_config,
                    messages=messages,
                    max_tokens=48,
                    temperature=0.2,
                )

            log.info(f"Chat {chat_id}: Raw LLM response: '{new_name[:200] if new_name else '(empty)'}'")
            # complete() already strips thinking tags

            # Clean up the name (remove quotes, limit length)
            new_name = new_name.strip('"\'').strip()
            # Remove trailing punctuation
            new_name = new_name.rstrip('.,!?;:')
            if len(new_name) > 50:
                new_name = new_name[:47] + "..."

            log.info(f"Chat {chat_id}: LLM returned name '{new_name}'")

            if not new_name:
                log.warning(f"Chat {chat_id}: LLM returned empty name, skipping update")
                return

            # Reject generic/uninformative names - keep "Untitled" instead
            generic_patterns = [
                "image generation",
                "image edit",
                "image request",
                "image chat",
                "generation request",
                "generation chat",
                "edit request",
                "photo edit",
                "picture edit",
                "make variations",
                "create variations",
                "image variations",
            ]
            name_lower = new_name.lower()
            if any(pattern in name_lower for pattern in generic_patterns):
                log.info(f"Chat {chat_id}: Rejecting generic name '{new_name}', keeping Untitled")
                return

            # Re-fetch chat to avoid stale data
            result = await session.execute(select(Chat).where(Chat.id == chat_id))
            chat = result.scalar_one_or_none()
            # Allow update if name is still auto-generated OR if we're re-evaluating a prior auto-name
            can_update = chat and (is_auto_generated_name(chat.name) or has_prior_auto_name)
            if can_update:
                # Skip update if LLM returned the same name (no change needed)
                if chat.name == new_name:
                    log.info(f"Chat {chat_id}: LLM kept existing name '{new_name}', no update needed")
                else:
                    chat.name = new_name
                    await session.commit()
                    await session.refresh(chat)  # Get latest generation_settings after commit

                    log.info(f"Chat {chat_id}: Updated name to '{new_name}'")

                    # Broadcast the update (name change, not settings)
                    await ws_manager.broadcast("chat_updated", {
                        "chat_id": chat_id,
                        "chat": chat.to_dict(),
                        "settings_changed": False
                    })
            else:
                log.warning(f"Chat {chat_id}: Chat not found or has user-set custom name, skipping update")

    except (LLMNotConfiguredError, LLMInsufficientBalanceError):
        log.info(f"Chat {chat_id}: No LLM available for auto-naming, skipping")
    except Exception as e:
        log.error(f"Error auto-naming chat {chat_id}: {e}", exc_info=True)
    finally:
        log.info(f"auto_name_chat finished for chat {chat_id}")


async def _run_agent_background(
    chat_id: int,
    user_message: Optional[str],
    profile_id: Optional[str],
    selected_media_ids: Optional[List[int]] = None,
):
    """Run the agent loop in the background with its own database session.

    The user message is already committed and broadcast by the time this runs,
    so the POST that triggered it can return immediately rather than holding the
    HTTP request open for the whole (potentially long) agent turn. Holding it
    open caused clients to time out mid-turn and treat the already-sent message
    as failed. Agent progress reaches the UI over WebSocket regardless.
    """
    from database_registry import get_database_registry
    from core.profile_context import set_current_profile, get_current_profile

    if profile_id is None:
        profile_id = get_current_profile()
    # Restore profile context so the agent's broadcasts carry the right profile.
    set_current_profile(profile_id)

    registry = get_database_registry()
    db = registry.get_database(profile_id)

    # Serialize runs per chat: if a run is already active (the user sent a
    # message mid-turn, or the previous run is still winding down after an
    # abort), wait for it to finish instead of letting run_agent's concurrency
    # guard drop this run — a dropped run means a committed user message the
    # agent never answers.
    from agent.v2.service import get_active_task
    prev_task = get_active_task(chat_id)
    if prev_task and not prev_task.done() and prev_task is not asyncio.current_task():
        log.info(f"Chat {chat_id}: waiting for previous agent run to finish before starting")
        await asyncio.gather(prev_task, return_exceptions=True)

    try:
        async with db.async_session_maker() as session:
            result = await session.execute(select(Chat).where(Chat.id == chat_id))
            chat = result.scalar_one_or_none()
            if not chat:
                log.warning(f"Chat {chat_id}: not found, skipping agent run")
                return

            from agent import run_agent
            await run_agent(
                chat=chat,
                user_message=user_message,
                session=session,
                ws_manager=ws_manager,
                selected_media_ids=selected_media_ids,
            )
            log.info(f"run_agent completed for chat {chat_id}")
    except Exception as e:
        # run_agent surfaces its own errors as chat items; this is a backstop.
        log.error(f"Agent execution error for chat {chat_id}: {e}", exc_info=True)


@router.post("", response_model=ChatResponse)
async def create_chat(
    request: ChatCreateRequest,
    session: AsyncSession = Depends(get_db_session)
):
    """Create a new chat."""
    project = None
    if request.project_id is not None:
        project = await get_project_or_404(session, request.project_id)
    if request.flow_id is not None:
        from flow_service import get_flow_or_404
        await get_flow_or_404(session, request.flow_id)

    # Use provided name or empty string (will be auto-named after first message)
    name = request.name or ""

    # Create chat with default generation settings
    import json
    default_settings = {
        "generator": None,
        "model": None,
        "parameters": {},
        "locked": [],
        "loras": [],
    }

    # Note: We no longer load chat_tool_selections defaults here.
    # Tool selection now happens dynamically via get_tool_selection_for_task()
    # which respects allowed_tools from the chat's tool permissions.

    chat = Chat(
        name=name,
        original_chatitem_id=request.original_chatitem_id,
        project_id=request.project_id,
        flow_id=request.flow_id,
        throttle='off',
        generation_settings=json.dumps(default_settings),
        # Snapshot the current choice. New chats follow the last explicitly
        # selected model; existing chats do not change when that choice moves.
        model_slug=normalize_model_slug(
            request.model_slug
            or (project.default_model_slug if project else None)
            or get_settings().default_model
        ),
    )
    session.add(chat)
    await session.commit()
    await session.refresh(chat)

    # Broadcast new chat via WebSocket
    await ws_manager.broadcast("chat_created", {
        "chat": chat.to_dict()
    })

    from object_hash import salted_hash
    from telemetry import get_telemetry_client
    _chat_created_props = {"chatHash": salted_hash(f"chat:{chat.id}")}
    if chat.project_id:
        _chat_created_props["projectHash"] = salted_hash(f"project:{chat.project_id}")
    get_telemetry_client().track("chat_created", _chat_created_props, category="chat")

    return ChatResponse(**chat.to_dict())


@router.get("", response_model=ChatListResponse)
async def list_chats(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    include_deleted: bool = Query(False),
    project_id: Optional[int] = Query(None),
    flow_id: Optional[int] = Query(None),
    session: AsyncSession = Depends(get_db_session)
):
    """List all chats, paginated and reverse chronological."""
    # Build query
    query = select(Chat)
    if not include_deleted:
        query = query.where(Chat.deleted_at.is_(None))
    if flow_id is None:
        query = query.where(Chat.flow_id.is_(None))
    if project_id is not None:
        query = query.where(Chat.project_id == project_id)
    if flow_id is not None:
        query = query.where(Chat.flow_id == flow_id)

    query = query.order_by(desc(Chat.updated_at))

    # Get total count
    count_query = select(func.count()).select_from(Chat)
    if not include_deleted:
        count_query = count_query.where(Chat.deleted_at.is_(None))
    if flow_id is None:
        count_query = count_query.where(Chat.flow_id.is_(None))
    if project_id is not None:
        count_query = count_query.where(Chat.project_id == project_id)
    if flow_id is not None:
        count_query = count_query.where(Chat.flow_id == flow_id)
    total_result = await session.execute(count_query)
    total = total_result.scalar()

    # Get page of results
    query = query.offset((page - 1) * page_size).limit(page_size)
    result = await session.execute(query)
    chats = result.scalars().all()

    return ChatListResponse(
        items=[ChatResponse(**chat.to_dict()) for chat in chats],
        total=total,
        page=page,
        page_size=page_size
    )


@router.get("/previews", response_model=ChatPreviewListResponse)
async def list_chat_previews(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    project_id: Optional[int] = Query(None),
    flow_id: Optional[int] = Query(None),
    session: AsyncSession = Depends(get_db_session)
):
    """List chats with message counts and recent generated media for the landing page."""
    # Get paginated chats
    query = select(Chat).where(Chat.deleted_at.is_(None))
    count_query = select(func.count()).select_from(Chat).where(Chat.deleted_at.is_(None))
    if flow_id is None:
        query = query.where(Chat.flow_id.is_(None))
        count_query = count_query.where(Chat.flow_id.is_(None))
    if project_id is not None:
        query = query.where(Chat.project_id == project_id)
        count_query = count_query.where(Chat.project_id == project_id)
    if flow_id is not None:
        query = query.where(Chat.flow_id == flow_id)
        count_query = count_query.where(Chat.flow_id == flow_id)
    query = query.order_by(desc(Chat.updated_at))

    total_result = await session.execute(count_query)
    total = total_result.scalar()

    query = query.offset((page - 1) * page_size).limit(page_size)
    result = await session.execute(query)
    chats = result.scalars().all()

    if not chats:
        return ChatPreviewListResponse(items=[], total=total, page=page, page_size=page_size)

    chat_ids = [c.id for c in chats]

    # Message counts: count user_message and assistant_message with text
    msg_count_query = (
        select(ChatItem.chat_id, func.count().label('cnt'))
        .where(
            ChatItem.chat_id.in_(chat_ids),
            ChatItem.item_type.in_(['user_message', 'assistant_message']),
            ChatItem.message_text.isnot(None),
            ChatItem.message_text != '',
        )
        .group_by(ChatItem.chat_id)
    )
    msg_result = await session.execute(msg_count_query)
    msg_counts = {row[0]: row[1] for row in msg_result.all()}

    # Last message text per chat (most recent user or assistant message)
    last_msg_subq = (
        select(
            ChatItem.chat_id,
            ChatItem.message_text,
            func.row_number().over(
                partition_by=ChatItem.chat_id,
                order_by=desc(ChatItem.id)
            ).label('rn')
        )
        .where(
            ChatItem.chat_id.in_(chat_ids),
            ChatItem.item_type.in_(['user_message', 'assistant_message']),
            ChatItem.message_text.isnot(None),
            ChatItem.message_text != '',
        )
        .subquery()
    )
    last_msg_query = select(last_msg_subq.c.chat_id, last_msg_subq.c.message_text).where(last_msg_subq.c.rn == 1)
    last_msg_result = await session.execute(last_msg_query)
    last_messages = {row[0]: row[1] for row in last_msg_result.all()}

    media_ids_by_chat, media_info = await collect_chat_media(session, chat_ids)

    # Build recent_media and gen_counts per chat
    gen_counts = {}
    recent_by_chat = {}
    for chat_id_val, mids in media_ids_by_chat.items():
        # Filter to existing (non-deleted) media
        valid_mids = [mid for mid in mids if mid in media_info]
        gen_counts[chat_id_val] = len(valid_mids)
        # Take most recent 10 for the strip
        recent_by_chat[chat_id_val] = [
            MediaPreview(media_id=mid, file_hash=media_info[mid])
            for mid in valid_mids[:10]
        ]

    # Build response
    items = []
    for chat in chats:
        items.append(ChatPreview(
            id=chat.id,
            name=chat.name or '',
            created_at=chat.created_at.isoformat() if chat.created_at else '',
            updated_at=chat.updated_at.isoformat() if chat.updated_at else '',
            project_id=chat.project_id,
            message_count=msg_counts.get(chat.id, 0),
            generated_count=gen_counts.get(chat.id, 0),
            recent_media=recent_by_chat.get(chat.id, []),
            last_message=last_messages.get(chat.id, ''),
        ))

    return ChatPreviewListResponse(items=items, total=total, page=page, page_size=page_size)


@router.get("/agent/running")
async def get_running_agent_chats():
    """Chat ids with an active agent execution — lets the frontend prime
    its spinner state on load/reconnect instead of relying solely on
    agent_started/agent_stopped WebSocket events. Must stay declared
    before the /{chat_id} routes."""
    from agent.v2.service import get_active_chat_ids
    return {"chat_ids": get_active_chat_ids()}


@router.get("/{chat_id}", response_model=ChatResponse)
async def get_chat(
    chat_id: int,
    session: AsyncSession = Depends(get_db_session)
):
    """Get a specific chat by ID."""
    result = await session.execute(
        select(Chat).where(Chat.id == chat_id)
    )
    chat = result.scalar_one_or_none()

    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")

    return ChatResponse(**chat.to_dict())


@router.get("/{chat_id}/preview")
async def get_chat_preview(
    chat_id: int,
    session: AsyncSession = Depends(get_db_session)
):
    """Get preview data for a chat (thumbnail + last message) for sidebar display."""
    chat_result = await session.execute(
        select(Chat).where(Chat.id == chat_id, Chat.deleted_at.is_(None))
    )
    chat = chat_result.scalar_one_or_none()
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")

    # Last message
    last_msg_query = (
        select(ChatItem.message_text)
        .where(
            ChatItem.chat_id == chat_id,
            ChatItem.item_type.in_(['user_message', 'assistant_message']),
            ChatItem.message_text.isnot(None),
            ChatItem.message_text != '',
        )
        .order_by(desc(ChatItem.id))
        .limit(1)
    )
    last_msg_result = await session.execute(last_msg_query)
    last_message = last_msg_result.scalar() or ''

    # Most recent media (for thumbnail)
    media_display_query = (
        select(ChatItem.item_metadata)
        .where(
            ChatItem.chat_id == chat_id,
            ChatItem.item_type == 'media_display',
            ChatItem.item_metadata.isnot(None),
        )
        .order_by(desc(ChatItem.id))
        .limit(5)
    )
    media_display_result = await session.execute(media_display_query)

    thumbnail_media_id = None
    for (metadata_raw,) in media_display_result:
        try:
            metadata = json.loads(metadata_raw) if isinstance(metadata_raw, str) else metadata_raw
            if not metadata:
                continue
            display_data = metadata.get('display_data', {})
            if not isinstance(display_data, dict):
                continue
            for media_row in display_data.get('rows', []):
                if not isinstance(media_row, dict):
                    continue
                output = media_row.get('output', {})
                if isinstance(output, dict) and output.get('status') == 'complete':
                    mid = output.get('media_id')
                    if mid and isinstance(mid, int):
                        # Verify media exists
                        check = await session.execute(
                            select(MediaItem.id).where(MediaItem.id == mid, MediaItem.deleted_at.is_(None))
                        )
                        if check.scalar():
                            thumbnail_media_id = mid
                            break
            if thumbnail_media_id:
                break
        except (json.JSONDecodeError, TypeError):
            continue

    return {
        'project_id': chat.project_id,
        'thumbnail_media_id': thumbnail_media_id,
        'last_message': last_message[:200] if last_message else '',
    }


@router.patch("/{chat_id}", response_model=ChatResponse)
async def update_chat(
    chat_id: int,
    request: ChatUpdateRequest,
    session: AsyncSession = Depends(get_db_session)
):
    """Update a chat's settings."""
    result = await session.execute(
        select(Chat).where(Chat.id == chat_id)
    )
    chat = result.scalar_one_or_none()

    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")

    # Update fields that were provided
    update_data = request.dict(exclude_unset=True)
    if "model_slug" in update_data:
        update_data["model_slug"] = normalize_model_slug(update_data["model_slug"])

    # Check if settings (not just name) are being changed
    settings_changed = 'throttle' in update_data or 'generation_settings' in update_data

    for key, value in update_data.items():
        setattr(chat, key, value)

    # Note: We intentionally don't update updated_at here.
    # updated_at should only change when messages are added (in create_chat_item),
    # not when settings are changed. This keeps the sidebar sorted by message activity.

    await session.commit()
    await session.refresh(chat)

    # Broadcast chat update via WebSocket
    await ws_manager.broadcast("chat_updated", {
        "chat_id": chat_id,
        "chat": chat.to_dict(),
        "settings_changed": settings_changed
    })

    return ChatResponse(**chat.to_dict())


async def _cancel_chat_work(
    session: AsyncSession,
    chat_ids: list[int],
    cancelled_at: datetime,
) -> None:
    """Stop chat-scoped work from creating new owners after deletion."""
    if not chat_ids:
        return

    from agent.v2.service import get_active_task

    current_task = asyncio.current_task()
    for chat_id in chat_ids:
        task = get_active_task(chat_id)
        if task is not None and task is not current_task and not task.done():
            task.cancel()

    await session.execute(
        update(GenerationJob)
        .where(
            GenerationJob.output_context_kind == "chat",
            GenerationJob.output_context_id.in_([str(value) for value in chat_ids]),
            GenerationJob.status.in_(("queued", "assigned", "processing")),
        )
        .values(
            status="cancelled",
            error="Cancelled because the chat was deleted",
            completed_at=cancelled_at,
        )
    )


@router.delete("/{chat_id}")
async def delete_chat(
    chat_id: int,
    session: AsyncSession = Depends(get_db_session)
):
    """Soft delete a chat."""
    result = await session.execute(
        select(Chat).where(Chat.id == chat_id)
    )
    chat = result.scalar_one_or_none()

    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")

    if chat.deleted_at is not None:
        return {"success": True}

    deleted_at = datetime.utcnow()
    chat.deleted_at = deleted_at
    await _cancel_chat_work(session, [chat_id], deleted_at)
    await session.commit()

    # Broadcast chat deletion via WebSocket
    await ws_manager.broadcast("chat_deleted", {
        "chat_id": chat_id
    })

    from object_hash import salted_hash
    from telemetry import get_telemetry_client
    get_telemetry_client().track(
        "chat_deleted", {"chatHash": salted_hash(f"chat:{chat_id}")}, category="chat"
    )

    return {"success": True}


@router.post("/batch/delete")
async def batch_delete_chats(
    request: BatchDeleteRequest,
    session: AsyncSession = Depends(get_db_session)
):
    """Batch soft delete multiple chats."""
    if not request.ids:
        return {"success": True, "deleted": 0}

    result = await session.execute(
        select(Chat).where(Chat.id.in_(request.ids), Chat.deleted_at.is_(None))
    )
    chats_to_delete = result.scalars().all()

    deleted_at = datetime.utcnow()
    for chat in chats_to_delete:
        chat.deleted_at = deleted_at

    await _cancel_chat_work(
        session,
        [chat.id for chat in chats_to_delete],
        deleted_at,
    )

    await session.commit()

    # Broadcast deletion for each chat
    from object_hash import salted_hash
    from telemetry import get_telemetry_client
    for chat in chats_to_delete:
        await ws_manager.broadcast("chat_deleted", {"chat_id": chat.id})
        get_telemetry_client().track(
            "chat_deleted", {"chatHash": salted_hash(f"chat:{chat.id}")}, category="chat"
        )

    return {"success": True, "deleted": len(chats_to_delete)}


@router.post("/batch/restore")
async def batch_restore_chats(
    request: BatchDeleteRequest,
    session: AsyncSession = Depends(get_db_session)
):
    """Batch restore — pairs with batch/delete for undo."""
    if not request.ids:
        return {"success": True, "restored": 0}

    result = await session.execute(
        select(Chat).where(Chat.id.in_(request.ids), Chat.deleted_at.isnot(None))
    )
    chats_to_restore = result.scalars().all()

    for chat in chats_to_restore:
        chat.deleted_at = None

    await session.commit()

    for chat in chats_to_restore:
        await session.refresh(chat)
        await ws_manager.broadcast("chat_restored", {"chat": chat.to_dict()})

    return {"success": True, "restored": len(chats_to_restore)}


@router.post("/{chat_id}/restore", response_model=ChatResponse)
async def restore_chat(
    chat_id: int,
    session: AsyncSession = Depends(get_db_session)
):
    """Clear the soft-delete tombstone — pairs with DELETE for undo."""
    result = await session.execute(select(Chat).where(Chat.id == chat_id))
    chat = result.scalar_one_or_none()
    if chat is None:
        raise HTTPException(status_code=404, detail="Chat not found")
    if chat.deleted_at is None:
        raise HTTPException(status_code=400, detail="Chat is not deleted")
    chat.deleted_at = None
    await session.commit()
    await session.refresh(chat)
    await ws_manager.broadcast("chat_restored", {"chat": chat.to_dict()})
    return ChatResponse(**chat.to_dict())


@router.post("/{chat_id}/fork", response_model=ChatResponse)
async def fork_chat(
    chat_id: int,
    from_chatitem_id: int,
    session: AsyncSession = Depends(get_db_session)
):
    """Fork a chat from a specific chat item."""
    # Verify source chat exists
    result = await session.execute(
        select(Chat).where(Chat.id == chat_id)
    )
    source_chat = result.scalar_one_or_none()

    if not source_chat:
        raise HTTPException(status_code=404, detail="Source chat not found")

    # Verify chat item exists and belongs to this chat
    result = await session.execute(
        select(ChatItem).where(
            and_(
                ChatItem.id == from_chatitem_id,
                ChatItem.chat_id == chat_id
            )
        )
    )
    chat_item = result.scalar_one_or_none()

    if not chat_item:
        raise HTTPException(status_code=404, detail="Chat item not found")

    # Generate name for forked chat
    result = await session.execute(
        select(Chat.name).where(Chat.deleted_at.is_(None))
    )
    existing_names = [row[0] for row in result]
    name = generate_unique_chat_name(existing_names)

    # Create forked chat with same settings as source
    forked_chat = Chat(
        name=name,
        original_chatitem_id=from_chatitem_id,
        throttle=source_chat.throttle,
        generation_settings=source_chat.generation_settings
    )

    session.add(forked_chat)
    await session.commit()
    await session.refresh(forked_chat)

    return ChatResponse(**forked_chat.to_dict())


def generate_clone_name(base_name: str, existing_names: List[str]) -> str:
    """Generate a unique clone name with ' 1', ' 2' suffix."""
    import re

    # Strip any existing numeric suffix from base name
    # e.g., "My Chat 2" -> "My Chat"
    match = re.match(r'^(.+?)\s+(\d+)$', base_name)
    if match:
        base_name = match.group(1)

    # Find the highest existing suffix number for this base name
    max_num = 0
    pattern = re.compile(rf'^{re.escape(base_name)}\s+(\d+)$')

    for name in existing_names:
        # Check exact match (base name with no suffix)
        if name == base_name:
            max_num = max(max_num, 0)
        # Check suffixed versions
        m = pattern.match(name)
        if m:
            max_num = max(max_num, int(m.group(1)))

    return f"{base_name} {max_num + 1}"


@router.post("/{chat_id}/clone", response_model=ChatResponse)
async def clone_chat(
    chat_id: int,
    session: AsyncSession = Depends(get_db_session)
):
    """Clone a chat with all its settings but no messages."""
    log.info(f"Clone chat request received for chat_id={chat_id}")

    # Get source chat
    result = await session.execute(
        select(Chat).where(Chat.id == chat_id)
    )
    source_chat = result.scalar_one_or_none()

    if not source_chat:
        raise HTTPException(status_code=404, detail="Chat not found")

    # Generate name for cloned chat based on source name
    result = await session.execute(
        select(Chat.name).where(Chat.deleted_at.is_(None))
    )
    existing_names = [row[0] for row in result]
    name = generate_clone_name(source_chat.name, existing_names)

    # Create cloned chat with same settings
    cloned_chat = Chat(
        name=name,
        generation_settings=source_chat.generation_settings,
        throttle=source_chat.throttle
    )

    session.add(cloned_chat)
    await session.commit()
    await session.refresh(cloned_chat)

    # Broadcast chat creation via WebSocket
    await ws_manager.broadcast("chat_created", {
        "chat": cloned_chat.to_dict()
    })

    log.info(f"Cloned chat created: id={cloned_chat.id}, name={cloned_chat.name}")
    return ChatResponse(**cloned_chat.to_dict())


def generate_branch_name(base_name: str, existing_names: List[str]) -> str:
    """Generate a unique branched-chat name like 'X (copy)', 'X (copy 2)'."""
    import re

    match = re.match(r'^(.+?)\s+\(copy(?:\s+(\d+))?\)$', base_name)
    if match:
        base_name = match.group(1)

    candidate = f"{base_name} (copy)"
    if candidate not in existing_names:
        return candidate

    n = 2
    while f"{base_name} (copy {n})" in existing_names:
        n += 1
    return f"{base_name} (copy {n})"


@router.post("/{chat_id}/branch", response_model=ChatResponse)
async def branch_chat(
    chat_id: int,
    from_chatitem_id: int,
    session: AsyncSession = Depends(get_db_session)
):
    """Create a new chat that's a copy of this chat's items up to and including from_chatitem_id."""
    result = await session.execute(select(Chat).where(Chat.id == chat_id))
    source_chat = result.scalar_one_or_none()

    if not source_chat:
        raise HTTPException(status_code=404, detail="Source chat not found")

    result = await session.execute(
        select(ChatItem).where(
            and_(ChatItem.id == from_chatitem_id, ChatItem.chat_id == chat_id)
        )
    )
    anchor_item = result.scalar_one_or_none()

    if not anchor_item:
        raise HTTPException(status_code=404, detail="Chat item not found")

    result = await session.execute(
        select(ChatItem)
        .where(and_(ChatItem.chat_id == chat_id, ChatItem.id <= from_chatitem_id))
        .order_by(ChatItem.id)
    )
    source_items = result.scalars().all()

    result = await session.execute(
        select(Chat.name).where(Chat.deleted_at.is_(None))
    )
    existing_names = [row[0] for row in result]
    name = generate_branch_name(source_chat.name, existing_names)

    branched_chat = Chat(
        name=name,
        project_id=source_chat.project_id,
        flow_id=source_chat.flow_id,
        throttle=source_chat.throttle,
        generation_settings=source_chat.generation_settings,
        additional_instructions=source_chat.additional_instructions,
        agent_tool_config=source_chat.agent_tool_config,
        model_slug=source_chat.model_slug,
    )
    session.add(branched_chat)
    await session.flush()

    id_map = {}
    for old_item in source_items:
        new_item = ChatItem(
            chat_id=branched_chat.id,
            created_at=old_item.created_at,
            item_type=old_item.item_type,
            message_text=old_item.message_text,
            tool_name=old_item.tool_name,
            tool_call_id=old_item.tool_call_id,
            tool_args=old_item.tool_args,
            tool_result=old_item.tool_result,
            tool_error=old_item.tool_error,
            media_id=old_item.media_id,
            media_ids=old_item.media_ids,
            grid_layout=old_item.grid_layout,
            parent_item_id=id_map.get(old_item.parent_item_id),
            item_metadata=old_item.item_metadata,
        )
        session.add(new_item)
        await session.flush()
        id_map[old_item.id] = new_item.id

    await session.commit()
    await session.refresh(branched_chat)

    await ws_manager.broadcast("chat_created", {
        "chat": branched_chat.to_dict()
    })

    log.info(f"Branched chat created: id={branched_chat.id}, name={branched_chat.name}, from chat={chat_id} item={from_chatitem_id}, items={len(source_items)}")
    return ChatResponse(**branched_chat.to_dict())


@router.post("/{chat_id}/clear")
async def clear_chat(
    chat_id: int,
    session: AsyncSession = Depends(get_db_session)
):
    """Clear all messages from a chat while keeping settings."""
    # Verify chat exists
    result = await session.execute(
        select(Chat).where(Chat.id == chat_id)
    )
    chat = result.scalar_one_or_none()

    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")

    # Delete all chat items for this chat
    await session.execute(
        delete(ChatItem).where(ChatItem.chat_id == chat_id)
    )

    # CRITICAL: Also clear the working_context from generation_settings
    # Otherwise old context (prompts, selections) persists and pollutes new conversations
    if chat.generation_settings:
        import json
        try:
            settings = json.loads(chat.generation_settings)
            if "working_context" in settings:
                del settings["working_context"]
                chat.generation_settings = json.dumps(settings)
        except (json.JSONDecodeError, KeyError):
            pass

    await session.commit()

    # Broadcast that chat was cleared
    await ws_manager.broadcast("chat_cleared", {
        "chat_id": chat_id
    })

    return {"success": True}


# Chat Items endpoints
def _is_visible_item(item: ChatItem) -> bool:
    """Check if a chat item is visible in the chat view (not hidden like tool_call/tool_result)."""
    if item.item_type == 'tool_call':
        return True
    if item.item_type == 'tool_result':
        # Tool results only visible if they have an error
        try:
            result_data = json.loads(item.tool_result) if item.tool_result else {}
            return bool(result_data.get('error'))
        except:
            return False
    # Assistant messages only visible if they have actual text content
    if item.item_type == 'assistant_message':
        if item.message_text and item.message_text.strip():
            return True
        try:
            metadata = json.loads(item.item_metadata) if item.item_metadata else {}
            return bool(metadata.get('thinking_status') or metadata.get('thinking_content'))
        except Exception:
            return False
    # Everything else is visible
    return True


async def _mark_deleted_media_in_items(items: list, session: AsyncSession) -> list:
    """
    Process chat items and mark any references to deleted media.
    Checks all known locations where media_ids can be stored.
    """
    # Collect all media_ids from all possible locations
    media_ids = set()
    for item in items:
        # Check media_ids JSON array field
        if item.media_ids:
            try:
                ids = json.loads(item.media_ids) if isinstance(item.media_ids, str) else item.media_ids
                if isinstance(ids, list):
                    media_ids.update(id for id in ids if isinstance(id, int))
            except (json.JSONDecodeError, TypeError):
                pass

        # Check item_metadata for various structures
        if item.item_metadata:
            try:
                metadata = json.loads(item.item_metadata) if isinstance(item.item_metadata, str) else item.item_metadata

                # Check attachments (user_message)
                for attachment in metadata.get('attachments', []):
                    if attachment.get('media_id'):
                        media_ids.add(attachment['media_id'])

                # Check display_data.rows[].output.media_id (media_display)
                display_data = metadata.get('display_data', {})
                if isinstance(display_data, dict):
                    for row in display_data.get('rows', []):
                        if isinstance(row, dict):
                            output = row.get('output', {})
                            if isinstance(output, dict) and output.get('media_id'):
                                media_ids.add(output['media_id'])

                # Check media_ids in metadata
                if metadata.get('media_ids'):
                    for mid in metadata['media_ids']:
                        if isinstance(mid, int):
                            media_ids.add(mid)

                # Check single media_id in metadata
                if metadata.get('media_id'):
                    media_ids.add(metadata['media_id'])

                # Check results array (search_results, scored_results)
                for result in metadata.get('results', []):
                    if result.get('media_id'):
                        media_ids.add(result['media_id'])
            except (json.JSONDecodeError, TypeError):
                pass

    log.debug(f"[_mark_deleted_media] Found {len(media_ids)} media_ids")

    if not media_ids:
        return [ChatItemResponse(**item.to_dict()) for item in items]

    # Query which media_ids still exist
    result = await session.execute(
        select(MediaItem.id).where(MediaItem.id.in_(media_ids))
    )
    existing_ids = set(row[0] for row in result.all())
    deleted_ids = media_ids - existing_ids

    if deleted_ids:
        log.info(f"[_mark_deleted_media] Found {len(deleted_ids)} deleted media references")

    if not deleted_ids:
        return [ChatItemResponse(**item.to_dict()) for item in items]

    # Process items and mark deleted media
    processed = []
    for item in items:
        item_dict = item.to_dict()

        # Mark deleted IDs in media_ids array
        if item_dict.get('media_ids'):
            original_ids = item_dict['media_ids']
            if isinstance(original_ids, list):
                # Filter out deleted IDs
                item_dict['media_ids'] = [mid for mid in original_ids if mid not in deleted_ids]
                if len(item_dict['media_ids']) != len(original_ids):
                    log.debug(f"[_mark_deleted_media] Filtered media_ids for item {item.id}")

        # Mark deleted in item_metadata
        if item_dict.get('item_metadata'):
            metadata = item_dict['item_metadata']
            modified = False

            # Mark attachments
            for attachment in metadata.get('attachments', []):
                if attachment.get('media_id') in deleted_ids:
                    attachment['deleted'] = True
                    modified = True

            # Mark display_data.rows[].output (media_display)
            display_data = metadata.get('display_data', {})
            if isinstance(display_data, dict):
                for row in display_data.get('rows', []):
                    if isinstance(row, dict):
                        output = row.get('output', {})
                        if isinstance(output, dict) and output.get('media_id') in deleted_ids:
                            output['deleted'] = True
                            modified = True

            # Filter media_ids in metadata
            if metadata.get('media_ids') and isinstance(metadata['media_ids'], list):
                original = metadata['media_ids']
                metadata['media_ids'] = [mid for mid in original if mid not in deleted_ids]
                if len(metadata['media_ids']) != len(original):
                    modified = True

            # Mark single media_id in metadata
            if metadata.get('media_id') in deleted_ids:
                metadata['deleted'] = True
                modified = True

            # Mark results
            for result in metadata.get('results', []):
                if result.get('media_id') in deleted_ids:
                    result['deleted'] = True
                    modified = True

            if modified:
                item_dict['item_metadata'] = metadata

        processed.append(ChatItemResponse(**item_dict))

    return processed


@router.get("/{chat_id}/items", response_model=ChatItemListResponse)
async def list_chat_items(
    chat_id: int,
    limit: int = Query(50, ge=1, le=200),
    before_id: Optional[int] = Query(None),
    visible_limit: Optional[int] = Query(None, ge=1, le=500),
    session: AsyncSession = Depends(get_db_session)
):
    """
    Get chat items for a chat, with reverse pagination.

    If visible_limit is provided, keeps fetching until we have that many
    visible items (filtering out tool_call, tool_result, etc.).
    """
    # Verify chat exists
    result = await session.execute(
        select(Chat).where(Chat.id == chat_id)
    )
    chat = result.scalar_one_or_none()

    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")

    # If visible_limit is requested, we need to fetch in batches until we have enough
    if visible_limit and not before_id:
        all_items = []
        visible_count = 0
        current_before_id = None
        batch_size = 200  # Fetch in larger batches for efficiency
        max_iterations = 10  # Safety limit

        for _ in range(max_iterations):
            query = select(ChatItem).where(ChatItem.chat_id == chat_id)
            if current_before_id:
                query = query.where(ChatItem.id < current_before_id)
            query = query.order_by(desc(ChatItem.created_at)).limit(batch_size)

            result = await session.execute(query)
            batch = list(result.scalars().all())

            if not batch:
                break  # No more items

            all_items.extend(batch)
            visible_count = sum(1 for item in all_items if _is_visible_item(item))

            if visible_count >= visible_limit:
                break  # We have enough visible items

            current_before_id = batch[-1].id  # Continue from oldest in batch

            if len(batch) < batch_size:
                break  # No more items to fetch

        # Check if there are more items beyond what we fetched
        if all_items:
            oldest_id = all_items[-1].id
            count_result = await session.execute(
                select(func.count()).select_from(ChatItem).where(
                    and_(ChatItem.chat_id == chat_id, ChatItem.id < oldest_id)
                )
            )
            remaining = count_result.scalar()
            has_more = remaining > 0
        else:
            has_more = False

        # Mark deleted media in attachments before returning
        processed_items = await _mark_deleted_media_in_items(all_items, session)
        return ChatItemListResponse(
            items=processed_items,
            has_more=has_more
        )

    # Standard pagination (original behavior)
    query = select(ChatItem).where(ChatItem.chat_id == chat_id)

    if before_id:
        query = query.where(ChatItem.id < before_id)

    query = query.order_by(desc(ChatItem.created_at)).limit(limit + 1)

    result = await session.execute(query)
    items = result.scalars().all()

    # Check if there are more items
    has_more = len(items) > limit
    if has_more:
        items = items[:limit]

    # Mark deleted media in attachments before returning
    processed_items = await _mark_deleted_media_in_items(items, session)
    return ChatItemListResponse(
        items=processed_items,
        has_more=has_more
    )


@router.post("/{chat_id}/items", response_model=ChatItemResponse)
async def create_chat_item(
    chat_id: int,
    request: ChatItemCreateRequest,
    session: AsyncSession = Depends(get_db_session)
):
    """Create a new chat item."""
    # Verify chat exists
    result = await session.execute(
        select(Chat).where(Chat.id == chat_id)
    )
    chat = result.scalar_one_or_none()

    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")

    # Build item_metadata, including attachments if present
    item_metadata = request.item_metadata
    if request.item_type == "user_message" and request.attachments:
        # Store attachments in metadata for display
        metadata_dict = {}
        if item_metadata:
            try:
                metadata_dict = json.loads(item_metadata) if isinstance(item_metadata, str) else item_metadata
            except json.JSONDecodeError:
                pass
        metadata_dict["attachments"] = [a.dict() for a in request.attachments]
        item_metadata = json.dumps(metadata_dict)

    # Create chat item
    item = ChatItem(
        chat_id=chat_id,
        item_type=request.item_type,
        message_text=request.message_text,
        tool_name=request.tool_name,
        tool_call_id=request.tool_call_id,
        tool_args=request.tool_args,
        tool_result=request.tool_result,
        tool_error=request.tool_error,
        media_id=request.media_id,
        media_ids=request.media_ids,
        grid_layout=request.grid_layout,
        parent_item_id=request.parent_item_id,
        item_metadata=item_metadata
    )

    session.add(item)

    # Update chat's updated_at timestamp
    chat.updated_at = datetime.utcnow()

    await session.commit()
    await session.refresh(item)

    # Broadcast new chat item via WebSocket
    await ws_manager.broadcast("chat_item_created", {
        "chat_id": chat_id,
        "item": item.to_dict()
    })

    # Track user messages for telemetry
    if request.item_type == "user_message":
        from telemetry import get_telemetry_client
        msg_count_result = await session.execute(
            select(func.count(ChatItem.id)).where(
                and_(
                    ChatItem.chat_id == chat_id,
                    ChatItem.item_type == "user_message"
                )
            )
        )
        message_count = msg_count_result.scalar()
        from object_hash import salted_hash
        get_telemetry_client().track("chat_message_sent", {
            "chatHash": salted_hash(f"chat:{chat_id}"),
            "hasAttachments": bool(request.attachments),
            "hasSelectedMedia": bool(request.media_ids),
            "messageCount": message_count,
        }, category="chat")

    # If item_type is "user_message", trigger auto-naming and agent execution
    if request.item_type == "user_message":
        # Check user message count for auto-naming (triggers on messages 1-3)
        all_user_msgs_result = await session.execute(
            select(ChatItem.id, ChatItem.message_text).where(
                and_(
                    ChatItem.chat_id == chat_id,
                    ChatItem.item_type == "user_message"
                )
            ).order_by(ChatItem.id)
        )
        all_user_msgs = all_user_msgs_result.fetchall()
        user_msg_count = len(all_user_msgs)
        log.debug(f"Chat {chat_id}: {user_msg_count} user messages, just created item.id={item.id}")

        # Auto-name on first 3 user messages (run in background, don't block)
        log.info(f"Chat {chat_id}: user_msg_count={user_msg_count}, message_text={bool(request.message_text)}")
        has_naming_context = bool((request.message_text or "").strip()) or bool(request.selected_media_ids)
        if user_msg_count <= 3 and has_naming_context:
            log.info(f"Chat {chat_id}: Triggering auto-name for message #{user_msg_count}")
            from core.profile_context import get_current_profile
            # Collect all user message texts for context
            msg_texts = [m.message_text for m in all_user_msgs if m.message_text]
            asyncio.create_task(
                auto_name_chat(
                    chat_id,
                    request.message_text or "",
                    get_current_profile(),
                    request.selected_media_ids,
                    user_messages=msg_texts if user_msg_count > 1 else None,
                    current_name=chat.name if user_msg_count > 1 else None,
                )
            )
        elif user_msg_count > 3:
            log.info(f"Chat {chat_id}: Skipping auto-name - title is baked ({user_msg_count} user messages)")

        from telemetry import get_telemetry_client
        try:
            from config import get_settings
            _llm_role = get_settings().llms.get('agent')
            _llm_source = _llm_role.source if _llm_role else 'unknown'
        except Exception:
            _llm_source = 'unknown'
        from object_hash import salted_hash as _salted_hash
        if _llm_source not in ("stimma_cloud", "endpoint"):
            _llm_source = "unknown"  # closed enum; 'auto' resolves per-call
        get_telemetry_client().track("agent_chat_sent", {
            "chatHash": _salted_hash(f"chat:{chat_id}"),
            "llmSource": _llm_source,
        }, category="chat")

        # Run the agent in the background with its own DB session so this POST
        # returns as soon as the user message is persisted. Blocking the request
        # on the full agent turn caused clients to time out mid-turn and then
        # treat the already-sent message as failed (resurrecting attachments).
        # Agent progress reaches the UI over WebSocket. The user message above is
        # already committed and broadcast, so the background task is safe.
        from core.profile_context import get_current_profile
        log.info(f"Spawning background agent run for chat {chat_id}")
        asyncio.create_task(
            _run_agent_background(
                chat_id=chat_id,
                user_message=request.message_text,
                profile_id=get_current_profile(),
                selected_media_ids=request.selected_media_ids,
            )
        )

    return ChatItemResponse(**item.to_dict())


@router.delete("/items/{item_id}")
async def delete_chat_item(
    item_id: int,
    session: AsyncSession = Depends(get_db_session)
):
    """Delete a chat item."""
    result = await session.execute(
        select(ChatItem).where(ChatItem.id == item_id)
    )
    item = result.scalar_one_or_none()

    if not item:
        raise HTTPException(status_code=404, detail="Chat item not found")

    # If deleting a plan item, also clear the active_plan from chat settings
    # This prevents stale plans from being reused after "delete forward"
    if item.item_type == "system" and item.message_text == "Plan":
        chat_result = await session.execute(
            select(Chat).where(Chat.id == item.chat_id)
        )
        chat = chat_result.scalar_one_or_none()
        if chat and chat.generation_settings:
            try:
                settings = json.loads(chat.generation_settings)
                if "active_plan" in settings:
                    del settings["active_plan"]
                    chat.generation_settings = json.dumps(settings)
                    log.info(f"Cleared active_plan from chat {chat.id} after plan item deletion")
            except json.JSONDecodeError:
                pass

    await session.delete(item)
    await session.commit()

    return {"success": True}


@router.get("/by-item/{chat_item_id}", response_model=ChatResponse)
async def get_chat_by_item(
    chat_item_id: int,
    session: AsyncSession = Depends(get_db_session)
):
    """Get the chat that contains a specific chat item (used for 'Jump to Chat' feature)."""
    # Find the chat item
    result = await session.execute(
        select(ChatItem).where(ChatItem.id == chat_item_id)
    )
    chat_item = result.scalar_one_or_none()

    if not chat_item:
        raise HTTPException(status_code=404, detail="Chat item not found")

    # Get the associated chat
    result = await session.execute(
        select(Chat).where(Chat.id == chat_item.chat_id)
    )
    chat = result.scalar_one_or_none()

    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")

    # Check if chat is deleted
    if chat.deleted_at is not None:
        raise HTTPException(status_code=410, detail="Chat has been deleted")

    return ChatResponse(**chat.to_dict())


@router.patch("/items/{chat_item_id}/metadata")
async def update_chat_item_metadata(
    chat_item_id: int,
    metadata: dict,
    session: AsyncSession = Depends(get_db_session)
):
    """Update a chat item's metadata (used for persisting media_display updates)."""
    result = await session.execute(
        select(ChatItem).where(ChatItem.id == chat_item_id)
    )
    chat_item = result.scalar_one_or_none()

    if not chat_item:
        raise HTTPException(status_code=404, detail="Chat item not found")

    # Only allow updating media_display items
    if chat_item.item_type != "media_display":
        raise HTTPException(status_code=400, detail="Can only update media_display items")

    # Update metadata
    chat_item.item_metadata = json.dumps(metadata)
    await session.commit()

    # Broadcast update
    from utils.websocket import ws_manager
    await ws_manager.broadcast("chat_item_updated", {
        "chat_id": chat_item.chat_id,
        "item": chat_item.to_dict(),
    })

    return {"success": True}


# Human-in-the-loop response model
class HITLResponseRequest(PydanticBaseModel):
    """Request model for HITL responses."""
    # For approve/plan_approval: {"approved": true/false, "refinement": "optional text"}
    # For choose: {"selected_media_ids": [1, 2, 3]}
    # For feedback: {"item_feedback": {1: true, 2: false}}
    # For answer: {"answer": "text response"}
    # For retry: {"action": "retry" | "abort" | "refine", "refinement": "optional text"}
    # For tool_permission: {"approved": true/false, "selected_tool_id": "provider:tool-id"}
    # For natural language: {"text": "yeah do it"} - will be interpreted by LLM
    approved: Optional[bool] = None
    selected_media_ids: Optional[List[int]] = None
    item_feedback: Optional[dict] = None
    answer: Optional[str] = None
    action: Optional[str] = None  # For retry: "retry", "abort", "refine"
    refinement: Optional[str] = None  # For retry/plan_approval refinement
    text: Optional[str] = None  # Natural language input to be interpreted
    selected_tool_id: Optional[str] = None  # For tool permission: user-selected tool
    scope: Optional[str] = None  # Permission scope: 'once' | 'chat' | 'always'


async def _interpret_plan_response(text: str) -> dict:
    """
    Use LLM to interpret natural language response to a plan approval.

    Returns:
        {"approved": True} - if user approves
        {"approved": False} - if user rejects
        {"approved": False, "refinement": "..."} - if user wants changes
    """
    from llm import llm_complete_text
    from config import get_settings

    settings = get_settings()
    llm_config = settings.agent_fast_llm

    prompt = f"""The user was shown an execution plan and asked if they approve. Their response was:

"{text}"

Interpret their response and return JSON with one of these formats:
- If they approve/agree: {{"approved": true}}
- If they reject/cancel: {{"approved": false}}
- If they want changes: {{"approved": false, "refinement": "their requested changes"}}

Return ONLY the JSON, no other text."""

    try:
        result_text = await llm_complete_text(
            config=llm_config,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=200,
        )
        result_text = result_text.strip()
        # Parse JSON from response
        if result_text.startswith("```"):
            # Remove markdown code block
            lines = result_text.split("\n")
            result_text = "\n".join(lines[1:-1])

        return json.loads(result_text)
    except Exception as e:
        log.warning(f"Error interpreting plan response: {e}")
        # Default to treating as refinement if we can't parse
        return {"approved": False, "refinement": text}


@router.post("/{chat_id}/human-response")
async def submit_human_response(
    chat_id: int,
    request: HITLResponseRequest,
    session: AsyncSession = Depends(get_db_session)
):
    """
    Submit a human response to a pending HITL request.

    This endpoint is called when the user responds to an approval prompt,
    choice selection, feedback request, or question.
    """
    log.info(f"human-response endpoint called for chat {chat_id}, request: {request}")

    # Get the chat
    result = await session.execute(
        select(Chat).where(Chat.id == chat_id)
    )
    chat = result.scalar_one_or_none()

    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")

    # Find pending HITL action from most recent hitl_request chat item
    # (New architecture stores HITL in chat items, not working_context)
    hitl_result = await session.execute(
        select(ChatItem)
        .where(ChatItem.chat_id == chat_id)
        .where(ChatItem.item_type == "hitl_request")
        .order_by(ChatItem.created_at.desc())
        .limit(1)
    )
    hitl_item = hitl_result.scalar_one_or_none()

    pending_action = None
    if hitl_item and hitl_item.item_metadata:
        # Check if this HITL request already has a response
        response_result = await session.execute(
            select(ChatItem)
            .where(ChatItem.chat_id == chat_id)
            .where(ChatItem.item_type == "hitl_response")
            .where(ChatItem.created_at > hitl_item.created_at)
            .limit(1)
        )
        if response_result.scalar_one_or_none():
            # Already responded - treat as no pending action
            pass
        else:
            try:
                pending_action = json.loads(hitl_item.item_metadata) if isinstance(hitl_item.item_metadata, str) else hitl_item.item_metadata
            except json.JSONDecodeError:
                pass

    # Fall back to working_context for backward compatibility
    if not pending_action:
        context_data = {}
        if chat.generation_settings:
            try:
                settings = json.loads(chat.generation_settings)
                context_data = settings.get("working_context", {})
            except json.JSONDecodeError:
                pass
        pending_action = context_data.get("pending_human_action")

    log.debug(f"pending_action: {pending_action is not None}, type: {pending_action.get('type') if pending_action else 'none'}")
    if not pending_action:
        raise HTTPException(status_code=400, detail="No pending HITL action")

    # If natural language text provided for plan_approval, interpret it with LLM
    if request.text and pending_action.get("type") == "plan_approval":
        interpreted = await _interpret_plan_response(request.text)
        request.approved = interpreted.get("approved")
        request.refinement = interpreted.get("refinement")

    # Build response data dict
    response_data = {}
    if request.approved is not None:
        response_data["approved"] = request.approved
    if request.selected_media_ids is not None:
        response_data["selected_media_ids"] = request.selected_media_ids
    if request.item_feedback is not None:
        response_data["item_feedback"] = request.item_feedback
    if request.answer is not None:
        response_data["answer"] = request.answer
    if request.action is not None:
        response_data["action"] = request.action
    if request.refinement is not None:
        response_data["refinement"] = request.refinement
    if request.selected_tool_id is not None:
        response_data["selected_tool_id"] = request.selected_tool_id
    if request.scope is not None:
        response_data["scope"] = request.scope

    # In-process permission gate (STP tool call made from inside run_code): the turn
    # is parked on a future, NOT unwound. Resolve the future in place instead of
    # replaying the turn (replay would re-run every tool call before the gated one).
    v2_args = pending_action.get("v2_tool_args", {}) if isinstance(pending_action, dict) else {}
    inprocess_id = v2_args.get("_inprocess_request_id")
    if inprocess_id:
        from agent.v2.tool_permission_gate import is_pending_permission, resolve_pending_permission
        if is_pending_permission(inprocess_id):
            scope = request.scope or "once"
            approved = bool(request.approved)
            # Persist chat/always grants using this request's session (the parked
            # coroutine never holds a write txn across the wait).
            tool_id = v2_args.get("tool_id")
            if tool_id and scope in ("chat", "always"):
                from agent.v2.permissions import apply_stp_permission
                await apply_stp_permission(tool_id, scope, approved, chat)
                await session.commit()
            resolve_pending_permission(inprocess_id, {"approved": approved, "scope": scope})
            # Record the response so the card renders as resolved (not still actionable).
            resp_item = ChatItem(
                chat_id=chat_id,
                item_type="hitl_response",
                item_metadata=json.dumps({"approved": approved, "scope": scope}),
            )
            session.add(resp_item)
            await session.commit()
            await ws_manager.broadcast("chat_item_created", {
                "chat_id": chat_id,
                "item": resp_item.to_dict(),
            })
            return {"success": True}

    # Resume agent with the response
    log.debug(f"Calling resume_agent_after_hitl with response_data: {response_data}")
    from agent import resume_agent_after_hitl
    await resume_agent_after_hitl(
        chat=chat,
        response_data=response_data,
        session=session,
        ws_manager=ws_manager,
    )
    log.info(f"resume_agent_after_hitl completed")

    return {"success": True}


@router.post("/{chat_id}/abort")
async def abort_plan_execution(
    chat_id: int,
    session: AsyncSession = Depends(get_db_session),
):
    """
    Abort the currently running plan for a chat.
    """
    # Get chat
    result = await session.execute(select(Chat).where(Chat.id == chat_id))
    chat = result.scalar_one_or_none()

    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")

    from agent import abort_plan
    await abort_plan(
        chat=chat,
        session=session,
        ws_manager=ws_manager,
    )

    return {"success": True}


@router.post("/{chat_id}/stop")
async def stop_agent_execution(
    chat_id: int,
    session: AsyncSession = Depends(get_db_session),
):
    """
    Stop the currently running agent.

    This is a hard interrupt and does not resume/respond.
    """
    # Get chat
    result = await session.execute(select(Chat).where(Chat.id == chat_id))
    chat = result.scalar_one_or_none()

    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")

    # Abort current execution
    from agent import abort_plan
    await abort_plan(
        chat=chat,
        session=session,
        ws_manager=ws_manager,
    )

    # Create a system stop marker (hidden from normal display via metadata)
    stop_message = "The user interrupted the current operation."
    item = ChatItem(
        chat_id=chat_id,
        item_type="user_message",
        message_text=stop_message,
        item_metadata=json.dumps({"stop_event": True}),
    )
    session.add(item)
    chat.updated_at = datetime.utcnow()
    await session.commit()
    await session.refresh(item)

    # Broadcast the stop item
    await ws_manager.broadcast("chat_item_created", {
        "chat_id": chat_id,
        "item": item.to_dict()
    })

    return {"success": True}


@router.post("/{chat_id}/retry")
async def retry_after_error(
    chat_id: int,
    session: AsyncSession = Depends(get_db_session),
):
    """
    Retry the last agent turn after an error.

    Deletes the trailing error item(s) so the transient failure leaves no
    residue in the transcript, then re-runs the agent loop on the existing
    conversation (no new user message is appended).
    """
    result = await session.execute(select(Chat).where(Chat.id == chat_id))
    chat = result.scalar_one_or_none()

    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")

    from agent.v2.service import is_execution_active
    if is_execution_active(chat_id):
        raise HTTPException(status_code=409, detail="Agent is already running")

    # Delete trailing consecutive error items
    items_result = await session.execute(
        select(ChatItem)
        .where(ChatItem.chat_id == chat_id)
        .order_by(ChatItem.id.desc())
    )
    deleted_ids = []
    for item in items_result.scalars():
        if item.item_type != "error":
            break
        deleted_ids.append(item.id)
        await session.delete(item)
    if deleted_ids:
        await session.commit()
        for item_id in deleted_ids:
            await ws_manager.broadcast("chat_item_deleted", {
                "chat_id": chat_id,
                "item_id": item_id,
            })

    from core.profile_context import get_current_profile
    asyncio.create_task(
        _run_agent_background(
            chat_id=chat_id,
            user_message=None,
            profile_id=get_current_profile(),
        )
    )

    return {"success": True}


@router.get("/{chat_id}/debug-messages")
async def get_debug_messages(
    chat_id: int,
    session: AsyncSession = Depends(get_db_session),
):
    """
    Get the actual messages that would be sent to the LLM for debugging.
    Shows exactly what the model sees including system prompt with tool descriptions.
    """
    # Get chat
    result = await session.execute(select(Chat).where(Chat.id == chat_id))
    chat = result.scalar_one_or_none()

    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")

    from agent.v2.prompts import get_system_prompt
    from agent.v2.conversation import build_messages
    from agent.v2.agent_config import resolve_agent_config

    resolved_config = await resolve_agent_config(chat, session)

    system_prompt = get_system_prompt(
        additional_instructions=resolved_config.additional_instructions,
    )
    messages, _estimated = await build_messages(
        chat_id=chat_id,
        session=session,
        system_prompt=system_prompt,
    )

    # Also return the system prompt separately for easy inspection
    return {
        "messages": messages,
        "system_prompt": system_prompt,
    }


@router.get("/{chat_id}/workspace-path")
async def get_workspace_path(
    chat_id: int,
    session: AsyncSession = Depends(get_db_session),
):
    """Return the absolute path to the chat's workspace directory."""
    from agent.v2.workspace import get_workspace_dir

    result = await session.execute(select(Chat).where(Chat.id == chat_id))
    chat = result.scalar_one_or_none()
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")

    workspace = get_workspace_dir(chat_id, chat.project_id)
    workspace.mkdir(parents=True, exist_ok=True)
    return {"path": str(workspace)}


@router.get("/{chat_id}/workspace/{filename}")
async def get_workspace_file(
    chat_id: int,
    filename: str,
    session: AsyncSession = Depends(get_db_session),
):
    """Serve a file from the chat's workspace directory."""
    from fastapi.responses import FileResponse
    from agent.v2.workspace import get_workspace_dir

    # Security: reject path traversal
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")

    # Verify chat exists
    result = await session.execute(select(Chat).where(Chat.id == chat_id))
    chat = result.scalar_one_or_none()
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")

    workspace = get_workspace_dir(chat_id, chat.project_id)
    file_path = workspace / filename

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")

    # Guess content type
    import mimetypes
    content_type, _ = mimetypes.guess_type(filename)
    return FileResponse(file_path, media_type=content_type or "application/octet-stream")


async def _cleanup_stale_v2_items(
    chat_id: int,
    session: AsyncSession,
    ws_manager,
) -> bool:
    """
    Clean up stale in-progress items left behind when the server restarted
    mid-v2-execution.  Returns True if any items were cleaned up.
    """
    cleaned = False

    # 1. Find thinking items still marked "in_progress"
    result = await session.execute(
        select(ChatItem)
        .where(ChatItem.chat_id == chat_id)
        .where(ChatItem.item_type == "assistant_message")
    )
    for item in result.scalars().all():
        try:
            meta = json.loads(item.item_metadata) if item.item_metadata else {}
        except (json.JSONDecodeError, TypeError):
            meta = {}
        if meta.get("thinking_status") == "in_progress":
            item.item_metadata = json.dumps({
                "thinking_status": "failed",
                "thinking_content": "Interrupted by server restart.",
                "thinking_duration_seconds": 0,
            })
            cleaned = True

    # 2. Find orphaned tool_calls (no matching tool_result) and create
    #    interrupted results so they don't show as "running" forever.
    calls_result = await session.execute(
        select(ChatItem)
        .where(ChatItem.chat_id == chat_id)
        .where(ChatItem.item_type == "tool_call")
    )
    tool_calls = calls_result.scalars().all()

    if tool_calls:
        results_result = await session.execute(
            select(ChatItem.tool_call_id)
            .where(ChatItem.chat_id == chat_id)
            .where(ChatItem.item_type == "tool_result")
        )
        existing_result_ids = {row[0] for row in results_result.all()}

        for call_item in tool_calls:
            if call_item.tool_call_id and call_item.tool_call_id not in existing_result_ids:
                result_item = ChatItem(
                    chat_id=chat_id,
                    item_type="tool_result",
                    tool_call_id=call_item.tool_call_id,
                    tool_result=json.dumps({
                        "tool_name": call_item.tool_name or "unknown",
                        "error": "Interrupted by server restart.",
                    }),
                )
                session.add(result_item)
                cleaned = True

    if not cleaned:
        return False

    await session.commit()
    log.info(f"Cleaned up stale v2 in-progress items for chat {chat_id}")
    return True


@router.get("/{chat_id}/plan-status")
async def get_plan_status(
    chat_id: int,
    session: AsyncSession = Depends(get_db_session),
):
    """
    Get the current plan/execution status for a chat.

    Returns execution status and whether it's HITL-paused.
    """
    # Get chat
    result = await session.execute(select(Chat).where(Chat.id == chat_id))
    chat = result.scalar_one_or_none()

    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")

    from agent.v2.service import is_execution_active as v2_active
    if v2_active(chat_id):
        return {
            "has_plan": True,
            "status": "running",
            "manually_paused": False,
            "hitl_paused": False,
            "is_stale": False,
        }
    # Check if paused for HITL (permission or ask_user)
    import json as _json
    try:
        gen = _json.loads(chat.generation_settings) if isinstance(chat.generation_settings, str) else (chat.generation_settings or {})
    except (TypeError, _json.JSONDecodeError):
        gen = {}
    if gen.get("_v2_pending") or gen.get("_v2_ask_pending"):
        return {
            "has_plan": True,
            "status": "paused",
            "manually_paused": False,
            "hitl_paused": True,
            "is_stale": False,
        }

    # Not active and no HITL pending — check for stale in-progress items
    # left behind by a server restart mid-execution.
    cleaned = await _cleanup_stale_v2_items(chat_id, session, ws_manager)

    return {
        "has_plan": False,
        "status": None,
        "manually_paused": False,
        "hitl_paused": False,
        "is_stale": cleaned,  # True if we cleaned up stale items
    }


# LLM Trace endpoints for sub-agent debugging
class TraceListItem(PydanticBaseModel):
    id: int
    trace_type: str
    node_id: Optional[str]
    tool_call_id: Optional[str]
    model: Optional[str]
    created_at: str
    message_count: int
    est_tokens: int = 0  # Estimated token count (chars / 4)


class TraceDetail(PydanticBaseModel):
    id: int
    trace_type: str
    node_id: Optional[str]
    tool_call_id: Optional[str]
    messages: list
    response: Optional[str]
    model: Optional[str]
    created_at: str


@router.get("/{chat_id}/traces")
async def get_chat_traces(
    chat_id: int,
    trace_type: Optional[str] = Query(None, description="Filter by trace type: planner, prompt_craft, resolve_reference, delegate"),
    plan_id: Optional[str] = Query(None, description="Filter by plan ID to get all traces for a specific plan"),
    tool_call_id: Optional[str] = Query(None, description="Filter by tool_call_id (e.g. parent item ID for delegate traces)"),
    session: AsyncSession = Depends(get_db_session),
):
    """
    List all LLM traces for a chat.

    Returns trace metadata without full message contents (use /{trace_id} for details).
    """
    # Verify chat exists
    result = await session.execute(select(Chat).where(Chat.id == chat_id))
    chat = result.scalar_one_or_none()
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")

    # Build query
    query = select(LLMTrace).where(LLMTrace.chat_id == chat_id)
    if trace_type:
        query = query.where(LLMTrace.trace_type == trace_type)
    if plan_id:
        query = query.where(LLMTrace.plan_id == plan_id)
    if tool_call_id:
        query = query.where(LLMTrace.tool_call_id == tool_call_id)
    query = query.order_by(desc(LLMTrace.created_at))

    result = await session.execute(query)
    traces = result.scalars().all()

    log.info(f"[traces] Found {len(traces)} traces for chat {chat_id} (plan_id={plan_id}): {[(t.id, t.trace_type, t.plan_id) for t in traces]}")

    items = []
    for t in traces:
        # Parse messages to get count and estimate tokens
        try:
            messages = json.loads(t.messages) if isinstance(t.messages, str) else t.messages
            message_count = len(messages) if isinstance(messages, list) else 0
            # Estimate tokens from total character count (rough: chars / 4)
            total_chars = len(t.messages) if isinstance(t.messages, str) else 0
            est_tokens = total_chars // 4
        except (json.JSONDecodeError, TypeError):
            message_count = 0
            est_tokens = 0

        items.append(TraceListItem(
            id=t.id,
            trace_type=t.trace_type,
            node_id=t.node_id,
            tool_call_id=t.tool_call_id,
            model=t.model,
            created_at=t.created_at.isoformat() if t.created_at else "",
            message_count=message_count,
            est_tokens=est_tokens,
        ))

    return {"items": items}


@router.get("/{chat_id}/traces/{trace_id}")
async def get_trace_detail(
    chat_id: int,
    trace_id: int,
    session: AsyncSession = Depends(get_db_session),
):
    """
    Get full trace details including messages and response.
    """
    result = await session.execute(
        select(LLMTrace).where(
            and_(LLMTrace.id == trace_id, LLMTrace.chat_id == chat_id)
        )
    )
    trace = result.scalar_one_or_none()

    if not trace:
        raise HTTPException(status_code=404, detail="Trace not found")

    # Parse messages JSON
    try:
        messages = json.loads(trace.messages) if isinstance(trace.messages, str) else trace.messages
    except (json.JSONDecodeError, TypeError):
        messages = []

    return TraceDetail(
        id=trace.id,
        trace_type=trace.trace_type,
        node_id=trace.node_id,
        tool_call_id=trace.tool_call_id,
        messages=messages,
        response=trace.response,
        model=trace.model,
        created_at=trace.created_at.isoformat() if trace.created_at else "",
    )


# --- Agent Settings Endpoints ---

class ToolConfigModel(PydanticBaseModel):
    """Tool configuration for agent settings."""
    allowed_tools: List[str] = []
    denied_tools: List[str] = []
    v2_permissions: Optional[dict] = None  # v2 agent tool permissions
    enabled_stimpacks: Optional[List[str]] = None


class AgentSettingsResponse(PydanticBaseModel):
    """Response model for agent settings."""
    additional_instructions: Optional[str]
    tool_config: Optional[dict]


class AgentSettingsUpdate(PydanticBaseModel):
    """Request body for updating agent settings."""
    additional_instructions: Optional[str] = None
    tool_config: Optional[ToolConfigModel] = None


@router.get("/{chat_id}/agent-settings", response_model=AgentSettingsResponse)
async def get_agent_settings(
    chat_id: int,
    session: AsyncSession = Depends(get_db_session),
):
    """Get agent settings for a chat."""
    result = await session.execute(select(Chat).where(Chat.id == chat_id))
    chat = result.scalar_one_or_none()

    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")

    # Parse tool_config
    tool_config = None
    if chat.agent_tool_config:
        try:
            tool_config = json.loads(chat.agent_tool_config)
        except json.JSONDecodeError:
            pass

    return AgentSettingsResponse(
        additional_instructions=chat.additional_instructions,
        tool_config=tool_config,
    )


@router.put("/{chat_id}/agent-settings", response_model=AgentSettingsResponse)
async def update_agent_settings(
    chat_id: int,
    data: AgentSettingsUpdate,
    session: AsyncSession = Depends(get_db_session),
):
    """Update agent settings for a chat."""
    result = await session.execute(select(Chat).where(Chat.id == chat_id))
    chat = result.scalar_one_or_none()

    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")

    # Update fields if provided
    if data.additional_instructions is not None:
        chat.additional_instructions = data.additional_instructions
    if data.tool_config is not None:
        chat.agent_tool_config = json.dumps(data.tool_config.model_dump())

    await session.commit()

    # Broadcast settings update
    await ws_manager.broadcast("chat_agent_settings_updated", {
        "chat_id": chat_id,
        "settings": {
            "additional_instructions": chat.additional_instructions,
            "tool_config": json.loads(chat.agent_tool_config) if chat.agent_tool_config else None,
        }
    })

    return AgentSettingsResponse(
        additional_instructions=chat.additional_instructions,
        tool_config=json.loads(chat.agent_tool_config) if chat.agent_tool_config else None,
    )


@router.get("/{chat_id}/invoked-skills")
async def list_invoked_skills(
    chat_id: int,
    session: AsyncSession = Depends(get_db_session),
):
    """List skills that have been invoked in this chat.

    "stimpack_name" is the legacy metadata key from before skills were
    addressed flat — old history items still count as invoked.
    """
    result = await session.execute(
        select(ChatItem)
        .where(ChatItem.chat_id == chat_id, ChatItem.item_type == "stimpack_injection")
    )
    names = []
    for item in result.scalars():
        if item.item_metadata:
            try:
                meta = json.loads(item.item_metadata) if isinstance(item.item_metadata, str) else item.item_metadata
                name = meta.get("skill_name") or meta.get("stimpack_name")
                if name and name not in names:
                    names.append(name)
            except (json.JSONDecodeError, TypeError):
                pass
    return {"skills": names}


class InvokeSkillRequest(PydanticBaseModel):
    name: str


@router.post("/{chat_id}/invoke-skill")
async def invoke_skill_in_chat(
    chat_id: int,
    body: InvokeSkillRequest,
    session: AsyncSession = Depends(get_db_session),
):
    """Directly inject a skill into a chat's conversation context.

    Creates a stimpack_injection ChatItem without requiring an agent turn.
    Used by the frontend sidebar for manual skill activation.
    """
    chat = await session.get(Chat, chat_id)
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")

    from agent.v2.stimpacks import load_skill

    loaded = load_skill(body.name)
    if not loaded:
        raise HTTPException(status_code=404, detail=f"Skill '{body.name}' not found")
    qualified = loaded.skill.qualified_name

    # Check if already invoked
    result = await session.execute(
        select(ChatItem)
        .where(ChatItem.chat_id == chat_id, ChatItem.item_type == "stimpack_injection")
    )
    for item in result.scalars():
        if item.item_metadata:
            try:
                meta = json.loads(item.item_metadata) if isinstance(item.item_metadata, str) else item.item_metadata
                if qualified in (meta.get("skill_name"), meta.get("stimpack_name")):
                    return {"status": "already_loaded", "skill_name": qualified}
            except (json.JSONDecodeError, TypeError):
                pass

    inj_item = ChatItem(
        chat_id=chat_id,
        item_type="stimpack_injection",
        message_text=f"## Skill: {loaded.skill.display_name}\n\n{loaded.content}",
        item_metadata=json.dumps({
            "skill_name": qualified,
            "skill_display_name": loaded.skill.display_name,
        }),
    )
    session.add(inj_item)
    await session.commit()
    await ws_manager.broadcast("chat_item_created", {
        "chat_id": chat_id,
        "item": inj_item.to_dict(),
    })

    return {"status": "loaded", "skill_name": qualified, "item_id": inj_item.id}
