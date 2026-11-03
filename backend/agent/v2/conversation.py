"""V2 conversation builder — maps ChatItems to LLM messages."""

import base64
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import ChatItem
from core.logging import get_logger
from .vision_payload import encode_agent_jpeg

log = get_logger(__name__)

# Context compression settings
STALE_TURN_THRESHOLD = 3       # Tool results older than this many user turns get compressed
TRUNCATION_MIN_CHARS = 500     # Only compress tool results larger than this
RECENT_TURNS_TO_KEEP = 5       # User turns to preserve in token-budget backstop
MAX_ACTIVE_VIEW_IMAGES = 4     # Hard multimodal budget; older images stay tool-retrievable
COMPACTION_PCT = 0.80          # Fraction of the context window we're willing to fill
# A long run from one user message has no user turns to age out, so the settings
# below apply context pressure by step instead.
RUN_KEEP_RECENT_RESULTS = 8    # Newest tool results a run keeps verbatim under pressure
RUN_COMPRESSION_TRIGGER = 0.85 # Fraction of the history budget where compression starts
RUN_COMPRESSION_TARGET = 0.60  # Fraction of the history budget compression aims to reach
RUN_PRESSURE_CHUNK = 4         # Work in budget/N chunks, so the cached prefix rarely moves
RUN_COMPRESSION_EXEMPT_TOOLS = {"ask_user", "skill"}  # Human answers and loaded instructions


