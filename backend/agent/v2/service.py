"""V2 agent service — agentic loop with iterative tool calling."""

import asyncio
import json
import os
import re
import shutil
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from llm import llm_completion, QuotaExceededError, ContentFilteredError, Usage, is_auto_tool_choice_unsupported_error, strip_thinking_tags
from llm_correlation import llm_correlation_context
from llm_resolver import get_effective_llm_config, get_chat_llm_config, resolve_chat_model_slug, LLMNotConfiguredError, LLMSubscriptionRequiredError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from core.logging import get_logger
from database import Chat, ChatItem, MediaItem
from utils.websocket import WebSocketManager

from .conversation import build_messages, response_reserve
from .agent_config import resolve_agent_config
from .llm_options import agent_llm_options
from ..hitl import HumanActionRequired
from .permissions import check_permission_for_call, check_stp_permission, apply_permission, apply_stp_permission
from .prompts import get_system_prompt
from .tools.bash import get_shell_runtime_name
from .tools_registry import get_tools_schema, get_tool, get_all_tools
from .tools.notepad import format_notepad_for_prompt
from .workspace import get_project_workspace, get_workspace_dir

log = get_logger(__name__)

# Track active executions to prevent concurrent runs on the same chat
_active_chat_executions: set[int] = set()
_active_chat_tasks: dict[int, asyncio.Task] = {}
_interrupt_flags: dict[int, bool] = {}

def is_execution_active(chat_id: int) -> bool:
    """Check if there's an active agent execution for this chat."""
    return chat_id in _active_chat_executions


def get_active_task(chat_id: int) -> Optional[asyncio.Task]:
    """Return the asyncio task of the active execution for this chat, if any."""
    return _active_chat_tasks.get(chat_id)


def _mark_running(chat_id: int) -> None:
    _interrupt_flags[chat_id] = False


def _mark_interrupted(chat_id: int) -> None:
    _interrupt_flags[chat_id] = True


def _clear_interrupt(chat_id: int) -> None:
    _interrupt_flags.pop(chat_id, None)


def _is_interrupted(chat_id: int) -> bool:
    return bool(_interrupt_flags.get(chat_id))


def _max_turns_for_chat(chat: Chat) -> int:
    # A turn cap exists only as a runaway-cost backstop for occasional bad
    # model behavior — it should be rare to hit, not a routine ceiling that
    # truncates legitimate multi-step work (a layout task can easily spend
    # 10-15 turns). 100 is a generous ceiling for both chat and flow work;
    # exhausting it is handled gracefully (see the for/else in the loop).
    return 100


def _track_skill_invoked(chat_id: int, skill_name: str) -> None:
    """Emit stimpack_invoked {chatHash, stimpackSource, stimpackName?}.

    The invoked unit is a skill; source/name classification runs on its owning
    pack. The name passes only for marketplace packs (catalog data, D17) — dev /
    user-authored skill names are user content and never egress.
    """
    try:
        from object_hash import salted_hash
        from telemetry import get_telemetry_client
        from .stimpacks import find_skill, telemetry_stimpack_source
        found = find_skill(skill_name)
        source = telemetry_stimpack_source(found[0] if found else None)
        props = {
            "chatHash": salted_hash(f"chat:{chat_id}"),
            "stimpackSource": source,
        }
        if source == "marketplace":
            props["stimpackName"] = skill_name
        get_telemetry_client().track("stimpack_invoked", props, category="chat")
    except Exception:
        pass


def _format_raw_error(e: BaseException) -> str:
    """Build the raw-error text shown behind the chat error 'Details' disclosure.

    Stitches together: `ClassName: str(e)` on the first line, then any upstream
    provider detail the exception carries (cloud-routed errors propagate
    `upstream_message` / `upstream_metadata` / `upstream_status` through
    QuotaExceededError and ContentFilteredError so users can troubleshoot
    without devmode). For everything else, `str(e)` alone — which for LLM
    HTTP failures already includes "HTTP <status> from <url>: <body>" from
    llm_http.py and is the most useful single string for BYOAI / LM Studio
    debugging.
    """
    parts: list[str] = [f"{type(e).__name__}: {e}"]
    upstream_status = getattr(e, "upstream_status", None)
    upstream_message = getattr(e, "upstream_message", None)
    upstream_metadata = getattr(e, "upstream_metadata", None)
    if upstream_status is not None:
        parts.append(f"\nUpstream status: {upstream_status}")
    if upstream_message:
        parts.append(f"\nUpstream message:\n{upstream_message}")
    if upstream_metadata:
        try:
            meta_str = json.dumps(upstream_metadata, indent=2, default=str)
        except Exception:
            meta_str = str(upstream_metadata)
        parts.append(f"\nUpstream metadata:\n{meta_str}")
    return "".join(parts)


class _AgentInterrupted(Exception):
    """Internal signal that the current v2 run was interrupted by the user."""


def _raise_if_interrupted(chat_id: int) -> None:
    if _is_interrupted(chat_id):
        raise _AgentInterrupted()


async def _create_thinking_item(
    chat_id: int,
    session: AsyncSession,
    ws_manager: WebSocketManager,
) -> ChatItem:
    item = ChatItem(
        chat_id=chat_id,
        item_type="assistant_message",
        message_text="",
        item_metadata=json.dumps({"thinking_status": "in_progress"}),
    )
    session.add(item)
    await session.commit()
    await ws_manager.broadcast("chat_item_created", {
        "chat_id": chat_id,
        "item": item.to_dict(),
    })
    return item


async def _finalize_thinking_item(
    item: ChatItem,
    message_text: str,
    reasoning: str | None,
    duration_seconds: float,
    session: AsyncSession,
    ws_manager: WebSocketManager,
    usage: Usage | None = None,
    model: str = "",
    elapsed_seconds: float = 0.0,
    tokens_per_second: float = 0.0,
    estimated_prompt_tokens: int = 0,
) -> None:
    item.message_text = message_text
    metadata = {
        "thinking_status": "completed",
        "thinking_content": reasoning or "",
        "thinking_duration_seconds": round(duration_seconds, 2),
    }
    if usage:
        metadata["llm_usage"] = {
            "prompt_tokens": usage.prompt_tokens,
            "completion_tokens": usage.completion_tokens,
            "total_tokens": usage.total_tokens,
            "reasoning_tokens": usage.reasoning_tokens,
            "cache_creation_input_tokens": usage.cache_creation_input_tokens,
            "cache_read_input_tokens": usage.cache_read_input_tokens,
            "model": model,
            "elapsed_seconds": round(elapsed_seconds, 2),
            "tokens_per_second": round(tokens_per_second, 1),
            "estimated_prompt_tokens": int(estimated_prompt_tokens),
        }
    item.item_metadata = json.dumps(metadata)
    await session.commit()
    await ws_manager.broadcast("chat_item_updated", {
        "chat_id": item.chat_id,
        "item": item.to_dict(),
    })


async def _fail_thinking_item(
    item: ChatItem,
    error_text: str,
    duration_seconds: float,
    session: AsyncSession,
    ws_manager: WebSocketManager,
    usage: Usage | None = None,
    model: str = "",
    elapsed_seconds: float = 0.0,
    tokens_per_second: float = 0.0,
    estimated_prompt_tokens: int = 0,
) -> None:
    metadata = {
        "thinking_status": "failed",
        "thinking_content": error_text,
        "thinking_duration_seconds": round(duration_seconds, 2),
    }
    if usage:
        metadata["llm_usage"] = {
            "prompt_tokens": usage.prompt_tokens,
            "completion_tokens": usage.completion_tokens,
            "total_tokens": usage.total_tokens,
            "reasoning_tokens": usage.reasoning_tokens,
            "cache_creation_input_tokens": usage.cache_creation_input_tokens,
            "cache_read_input_tokens": usage.cache_read_input_tokens,
            "model": model,
            "elapsed_seconds": round(elapsed_seconds, 2),
            "tokens_per_second": round(tokens_per_second, 1),
            "estimated_prompt_tokens": int(estimated_prompt_tokens),
        }
    item.item_metadata = json.dumps(metadata)
    await session.commit()
    await ws_manager.broadcast("chat_item_updated", {
        "chat_id": item.chat_id,
        "item": item.to_dict(),
    })


async def _interrupt_in_progress_thinking_items(
    chat_id: int,
    session: AsyncSession,
    ws_manager: WebSocketManager,
) -> None:
    result = await session.execute(
        select(ChatItem)
        .where(ChatItem.chat_id == chat_id)
        .where(ChatItem.item_type == "assistant_message")
    )
    interrupted_items: list[ChatItem] = []
    for item in result.scalars().all():
        try:
            metadata = json.loads(item.item_metadata) if item.item_metadata else {}
        except (json.JSONDecodeError, TypeError):
            metadata = {}
        if metadata.get("thinking_status") != "in_progress":
            continue
        item.item_metadata = json.dumps({
            "thinking_status": "failed",
            "thinking_content": "Interrupted by user.",
            "thinking_duration_seconds": 0,
        })
        interrupted_items.append(item)

    if not interrupted_items:
        return

    await session.commit()
    for item in interrupted_items:
        await session.refresh(item)
        await ws_manager.broadcast("chat_item_updated", {
            "chat_id": chat_id,
            "item": item.to_dict(),
        })


