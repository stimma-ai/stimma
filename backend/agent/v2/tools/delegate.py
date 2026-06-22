"""Delegate tool — spawn a subagent for bulk or isolated work."""

import asyncio
import json
import os
import re
import time
import uuid
from pathlib import Path
from typing import Optional

from llm import llm_completion, Usage, FinishReason
from llm_correlation import llm_correlation_context
from llm_resolver import get_effective_llm_config, get_chat_llm_config
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..tools_registry import tool, ToolParameter, get_all_tools
from ..prompts import get_system_prompt
from ..conversation import response_reserve
from ..llm_options import agent_llm_options

from core.logging import get_logger
from database import Chat, ChatItem, LLMTrace
from utils.websocket import WebSocketManager
from ..permissions import check_permission_for_call, check_stp_permission
from ...hitl import HumanActionRequest, HumanActionRequired

log = get_logger(__name__)

_SPECIALISTS_DIR = Path(__file__).parent.parent / "specialists"


def _load_specialist(name: str) -> Optional[str]:
    """Load a specialist prompt from the specialists/ directory."""
    # Sanitize: only allow simple names (no path traversal)
    if not re.match(r"^[a-z0-9_-]+$", name):
        return None
    path = _SPECIALISTS_DIR / f"{name}.md"
    if not path.is_file():
        return None
    return path.read_text(encoding="utf-8").strip()

# Tools excluded from subagent — no recursion, no user interaction, no display
# (show is excluded so the parent agent controls what gets displayed)
_EXCLUDED_TOOLS = {"delegate", "ask_user", "show"}


def _get_delegate_tools_schema() -> list[dict]:
    """Get tool schemas for the subagent, excluding delegate and ask_user."""
    tools = get_all_tools()
    return [
        t.to_openai_schema()
        for name, t in tools.items()
        if name not in _EXCLUDED_TOOLS
    ]


@tool(
    name="delegate",
    description="Spawn a subagent for bulk or isolated work. The subagent shares your workspace and tools (except delegate, ask_user, and show) and returns a summary when done. The subagent's response will contain media_ids — pass them to show(media_ids=[...]) to display results to the user.",
    parameters=[
        ToolParameter(
            name="task",
            type="string",
            description="Instruction for the subagent — what it should accomplish",
            required=True,
        ),
        ToolParameter(
            name="context",
            type="string",
            description="Extra context appended to the subagent's system prompt",
            required=False,
        ),
        ToolParameter(
            name="specialist",
            type="string",
            description="Name of a specialist profile to load (e.g. 'layout-design'). Adds domain-specific expertise to the subagent's prompt.",
            required=False,
        ),
        ToolParameter(
            name="max_turns",
            type="integer",
            description="Maximum number of LLM turns for the subagent (default 20, max 30)",
            required=False,
        ),
    ],
)
async def delegate_tool(
    task: str,
    context: str | None = None,
    specialist: str | None = None,
    max_turns: int | None = None,
    **kwargs,
) -> str:
    session: AsyncSession = kwargs.get("session")
    chat_id: int = kwargs.get("chat_id")
    workspace_dir: str = kwargs.get("workspace_dir")
    project_workspace_dir: str | None = kwargs.get("project_workspace_dir")
    interrupt_checker = kwargs.get("interrupt_checker", lambda: False)
    session_media_ids: list[int] = kwargs.get("session_media_ids", [])
    parent_item_id: int | None = kwargs.get("_parent_item_id")
    ws_manager: WebSocketManager | None = kwargs.get("_ws_manager")
    parent_turn: int = kwargs.get("_parent_turn", 0)
    parent_remaining: list = kwargs.get("_parent_remaining", [])
    effective_model_slug: str | None = kwargs.get("_effective_model_slug")

    if not session or not chat_id or not workspace_dir:
        return "Error: Missing required context (session, chat_id, or workspace_dir)"

    # Load chat for permission checks
    chat = await session.get(Chat, chat_id)

    effective_max_turns = min(max_turns or 20, 30)

    turn_started = time.monotonic()

    async def _track_delegate_turn(status: str, tool_call_count: int, error_type: str | None = None):
        try:
            from object_hash import salted_hash
            from telemetry import get_telemetry_client
            from telemetry_props import llm_config_fields
            try:
                llm_config = await get_chat_llm_config(effective_model_slug, role='agent')
            except Exception:
                llm_config = None
            props = {
                "chatHash": salted_hash(f"chat:{chat_id}"),
                **llm_config_fields(llm_config),
                "durationMs": int((time.monotonic() - turn_started) * 1000),
                "toolCallCount": tool_call_count,
                "status": status,
                "agentContext": "delegate",
            }
            if error_type:
                props["errorType"] = error_type
            get_telemetry_client().track("agent_turn_completed", props, category="chat")
        except Exception:
            pass

    try:
        result, usage = await _run_delegate_loop(
            task=task,
            context=context,
            specialist=specialist,
            max_turns=effective_max_turns,
            session=session,
            chat_id=chat_id,
            workspace_dir=workspace_dir,
            project_workspace_dir=project_workspace_dir,
            interrupt_checker=interrupt_checker,
            session_media_ids=session_media_ids,
            parent_item_id=parent_item_id,
            ws_manager=ws_manager,
            chat=chat,
            parent_turn=parent_turn,
            parent_remaining=parent_remaining,
            effective_model_slug=effective_model_slug,
        )
        # Refusal classification (shared classifier, all agent surfaces):
        # only the categorical label egresses.
        from refusal_detection import is_refusal
        tool_count = usage.get("tool_call_count", 0) if isinstance(usage, dict) else 0
        if is_refusal(result):
            await _track_delegate_turn("failed", tool_count, error_type="refusal")
        else:
            await _track_delegate_turn("completed", tool_count)
        return result
    except (asyncio.CancelledError, HumanActionRequired):
        raise
    except Exception as e:
        log.error(f"Delegate error in chat {chat_id}: {type(e).__name__}: {e}")
        from telemetry_props import classify_agent_error
        await _track_delegate_turn("failed", 0, error_type=classify_agent_error(e))
        return f"Subagent error: {type(e).__name__}: {e}"