def response_reserve(max_context_tokens: int) -> int:
    """Tokens held back from the prompt budget for the model's own output.

    Scales with the window (10%) and clamps to [2k, 8k]: small local windows
    (32k) still have room for history, and huge windows don't waste reserve
    on an output that rarely exceeds a few thousand tokens in agent usage.
    """
    return max(2_048, min(8_192, max_context_tokens // 10))


def max_output_tokens(max_context_tokens: int, model_output_limit: int | None = None) -> int:
    """Allow larger tool arguments when the window has spare output room.

    Keep the prompt reserve independent: its 80% budget already leaves enough
    headroom for 16k output on windows of 128k or larger. Respect a known
    model output cap, including caps smaller than the prompt reserve.
    """
    allowance = 16_384 if max_context_tokens >= 128_000 else response_reserve(max_context_tokens)
    return min(allowance, model_output_limit) if model_output_limit else allowance


def compute_history_budget(max_context_tokens: int, system_tokens: int, overhead_tokens: int = 0) -> int:
    """Estimated-token budget for history + images after reserving system and response.

    overhead_tokens covers prompt content that isn't in the messages list —
    principally the tools schema (function definitions), which the provider
    counts as input. On 128k windows it's noise; on a 32k local model the
    agent's ~8k tool schema is a quarter of the window and ignoring it
    overflows the context.
    """
    return int(max_context_tokens * COMPACTION_PCT) - system_tokens - overhead_tokens - response_reserve(max_context_tokens)


async def build_messages(
    chat_id: int,
    session: AsyncSession,
    system_prompt: str,
    system_reminders: List[str] | None = None,
    max_context_tokens: int = 128_000,
    overhead_tokens: int = 0,
) -> tuple[List[Dict[str, Any]], int]:
    """Build LLM messages from chat history.

    Queries ChatItems ordered by created_at and maps them to OpenAI message format.
    Skips item types that don't map to conversation (generated_media, media_grid, etc.).
    Applies context compression to keep token usage within the window.

    Compression is persisted to the database so that the message prefix is stable
    across consecutive turns — this is critical for prompt caching (both Anthropic
    explicit cache_control and OpenAI automatic prefix caching).

    system_reminders: Runtime context persisted as new messages at the tail when
    it changes. User timestamps are persisted once, so replay leaves the prefix
    unchanged until context pressure requires compression or trimming.
    Wrap each reminder in <system-reminder> tags before passing.

    max_context_tokens: Advertised window for the target model. Used to derive the
    compaction threshold (80% of window minus response reserve and system prompt).

    Returns (messages, estimated_prompt_tokens). The estimate covers the whole
    prompt including overhead_tokens and is deliberately uncorrected: it's what
    the next turn compares to the provider's actual count to learn the per-chat
    correction factor applied to the budget here.
    """
    result = await session.execute(
        select(ChatItem)
        .where(ChatItem.chat_id == chat_id, ChatItem.parent_item_id.is_(None))
        .order_by(ChatItem.created_at.asc(), ChatItem.id.asc())
    )
    items = list(result.scalars().all())
    await _persist_prompt_context(chat_id, items, session, system_reminders or [])

    # Compress stale tool results and superseded run_code source directly in the
    # database. This ensures future rebuilds produce identical message prefixes.
    compacted = await _compress_stale_items(items, session)

    # Self-tuning: use prior turn's actual prompt_tokens vs. our estimate at the
    # time to correct the estimator for this chat. Charmodel/4 tends to
    # underestimate for Anthropic/Qwen and overestimate for some JSON-heavy cases.
    correction = _read_prior_correction(items)

    messages = _items_to_messages(items, system_prompt)

    # Token budget: drop middle messages if history exceeds budget.
    # Preserves first + last turns so the prefix stays anchored for caching.
    pre_tokens = _estimate_tokens(messages)
    budget = compute_history_budget(max_context_tokens, pre_tokens["system"], overhead_tokens)
    # Both trims return the list they were given when they change nothing.
    untrimmed = messages
    messages = _apply_token_budget(untrimmed, budget=budget, correction=correction)
    compacted = compacted or messages is not untrimmed

    # Still filling up: this is a long run rather than a long conversation. Shed
    # old tool output first, since that keeps the record of what was done, and
    # only then whole steps. Starting short of the budget means dropping steps
    # stays the last resort rather than something a run flaps in and out of.
    if (
        _tokens_over_budget(messages, int(budget * RUN_COMPRESSION_TRIGGER), correction) > 0
        and await _compress_run_under_pressure(items, session, messages, budget, correction)
    ):
        compacted = True
        messages = _items_to_messages(items, system_prompt)
        messages = _apply_token_budget(messages, budget=budget, correction=correction)
    untrimmed = messages
    messages = _trim_run_steps(untrimmed, budget=budget, correction=correction)
    if compacted or messages is not untrimmed:
        # A provider continuing from its own stored copy of the run would keep
        # everything just removed, so this turn has to send the smaller history.
        messages[0]["_stimma_replay_history"] = True
    # Trimming cuts on user-turn boundaries, so it should not split a call from
    # its result — but this is the last thing that touches the list before it
    # reaches the provider, and re-running it is cheap and idempotent.
    _repair_tool_call_pairing(messages)
    post_tokens = _estimate_tokens(messages)

    adjusted_total = int(post_tokens["total"] * correction)

    if pre_tokens["total"] != post_tokens["total"]:
        log.info(
            f"Chat {chat_id}: context compressed "
            f"{pre_tokens['total']}→{post_tokens['total']} est. tokens "
            f"(adj={adjusted_total}, budget={budget}, window={max_context_tokens}, "
            f"correction={correction:.2f})"
        )
    else:
        log.debug(
            f"Chat {chat_id}: context {post_tokens['total']} est. tokens "
            f"(adj={adjusted_total}, budget={budget}, window={max_context_tokens}, "
            f"correction={correction:.2f})"
        )

    return messages, post_tokens["total"] + overhead_tokens


def _items_to_messages(items: List["ChatItem"], system_prompt: str) -> List[Dict[str, Any]]:
    """Map ChatItems to provider messages with well-formed tool call pairing."""
    messages: List[Dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
    ]

    seen_provider_batches: set[str] = set()
    for item in items:
        # A single assistant response can request several tools. ChatItems are
        # persisted call/result/call/result for execution/UI purposes, while
        # provider APIs require the original assistant batch exactly once.
        # Every call in a native-provider batch carries the same opaque state;
        # collapse duplicates here so replay is assistant(all calls), then all
        # tool results.
        if item.item_type == "tool_call" and item.item_metadata:
            try:
                metadata = json.loads(item.item_metadata) if isinstance(item.item_metadata, str) else item.item_metadata
                state = (metadata or {}).get("llm_provider_state")
                batch_key = json.dumps(state, sort_keys=True, separators=(",", ":")) if state else None
            except (json.JSONDecodeError, TypeError):
                batch_key = None
            if batch_key:
                if batch_key in seen_provider_batches:
                    continue
                seen_provider_batches.add(batch_key)
        msg = _item_to_message(item)
        if msg is not None:
            messages.append(msg)

    # Safety net: an interrupt or server restart can break the pairing between
    # tool calls and their results. Providers reject the whole conversation for
    # either half of that, bricking every later turn.
    _repair_tool_call_pairing(messages)
    return messages


INTERRUPTED_TOOL_RESULT = (
    "[Tool execution was interrupted before completing. No result was recorded.]"
)


def _repair_tool_call_pairing(messages: List[Dict[str, Any]]) -> None:
    """Make every tool call/result pair well-formed. Mutates in place.

    Providers require each assistant tool call to be answered by a tool result
    in the immediately following run of messages — and reject a tool result
    that no such call issued. Both halves break in practice:

    * A turn killed after the tool_call item was persisted but before its
      result leaves a call with no answer.
    * A server restart can persist the result LATE, after the user has already
      sent another message. The result then sits far from its call, matching
      nothing that precedes it. Its own call, meanwhile, reads as unanswered.

    The second case is the nastier one: nothing is missing, so a synthesize-only
    pass sees a valid-looking history and the provider still 400s on the stray
    result. So drop first, then fill — in that order, or the late result would
    count as an answer and its call would be left bare.

    Both are permanent once persisted: the same malformed history is rebuilt on
    every subsequent turn, so the chat stays bricked until it is repaired here.
    """
    # Skill context is user-shaped but is not a human interruption. Normalize
    # complete provider batches before repair; otherwise the context splits the
    # batch and repair destroys valid results before the transport sees them.
    from llm import _normalize_parallel_tool_history
    messages[:] = _normalize_parallel_tool_history(messages)
    _drop_orphaned_tool_results(messages)
    _synthesize_missing_tool_results(messages)


def _drop_orphaned_tool_results(messages: List[Dict[str, Any]]) -> None:
    """Drop tool results that the preceding assistant message did not ask for."""
    kept: List[Dict[str, Any]] = []
    pending: set = set()
    for msg in messages:
        role = msg.get("role")
        if role == "tool":
            call_id = msg.get("tool_call_id")
            if call_id in pending:
                pending.discard(call_id)
                kept.append(msg)
            else:
                log.warning(
                    f"Dropping orphaned tool result (tool_call_id={call_id!r}) — "
                    "no immediately preceding assistant message issued it."
                )
            continue
        if role == "assistant" and msg.get("tool_calls"):
            pending = {c.get("id") or "" for c in msg["tool_calls"]}
        else:
            pending = set()
        kept.append(msg)
    messages[:] = kept


def _synthesize_missing_tool_results(messages: List[Dict[str, Any]]) -> None:
    """Insert synthetic tool results for assistant tool_calls with no result.

    Mutates messages in place. For each assistant message carrying tool_calls,
    the immediately following role=="tool" messages are matched by
    tool_call_id; any unmatched ids get a synthetic interrupted-result inserted
    after the real ones, preserving provider ordering requirements.
    """
    i = 0
    while i < len(messages):
        msg = messages[i]
        calls = msg.get("tool_calls") if msg.get("role") == "assistant" else None
        if not calls:
            i += 1
            continue
        j = i + 1
        answered = set()
        while j < len(messages) and messages[j].get("role") == "tool":
            answered.add(messages[j].get("tool_call_id"))
            j += 1
        for call in calls:
            call_id = call.get("id") or ""
            if call_id in answered:
                continue
            messages.insert(j, {
                "role": "tool",
                "tool_call_id": call_id,
                "content": INTERRUPTED_TOOL_RESULT,
            })
            j += 1
        i = j


def _item_metadata(item: ChatItem) -> dict:
    try:
        metadata = json.loads(item.item_metadata) if isinstance(item.item_metadata, str) else item.item_metadata
        return metadata if isinstance(metadata, dict) else {}
    except (ValueError, TypeError):
        return {}


async def _persist_prompt_context(
    chat_id: int,
    items: List[ChatItem],
    session: AsyncSession,
    reminders: List[str],
) -> None:
    """Record user timestamps once and append changed runtime context.

    Older chats acquire timestamps on their first rebuild. Afterwards the same
    text is replayed, including across runs. Reminders follow completed tool
    batches rather than changing a user message earlier in the conversation.
    """
    dirty = False
    previous_reminders = []
    for item in items:
        metadata = _item_metadata(item)
        if item.item_type == "user_message" and "prompt_timestamp" not in metadata:
            created = item.created_at or datetime.now().astimezone()
            # Stored timestamps are UTC-naive; new in-memory items may be aware.
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            timestamp = created.astimezone().strftime("%Y-%m-%d %H:%M %Z")
            metadata["prompt_timestamp"] = f"[Current date/time: {timestamp}]"
            item.item_metadata = json.dumps(metadata)
            dirty = True
        elif item.item_type == "system_reminder":
            previous_reminders = metadata.get("prompt_reminders", [])
    if reminders != previous_reminders:
        item = ChatItem(
            chat_id=chat_id,
            item_type="system_reminder",
            message_text="\n\n".join(reminders),
            item_metadata=json.dumps({"prompt_reminders": reminders}),
        )
        session.add(item)
        items.append(item)
        dirty = True
    if dirty:
        await session.commit()


def _inject_last_user_context(
    messages: List[Dict[str, Any]],
    system_reminders: List[str],
) -> None:
    """Transient context for the stateless editor-agent request builder.

    The durable chat loop uses _persist_prompt_context instead, so its earlier
    messages are never rewritten when the clock or reminders change.
    """
    now = datetime.now().astimezone()
    timestamp = now.strftime("%Y-%m-%d %H:%M %Z")

    prefix_parts = [f"[Current date/time: {timestamp}]"]
    for reminder in system_reminders:
        prefix_parts.append(reminder)

    prefix = "\n".join(prefix_parts)

    for msg in reversed(messages):
        if msg.get("role") == "user" and isinstance(msg.get("content"), str):
            msg["content"] = f"{prefix}\n\n{msg['content']}"
            return


def _workspace_file_note(f: Dict[str, Any]) -> str:
    """One attachment's note entry, with recorded provenance when present.

    'x.png (media_id=42, generated by provider:tool, image-to-video of media 41)'
    — the generating tool is invisible to the flow agent otherwise, and
    guessing it is the observed failure mode."""
    note = f'{f["filename"]} (media_id={f["media_id"]}'
    if f.get("generated_by"):
        note += f', generated by {f["generated_by"]}'
    if f.get("task_type") and f.get("source_media_ids"):
        ids = ", ".join(str(i) for i in f["source_media_ids"])
        note += f', {f["task_type"]} of media {ids}'
    elif f.get("task_type"):
        note += f', {f["task_type"]}'
    return note + ")"


def _item_to_message(item: ChatItem) -> Dict[str, Any] | None:
    """Convert a ChatItem to an LLM message dict, or None to skip."""
    if item.item_type == "user_message":
        text = item.message_text or ""
        # If user attached images, tell the agent what files are in the workspace
        metadata = None
        if item.item_metadata:
            try:
                metadata = json.loads(item.item_metadata) if isinstance(item.item_metadata, str) else item.item_metadata
            except (json.JSONDecodeError, TypeError):
                pass
        if metadata and metadata.get("workspace_files"):
            files = metadata["workspace_files"]
            file_list = ", ".join(_workspace_file_note(f) for f in files)
            text += f"\n\n[Attached files in workspace: {file_list}. Use view_image to see them, or media_id for call_tool input_images. media_info(media_id) returns the recorded settings and full ancestor chain.]"
        if metadata and metadata.get('workspace_refs'):
            refs = json.dumps(metadata['workspace_refs'], ensure_ascii=False)
            text += f"\n\n[Attached workspace files: {refs}. Chat paths are relative to your workspace; project paths are relative to stimma.project_path(). Read these files for context.]"
        if metadata and metadata.get("prompt_timestamp"):
            text = f"{metadata['prompt_timestamp']}\n\n{text}"
        return {"role": "user", "content": text}

    if item.item_type == "system_reminder":
        if not item.message_text:
            return None
        return {
            "role": "user", "name": "_stimma_context",
            "content": item.message_text, "_stimma_reminder": True,
        }

    if item.item_type == "assistant_message":
        if not (item.message_text or "").strip():
            return None
        return {"role": "assistant", "content": item.message_text or ""}

    if item.item_type == "tool_call":
        # Reconstruct assistant message with tool_calls. Arguments must be
        # valid JSON on replay: strict providers (Fireworks, OpenAI) validate
        # historical tool_calls and 400 the WHOLE conversation on one
        # malformed entry, bricking every later turn. Wrap irreparable args
        # instead of replaying them raw.
        args = item.tool_args or "{}"
        try:
            json.loads(args)
        except (ValueError, TypeError):
            args = json.dumps({"_malformed_arguments": str(item.tool_args)[:2000]})
        tool_call = {
            "id": item.tool_call_id or "",
            "type": "function",
            "function": {
                "name": item.tool_name or "",
                "arguments": args,
            },
        }
        message = {
            "role": "assistant",
            "content": None,
            "tool_calls": [tool_call],
        }
        if item.item_metadata:
            try:
                metadata = json.loads(item.item_metadata) if isinstance(item.item_metadata, str) else item.item_metadata
                state = (metadata or {}).get("llm_provider_state")
            except (json.JSONDecodeError, TypeError):
                state = None
            if isinstance(state, dict) and state.get("kind") == "anthropic_message":
                message["_stimma_provider_state"] = state
                state_calls = []
                for block in state.get("content") or []:
                    if not isinstance(block, dict) or block.get("type") != "tool_use":
                        continue
                    state_calls.append({
                        "id": block.get("id", ""),
                        "type": "function",
                        "function": {
                            "name": block.get("name", ""),
                            "arguments": json.dumps(block.get("input") or {}),
                        },
                    })
                if state_calls:
                    message["tool_calls"] = state_calls
            elif isinstance(state, dict) and state.get("kind") == "openai_chat_tool_batch":
                state_calls = state.get("tool_calls")
                if isinstance(state_calls, list) and state_calls:
                    message["tool_calls"] = state_calls
                message["_stimma_provider_state"] = state
        return message

    if item.item_type == "tool_result":
        content = item.tool_result or item.tool_error or ""
        if isinstance(content, str):
            # Check for __view_image__ marker — inject multimodal content
            try:
                parsed = json.loads(content)
                if isinstance(parsed, dict) and parsed.get("__view_image__"):
                    return _build_view_image_result(item.tool_call_id or "", parsed)
                content = json.dumps(parsed) if not isinstance(parsed, str) else parsed
            except (json.JSONDecodeError, TypeError):
                pass
        return {
            "role": "tool",
            "tool_call_id": item.tool_call_id or "",
            "content": str(content),
        }

    if item.item_type == "stimpack_injection":
        # Keep this user-shaped for provider prompt semantics, but mark it so
        # stateful transports do not mistake injected context for a new human
        # turn when locating an outstanding parallel tool-call batch.
        return {
            "role": "user",
            "name": "_stimma_context",
            "content": item.message_text or "",
        }

    # Skip: generated_media, media_grid, error, system, hitl_request, etc.
    return None


def _build_view_image_result(tool_call_id: str, marker: dict) -> dict:
    """Build a multimodal tool result for view_image, reading pixels from disk."""
    from PIL import Image

    file_path = marker.get("path", "")
    detail = marker.get("detail", "low")
    max_side = 1024 if detail == "high" else 512

    resolved = Path(file_path)
    if not resolved.exists():
        return {
            "role": "tool",
            "tool_call_id": tool_call_id,
            "content": f"Image no longer available at {file_path} (workspace may have been cleaned up).",
        }

    try:
        from utils.image_ops import open_oriented
        img = open_oriented(resolved)
        w, h = img.size
        resized_for_payload = False
        # Markers written by current view_image point at a pre-rendered
        # snapshot and carry the source's native size. Older markers point at
        # the source file itself, so its pre-resize size IS the native size.
        native_w, native_h = marker.get("native_size") or (w, h)
        if max(w, h) > max_side:
            scale = max_side / max(w, h)
            w, h = int(w * scale), int(h * scale)
            img = img.resize((w, h), Image.LANCZOS)
            resized_for_payload = True

        # New markers already point at a cached JPEG snapshot. Read those bytes
        # directly so rebuilding a conversation does not repeat image encoding.
        if (
            marker.get("media_type") == "image/jpeg"
            and resolved.suffix.lower() in {".jpg", ".jpeg"}
            and not resized_for_payload
        ):
            encoded = resolved.read_bytes()
        else:
            # Legacy PNG markers are still accepted, but all model-bound bytes
            # use the same JPEG-85 policy as newly created snapshots.
            encoded = encode_agent_jpeg(img)
        b64 = base64.b64encode(encoded).decode("ascii")
    except Exception as e:
        log.warning(f"Failed to load image for view_image: {e}")
        return {
            "role": "tool",
            "tool_call_id": tool_call_id,
            "content": f"Error loading image {file_path}: {e}",
        }

    if (native_w, native_h) != (w, h):
        text = (
            f"Image loaded: native size {native_w}x{native_h}px, displayed downscaled "
            f"at {w}x{h}px. Express pixel coordinates in the native {native_w}x{native_h} "
            f"frame (estimate positions as fractions of the displayed image, then scale). "
            f"Analyze what you see."
        )
    else:
        text = f"Image loaded ({w}x{h}px). Analyze what you see."

    if marker.get("description"):
        text += " " + str(marker["description"])

    faces = marker.get("faces")
    if faces:
        face_parts = []
        for i, f in enumerate(faces, 1):
            face_parts.append(
                f"face {i}: x={f['x']:.3f} y={f['y']:.3f} w={f['width']:.3f} h={f['height']:.3f} (normalized 0-1, confidence={f['confidence']})"
            )
        text += f" Detected faces (normalized 0-1): {'; '.join(face_parts)}."

    layout_source = marker.get("layout_source")
    if layout_source:
        text += f" Layout HTML source copied to workspace: {layout_source}"

    return {
        "role": "tool",
        "tool_call_id": tool_call_id,
        "content": [
            {"type": "text", "text": text},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
        ],
    }


# ---------------------------------------------------------------------------
# Context compression
# ---------------------------------------------------------------------------

def _estimate_tokens(messages: List[Dict[str, Any]]) -> Dict[str, int]:
    """Estimate token counts for a message list.

    Uses len/4 for text (rough but sufficient for logging/budgeting).
    Vision tokens are ~85 (low detail) or ~765 (high detail) per image.
    """
    system = 0
    history = 0
    images = 0

    for msg in messages:
        content = msg.get("content")
        role = msg.get("role", "")

        # Tool results are JSON/code-dense and tokenize nearer chars/3 than
        # the chars/4 of prose; underestimating them overflows small windows.
        divisor = 3 if role == "tool" else 4

        text_tokens = 0
        if isinstance(content, str):
            text_tokens = len(content) // divisor
        elif isinstance(content, list):
            # Multimodal content blocks
            for block in content:
                if isinstance(block, dict):
                    if block.get("type") == "text":
                        text_tokens += len(block.get("text", "")) // 4
                    elif block.get("type") == "image_url":
                        # Vision tokens vary by model family and detail level;
                        # Qwen-VL-style patch encoders run ~1300 tokens for a
                        # 1024px image. Underestimating here overflows small
                        # context windows, so budget high.
                        images += 900
        elif content is None:
            # Assistant message with tool_calls
            tool_calls = msg.get("tool_calls", [])
            for tc in tool_calls:
                fn = tc.get("function", {})
                text_tokens += len(fn.get("name", "")) // 4
                text_tokens += len(fn.get("arguments", "")) // 4

        if role == "system":
            system += text_tokens
        else:
            history += text_tokens

    return {"system": system, "history": history, "images": images, "total": system + history + images}


def _find_user_turn_boundaries(messages: List[Dict[str, Any]]) -> List[int]:
    """Return human-turn boundaries, excluding runtime reminder messages."""
    return [i for i, m in enumerate(messages) if m.get("role") == "user" and not m.get("_stimma_reminder")]


async def _compress_stale_items(
    items: List["ChatItem"],
    session: AsyncSession,
) -> bool:
    """Compress stale tool results and superseded run_code source in the database.

    Modifies ChatItem rows in-place so that future build_messages() calls produce
    identical message prefixes — critical for prompt caching. Once a tool result
    is compressed, it stays compressed permanently.

    - Replaces large tool results older than STALE_TURN_THRESHOLD user turns
    - Replaces superseded run_code arguments with a line-count summary
    - Keeps at most MAX_ACTIVE_VIEW_IMAGES raw images, all from within the most
      recent STALE_TURN_THRESHOLD user turns. Older markers become lightweight
      placeholders and remain retrievable by calling view_image again.

    Returns whether anything changed.
    """
    # Find user turn boundaries in the items list
    user_turn_indices = [i for i, item in enumerate(items) if item.item_type == "user_message"]
    cutoff_idx = (
        user_turn_indices[-STALE_TURN_THRESHOLD]
        if len(user_turn_indices) > STALE_TURN_THRESHOLD
        else 0
    )

    view_image_indices: list[int] = []
    for i, item in enumerate(items):
        if item.item_type != "tool_result" or not item.tool_result:
            continue
        try:
            parsed = json.loads(item.tool_result)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(parsed, dict) and parsed.get("__view_image__"):
            view_image_indices.append(i)
    retained_image_indices = set(view_image_indices[-MAX_ACTIVE_VIEW_IMAGES:])

    # Build tool_call_id -> tool_name mapping and find the last run_code call
    call_id_to_name: Dict[str, str] = {}
    last_run_code_call_id: str | None = None
    for item in items:
        if item.item_type == "tool_call" and item.tool_call_id:
            call_id_to_name[item.tool_call_id] = item.tool_name or "tool"
            if item.tool_name == "run_code":
                last_run_code_call_id = item.tool_call_id

    dirty = False

    for i, item in enumerate(items):
        # Compress old tool results
        if item.item_type == "tool_result":
            content = item.tool_result or item.tool_error or ""
            if isinstance(content, str) and content:
                # view_image markers are a small JSON pointer (path/detail) in
                # the DB — the actual image bytes are read from disk and
                # re-embedded as base64 on every build_messages call, so they
                # never trip the TRUNCATION_MIN_CHARS length check below even
                # though they're the largest thing in the request. Age them
                # out by turn regardless of their (tiny) stored length.
                try:
                    parsed = json.loads(content)
                except (json.JSONDecodeError, TypeError):
                    parsed = None

                if (
                    isinstance(parsed, dict)
                    and parsed.get("__view_image__")
                    and (i < cutoff_idx or i not in retained_image_indices)
                ):
                    if item.tool_result:
                        item.tool_result = "[Image shown earlier in this conversation — call view_image again if you need to see it]"
                        dirty = True
                    continue

            if i < cutoff_idx and _compress_tool_result(item, call_id_to_name):
                dirty = True

        # Compress superseded run_code arguments
        if i < cutoff_idx and item.item_type == "tool_call" and item.tool_name == "run_code":
            if item.tool_call_id != last_run_code_call_id and _compress_run_code_args(item):
                dirty = True

    if dirty:
        await session.commit()
    return dirty


def _compress_tool_result(item: "ChatItem", call_id_to_name: Dict[str, str]) -> int:
    """Replace a large tool result with its placeholder. Returns the chars saved."""
    content = item.tool_result or item.tool_error or ""
    if not isinstance(content, str) or len(content) <= TRUNCATION_MIN_CHARS:
        return 0
    tool_name = call_id_to_name.get(item.tool_call_id or "", "tool")
    placeholder = _stale_result_placeholder(tool_name, content)
    if item.tool_result:
        item.tool_result = placeholder
    else:
        item.tool_error = placeholder
    return max(len(content) - len(placeholder), 0)


def _compress_run_code_args(item: "ChatItem") -> int:
    """Replace superseded run_code source with a summary. Returns the chars saved."""
    try:
        args = json.loads(item.tool_args or "{}")
        code = args.get("code", "")
    except (json.JSONDecodeError, TypeError, AttributeError):
        return 0
    if not code or code.startswith("[Python"):
        return 0
    line_count = code.count("\n") + 1
    args["code"] = f"[Python — {line_count} lines — superseded by later code]"
    item.tool_args = json.dumps(args)
    return max(len(code) - len(args["code"]), 0)


def _tokens_over_budget(messages: List[Dict[str, Any]], budget: int, correction: float) -> int:
    """How far history + images overshoots the budget, in uncorrected tokens."""
    tokens = _estimate_tokens(messages)
    effective = (tokens["history"] + tokens["images"]) * correction
    return int((effective - budget) / correction) + 1 if effective > budget else 0


async def _compress_run_under_pressure(
    items: List["ChatItem"],
    session: AsyncSession,
    messages: List[Dict[str, Any]],
    budget: int,
    correction: float,
) -> bool:
    """Compress the oldest tool output of a run that has outgrown its budget.

    Persisted like _compress_stale_items, and for the same reason. Each write
    changes the prompt prefix and so costs a cache miss, which makes this work
    in batches: it compresses well below the budget, and passes on savings too
    small to be worth a miss. _trim_run_steps covers any overage left behind.
    """
    target_overage = _tokens_over_budget(messages, int(budget * RUN_COMPRESSION_TARGET), correction)
    worth_compressing = max(budget, 0) // RUN_PRESSURE_CHUNK

    result_indices = [i for i, item in enumerate(items) if item.item_type == "tool_result"]
    if len(result_indices) <= RUN_KEEP_RECENT_RESULTS:
        return False
    protected_from = result_indices[-RUN_KEEP_RECENT_RESULTS]

    call_id_to_name = {
        item.tool_call_id: item.tool_name or "tool"
        for item in items
        if item.item_type == "tool_call" and item.tool_call_id
    }
    last_run_code_id = next(
        (it.tool_call_id for it in reversed(items) if it.item_type == "tool_call" and it.tool_name == "run_code"),
        None,
    )

    # Plan first: a batch too small to be worth a cache miss writes nothing.
    planned: List["ChatItem"] = []
    saved = 0
    for item in items[:protected_from]:
        if saved >= target_overage:
            break
        if item.item_type == "tool_result":
            tool_name = call_id_to_name.get(item.tool_call_id or "", "tool")
            content = item.tool_result or item.tool_error or ""
            if tool_name in RUN_COMPRESSION_EXEMPT_TOOLS or len(content) <= TRUNCATION_MIN_CHARS:
                continue
            saved += len(content) // 3
            planned.append(item)
        elif (
            item.item_type == "tool_call"
            and item.tool_name == "run_code"
            and item.tool_call_id != last_run_code_id
            # Provider state replays the call as issued, so editing tool_args
            # would save nothing here.
            and "llm_provider_state" not in (item.item_metadata or "")
        ):
            try:
                code = json.loads(item.tool_args or "{}").get("code", "")
            except (json.JSONDecodeError, TypeError, AttributeError):
                continue
            if code and not code.startswith("[Python"):
                saved += len(code) // 4
                planned.append(item)

    if not planned or saved < worth_compressing:
        return False

    for item in planned:
        if item.item_type == "tool_result":
            _compress_tool_result(item, call_id_to_name)
        else:
            _compress_run_code_args(item)
    await session.commit()
    log.info(f"Run under context pressure: compressed {len(planned)} old tool items (~{saved} tokens)")
    return True


def _trim_run_steps(
    messages: List[Dict[str, Any]],
    *,
    budget: int,
    correction: float = 1.0,
) -> List[Dict[str, Any]]:
    """Drop the oldest whole steps when history is still over budget.

    A step is an assistant message plus the tool results answering it, so a call
    never loses its result. Appended runtime reminders travel with their step;
    human messages and loaded skills stay, as do the newest step and any step
    asking the user a question: those hold what the user wants.

    The cut only lands on fixed token boundaries counted from the start of the
    history. That keeps it in place, and the prompt cache valid, for many steps.
    """
    overage = _tokens_over_budget(messages, budget, correction)
    if overage <= 0:
        return messages

    steps: List[List[int]] = []
    open_step = False
    for i, message in enumerate(messages):
        role = message.get("role")
        if role == "assistant":
            steps.append([i])
            open_step = True
        elif (role == "tool" or message.get("_stimma_reminder")) and open_step:
            steps[-1].append(i)
        else:
            open_step = False

    def asks_user(step: List[int]) -> bool:
        return any(
            call.get("function", {}).get("name") == "ask_user"
            for call in messages[step[0]].get("tool_calls") or []
        )

    droppable = [step for step in steps[:-1] if not asks_user(step)]
    chunk = max(budget // RUN_PRESSURE_CHUNK, 1)
    dropped: set[int] = set()
    pending: List[int] = []
    counted = 0
    for position, step in enumerate(droppable):
        before = counted
        pending.extend(step)
        counted += _estimate_tokens([messages[i] for i in step])["total"]
        if counted // chunk > before // chunk or position == len(droppable) - 1:
            dropped.update(pending)
            pending = []
            if counted >= overage:
                break

    if not dropped:
        return messages
    dropped_tool_calls = sum(len(messages[i].get("tool_calls") or []) for i in dropped)

    placeholder = {
        "role": "user",
        "content": (
            f"[{dropped_tool_calls} earlier tool calls and their results from this work were removed "
            "to fit the context window. What they produced still exists: check your notepad, your "
            "workspace files and library(action='browse', scope='chat') rather than redoing it.]"
        ),
    }
    first_dropped = min(dropped)
    result = messages[:first_dropped] + [placeholder]
    result.extend(m for i, m in enumerate(messages) if i > first_dropped and i not in dropped)

    log.info(f"Token budget applied: dropped {len(dropped)} messages from the oldest steps of this run")
    return result


_MEDIA_ID_RE = re.compile(r"""media_ids?["']?\s*[=:\s]\s*\[?\s*(\d+(?:\s*,\s*\d+)*)""")
MAX_PLACEHOLDER_MEDIA_IDS = 50


def _stale_result_placeholder(tool_name: str, content: str) -> str:
    """Placeholder for a compressed tool result that keeps its media handles.

    Generation results are not reproducible by "using the tool again" — the
    media_ids are the only way back to what the user saw a few turns ago.
    """
    ids: list[str] = []
    for match in _MEDIA_ID_RE.finditer(content):
        for mid in re.split(r"\s*,\s*", match.group(1)):
            if mid not in ids:
                ids.append(mid)
    placeholder = f"[{tool_name} result: {len(content)} chars — use the tool again if you need this data"
    if ids:
        shown = ", ".join(ids[:MAX_PLACEHOLDER_MEDIA_IDS])
        more = f" (+{len(ids) - MAX_PLACEHOLDER_MEDIA_IDS} more)" if len(ids) > MAX_PLACEHOLDER_MEDIA_IDS else ""
        placeholder += f". Media it referenced: media_id {shown}{more}"
    return placeholder + "]"


def _read_prior_correction(items: List["ChatItem"]) -> float:
    """Derive a tokens-per-estimated-token correction factor from the most
    recent assistant turn that recorded both the actual context size of its LLM
    call and our estimate at call time. Tool-only turns record theirs on the
    tool call. llm_usage's prompt_tokens won't do: it totals the whole agent
    loop, while the estimate covers one call.

    Returns 1.0 when no prior measurement is available (fresh chat or old
    items without estimated_prompt_tokens). Clamped to a reasonable band so
    one outlier can't wildly skew the budget.
    """
    for item in reversed(items):
        if item.item_type not in ("assistant_message", "tool_call"):
            continue
        raw = item.item_metadata
        if not raw:
            continue
        try:
            meta = json.loads(raw) if isinstance(raw, str) else raw
        except (json.JSONDecodeError, TypeError):
            continue
        usage = (meta or {}).get("llm_call_size") or (meta or {}).get("llm_usage")
        if not usage:
            continue
        actual = usage.get("context_tokens")
        estimated = usage.get("estimated_prompt_tokens")
        if not actual or not estimated:
            continue
        try:
            ratio = float(actual) / float(estimated)
        except (TypeError, ValueError, ZeroDivisionError):
            continue
        # Clamp so a single weird turn can't cut our budget in half or double it.
        return max(0.6, min(1.8, ratio))
    return 1.0


def _apply_token_budget(
    messages: List[Dict[str, Any]],
    *,
    budget: int,
    correction: float = 1.0,
) -> List[Dict[str, Any]]:
    """If estimated (corrected) history tokens exceed budget, drop middle messages.

    Preserves: system prompt, first user message + response, last RECENT_TURNS_TO_KEEP
    user turns with all their associated messages.
    Replaces the middle with a condensed placeholder.
    """
    tokens = _estimate_tokens(messages)
    effective = int((tokens["history"] + tokens["images"]) * correction)
    if effective <= budget:
        return messages

    user_turns = _find_user_turn_boundaries(messages)
    if len(user_turns) <= RECENT_TURNS_TO_KEEP + 1:
        return messages  # Not enough turns to meaningfully compress

    # Find the boundary between "keep start" and "keep end"
    # Keep: system (idx 0), first user msg + everything until second user msg
    first_user_idx = user_turns[0]
    second_user_idx = user_turns[1] if len(user_turns) > 1 else first_user_idx + 1

    # Keep: last RECENT_TURNS_TO_KEEP user turns and everything after them
    recent_cutoff_idx = user_turns[-RECENT_TURNS_TO_KEEP]

    if second_user_idx >= recent_cutoff_idx:
        return messages  # Start and end overlap, nothing to cut

    # Build the condensed message list
    start_section = messages[:second_user_idx]  # system + first user turn
    middle_section = messages[second_user_idx:recent_cutoff_idx]
    end_section = messages[recent_cutoff_idx:]

    middle_user_count = sum(1 for m in middle_section if m.get("role") == "user")
    first_user_text = ""
    for m in messages:
        if m.get("role") == "user":
            first_user_text = (m.get("content") or "")[:200]
            break

    placeholder = {
        "role": "user",
        "content": (
            f"[{len(middle_section)} earlier messages covering {middle_user_count} turns "
            f"were condensed. The conversation began with: \"{first_user_text}\". "
            f"Use tools to re-fetch any data you need; library(action='browse', scope='chat') "
            f"lists the media from this chat.]"
        ),
    }

    result = start_section + [placeholder] + end_section

    log.info(
        f"Token budget applied: dropped {len(middle_section)} middle messages "
        f"({middle_user_count} turns), keeping first turn + last {RECENT_TURNS_TO_KEEP} turns"
    )

    return result


_STRICT_COMPACTION_PLACEHOLDER = {
    "role": "user",
    "content": "[Earlier turns were omitted to fit the model context window.]",
}


def _apply_token_budget_strict(
    messages: List[Dict[str, Any]],
    *,
    budget: int,
    correction: float = 1.0,
) -> List[Dict[str, Any]]:
    """Enforce a history budget by retaining complete, cache-friendly turns.

    The ordinary chat compactor intentionally keeps the first turn plus five
    recent turns, even when a very small window cannot hold all of them.  The
    ToolView mini-agent has a much larger fixed tool schema and can overflow a
    32k endpoint after only a few turns, so it needs a hard backstop.

    Keep the system prefix and, when it fits, the first turn.  Fill the tail
    with the newest contiguous complete turns.  A fixed placeholder separates
    them, so compaction never injects changing counts or summaries near the
    front of the request.  Live state is added to the final user message only
    after this function runs.
    """
    budget = max(0, int(budget))

    def _history_tokens(candidate: List[Dict[str, Any]]) -> int:
        tokens = _estimate_tokens(candidate)
        return int((tokens["history"] + tokens["images"]) * correction)

    if _history_tokens(messages) <= budget:
        return messages

    user_turns = _find_user_turn_boundaries(messages)
    if not user_turns:
        return messages

    prefix = messages[:user_turns[0]]
    turns = [
        messages[start:(user_turns[i + 1] if i + 1 < len(user_turns) else len(messages))]
        for i, start in enumerate(user_turns)
    ]
    if len(turns) == 1:
        # The current user message is authoritative and cannot be discarded.
        return prefix + turns[0]

    placeholder = [dict(_STRICT_COMPACTION_PLACEHOLDER)]
    first = turns[0]
    latest = turns[-1]

    keep_first = True
    result = prefix + first + placeholder + latest
    if _history_tokens(result) > budget:
        keep_first = False
        result = prefix + placeholder + latest
    if _history_tokens(result) > budget:
        # Even the fixed marker does not fit.  Keep only the current turn.
        return prefix + latest

    middle = turns[1:-1] if keep_first else turns[:-1]
    kept_recent: List[List[Dict[str, Any]]] = []
    for turn in reversed(middle):
        trial_recent = [turn] + kept_recent
        trial = prefix + (first if keep_first else []) + placeholder
        for kept_turn in trial_recent:
            trial += kept_turn
        trial += latest
        if _history_tokens(trial) > budget:
            break
        kept_recent = trial_recent
        result = trial

    omitted_turns = len(turns) - 1 - len(kept_recent) - (1 if keep_first else 0)
    log.info(
        f"Strict token budget applied: omitted {omitted_turns} turn(s), "
        f"kept_first={keep_first}, kept_recent={len(kept_recent) + 1}, "
        f"budget={budget}"
    )
    return result