def _enrich_tool_args(fn_name: str, fn_arguments: str) -> str:
    """Add display metadata (prefixed with _) to tool_args for frontend display."""
    try:
        args = json.loads(fn_arguments) if fn_arguments else {}
    except (json.JSONDecodeError, TypeError):
        return fn_arguments

    if fn_name == "skill" and args.get("name"):
        from .stimpacks import load_skill
        loaded = load_skill(args["name"])
        if loaded and loaded.skill.display_name:
            args["_display_name"] = loaded.skill.display_name

    if fn_name == "call_tool" and args.get("tool_id"):
        from .tools.discover import get_tool_display_name
        display = get_tool_display_name(args["tool_id"])
        if display:
            args["_display_name"] = display

    if args.get("_display_name"):
        return json.dumps(args)
    return fn_arguments


def _parse_tool_args(raw_arguments: Optional[str]) -> dict:
    try:
        return json.loads(raw_arguments) if raw_arguments else {}
    except (json.JSONDecodeError, TypeError):
        return {}


def _dump_tool_args(arguments: dict) -> str:
    return json.dumps(arguments)


def _serialize_tool_result(fn_name: str, result_str: str) -> str:
    if isinstance(result_str, str) and result_str.startswith("Error"):
        return json.dumps({
            "tool_name": fn_name,
            "error": result_str,
            "error_summary": result_str,
        })
    return result_str


def _annotate_ask_sequence(
    current_args: dict,
    remaining_tool_calls: list[dict],
) -> tuple[dict, list[dict]]:
    """Add progress metadata when multiple ask_user calls occur back-to-back."""
    ask_sequence = [current_args]
    consecutive_count = 0

    for tc in remaining_tool_calls:
        if tc.get("fn_name") != "ask_user":
            break
        ask_sequence.append(_parse_tool_args(tc.get("fn_arguments")))
        consecutive_count += 1

    if len(ask_sequence) <= 1:
        return current_args, remaining_tool_calls

    question_plan = [
        str(args.get("question") or f"Question {idx}")
        for idx, args in enumerate(ask_sequence, start=1)
    ]
    total = len(ask_sequence)

    def annotate(args: dict, index: int) -> dict:
        enriched = dict(args)
        enriched.setdefault("question_index", index)
        enriched.setdefault("question_total", total)
        enriched.setdefault("question_plan", question_plan)
        return enriched

    updated_remaining = list(remaining_tool_calls)
    for offset in range(consecutive_count):
        updated = dict(updated_remaining[offset])
        updated["fn_arguments"] = _dump_tool_args(annotate(ask_sequence[offset + 1], offset + 2))
        updated_remaining[offset] = updated

    return annotate(current_args, 1), updated_remaining


async def _pause_for_ask_user(
    chat: Chat,
    session: AsyncSession,
    ws_manager: WebSocketManager,
    tool_call_id: str,
    turn: int,
    question_args: dict,
    remaining_tool_calls: Optional[list] = None,
) -> None:
    """Pause execution and create a HITL request for ask_user."""
    from ..hitl import HumanActionRequest

    question = question_args.get("question", "")
    ask_options = question_args.get("options")
    ask_questions = question_args.get("questions")

    gen_settings = {}
    if chat.generation_settings:
        try:
            gen_settings = json.loads(chat.generation_settings)
        except json.JSONDecodeError:
            pass

    pending = {
        "tool_call_id": tool_call_id,
        "turn": turn,
        "remaining_tool_calls": remaining_tool_calls or [],
    }
    gen_settings["_v2_ask_pending"] = pending
    chat.generation_settings = json.dumps(gen_settings)

    hitl_action = HumanActionRequest(
        type="ask_user",
        prompt=question,
        ask_options=ask_options,
        ask_questions=ask_questions,
        ask_question_index=question_args.get("question_index"),
        ask_question_total=question_args.get("question_total"),
        ask_question_plan=question_args.get("question_plan"),
        node_id=tool_call_id,
        tool_call_id=tool_call_id,
    )
    hitl_item = ChatItem(
        chat_id=chat.id,
        item_type="hitl_request",
        item_metadata=json.dumps(hitl_action.to_dict()),
    )
    session.add(hitl_item)
    await session.commit()
    await ws_manager.broadcast("chat_item_created", {
        "chat_id": chat.id,
        "item": hitl_item.to_dict(),
    })


async def _execute_tool_call(
    fn_name: str,
    fn_arguments: str,
    tool_call_id: str,
    chat_id: int,
    workspace_dir: str,
    project_workspace_dir: str | None,
    session: AsyncSession,
    ws_manager: WebSocketManager,
    session_media_ids: list[int] | None = None,
    chat: Optional[Chat] = None,
    call_item_id: Optional[int] = None,
    shown_media_ids: set[int] | None = None,
    enabled_stimpacks: list[str] | None = None,
    parent_turn: int = 0,
    parent_remaining: list | None = None,
    effective_model_slug: str | None = None,
    needs_continuation_out: list[bool] | None = None,
) -> str:
    """Execute a single tool call and save the result ChatItem. Returns result string.

    ``needs_continuation_out``, if provided, is a mutable list the tool can
    append ``True`` to when its result represents unresolved work the agent
    must act on (not just narrate). The loop uses this to detect stalls.
    """
    _raise_if_interrupted(chat_id)
    tool_llm_usage = None
    injected_messages: list[dict] = []
    # Dispatch is scope-aware: a flow chat must never execute an agent-only
    # tool even if one somehow made it into the model's tool_calls (stale
    # schema from a prior turn, hallucination, etc.). Returns None → falls
    # through to the "unknown tool" error path below.
    scope = "flow" if (chat is not None and chat.flow_id is not None) else "agent"
    tool = get_tool(fn_name, scope=scope)
    if tool:
        try:
            kwargs = json.loads(fn_arguments) if fn_arguments else {}
            kwargs["session_media_ids"] = session_media_ids if session_media_ids is not None else []
            if shown_media_ids is not None:
                kwargs["_shown_media_ids"] = shown_media_ids
            # Pass model slug to all tools that may call the LLM
            kwargs["_effective_model_slug"] = effective_model_slug
            # Pass parent item id, ws_manager, and loop context for delegate subagent
            if fn_name == "delegate" and call_item_id is not None:
                kwargs["_parent_item_id"] = call_item_id
                kwargs["_ws_manager"] = ws_manager
                kwargs["_parent_turn"] = parent_turn
                kwargs["_parent_remaining"] = parent_remaining or []
            # Pass enabled stimpacks so run_code can resolve stimpack lib modules
            if enabled_stimpacks:
                kwargs["_enabled_stimpacks"] = enabled_stimpacks
            # Mutable containers for tools to stash data back to us
            usage_out = {}
            kwargs["_llm_usage_out"] = usage_out
            kwargs["_injected_messages"] = injected_messages
            if needs_continuation_out is not None:
                kwargs["_needs_continuation_out"] = needs_continuation_out
            result_str = await tool.handler(
                session=session,
                chat_id=chat_id,
                workspace_dir=workspace_dir,
                project_workspace_dir=project_workspace_dir,
                project_id=chat.project_id if chat else None,
                interrupt_checker=lambda: _is_interrupted(chat_id),
                **kwargs,
            )
            # Pick up LLM usage from run_code (stashed on the mutable container)
            tool_llm_usage = usage_out.get("llm_usage")
            _raise_if_interrupted(chat_id)
        except (_AgentInterrupted, asyncio.CancelledError):
            raise
        except HumanActionRequired:
            raise
        except Exception as e:
            log.error(f"Tool {fn_name} error: {e}")
            result_str = f"Error: {e}"
    else:
        result_str = f"Error: Unknown tool '{fn_name}'"

    _raise_if_interrupted(chat_id)

    # Track media_ids produced by call_tool for lineage across tool calls
    if session_media_ids is not None and fn_name == "call_tool" and "<result media_id=" in result_str:
        match = re.search(r"<result media_id=(\d+)", result_str)
        if match:
            session_media_ids.append(int(match.group(1)))

    # Build tool_result metadata
    result_metadata_dict = {}
    if fn_name == "delegate" and call_item_id is not None:
        # Store subagent trace info for the debug modal
        try:
            delegate_args = json.loads(fn_arguments) if fn_arguments else {}
        except (json.JSONDecodeError, TypeError):
            delegate_args = {}
        result_metadata_dict["subagent_trace"] = {
            "task": delegate_args.get("task", ""),
            "specialist": delegate_args.get("specialist"),
            "context": delegate_args.get("context"),
            "parent_item_id": call_item_id,
        }
    if tool_llm_usage:
        result_metadata_dict["llm_usage"] = tool_llm_usage

    result_item = ChatItem(
        chat_id=chat_id,
        item_type="tool_result",
        tool_call_id=tool_call_id,
        tool_result=_serialize_tool_result(fn_name, result_str),
        item_metadata=json.dumps(result_metadata_dict) if result_metadata_dict else None,
    )
    session.add(result_item)
    await session.commit()
    await ws_manager.broadcast("chat_item_created", {
        "chat_id": chat_id,
        "item": result_item.to_dict(),
    })

    # Inject skill content as conversation messages (from skill tool invoke).
    # The item_type stays "stimpack_injection" so existing history renders.
    if injected_messages:
        for inj in injected_messages:
            inj_item = ChatItem(
                chat_id=chat_id,
                item_type="stimpack_injection",
                message_text=inj["content"],
                item_metadata=json.dumps({
                    "skill_name": inj.get("skill_name", ""),
                    "skill_display_name": inj.get("skill_display_name", ""),
                }),
            )
            session.add(inj_item)
            await session.commit()
            await ws_manager.broadcast("chat_item_created", {
                "chat_id": chat_id,
                "item": inj_item.to_dict(),
            })

    # Broadcast run_code LLM usage so dev mode UI updates in real-time
    if tool_llm_usage and tool_llm_usage.get("calls", 0) > 0:
        tool_elapsed = tool_llm_usage.get("elapsed_seconds", 0.0)
        tool_comp = tool_llm_usage.get("completion_tokens", 0)
        await ws_manager.broadcast("llm_usage", {
            "chat_id": chat_id,
            "prompt_tokens": tool_llm_usage["prompt_tokens"],
            "completion_tokens": tool_comp,
            "total_tokens": tool_llm_usage["total_tokens"],
            "reasoning_tokens": tool_llm_usage["reasoning_tokens"],
            "tokens_per_second": round(tool_comp / tool_elapsed, 1) if tool_elapsed > 0 else 0,
            "cumulative_llm_seconds": round(tool_elapsed, 2),
            "source": "run_code",
        })

    return result_str