async def _get_workspace_context(
    session: AsyncSession,
    chat_id: int,
    workspace_dir: str,
) -> str:
    """Build workspace context string so subagent knows what files are available.

    Pulls media info from the most recent user_message's workspace_files metadata
    and lists actual files in the workspace directory.
    """
    parts = []

    # 1. Get workspace_files metadata from the most recent user_message
    result = await session.execute(
        select(ChatItem)
        .where(ChatItem.chat_id == chat_id, ChatItem.item_type == "user_message")
        .order_by(ChatItem.created_at.desc())
        .limit(1)
    )
    user_msg = result.scalar_one_or_none()
    if user_msg and user_msg.item_metadata:
        try:
            metadata = json.loads(user_msg.item_metadata) if isinstance(user_msg.item_metadata, str) else user_msg.item_metadata
        except (json.JSONDecodeError, TypeError):
            metadata = {}
        workspace_files = metadata.get("workspace_files")
        if workspace_files:
            file_list = ", ".join(
                f'{f["filename"]} (media_id={f["media_id"]})'
                for f in workspace_files
            )
            parts.append(f"User attached files: {file_list}. Use view_image to see them, or media_id for call_tool input_images.")

    # 2. List actual files in the workspace directory
    try:
        ws_path = Path(workspace_dir)
        if ws_path.is_dir():
            files = [f.name for f in ws_path.iterdir() if f.is_file()]
            if files:
                parts.append(f"Files in workspace directory: {', '.join(sorted(files))}")
    except OSError:
        pass

    return "\n".join(parts)


async def _broadcast_child_item(
    item: ChatItem,
    ws_manager: Optional[WebSocketManager],
    chat_id: int,
) -> None:
    """Broadcast a child ChatItem if ws_manager is available."""
    if ws_manager:
        await ws_manager.broadcast("chat_item_created", {
            "chat_id": chat_id,
            "item": item.to_dict(),
        })


async def _delegate_needs_permission(
    fn_name: str,
    fn_arguments: str,
    chat: Chat,
    session: AsyncSession,
) -> bool:
    """Check if a tool call needs permission — mirrors _needs_permission from service.py."""
    if not await check_permission_for_call(fn_name, fn_arguments, chat, session):
        return True
    if fn_name == "call_tool":
        try:
            args = json.loads(fn_arguments) if fn_arguments else {}
            stp_tool_id = args.get("tool_id", "")
            if stp_tool_id and not await check_stp_permission(stp_tool_id, chat, session):
                return True
        except (json.JSONDecodeError, TypeError):
            pass
    return False


