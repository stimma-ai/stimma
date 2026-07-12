"""V2 conversation builder — maps ChatItems to LLM messages."""

import base64
import io
import json
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import ChatItem
from core.logging import get_logger

log = get_logger(__name__)

# Context compression settings
STALE_TURN_THRESHOLD = 3       # Tool results older than this many user turns get compressed
TRUNCATION_MIN_CHARS = 500     # Only compress tool results larger than this
RECENT_TURNS_TO_KEEP = 5       # User turns to preserve in token-budget backstop
COMPACTION_PCT = 0.80          # Fraction of the context window we're willing to fill


def response_reserve(max_context_tokens: int) -> int:
    """Tokens held back from the prompt budget for the model's own output.

    Scales with the window (10%) and clamps to [2k, 8k]: small local windows
    (32k) still have room for history, and huge windows don't waste reserve
    on an output that rarely exceeds a few thousand tokens in agent usage.
    """
    return max(2_048, min(8_192, max_context_tokens // 10))


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

    system_reminders: Optional list of runtime-injected reminder strings. These are
    appended to the last user message (like the timestamp) to provide per-turn
    system-authored context without modifying the cached system prompt prefix.
    Wrap each reminder in <system-reminder> tags before passing.

    max_context_tokens: Advertised window for the target model. Used to derive the
    compaction threshold (80% of window minus response reserve and system prompt).

    Returns (messages, estimated_prompt_tokens). The estimate is adjusted by a
    per-chat correction factor learned from prior turns' actual usage.
    """
    result = await session.execute(
        select(ChatItem)
        .where(ChatItem.chat_id == chat_id, ChatItem.parent_item_id.is_(None))
        .order_by(ChatItem.created_at.asc())
    )
    items = list(result.scalars().all())

    # Compress stale tool results and superseded run_code source directly in the
    # database. This ensures future rebuilds produce identical message prefixes.
    await _compress_stale_items(items, session)

    # Self-tuning: use prior turn's actual prompt_tokens vs. our estimate at the
    # time to correct the estimator for this chat. Charmodel/4 tends to
    # underestimate for Anthropic/Qwen and overestimate for some JSON-heavy cases.
    correction = _read_prior_correction(items)

    messages: List[Dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
    ]

    for item in items:
        msg = _item_to_message(item)
        if msg is not None:
            messages.append(msg)

    # Safety net: if first non-system message is an orphaned tool result,
    # prepend a synthetic user message so the LLM gets a valid conversation.
    if len(messages) > 1 and messages[1].get("role") == "tool":
        messages.insert(1, {"role": "user", "content": "(continued)"})

    # Token budget: drop middle messages if history exceeds budget.
    # Preserves first + last turns so the prefix stays anchored for caching.
    pre_tokens = _estimate_tokens(messages)
    budget = compute_history_budget(max_context_tokens, pre_tokens["system"], overhead_tokens)
    messages = _apply_token_budget(messages, budget=budget, correction=correction)
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

    # Inject timestamp and system reminders into the last user message
    # (not the system prompt) so they don't bust prompt cache.
    _inject_last_user_context(messages, system_reminders or [])

    return messages, adjusted_total


def _inject_last_user_context(
    messages: List[Dict[str, Any]],
    system_reminders: List[str],
) -> None:
    """Prepend timestamp and system reminders to the last user message (mutates in place).

    System reminders are runtime-injected, system-authored context that the model
    should treat as authoritative guidance. They're placed in the last user message
    (rather than the system prompt) to keep the prompt prefix stable for caching.
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
        return {"role": "user", "content": text}

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
        return {
            "role": "assistant",
            "content": None,
            "tool_calls": [tool_call],
        }

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
        return {"role": "user", "content": item.message_text or ""}

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
        # Markers written by current view_image point at a pre-rendered
        # snapshot and carry the source's native size. Older markers point at
        # the source file itself, so its pre-resize size IS the native size.
        native_w, native_h = marker.get("native_size") or (w, h)
        if max(w, h) > max_side:
            scale = max_side / max(w, h)
            w, h = int(w * scale), int(h * scale)
            img = img.resize((w, h), Image.LANCZOS)

        # Convert to RGB if necessary (e.g. RGBA, P mode)
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")
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
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
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
    """Return indices of user messages (turn boundaries), excluding system messages."""
    return [i for i, m in enumerate(messages) if m.get("role") == "user"]


async def _compress_stale_items(
    items: List["ChatItem"],
    session: AsyncSession,
) -> None:
    """Compress stale tool results and superseded run_code source in the database.

    Modifies ChatItem rows in-place so that future build_messages() calls produce
    identical message prefixes — critical for prompt caching. Once a tool result
    is compressed, it stays compressed permanently.

    - Replaces large tool results older than STALE_TURN_THRESHOLD user turns
    - Replaces superseded run_code arguments with a line-count summary
    - Replaces view_image markers older than STALE_TURN_THRESHOLD user turns
      with a text placeholder (they'd otherwise re-embed full image bytes as
      base64 on every build_messages call, regardless of their tiny stored
      JSON length)
    """
    # Find user turn boundaries in the items list
    user_turn_indices = [i for i, item in enumerate(items) if item.item_type == "user_message"]
    if len(user_turn_indices) <= STALE_TURN_THRESHOLD:
        return

    cutoff_idx = user_turn_indices[-STALE_TURN_THRESHOLD]

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
        if i >= cutoff_idx:
            break

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

                if isinstance(parsed, dict) and parsed.get("__view_image__"):
                    if item.tool_result:
                        item.tool_result = "[Image shown earlier in this conversation — call view_image again if you need to see it]"
                        dirty = True
                    continue

            if isinstance(content, str) and len(content) > TRUNCATION_MIN_CHARS:
                tool_name = call_id_to_name.get(item.tool_call_id or "", "tool")
                placeholder = f"[{tool_name} result: {len(content)} chars — use the tool again if you need this data]"
                if item.tool_result and len(item.tool_result) > TRUNCATION_MIN_CHARS:
                    item.tool_result = placeholder
                    dirty = True
                elif item.tool_error and len(item.tool_error) > TRUNCATION_MIN_CHARS:
                    item.tool_error = placeholder
                    dirty = True

        # Compress superseded run_code arguments
        if item.item_type == "tool_call" and item.tool_name == "run_code":
            if item.tool_call_id != last_run_code_call_id:
                args_str = item.tool_args or "{}"
                try:
                    args = json.loads(args_str)
                    code = args.get("code", "")
                    if code and not code.startswith("[Python"):
                        line_count = code.count("\n") + 1
                        args["code"] = f"[Python — {line_count} lines — superseded by later code]"
                        item.tool_args = json.dumps(args)
                        dirty = True
                except (json.JSONDecodeError, TypeError):
                    pass

    if dirty:
        await session.commit()


def _read_prior_correction(items: List["ChatItem"]) -> float:
    """Derive a tokens-per-estimated-token correction factor from the most
    recent assistant turn that recorded both the actual prompt_tokens and our
    estimate at call time.

    Returns 1.0 when no prior measurement is available (fresh chat or old
    items without estimated_prompt_tokens). Clamped to a reasonable band so
    one outlier can't wildly skew the budget.
    """
    for item in reversed(items):
        if item.item_type != "assistant_message":
            continue
        raw = item.item_metadata
        if not raw:
            continue
        try:
            meta = json.loads(raw) if isinstance(raw, str) else raw
        except (json.JSONDecodeError, TypeError):
            continue
        usage = (meta or {}).get("llm_usage")
        if not usage:
            continue
        actual = usage.get("prompt_tokens")
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
            f"Use tools to re-fetch any data you need.]"
        ),
    }

    result = start_section + [placeholder] + end_section

    log.info(
        f"Token budget applied: dropped {len(middle_section)} middle messages "
        f"({middle_user_count} turns), keeping first turn + last {RECENT_TURNS_TO_KEEP} turns"
    )

    return result