def _build_tool_prompt(fn_name: str, kwargs: dict) -> str:
    """Build a human-readable permission prompt for a tool call."""
    if fn_name == "bash":
        cmd = kwargs.get("command", "")
        return f"Run {get_shell_runtime_name()} command: {cmd}"
    elif fn_name == "run_code":
        code = str(kwargs.get("code", "")).strip()
        preview = code.splitlines()[0][:80] if code else ""
        return f"Run Python code: {preview}" if preview else "Run Python code"
    elif fn_name == "browse_web":
        action = kwargs.get("action", "")
        if action == "fetch":
            url = kwargs.get("url", "")
            return f"Fetch URL: {url}"
        query = kwargs.get("query", "")
        suffix = " (images)" if action == "search_images" else ""
        return f"Search the web{suffix}: {query}"
    elif fn_name == "call_tool":
        tool_id = kwargs.get("tool_id", "")
        inputs = kwargs.get("inputs", {})
        prompt = str(inputs.get("prompt", ""))[:80]
        return f"Generate with {tool_id}: {prompt}" if prompt else f"Generate with {tool_id}"
    return f"Use tool: {fn_name}"


async def _needs_permission(
    fn_name: str,
    fn_arguments: str,
    chat: Chat,
    session: AsyncSession,
) -> bool:
    """Check if a tool call needs permission — handles both V2 gating and STP tool gating."""
    # V2 tool-level gating (bash, browse_web, run_code)
    if not await check_permission_for_call(fn_name, fn_arguments, chat, session):
        return True

    # For call_tool, also check per-STP-tool-id permission
    if fn_name == "call_tool":
        try:
            args = json.loads(fn_arguments) if fn_arguments else {}
            stp_tool_id = args.get("tool_id", "")
            if stp_tool_id and not await check_stp_permission(stp_tool_id, chat, session):
                return True
        except (json.JSONDecodeError, TypeError):
            pass

    return False


async def _pause_for_permission(
    fn_name: str,
    fn_arguments: str,
    tool_call_id: str,
    remaining_tool_calls: list,
    turn: int,
    chat: Chat,
    session: AsyncSession,
    ws_manager: WebSocketManager,
) -> None:
    """Pause execution and create a HITL request for tool permission."""
    from ..hitl import HumanActionRequest, HumanActionRequired

    chat_id = chat.id
    kwargs = json.loads(fn_arguments) if fn_arguments else {}
    kwargs["_v2_tool_name"] = fn_name

    # Add tool display name for frontend when calling an STP tool
    if fn_name == "call_tool":
        tool_id = kwargs.get("tool_id", "")
        if tool_id:
            try:
                from providers.registry import ProviderRegistry
                from .tools.call_tool import _resolve_effective_task_type
                registry = ProviderRegistry()
                pt = registry.get_tool(tool_id)
                if pt:
                    provider, descriptor = pt
                    inputs = kwargs.get("inputs", {}) or {}
                    task_type = _resolve_effective_task_type(descriptor, inputs) if isinstance(inputs, dict) else None
                    kwargs = {
                        **kwargs,
                        "_display_name": descriptor.name,
                        "_provider_name": provider.provider_name,
                        "_task_type": task_type,
                    }
            except Exception:
                pass

    # Build HITL action
    hitl_action = HumanActionRequest(
        type="v2_tool_permission",
        prompt=_build_tool_prompt(fn_name, kwargs),
        node_id=tool_call_id,
        tool_call_id=tool_call_id,
        v2_tool_args=kwargs,
    )

    # Save pending state so resume can continue the loop
    pending = {
        "tool_name": fn_name,
        "tool_call_id": tool_call_id,
        "fn_arguments": fn_arguments,
        "remaining_tool_calls": remaining_tool_calls,
        "turn": turn,
    }
    gen_settings = {}
    if chat.generation_settings:
        try:
            gen_settings = json.loads(chat.generation_settings)
        except json.JSONDecodeError:
            pass
    gen_settings["_v2_pending"] = pending
    chat.generation_settings = json.dumps(gen_settings)

    # Save HITL request ChatItem
    hitl_item = ChatItem(
        chat_id=chat_id,
        item_type="hitl_request",
        item_metadata=json.dumps(hitl_action.to_dict()),
    )
    session.add(hitl_item)
    await session.commit()

    await ws_manager.broadcast("chat_item_created", {
        "chat_id": chat_id,
        "item": hitl_item.to_dict(),
    })

    raise HumanActionRequired(hitl_action)


async def _copy_media_to_workspace(
    media_ids: List[int],
    chat_id: int,
    session: AsyncSession,
    project_id: int | None = None,
) -> List[Dict[str, Any]]:
    """Copy selected media files into the workspace.

    Returns list of dicts: [{"media_id": 123, "filename": "image.png"}, ...]
    """
    workspace = get_workspace_dir(chat_id, project_id)
    copied = []
    result = await session.execute(
        select(MediaItem.id, MediaItem.file_path).where(MediaItem.id.in_(media_ids))
    )
    for media_id, file_path in result.fetchall():
        if file_path and os.path.exists(file_path):
            filename = os.path.basename(file_path)
            dest = os.path.join(str(workspace), filename)
            try:
                source_path = Path(file_path)
                if source_path.is_dir():
                    if os.path.exists(dest):
                        shutil.rmtree(dest)
                    shutil.copytree(file_path, dest)
                else:
                    shutil.copy2(file_path, dest)
                copied.append({"media_id": media_id, "filename": filename})
            except Exception as e:
                log.warning(f"Failed to copy media {media_id} to workspace: {e}")
    return copied


async def _stamp_workspace_files_on_message(
    chat_id: int,
    workspace_files: List[Dict[str, Any]],
    session: AsyncSession,
) -> None:
    """Update the most recent user_message's metadata with workspace file info."""
    result = await session.execute(
        select(ChatItem)
        .where(ChatItem.chat_id == chat_id, ChatItem.item_type == "user_message")
        .order_by(ChatItem.created_at.desc())
        .limit(1)
    )
    item = result.scalar_one_or_none()
    if not item:
        return

    metadata = {}
    if item.item_metadata:
        try:
            metadata = json.loads(item.item_metadata) if isinstance(item.item_metadata, str) else item.item_metadata
        except (json.JSONDecodeError, TypeError):
            metadata = {}

    metadata["workspace_files"] = workspace_files
    item.item_metadata = json.dumps(metadata)
    await session.commit()