def _build_delegate_tool_prompt(fn_name: str, fn_arguments: str) -> str:
    """Build a human-readable permission prompt for a delegate tool call."""
    kwargs = json.loads(fn_arguments) if fn_arguments else {}
    if fn_name == "call_tool":
        tool_id = kwargs.get("tool_id", "")
        inputs = kwargs.get("inputs", {})
        prompt = str(inputs.get("prompt", ""))[:80] if isinstance(inputs, dict) else ""
        return f"Generate with {tool_id}: {prompt}" if prompt else f"Generate with {tool_id}"
    elif fn_name == "bash":
        cmd = kwargs.get("command", "")
        return f"Run shell command: {cmd}"
    elif fn_name == "run_code":
        code = str(kwargs.get("code", "")).strip()
        preview = code.splitlines()[0][:80] if code else ""
        return f"Run Python code: {preview}" if preview else "Run Python code"
    elif fn_name == "browse_web":
        action = kwargs.get("action", "")
        if action == "fetch":
            return f"Fetch URL: {kwargs.get('url', '')}"
        query = kwargs.get("query", "")
        return f"Search the web: {query}"
    return f"Use tool: {fn_name}"


async def _pause_delegate_for_permission(
    fn_name: str,
    fn_arguments: str,
    tool_call_id: str,
    chat: Chat,
    session: AsyncSession,
    ws_manager: WebSocketManager,
    delegate_state: dict,
) -> None:
    """Pause the delegate for a permission prompt, saving delegate state for resume."""
    chat_id = chat.id
    kwargs = json.loads(fn_arguments) if fn_arguments else {}
    kwargs["_v2_tool_name"] = fn_name

    # Add tool display name for frontend when calling an STP tool
    if fn_name == "call_tool":
        tool_id = kwargs.get("tool_id", "")
        if tool_id:
            try:
                from providers.registry import ProviderRegistry
                from .call_tool import _resolve_effective_task_type
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

    hitl_action = HumanActionRequest(
        type="v2_tool_permission",
        prompt=_build_delegate_tool_prompt(fn_name, fn_arguments),
        node_id=tool_call_id,
        tool_call_id=tool_call_id,
        v2_tool_args=kwargs,
    )

    # Save pending state with delegate context so resume can continue the delegate loop
    pending = {
        "tool_name": fn_name,
        "tool_call_id": tool_call_id,
        "fn_arguments": fn_arguments,
        "turn": delegate_state.get("parent_turn", 0),
        "remaining_tool_calls": delegate_state.get("parent_remaining", []),
        "delegate_state": delegate_state,
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

    if ws_manager:
        await ws_manager.broadcast("chat_item_created", {
            "chat_id": chat_id,
            "item": hitl_item.to_dict(),
        })

    raise HumanActionRequired(hitl_action)


async def _run_delegate_loop(**kwargs) -> tuple[str, dict]:
    """Run the delegate loop inside its own correlation scope.

    One delegate execution = one run id; nested LLM calls carry the
    `delegate` agent context on Stimma Cloud requests. Both call sites
    (delegate_tool and the HITL resume path) pass keyword args only.
    """
    with llm_correlation_context("delegate", chat_id=kwargs.get("chat_id")):
        return await _run_delegate_loop_inner(**kwargs)


async def _run_delegate_loop_inner(
    task: str,
    context: str | None,
    specialist: str | None,
    max_turns: int,
    session: AsyncSession,
    chat_id: int,
    workspace_dir: str,
    project_workspace_dir: str | None,
    interrupt_checker,
    session_media_ids: list[int],
    parent_item_id: int | None = None,
    ws_manager: WebSocketManager | None = None,
    chat: Chat | None = None,
    parent_turn: int = 0,
    parent_remaining: list | None = None,
    effective_model_slug: str | None = None,
    # Resume support: if provided, skip LLM calls and start from saved state
    resume_messages: list | None = None,
    resume_from_turn: int = 0,
    resume_pending_tool: dict | None = None,
    resume_remaining_tools: list | None = None,
    resume_created_media_ids: list[int] | None = None,
) -> tuple[str, dict]:
    """Run an ephemeral agentic loop with DB-persisted child items for UI visibility.

    Returns (result_text, cumulative_usage_dict).
    """

    # Build system prompt with optional specialist and context
    system_prompt = get_system_prompt()
    if specialist:
        specialist_content = _load_specialist(specialist)
        if specialist_content:
            system_prompt += f"\n\n## Specialist: {specialist}\n\n{specialist_content}"
        else:
            log.warning(f"Specialist '{specialist}' not found, continuing without it")
    if context:
        system_prompt += f"\n\n## Delegation Context\n\n{context}"

    # Gather workspace context so the subagent knows what files are available
    workspace_context = await _get_workspace_context(session, chat_id, workspace_dir)
    if workspace_context:
        system_prompt += f"\n\n## Workspace Files\n\n{workspace_context}"

    # Resume or fresh start
    if resume_messages is not None:
        messages = resume_messages
    else:
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": task},
        ]

    tools_schema = _get_delegate_tools_schema()
    all_tools = get_all_tools()

    last_text = ""
    persist = parent_item_id is not None and ws_manager is not None
    created_media_ids: list[int] = resume_created_media_ids[:] if resume_created_media_ids else []

    # Cumulative token usage for this delegation
    cumulative_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "reasoning_tokens": 0}
    cumulative_llm_seconds = 0.0

    start_turn = resume_from_turn if resume_messages is not None else 0

    for turn in range(start_turn, max_turns):
        # Check interrupt
        if interrupt_checker():
            return (last_text or "Subagent was interrupted."), cumulative_usage

        # On resume, skip the LLM call for the first turn and execute the pending tool
        if turn == start_turn and resume_pending_tool is not None:
            tool_calls_data = [resume_pending_tool] + (resume_remaining_tools or [])
            # Messages already contain the assistant message with tool_calls from before pause
        else:
            # Call LLM (using per-chat model selection)
            llm_started_at = time.monotonic()
            llm_config = await get_chat_llm_config(effective_model_slug, role='agent')
            tools = tools_schema if tools_schema else None
            resp = await llm_completion(
                llm_config, messages, tools=tools, cacheable=True,
                max_tokens=response_reserve(llm_config.max_context_tokens),
                **agent_llm_options(enable_thinking=True),
            )
            llm_duration = time.monotonic() - llm_started_at

            content = resp.content
            reasoning = resp.thinking

            # Accumulate token usage
            cumulative_usage["prompt_tokens"] += resp.usage.prompt_tokens
            cumulative_usage["completion_tokens"] += resp.usage.completion_tokens
            cumulative_usage["total_tokens"] += resp.usage.total_tokens
            cumulative_usage["reasoning_tokens"] += resp.usage.reasoning_tokens
            cumulative_llm_seconds += resp.elapsed_seconds
            cumulative_usage["elapsed_seconds"] = round(cumulative_llm_seconds, 2)

            if content:
                last_text = content

            # Persist LLM trace for debug visibility
            if persist:
                llm_trace = LLMTrace(
                    chat_id=chat_id,
                    trace_type="delegate",
                    tool_call_id=str(parent_item_id),
                    messages=json.dumps(messages),
                    response=content or "",
                    model=resp.model,
                )
                session.add(llm_trace)
                await session.commit()

            # Persist thinking/reasoning as a child ChatItem
            if persist and reasoning:
                thinking_metadata = {
                    "thinking_status": "completed",
                    "thinking_content": reasoning,
                    "thinking_duration_seconds": round(llm_duration, 2),
                    "llm_usage": {
                        "prompt_tokens": resp.usage.prompt_tokens,
                        "completion_tokens": resp.usage.completion_tokens,
                        "total_tokens": resp.usage.total_tokens,
                        "reasoning_tokens": resp.usage.reasoning_tokens,
                        "model": resp.model,
                        "elapsed_seconds": round(resp.elapsed_seconds, 2),
                        "tokens_per_second": round(resp.tokens_per_second, 1),
                    },
                }
                thinking_item = ChatItem(
                    chat_id=chat_id,
                    item_type="assistant_message",
                    message_text=content or "",
                    parent_item_id=parent_item_id,
                    item_metadata=json.dumps(thinking_metadata),
                )
                session.add(thinking_item)
                await session.commit()
                await _broadcast_child_item(thinking_item, ws_manager, chat_id)

            # Broadcast cumulative delegate usage
            if ws_manager:
                await ws_manager.broadcast("llm_usage", {
                    "chat_id": chat_id,
                    "prompt_tokens": cumulative_usage["prompt_tokens"],
                    "completion_tokens": cumulative_usage["completion_tokens"],
                    "total_tokens": cumulative_usage["total_tokens"],
                    "reasoning_tokens": cumulative_usage["reasoning_tokens"],
                    "model": resp.model,
                    "tokens_per_second": round(resp.tokens_per_second, 1),
                    "cumulative_llm_seconds": round(cumulative_llm_seconds, 2),
                    "source": "delegate",
                })

            # Warn if generation was truncated (max_tokens hit)
            if resp.finish_reason == FinishReason.LENGTH:
                log.warning(f"Delegate LLM response truncated (finish_reason=length) in chat {chat_id}, turn {turn}. Tool calls may be incomplete.")

            # No tool calls — done
            if not resp.tool_calls:
                break

            # Build assistant message for history
            assistant_msg: dict = {"role": "assistant", "content": content or None}
            tool_calls_data = []
            for tc in resp.tool_calls:
                tool_calls_data.append({
                    "id": tc.id or f"call_{uuid.uuid4().hex[:12]}",
                    "type": "function",
                    "function": {
                        "name": tc.name,
                        "arguments": tc.arguments or "{}",
                    },
                })
            assistant_msg["tool_calls"] = tool_calls_data
            messages.append(assistant_msg)

        # Execute each tool call
        for i, tc_data in enumerate(tool_calls_data):
            if interrupt_checker():
                return (last_text or "Subagent was interrupted."), cumulative_usage

            fn_name = tc_data["function"]["name"]
            fn_arguments = tc_data["function"]["arguments"]
            tool_call_id = tc_data["id"]

            # Permission check — pause for HITL if tool is not authorized
            if chat and await _delegate_needs_permission(fn_name, fn_arguments, chat, session):
                remaining_tools = tool_calls_data[i + 1:]
                delegate_state = {
                    "messages": messages,
                    "specialist": specialist,
                    "max_turns": max_turns,
                    "delegate_turn": turn,
                    "session_media_ids": session_media_ids,
                    "created_media_ids": created_media_ids,
                    "parent_item_id": parent_item_id,
                    "remaining_tools": remaining_tools,
                    "parent_turn": parent_turn,
                    "parent_remaining": parent_remaining or [],
                    "task": task,
                    "context": context,
                }
                await _pause_delegate_for_permission(
                    fn_name, fn_arguments, tool_call_id,
                    chat, session, ws_manager, delegate_state,
                )
                # _pause_delegate_for_permission always raises HumanActionRequired

            # Persist tool_call as a child ChatItem
            if persist:
                call_item = ChatItem(
                    chat_id=chat_id,
                    item_type="tool_call",
                    tool_name=fn_name,
                    tool_call_id=tool_call_id,
                    tool_args=fn_arguments,
                    parent_item_id=parent_item_id,
                )
                session.add(call_item)
                await session.commit()
                await _broadcast_child_item(call_item, ws_manager, chat_id)

            # Safety: skip excluded tools even if LLM hallucinates them
            if fn_name in _EXCLUDED_TOOLS:
                if fn_name == "show":
                    result_str = "Error: show is not available in delegation mode. The parent agent will call show() with the media_ids from your create_layout results."
                else:
                    result_str = f"Error: Tool '{fn_name}' is not available in delegation mode."
            else:
                tool_def = all_tools.get(fn_name)
                if tool_def:
                    cumulative_usage["tool_call_count"] = cumulative_usage.get("tool_call_count", 0) + 1
                    try:
                        kwargs = json.loads(fn_arguments) if fn_arguments else {}
                        kwargs["session_media_ids"] = session_media_ids
                        result_str = await tool_def.handler(
                            session=session,
                            chat_id=chat_id,
                            workspace_dir=workspace_dir,
                            project_workspace_dir=project_workspace_dir,
                            project_id=chat.project_id if chat else None,
                            interrupt_checker=interrupt_checker,
                            **kwargs,
                        )
                    except asyncio.CancelledError:
                        raise
                    except Exception as e:
                        log.error(f"Delegate tool {fn_name} error: {e}")
                        result_str = f"Error: {e}"
                else:
                    result_str = f"Error: Unknown tool '{fn_name}'"

            # Track media_ids for lineage
            if fn_name == "call_tool" and isinstance(result_str, str) and "<result media_id=" in result_str:
                match = re.search(r"<result media_id=(\d+)", result_str)
                if match:
                    session_media_ids.append(int(match.group(1)))

            # Track create_layout media_ids so the parent can show() them
            if fn_name == "create_layout" and isinstance(result_str, str):
                try:
                    parsed = json.loads(result_str)
                    if isinstance(parsed, dict) and "media_id" in parsed:
                        created_media_ids.append(parsed["media_id"])
                except (json.JSONDecodeError, TypeError):
                    pass

            result_content = result_str if isinstance(result_str, str) else str(result_str)

            # Persist tool_result as a child ChatItem
            if persist:
                result_item = ChatItem(
                    chat_id=chat_id,
                    item_type="tool_result",
                    tool_call_id=tool_call_id,
                    tool_result=result_content,
                    parent_item_id=parent_item_id,
                )
                session.add(result_item)
                await session.commit()
                await _broadcast_child_item(result_item, ws_manager, chat_id)

            messages.append({
                "role": "tool",
                "tool_call_id": tool_call_id,
                "content": result_content,
            })

    result_text = last_text or "Subagent completed without producing a final response."

    # Append created media_ids so the parent can show() them reliably
    if created_media_ids:
        ids_str = ", ".join(str(mid) for mid in created_media_ids)
        result_text += f"\n\nCreated media_ids: [{ids_str}]"

    return result_text, cumulative_usage