async def run_agent(
    chat: Chat,
    user_message: str,
    session: AsyncSession,
    ws_manager: WebSocketManager,
    selected_media_ids: Optional[List[int]] = None,
    max_turns: Optional[int] = None,
    force_plan: bool = False,
) -> None:
    """Run the v2 agentic loop for a chat.

    Iteratively calls the LLM, executes tool calls, and continues until
    the model produces a text response or max_turns is reached.
    """
    chat_id = chat.id
    if max_turns is None:
        max_turns = _max_turns_for_chat(chat)

    # Telemetry: one agent_turn_completed per run (user message -> outcome).
    # The loop fills the stats in (tool count, resolved LLM config, last
    # visible content for the shared refusal classifier).
    turn_started = time.monotonic()
    turn_stats: dict = {"tool_call_count": 0, "llm_config": None, "last_content": None}

    def _track_agent_turn(status: str, error_type: Optional[str] = None) -> None:
        try:
            from object_hash import salted_hash
            from telemetry import get_telemetry_client
            from telemetry_props import llm_config_fields
            props = {
                "chatHash": salted_hash(f"chat:{chat_id}"),
                **llm_config_fields(turn_stats.get("llm_config")),
                "durationMs": int((time.monotonic() - turn_started) * 1000),
                "toolCallCount": turn_stats.get("tool_call_count", 0),
                "status": status,
                "agentContext": "flow" if chat.flow_id is not None else "main",
            }
            if error_type:
                props["errorType"] = error_type
            get_telemetry_client().track("agent_turn_completed", props, category="chat")
        except Exception:
            pass

    def _track_gate_encountered(gate: str) -> None:
        try:
            from telemetry import get_telemetry_client
            get_telemetry_client().track("gate_encountered", {
                "gate": gate,
                "surface": "agent",
            }, category="account")
        except Exception:
            pass

    def _track_agent_error(error_type: str) -> None:
        try:
            from object_hash import salted_hash
            from telemetry import get_telemetry_client
            get_telemetry_client().track("agent_error", {
                "errorType": error_type,
                "chatHash": salted_hash(f"chat:{chat_id}"),
                "agentContext": "flow" if chat.flow_id is not None else "main",
            }, category="chat")
        except Exception:
            pass

    # Guard against concurrent execution. Callers serialize on the active task
    # before invoking run_agent, so this should not trip in practice — but if
    # it does, the frontend has already marked the agent as running, so a
    # silent return would leave it waiting for an agent_stopped that never
    # comes. Broadcast one so the UI recovers.
    if chat_id in _active_chat_executions:
        log.warning(f"Chat {chat_id}: Agent already running, skipping")
        await ws_manager.broadcast("agent_stopped", {"chat_id": chat_id, "reason": "already_running"})
        return
    _active_chat_executions.add(chat_id)
    _mark_running(chat_id)
    current_task = asyncio.current_task()
    if current_task:
        _active_chat_tasks[chat_id] = current_task

    # Copy any user-selected media into the workspace so the agent can access them
    if selected_media_ids:
        copied = await _copy_media_to_workspace(selected_media_ids, chat_id, session, chat.project_id)
        if copied:
            await _stamp_workspace_files_on_message(chat_id, copied, session)

    # Broadcast agent started
    await ws_manager.broadcast("agent_started", {"chat_id": chat_id})

    try:
        await _run_agentic_loop(chat, session, ws_manager, max_turns, start_turn=0, turn_stats=turn_stats)
        await ws_manager.broadcast("agent_stopped", {"chat_id": chat_id, "reason": "completed"})

        # Refusal classification (shared classifier, all agent surfaces) —
        # only the categorical label egresses.
        from refusal_detection import is_refusal
        if is_refusal(turn_stats.get("last_content")):
            _track_agent_turn("failed", error_type="refusal")
        else:
            _track_agent_turn("completed")

    except _PermissionPause:
        # Agent paused for permission — frontend will show HITL prompt
        # Don't broadcast agent_stopped; the agent is waiting, not done
        _track_agent_turn("paused_for_permission")

    except (_AgentInterrupted, asyncio.CancelledError):
        log.info(f"Chat {chat_id}: v2 agent interrupted")
        await ws_manager.broadcast("agent_stopped", {"chat_id": chat_id, "reason": "cancelled"})
        _track_agent_turn("cancelled")

    except QuotaExceededError as e:
        log.warning(f"Chat {chat_id}: Stimma Cloud quota exceeded: {e}")
        metadata = {
            "error_type": "quota_exceeded",
            "error_summary": str(e),
            "session": e.session,
            "weekly": e.weekly,
            "raw_error": _format_raw_error(e),
        }
        error_item = ChatItem(
            chat_id=chat_id,
            item_type="error",
            message_text=str(e),
            item_metadata=json.dumps(metadata),
        )
        session.add(error_item)
        await session.commit()
        await ws_manager.broadcast("chat_item_created", {
            "chat_id": chat_id,
            "item": error_item.to_dict(),
        })
        await ws_manager.broadcast("agent_stopped", {"chat_id": chat_id, "reason": "error", "error": str(e)})

        _track_agent_error("quota_exceeded")
        _track_agent_turn("quota_exceeded")
        _track_gate_encountered("quota_exhausted")

    except ContentFilteredError as e:
        log.warning(f"Chat {chat_id}: Content filtered: {e}")
        metadata = {
            "error_type": "content_filtered",
            "error_summary": str(e),
            "raw_error": _format_raw_error(e),
        }
        error_item = ChatItem(
            chat_id=chat_id,
            item_type="error",
            message_text=str(e),
            item_metadata=json.dumps(metadata),
        )
        session.add(error_item)
        await session.commit()
        await ws_manager.broadcast("chat_item_created", {
            "chat_id": chat_id,
            "item": error_item.to_dict(),
        })
        await ws_manager.broadcast("agent_stopped", {"chat_id": chat_id, "reason": "error", "error": str(e)})

        _track_agent_error("content_filtered")
        _track_agent_turn("failed", error_type="content_filtered")

    except LLMSubscriptionRequiredError as e:
        log.warning(f"Chat {chat_id}: Subscription required: {e}")
        metadata = {
            "error_type": e.code,
            "error_summary": str(e),
            "raw_error": _format_raw_error(e),
        }
        error_item = ChatItem(
            chat_id=chat_id,
            item_type="error",
            message_text=str(e),
            item_metadata=json.dumps(metadata),
        )
        session.add(error_item)
        await session.commit()
        await ws_manager.broadcast("chat_item_created", {
            "chat_id": chat_id,
            "item": error_item.to_dict(),
        })
        await ws_manager.broadcast("agent_stopped", {"chat_id": chat_id, "reason": "error", "error": str(e)})

        _track_agent_error("subscription_required")
        _track_agent_turn("failed", error_type="subscription_required")
        _track_gate_encountered("tier_required")

    except LLMNotConfiguredError as e:
        log.warning(f"Chat {chat_id}: No LLM configured: {e}")
        metadata = {
            "error_type": e.code,
            "error_summary": str(e),
            "raw_error": _format_raw_error(e),
        }
        error_item = ChatItem(
            chat_id=chat_id,
            item_type="error",
            message_text=str(e),
            item_metadata=json.dumps(metadata),
        )
        session.add(error_item)
        await session.commit()
        await ws_manager.broadcast("chat_item_created", {
            "chat_id": chat_id,
            "item": error_item.to_dict(),
        })
        await ws_manager.broadcast("agent_stopped", {"chat_id": chat_id, "reason": "error", "error": str(e)})

        _track_agent_error("llm_not_configured")
        _track_agent_turn("failed", error_type="llm_not_configured")
        _track_gate_encountered("signin_required")

    except Exception as e:
        log.error(f"V2 agent error for chat {chat_id}: {type(e).__name__}: {str(e)[:500]}")
        error_item = ChatItem(
            chat_id=chat_id,
            item_type="error",
            message_text=str(e),
            item_metadata=json.dumps({"raw_error": _format_raw_error(e)}),
        )
        session.add(error_item)
        await session.commit()
        await ws_manager.broadcast("chat_item_created", {
            "chat_id": chat_id,
            "item": error_item.to_dict(),
        })
        await ws_manager.broadcast("agent_stopped", {"chat_id": chat_id, "reason": "error", "error": str(e)})

        from telemetry_props import classify_agent_error
        _error_type = classify_agent_error(e)
        _track_agent_error(_error_type)
        _track_agent_turn("failed", error_type=_error_type)

    finally:
        _active_chat_executions.discard(chat_id)
        _active_chat_tasks.pop(chat_id, None)
        _clear_interrupt(chat_id)


class _PermissionPause(Exception):
    """Internal signal that the loop paused for a permission prompt."""
    pass


async def _run_agentic_loop(
    chat: Chat,
    session: AsyncSession,
    ws_manager: WebSocketManager,
    max_turns: int,
    start_turn: int = 0,
    pending_tool_calls: Optional[list] = None,
    session_media_ids: Optional[list[int]] = None,
    turn_stats: Optional[dict] = None,
) -> None:
    """Run the core loop inside a correlation scope.

    Each entry (fresh run or HITL resume) is one agent-loop execution: it
    mints a run id and stamps chat id + agent context so Stimma Cloud LLM
    requests made anywhere inside (main loop, run_code llm(), specialists)
    carry the mechanical X-Stimma-* correlation headers.
    """
    agent_context = "flow" if chat.flow_id is not None else "main"
    with llm_correlation_context(agent_context, chat_id=chat.id):
        await _run_agentic_loop_inner(
            chat, session, ws_manager, max_turns,
            start_turn=start_turn,
            turn_stats=turn_stats,
            pending_tool_calls=pending_tool_calls,
            session_media_ids=session_media_ids,
        )


async def _run_agentic_loop_inner(
    chat: Chat,
    session: AsyncSession,
    ws_manager: WebSocketManager,
    max_turns: int,
    start_turn: int = 0,
    pending_tool_calls: Optional[list] = None,
    session_media_ids: Optional[list[int]] = None,
    turn_stats: Optional[dict] = None,
) -> None:
    """Core agentic loop. Extracted so resume_after_hitl can re-enter.

    Args:
        pending_tool_calls: If resuming mid-turn, the remaining serialized
            tool calls to execute before calling the LLM again.
        session_media_ids: Mutable list accumulating media_ids produced by
            call_tool across tool calls, used for lineage tracking.
        turn_stats: Optional mutable dict the caller uses for the
            agent_turn_completed telemetry event (tool count, resolved LLM
            config, last visible content for refusal classification).
    """
    from ..hitl import HumanActionRequired

    chat_id = chat.id
    if turn_stats is None:
        turn_stats = {}
    workspace_dir = get_workspace_dir(chat_id, chat.project_id)
    project_workspace_dir = get_project_workspace(chat.project_id)
    if session_media_ids is None:
        session_media_ids = []
    shown_media_ids: set[int] = set()
    resolved_config = await resolve_agent_config(chat, session)

    # Resolve the effective model slug for this chat (chat -> project -> global)
    project_default_slug = None
    if chat.project_id:
        from database import Project
        from sqlalchemy import select as sa_select
        proj_result = await session.execute(
            sa_select(Project.default_model_slug).where(Project.id == chat.project_id)
        )
        project_default_slug = proj_result.scalar_one_or_none()
    from config import get_settings as _get_settings
    effective_model_slug = resolve_chat_model_slug(
        chat.model_slug, project_default_slug, _get_settings().default_model
    )

    # Build system prompt once — stimpacks and other volatile context are delivered
    # via system reminders (injected into the last user message per turn)
    from .stimpacks import list_skills
    from .system_reminders import build_skills_reminder, build_user_program_edit_reminder
    all_skills = list_skills()
    notepad_state = format_notepad_for_prompt(str(workspace_dir))
    # Flow chats get a specialized system prompt + the flow directory as
    # the workspace for program.py edits. Everything else (tools, LLM,
    # broadcast) is shared with the main agent loop.
    if chat.flow_id is not None:
        from .flow_prompt import get_flow_system_prompt
        from flow_runtime import get_flow_dir
        system_prompt = get_flow_system_prompt(
            additional_instructions=resolved_config.additional_instructions,
            global_memory=resolved_config.global_memory,
            project_memory=resolved_config.project_memory,
        )
        flow_dir = get_flow_dir(chat.flow_id)
        if flow_dir.exists():
            workspace_dir = str(flow_dir)
    else:
        system_prompt = get_system_prompt(
            additional_instructions=resolved_config.additional_instructions,
            global_memory=resolved_config.global_memory,
            project_memory=resolved_config.project_memory,
            notepad_state=notepad_state,
        )

    # Materialize the read-only .stimma/ tool catalog into the workspace so the
    # agent (and flow author) can browse tools with ls/grep/cat and call them
    # via `from stimma.tools.<task> import <tool>`. Single source of truth shared
    # with the run_code import namespace; idempotent + fingerprinted, so this is
    # a cheap no-op when the provider catalog hasn't changed.
    try:
        from .tool_fs import materialize_tool_fs
        from providers.registry import ProviderRegistry
        materialize_tool_fs(ProviderRegistry.get_instance(), workspace_dir)
    except Exception as e:
        log.warning(f"Failed to materialize .stimma/ tool catalog: {e}")

    # Track invoked skills for run_code lib modules ("stimpack_name" is the
    # legacy metadata key from before skills were addressed flat)
    _invoked_skills: set[str] = set()
    _invoked_result = await session.execute(
        select(ChatItem.item_metadata)
        .where(ChatItem.chat_id == chat_id, ChatItem.item_type == "stimpack_injection")
    )
    for (meta_str,) in _invoked_result:
        if meta_str:
            try:
                meta = json.loads(meta_str) if isinstance(meta_str, str) else meta_str
                invoked_name = meta.get("skill_name") or meta.get("stimpack_name")
                if invoked_name:
                    _invoked_skills.add(invoked_name)
            except (json.JSONDecodeError, TypeError):
                pass

    # Scope the tool surface: flow chats must not see run_code / sdk_help /
    # library, otherwise the model pulls stimma-SDK docs (agent sandbox) into
    # flow program.py edits and writes code that can't run in the flow
    # sandbox.
    tool_scope = "flow" if chat.flow_id is not None else "agent"
    tools_schema = get_tools_schema(tool_scope)
    tools_enabled = bool(tools_schema)

    # Cumulative token usage for this agent session
    cumulative_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "reasoning_tokens": 0, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}
    cumulative_llm_seconds = 0.0

    # Turn-termination state. The loop hands control back to the user only on
    # an *explicit* signal: the model calls `finish` (or ask_user / a
    # permission pause). A text-only message no longer silently ends the turn
    # once the model has started working — that's the classic narration-stall
    # ("retrying with the corrected code…" with no tool call attached) that
    # used to drop multi-step tasks on the floor.
    #
    # `any_tool_executed` goes sticky-true once the model has acted this run.
    # `consecutive_textonly` counts back-to-back text-only responses; a single
    # tool call resets it. If the model stalls (text-only with work in flight)
    # we nudge it once to continue-or-`finish`; if it stalls again immediately
    # without making progress we give up and end the turn, so a model that
    # won't comply can't spin against max_turns. `needs_continuation` is the
    # stronger per-tool signal (flow build still broken) and gets a more
    # specific nudge. The list persists across iterations so turn N's tool
    # result is still visible at turn N+1's check.
    pending_stall_nudge: str | None = None
    any_tool_executed = False
    consecutive_textonly = 0
    needs_continuation: list[bool] = []
    # Whether the user has seen anything this run — a non-empty assistant
    # message or surfaced media. Lets us catch a turn that ends (via `finish`
    # or empty narration) having shown nothing, which reasoning models do when
    # they spend the whole turn in the think block. `empty_finish_nudged` keeps
    # that recovery one-shot so a model that insists on finishing empty can't
    # spin against max_turns.
    produced_visible_output = False
    empty_finish_nudged = False

    # If resuming with pending tool calls, execute them first
    if pending_tool_calls:
        for index, tc_data in enumerate(pending_tool_calls):
            _raise_if_interrupted(chat_id)
            fn_name = tc_data["fn_name"]
            fn_arguments = tc_data["fn_arguments"]
            tool_call_id = tc_data["tool_call_id"]

            # `finish` is control flow, never a real tool — if it was batched
            # behind a permission-gated call, skip it here rather than
            # persisting a bogus tool_call/result. The loop below re-invokes
            # the model, which will call `finish` again to end cleanly.
            if fn_name == "finish":
                continue

            # Permission check (the first one was already approved, but
            # remaining calls in the same batch might need prompting too)
            if await _needs_permission(fn_name, fn_arguments, chat, session):
                remaining = pending_tool_calls[pending_tool_calls.index(tc_data):]
                remaining = remaining[1:]  # exclude current one
                try:
                    await _pause_for_permission(
                        fn_name, fn_arguments, tool_call_id,
                        remaining, start_turn, chat, session, ws_manager,
                    )
                except HumanActionRequired:
                    raise _PermissionPause()

            # Enrich tool_args with display metadata for the frontend
            enriched_args = _enrich_tool_args(fn_name, fn_arguments)

            # Save tool_call ChatItem (wasn't saved before pause)
            call_item = ChatItem(
                chat_id=chat_id,
                item_type="tool_call",
                tool_name=fn_name,
                tool_call_id=tool_call_id,
                tool_args=enriched_args,
            )
            session.add(call_item)
            await session.commit()
            await ws_manager.broadcast("chat_item_created", {
                "chat_id": chat_id,
                "item": call_item.to_dict(),
            })

            if fn_name == "ask_user":
                ask_args = _parse_tool_args(fn_arguments)
                ask_args, updated_remaining = _annotate_ask_sequence(
                    ask_args,
                    pending_tool_calls[index + 1:],
                )
                await _pause_for_ask_user(
                    chat=chat,
                    session=session,
                    ws_manager=ws_manager,
                    tool_call_id=tool_call_id,
                    turn=start_turn,
                    question_args=ask_args,
                    remaining_tool_calls=updated_remaining,
                )
                return

            _raise_if_interrupted(chat_id)
            turn_stats["tool_call_count"] = turn_stats.get("tool_call_count", 0) + 1
            await _execute_tool_call(
                fn_name, fn_arguments, tool_call_id,
                chat_id, workspace_dir, str(project_workspace_dir) if project_workspace_dir else None, session, ws_manager,
                session_media_ids=session_media_ids,
                chat=chat,
                call_item_id=call_item.id,
                shown_media_ids=shown_media_ids,
                enabled_stimpacks=list(_invoked_skills) if _invoked_skills else None,
                effective_model_slug=effective_model_slug,
            )
            # Track newly invoked skills
            if fn_name == "skill":
                try:
                    skill_args = json.loads(fn_arguments) if fn_arguments else {}
                    if skill_args.get("action") == "invoke" and skill_args.get("name"):
                        _invoked_skills.add(skill_args["name"])
                        _track_skill_invoked(chat_id, skill_args["name"])
                except (json.JSONDecodeError, TypeError):
                    pass

    for turn in range(start_turn, max_turns):
        _raise_if_interrupted(chat_id)
        # Build messages from chat history with system reminders
        system_reminders = []
        # Each skill declares which environments it's eligible for
        # (`environments:` frontmatter); the reminder only advertises skills
        # opted into this surface. Flow chats historically got none — skills
        # authored for chat polluted trivial flow builds — so flow eligibility
        # is strict opt-in per skill, and eligibility still isn't activation:
        # the invoke judgment stays with the agent.
        skills_environment = "flow" if chat.flow_id is not None else "chat"
        skills_reminder = build_skills_reminder(
            all_skills, _invoked_skills, environment=skills_environment
        )
        if skills_reminder:
            system_reminders.append(skills_reminder)
        if pending_stall_nudge:
            system_reminders.append(pending_stall_nudge)
            pending_stall_nudge = None
        if chat.flow_id is not None:
            program_edit_reminder = build_user_program_edit_reminder(chat.flow_id)
            if program_edit_reminder:
                system_reminders.append(program_edit_reminder)

        # Resolve LLM config first so build_messages knows the window size and
        # we don't leave a dangling "thinking.." if no model is configured.
        llm_config = await get_chat_llm_config(effective_model_slug, role='agent')
        turn_stats["llm_config"] = llm_config

        messages, estimated_prompt_tokens = await build_messages(
            chat_id, session, system_prompt,
            system_reminders=system_reminders,
            max_context_tokens=llm_config.max_context_tokens,
        )

        thinking_item = await _create_thinking_item(chat_id, session, ws_manager)
        llm_started_at = time.monotonic()

        tools = tools_schema if tools_enabled and tools_schema else None
        max_response_tokens = response_reserve(llm_config.max_context_tokens)

        try:
            resp = await llm_completion(
                llm_config, messages,
                tools=tools,
                cacheable=True,
                max_tokens=max_response_tokens,
                session_id=f"chat-{chat_id}",
                **agent_llm_options(enable_thinking=True),
            )
        except Exception as e:
            if tools_enabled and is_auto_tool_choice_unsupported_error(e):
                log.error(
                    f"Chat {chat_id}: vLLM rejected tool calling. "
                    f"Server needs --enable-auto-tool-choice --tool-call-parser <parser>. "
                    f"Falling back to text-only mode for this session."
                )
                tools_enabled = False
                continue
            await _fail_thinking_item(
                thinking_item,
                f"LLM error: {type(e).__name__}: {e}",
                time.monotonic() - llm_started_at,
                session,
                ws_manager,
            )
            raise

        content = resp.content
        reasoning = resp.thinking
        if content and content.strip():
            produced_visible_output = True
            turn_stats["last_content"] = content

        # Accumulate token usage for this session
        cumulative_usage["prompt_tokens"] += resp.usage.prompt_tokens
        cumulative_usage["completion_tokens"] += resp.usage.completion_tokens
        cumulative_usage["total_tokens"] += resp.usage.total_tokens
        cumulative_usage["reasoning_tokens"] += resp.usage.reasoning_tokens
        cumulative_usage["cache_creation_input_tokens"] += resp.usage.cache_creation_input_tokens
        cumulative_usage["cache_read_input_tokens"] += resp.usage.cache_read_input_tokens
        cumulative_llm_seconds += resp.elapsed_seconds

        if reasoning:
            await _finalize_thinking_item(
                thinking_item,
                content,
                reasoning,
                time.monotonic() - llm_started_at,
                session,
                ws_manager,
                usage=Usage(**cumulative_usage),
                model=resp.model,
                elapsed_seconds=cumulative_llm_seconds,
                tokens_per_second=resp.tokens_per_second,
                estimated_prompt_tokens=estimated_prompt_tokens,
            )
        else:
            # No thinking content — remove the thinking item so no empty
            # "Thought for Xs" block appears in the UI.
            await session.delete(thinking_item)
            await session.commit()
            await ws_manager.broadcast("chat_item_deleted", {
                "chat_id": chat_id,
                "item_id": thinking_item.id,
            })
            # If the LLM returned text content without reasoning, we still
            # need a message item for it.
            if content:
                # Store cumulative usage for the entire agent loop (not just this call),
                # so the session bar correctly totals all tokens across tool-call turns.
                usage_metadata = {
                    "llm_usage": {
                        "prompt_tokens": cumulative_usage["prompt_tokens"],
                        "completion_tokens": cumulative_usage["completion_tokens"],
                        "total_tokens": cumulative_usage["total_tokens"],
                        "reasoning_tokens": cumulative_usage["reasoning_tokens"],
                        "cache_creation_input_tokens": cumulative_usage["cache_creation_input_tokens"],
                        "cache_read_input_tokens": cumulative_usage["cache_read_input_tokens"],
                        "model": resp.model,
                        "elapsed_seconds": round(cumulative_llm_seconds, 2),
                        "tokens_per_second": round(resp.tokens_per_second, 1),
                        "estimated_prompt_tokens": int(estimated_prompt_tokens),
                    }
                }
                text_item = ChatItem(
                    chat_id=chat_id,
                    item_type="assistant_message",
                    message_text=content,
                    item_metadata=json.dumps(usage_metadata),
                )
                session.add(text_item)
                await session.commit()
                await ws_manager.broadcast("chat_item_created", {
                    "chat_id": chat_id,
                    "item": text_item.to_dict(),
                })

        # Broadcast cumulative usage for dev mode UI
        usage_broadcast = {
            "chat_id": chat_id,
            "prompt_tokens": cumulative_usage["prompt_tokens"],
            "completion_tokens": cumulative_usage["completion_tokens"],
            "total_tokens": cumulative_usage["total_tokens"],
            "reasoning_tokens": cumulative_usage["reasoning_tokens"],
            "cache_creation_input_tokens": cumulative_usage["cache_creation_input_tokens"],
            "cache_read_input_tokens": cumulative_usage["cache_read_input_tokens"],
            "context_tokens": resp.usage.prompt_tokens + resp.usage.cache_creation_input_tokens + resp.usage.cache_read_input_tokens,
            "model": resp.model,
            "tokens_per_second": round(resp.tokens_per_second, 1),  # this call
            "cumulative_llm_seconds": round(cumulative_llm_seconds, 2),
        }
        if resp.quota:
            usage_broadcast["quota"] = {
                "session_percent": resp.quota.session_percent,
                "weekly_percent": resp.quota.weekly_percent,
            }
        await ws_manager.broadcast("llm_usage", usage_broadcast)
        tool_calls = resp.tool_calls or None
        log.info(
            f"Chat {chat_id} turn {turn}: "
            f"reasoning={'yes (' + str(len(reasoning)) + ' chars)' if reasoning else 'none'}, "
            f"content={content[:150]!r}, "
            f"tool_calls={len(tool_calls) if tool_calls else 0}"
        )

        # Check for tool calls
        if tool_calls and tools_schema:
            # LLM is acting on its own — any stale continuation signal from
            # the prior turn is now superseded by the new tool batch. Clear
            # it so only the new batch's flags drive the stall check.
            needs_continuation.clear()
            finish_requested = False
            for i, tool_call in enumerate(tool_calls):
                _raise_if_interrupted(chat_id)
                fn_name = tool_call.name
                fn_arguments = tool_call.arguments
                tool_call_id = tool_call.id or f"call_{uuid.uuid4().hex[:12]}"

                # `finish` is the explicit end-of-turn signal — pure control
                # flow. Don't persist a tool_call item for it (an unmatched
                # tool_call would corrupt the next turn's reconstructed
                # history) and don't execute it. The model's assistant message
                # is its closing remark; finish just ends the loop. Any tool
                # calls the model batched *before* finish have already run
                # above; anything after it is intentionally dropped.
                if fn_name == "finish":
                    finish_requested = True
                    break

                remaining = []
                for tc in tool_calls[i + 1:]:
                    remaining.append({
                        "fn_name": tc.name,
                        "fn_arguments": tc.arguments,
                        "tool_call_id": tc.id or f"call_{uuid.uuid4().hex[:12]}",
                    })

                # Permission check before execution
                if await _needs_permission(fn_name, fn_arguments or "", chat, session):
                    try:
                        await _pause_for_permission(
                            fn_name, fn_arguments, tool_call_id,
                            remaining, turn, chat, session, ws_manager,
                        )
                    except HumanActionRequired:
                        raise _PermissionPause()

                # Save tool_call ChatItem
                call_item = ChatItem(
                    chat_id=chat_id,
                    item_type="tool_call",
                    tool_name=fn_name,
                    tool_call_id=tool_call_id,
                    tool_args=_enrich_tool_args(fn_name, fn_arguments),
                )
                session.add(call_item)
                await session.commit()
                await ws_manager.broadcast("chat_item_created", {
                    "chat_id": chat_id,
                    "item": call_item.to_dict(),
                })

                # ask_user: pause with HITL prompt instead of executing the tool.
                # The tool_result (with the user's answer) is saved on resume.
                if fn_name == "ask_user":
                    ask_args = _parse_tool_args(fn_arguments)
                    ask_args, updated_remaining = _annotate_ask_sequence(ask_args, remaining)
                    await _pause_for_ask_user(
                        chat=chat,
                        session=session,
                        ws_manager=ws_manager,
                        tool_call_id=tool_call_id,
                        turn=turn,
                        question_args=ask_args,
                        remaining_tool_calls=updated_remaining,
                    )
                    return

                # Execute tool
                _raise_if_interrupted(chat_id)
                turn_stats["tool_call_count"] = turn_stats.get("tool_call_count", 0) + 1
                try:
                    await _execute_tool_call(
                        fn_name, fn_arguments, tool_call_id,
                        chat_id, workspace_dir, str(project_workspace_dir) if project_workspace_dir else None, session, ws_manager,
                        session_media_ids=session_media_ids,
                        chat=chat,
                        call_item_id=call_item.id,
                        shown_media_ids=shown_media_ids,
                        enabled_stimpacks=list(_invoked_skills) if _invoked_skills else None,
                        parent_turn=turn,
                        parent_remaining=remaining,
                        effective_model_slug=effective_model_slug,
                        needs_continuation_out=needs_continuation,
                    )
                except HumanActionRequired:
                    # Delegate subagent paused for permission — propagate as _PermissionPause
                    raise _PermissionPause()

                # Track newly invoked skills for run_code lib modules
                if fn_name == "skill":
                    try:
                        skill_args = json.loads(fn_arguments) if fn_arguments else {}
                        if skill_args.get("action") == "invoke" and skill_args.get("name"):
                            _invoked_skills.add(skill_args["name"])
                            _track_skill_invoked(chat_id, skill_args["name"])
                    except (json.JSONDecodeError, TypeError):
                        pass

            # The model invoked `finish` — explicit end of turn. `finish` is
            # pure control flow; the assistant's message is its closing remark.
            # But if the model finishes having surfaced nothing this run — no
            # message and no shown media — the turn produced zero visible
            # output (common when a reasoning model empties the whole turn into
            # the think block, e.g. greets in its reasoning then just finishes).
            # Nudge once for a real reply before accepting the finish; the empty
            # assistant item is dropped from history (conversation.py), so the
            # retry is a clean re-sample.
            if finish_requested:
                visible = produced_visible_output or bool(shown_media_ids)
                if not visible and not empty_finish_nudged:
                    empty_finish_nudged = True
                    pending_stall_nudge = (
                        "<system-reminder>\n"
                        "You called `finish` but haven't sent the user any message or shown any result, "
                        "so they would see nothing. Reply with a brief message now, then finish.\n"
                        "</system-reminder>"
                    )
                    continue
                break

            # A tool ran: the model is working and has made progress, so any
            # prior narration-stall streak is cleared.
            any_tool_executed = True
            consecutive_textonly = 0
            # Continue loop for next LLM call
            continue

        # Text response with no tool call. This is only a real end-of-turn if
        # the model produced a visible reply and hasn't started working yet (a
        # plain conversational answer). Two cases are NOT valid ends and get one
        # nudge before we give up, so the model can neither stall silently nor
        # spin:
        #   - narration stall: it already acted, then ended on a message with no
        #     `finish` (it was supposed to keep going or call `finish`).
        #   - empty turn: no visible message AND no tool call. Some reasoning
        #     models spend the whole turn inside the think block and emit no
        #     post-think content, so the user would see nothing. The empty
        #     assistant item is dropped from history (see conversation.py), so
        #     the retry is a clean re-sample, not a turn conditioned on silence.
        _raise_if_interrupted(chat_id)
        consecutive_textonly += 1
        empty_turn = not (content and content.strip())
        work_in_flight = bool(needs_continuation) or any_tool_executed
        if (work_in_flight or empty_turn) and consecutive_textonly < 2:
            if needs_continuation:
                # Stronger signal: a tool reported unresolved work (e.g. the
                # flow build is still broken). Point the model straight at it.
                needs_continuation.clear()
                pending_stall_nudge = (
                    "<system-reminder>\n"
                    "Your last tool call reported unresolved work (the flow build is still broken). "
                    "Continue with the tool call that fixes it — do not end on a narration-only message. "
                    "Call `finish` only once the work is actually done.\n"
                    "</system-reminder>"
                )
            elif empty_turn:
                pending_stall_nudge = (
                    "<system-reminder>\n"
                    "Your last turn produced no message and no tool call, so nothing was sent to the user. "
                    "Reply with a message now, or make the appropriate tool call if there is work to do. "
                    "Call `finish` only once you are genuinely done.\n"
                    "</system-reminder>"
                )
            else:
                pending_stall_nudge = (
                    "<system-reminder>\n"
                    "Your last message did not hand control back — that takes an explicit `finish` call. "
                    "If the task is still in progress, continue with the next tool call. "
                    "If you're done (or are waiting on the user), just call `finish` now — silently, with no new message, "
                    "since the message you already sent speaks for itself. `finish` is invisible to the user, so don't announce that you're finishing.\n"
                    "</system-reminder>"
                )
            continue
        break
    else:
        # Every allowed turn ran without the model ending its own turn (no
        # `finish`, no text-only completion, no stall give-up — all of which
        # `break`). That's the runaway-cost backstop firing. Emit an honest
        # hand-off instead of stopping silently mid-task, which reads as the
        # agent giving up.
        log.warning(
            f"Chat {chat_id}: reached max_turns ({max_turns}) without finishing — emitting graceful hand-off"
        )
        limit_item = ChatItem(
            chat_id=chat_id,
            item_type="assistant_message",
            message_text=(
                f"I reached my step limit ({max_turns} actions) before wrapping this up, "
                "so I've paused here rather than run on indefinitely. Tell me to keep going "
                "and I'll pick up from where I left off."
            ),
            item_metadata=json.dumps({"max_turns_reached": True}),
        )
        session.add(limit_item)
        await session.commit()
        await ws_manager.broadcast("chat_item_created", {
            "chat_id": chat_id,
            "item": limit_item.to_dict(),
        })


async def _resume_delegate_after_permission(
    pending: dict,
    delegate_state: dict,
    chat: Chat,
    session: AsyncSession,
    ws_manager: WebSocketManager,
    workspace_dir: str,
) -> None:
    """Resume a delegate subagent after a tool permission was approved inside it."""
    from .tools.delegate import _run_delegate_loop

    chat_id = chat.id
    _raise_if_interrupted(chat_id)

    # Reconstruct the pending tool call for the delegate loop to execute
    resume_pending_tool = {
        "id": pending["tool_call_id"],
        "type": "function",
        "function": {
            "name": pending["tool_name"],
            "arguments": pending["fn_arguments"],
        },
    }

    # Resolve model slug for this chat
    _project_default = None
    if chat.project_id:
        from database import Project
        from sqlalchemy import select as sa_select
        _proj_r = await session.execute(
            sa_select(Project.default_model_slug).where(Project.id == chat.project_id)
        )
        _project_default = _proj_r.scalar_one_or_none()
    from config import get_settings as _get_settings
    _eff_slug = resolve_chat_model_slug(
        chat.model_slug, _project_default, _get_settings().default_model
    )

    # Resume the delegate loop from saved state
    session_media_ids = delegate_state.get("session_media_ids", [])
    result, _usage = await _run_delegate_loop(
        task=delegate_state.get("task", ""),
        context=delegate_state.get("context"),
        specialist=delegate_state.get("specialist"),
        max_turns=delegate_state.get("max_turns", 20),
        session=session,
        chat_id=chat_id,
        workspace_dir=workspace_dir,
        project_workspace_dir=str(get_project_workspace(chat.project_id)) if chat.project_id else None,
        interrupt_checker=lambda: _is_interrupted(chat_id),
        session_media_ids=session_media_ids,
        parent_item_id=delegate_state.get("parent_item_id"),
        ws_manager=ws_manager,
        chat=chat,
        parent_turn=delegate_state.get("parent_turn", 0),
        parent_remaining=delegate_state.get("parent_remaining", []),
        effective_model_slug=_eff_slug,
        # Resume-specific params
        resume_messages=delegate_state.get("messages"),
        resume_from_turn=delegate_state.get("delegate_turn", 0),
        resume_pending_tool=resume_pending_tool,
        resume_remaining_tools=delegate_state.get("remaining_tools", []),
        resume_created_media_ids=delegate_state.get("created_media_ids", []),
    )

    # Save the delegate result as a tool_result ChatItem (the delegate call itself)
    parent_item_id = delegate_state.get("parent_item_id")
    if parent_item_id:
        result_item = ChatItem(
            chat_id=chat_id,
            item_type="tool_result",
            tool_call_id=f"delegate_{parent_item_id}",
            tool_result=result if isinstance(result, str) else str(result),
            parent_item_id=None,  # top-level result for the delegate call
        )
        session.add(result_item)
        await session.commit()
        await ws_manager.broadcast("chat_item_created", {
            "chat_id": chat_id,
            "item": result_item.to_dict(),
        })

    # Continue the parent agentic loop
    await _run_agentic_loop(
        chat, session, ws_manager,
        max_turns=_max_turns_for_chat(chat),
        start_turn=delegate_state.get("parent_turn", 0),
        pending_tool_calls=delegate_state.get("parent_remaining", []),
        session_media_ids=session_media_ids,
    )


async def resume_after_hitl(
    chat: Chat,
    response_data: Dict[str, Any],
    session: AsyncSession,
    ws_manager: WebSocketManager,
) -> None:
    """Resume v2 agent after a permission HITL response."""
    from ..hitl import parse_human_response, ToolPermissionResponse

    chat_id = chat.id
    await session.refresh(chat)

    # Parse the response
    response = parse_human_response("v2_tool_permission", response_data)
    if not isinstance(response, ToolPermissionResponse):
        log.error(f"Unexpected response type for v2_tool_permission: {type(response)}")
        return

    # Load pending state
    gen_settings = {}
    if chat.generation_settings:
        try:
            gen_settings = json.loads(chat.generation_settings)
        except json.JSONDecodeError:
            pass

    pending = gen_settings.pop("_v2_pending", None)
    if not pending:
        log.warning(f"Chat {chat_id}: No _v2_pending state for resume")
        return

    # Save HITL response ChatItem
    response_item = ChatItem(
        chat_id=chat_id,
        item_type="hitl_response",
        item_metadata=json.dumps(response_data),
    )
    session.add(response_item)
    await session.commit()
    await ws_manager.broadcast("chat_item_created", {
        "chat_id": chat_id,
        "item": response_item.to_dict(),
    })

    # Clear pending state
    chat.generation_settings = json.dumps(gen_settings)

    # Apply permission — for call_tool, use per-STP-tool-id gating
    scope = response.scope or "chat"
    if pending["tool_name"] == "call_tool":
        try:
            args = json.loads(pending["fn_arguments"]) if pending.get("fn_arguments") else {}
            stp_tool_id = args.get("tool_id", "")
        except (json.JSONDecodeError, TypeError):
            stp_tool_id = ""
        if stp_tool_id:
            await apply_stp_permission(stp_tool_id, scope, response.approved, chat)
        else:
            await apply_permission(pending["tool_name"], scope, response.approved, chat)
    else:
        await apply_permission(pending["tool_name"], scope, response.approved, chat)
    await session.commit()
    await session.refresh(chat)

    # Broadcast settings update so the permissions panel reflects the change
    if scope in ("chat", "always"):
        tool_config = {}
        if chat.agent_tool_config:
            try:
                tool_config = json.loads(chat.agent_tool_config)
            except json.JSONDecodeError:
                pass
        await ws_manager.broadcast("chat_agent_settings_updated", {
            "chat_id": chat_id,
            "settings": {
                "tool_config": tool_config,
            },
        })

    if not response.approved:
        # Denied — stop the agent and let the user decide what to do next
        await ws_manager.broadcast("agent_stopped", {"chat_id": chat_id, "reason": "completed"})
        return

    # Approved — resume the agentic loop
    _active_chat_executions.add(chat_id)
    _mark_running(chat_id)
    current_task = asyncio.current_task()
    if current_task:
        _active_chat_tasks[chat_id] = current_task
    await ws_manager.broadcast("agent_started", {"chat_id": chat_id})

    try:
        _raise_if_interrupted(chat_id)
        workspace_dir = get_workspace_dir(chat_id, chat.project_id)
        project_workspace_dir = get_project_workspace(chat.project_id)

        # Resolve model slug for this chat
        _project_default_slug = None
        if chat.project_id:
            from database import Project
            from sqlalchemy import select as sa_select
            _proj_result = await session.execute(
                sa_select(Project.default_model_slug).where(Project.id == chat.project_id)
            )
            _project_default_slug = _proj_result.scalar_one_or_none()
        from config import get_settings as _get_settings
        _effective_model_slug = resolve_chat_model_slug(
            chat.model_slug, _project_default_slug, _get_settings().default_model
        )

        delegate_state = pending.get("delegate_state")

        if delegate_state:
            # Resuming a delegate subagent — the tool needing permission was inside a delegate loop
            await _resume_delegate_after_permission(
                pending, delegate_state, chat, session, ws_manager, workspace_dir,
            )
        else:
            # Normal (non-delegate) resume
            tool_call_id = pending["tool_call_id"]

            # Save the tool_call item (wasn't saved before pause)
            call_item = ChatItem(
                chat_id=chat_id,
                item_type="tool_call",
                tool_name=pending["tool_name"],
                tool_call_id=tool_call_id,
                tool_args=_enrich_tool_args(pending["tool_name"], pending["fn_arguments"]),
            )
            session.add(call_item)
            await session.commit()
            await ws_manager.broadcast("chat_item_created", {
                "chat_id": chat_id,
                "item": call_item.to_dict(),
            })

            _raise_if_interrupted(chat_id)
            session_media_ids: list[int] = []
            shown_media_ids: set[int] = set()

            # Resolve invoked skills from conversation history for run_code lib
            # modules ("stimpack_name" is the legacy metadata key)
            _resume_result = await session.execute(
                select(ChatItem.item_metadata)
                .where(ChatItem.chat_id == chat_id, ChatItem.item_type == "stimpack_injection")
            )
            enabled_stimpacks: list[str] = []
            for (meta_str,) in _resume_result:
                if meta_str:
                    try:
                        meta = json.loads(meta_str) if isinstance(meta_str, str) else meta_str
                        invoked_name = meta.get("skill_name") or meta.get("stimpack_name")
                        if invoked_name and invoked_name not in enabled_stimpacks:
                            enabled_stimpacks.append(invoked_name)
                    except (json.JSONDecodeError, TypeError):
                        pass

            await _execute_tool_call(
                pending["tool_name"], pending["fn_arguments"], tool_call_id,
                chat_id, workspace_dir, str(project_workspace_dir) if project_workspace_dir else None, session, ws_manager,
                session_media_ids=session_media_ids,
                chat=chat,
                call_item_id=call_item.id,
                shown_media_ids=shown_media_ids,
                enabled_stimpacks=enabled_stimpacks or None,
                effective_model_slug=_effective_model_slug,
            )

            # Continue with remaining tool calls from the same batch, then loop
            await _run_agentic_loop(
                chat, session, ws_manager,
                max_turns=_max_turns_for_chat(chat),
                start_turn=pending.get("turn", 0),
                pending_tool_calls=pending.get("remaining_tool_calls"),
                session_media_ids=session_media_ids,
            )

        await ws_manager.broadcast("agent_stopped", {"chat_id": chat_id, "reason": "completed"})

    except _PermissionPause:
        # Paused again for another permission
        pass

    except (_AgentInterrupted, asyncio.CancelledError):
        log.info(f"Chat {chat_id}: v2 resume interrupted")
        await ws_manager.broadcast("agent_stopped", {"chat_id": chat_id, "reason": "cancelled"})

    except Exception as e:
        log.error(f"V2 agent resume error for chat {chat_id}: {type(e).__name__}: {str(e)[:500]}")
        error_item = ChatItem(
            chat_id=chat_id,
            item_type="error",
            message_text=str(e),
        )
        session.add(error_item)
        await session.commit()
        await ws_manager.broadcast("chat_item_created", {
            "chat_id": chat_id,
            "item": error_item.to_dict(),
        })
        await ws_manager.broadcast("agent_stopped", {"chat_id": chat_id, "reason": "error", "error": str(e)})

    finally:
        _active_chat_executions.discard(chat_id)
        _active_chat_tasks.pop(chat_id, None)
        _clear_interrupt(chat_id)


async def resume_after_ask_user(
    chat: Chat,
    response_data: Dict[str, Any],
    session: AsyncSession,
    ws_manager: WebSocketManager,
) -> None:
    """Resume v2 agent after the user answers an ask_user prompt."""
    chat_id = chat.id
    await session.refresh(chat)

    # Handle case where frontend sends a plain string instead of a dict
    if isinstance(response_data, str):
        response_data = {"answer": response_data}
    answer = response_data.get("answer", "")

    # Load and clear pending state
    gen_settings = {}
    if chat.generation_settings:
        try:
            gen_settings = json.loads(chat.generation_settings)
        except json.JSONDecodeError:
            pass

    pending = gen_settings.pop("_v2_ask_pending", None)
    if not pending:
        log.warning(f"Chat {chat_id}: No _v2_ask_pending state for resume")
        return

    # Save HITL response ChatItem
    response_item = ChatItem(
        chat_id=chat_id,
        item_type="hitl_response",
        item_metadata=json.dumps(response_data),
    )
    session.add(response_item)

    # Save tool_result ChatItem so the LLM sees the user's answer
    result_item = ChatItem(
        chat_id=chat_id,
        item_type="tool_result",
        tool_call_id=pending["tool_call_id"],
        tool_result=answer,
    )
    session.add(result_item)

    # Clear pending state
    chat.generation_settings = json.dumps(gen_settings)
    await session.commit()

    await ws_manager.broadcast("chat_item_created", {
        "chat_id": chat_id,
        "item": response_item.to_dict(),
    })
    await ws_manager.broadcast("chat_item_created", {
        "chat_id": chat_id,
        "item": result_item.to_dict(),
    })

    # Re-enter the agentic loop
    _active_chat_executions.add(chat_id)
    _mark_running(chat_id)
    current_task = asyncio.current_task()
    if current_task:
        _active_chat_tasks[chat_id] = current_task
    await ws_manager.broadcast("agent_started", {"chat_id": chat_id})

    try:
        await _run_agentic_loop(
            chat, session, ws_manager,
            max_turns=_max_turns_for_chat(chat),
            start_turn=pending.get("turn", 0) + 1,
        )
        await ws_manager.broadcast("agent_stopped", {"chat_id": chat_id, "reason": "completed"})

    except _PermissionPause:
        pass

    except (_AgentInterrupted, asyncio.CancelledError):
        log.info(f"Chat {chat_id}: v2 resume after ask_user interrupted")
        await ws_manager.broadcast("agent_stopped", {"chat_id": chat_id, "reason": "cancelled"})

    except Exception as e:
        log.error(f"V2 agent resume_after_ask_user error for chat {chat_id}: {type(e).__name__}: {str(e)[:500]}")
        error_item = ChatItem(
            chat_id=chat_id,
            item_type="error",
            message_text=str(e),
        )
        session.add(error_item)
        await session.commit()
        await ws_manager.broadcast("chat_item_created", {
            "chat_id": chat_id,
            "item": error_item.to_dict(),
        })
        await ws_manager.broadcast("agent_stopped", {"chat_id": chat_id, "reason": "error", "error": str(e)})

    finally:
        _active_chat_executions.discard(chat_id)
        _active_chat_tasks.pop(chat_id, None)
        _clear_interrupt(chat_id)


async def interrupt_execution(
    chat: Chat,
    session: AsyncSession,
    ws_manager: WebSocketManager,
) -> bool:
    """Interrupt an active v2 execution immediately."""
    chat_id = chat.id

    was_active = chat_id in _active_chat_executions
    _mark_interrupted(chat_id)
    _active_chat_executions.discard(chat_id)

    task = _active_chat_tasks.get(chat_id)
    if task and not task.done():
        task.cancel()

    await _interrupt_in_progress_thinking_items(chat_id, session, ws_manager)

    # Best-effort provider stop for in-flight STP operations/queues.
    try:
        from providers.registry import ProviderRegistry
        await ProviderRegistry.get_instance().interrupt_and_clear_all()
    except Exception as e:
        log.warning(f"Chat {chat_id}: failed provider interrupt on v2 cancel: {e}")

    # Clear any pending v2 HITL continuation state.
    # If there was a pending permission prompt, create a denial response so the
    # UI permanently shows it as resolved.
    gen_settings = {}
    created_hitl_responses: list[ChatItem] = []
    if chat.generation_settings:
        try:
            gen_settings = json.loads(chat.generation_settings)
        except json.JSONDecodeError:
            pass
    needs_commit = False
    if "_v2_pending" in gen_settings:
        gen_settings.pop("_v2_pending", None)
        chat.generation_settings = json.dumps(gen_settings)

        # Save a hitl_response item so the prompt shows as denied on reload
        denial_item = ChatItem(
            chat_id=chat_id,
            item_type="hitl_response",
            item_metadata=json.dumps({"approved": False, "scope": "once"}),
        )
        session.add(denial_item)
        created_hitl_responses.append(denial_item)
        needs_commit = True

    if "_v2_ask_pending" in gen_settings:
        gen_settings.pop("_v2_ask_pending", None)
        chat.generation_settings = json.dumps(gen_settings)

        # Save a hitl_response so the ask_user prompt shows as interrupted
        dismiss_item = ChatItem(
            chat_id=chat_id,
            item_type="hitl_response",
            item_metadata=json.dumps({"answer": "", "interrupted": True}),
        )
        session.add(dismiss_item)
        created_hitl_responses.append(dismiss_item)
        needs_commit = True

    if needs_commit:
        await session.commit()
        for item in created_hitl_responses:
            await session.refresh(item)
            await ws_manager.broadcast("chat_item_created", {
                "chat_id": chat_id,
                "item": item.to_dict(),
            })

    await ws_manager.broadcast("agent_stopped", {"chat_id": chat_id, "reason": "cancelled"})
    return was_active
