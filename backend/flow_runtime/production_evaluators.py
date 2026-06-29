"""Production evaluators — wire the FRP engine to real services.

Phase 5.5 filler. Each evaluator here implements
``flow_runtime.evaluators.Evaluator`` for one equation type and raises
``EvaluatorError`` with the correct category so the engine's retry / pause /
error-task flow does the right thing (see FLOWS_TECH.md §Error Handling):

  - ``tool_call``  → generation queue + ``execute_call_tool`` path used by
    the agent. Returns an ``EvaluationResult`` whose ``media_ids`` are the
    produced library media. Tags each produced ``MediaItem.generation_metadata``
    with ``{source: "flow", flow_id, equation_key, phase_path}`` so Phase 6
    filters / badges / lineage have something to key off of.
  - ``llm_call``   → ``llm.llm_completion`` with the prompt template rendered
    from ``resolved_inputs``. Parses structured output when
    ``response_format`` is set on the DSL call.
  - ``code``       → a thin re-use of the agent's code-runtime sandbox
    primitives (``build_safe_builtins``) with the resolved DSL inputs bound
    into globals. Not a second sandbox — shares the allow-list / safe open /
    safe import with the agent. Exceptions inside the snippet map to
    ``CODE_ERROR``.

HITL evaluators aren't registered here — the engine detects
``equation_type == 'hitl'`` and creates tasks itself
(``engine._create_hitl_task``). Leaving the HITL slot in the registry empty
is intentional.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import traceback
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

from sqlalchemy import func, select, update

from generation_metadata import dump_generation_metadata

from .evaluators import (
    CODE_ERROR,
    LLM_ERROR,
    RESOURCE_ERROR,
    TOOL_ERROR,
    TOOL_UNAVAILABLE,
    TRANSIENT,
    EvaluationRequest,
    EvaluationResult,
    Evaluator,
    EvaluatorError,
    EvaluatorRegistry,
)


log = logging.getLogger(__name__)


# =============================================================================
# Error classification
# =============================================================================


_TRANSIENT_RE = re.compile(
    r"(rate[\s_-]?limit|timeout|timed out|temporarily|503|502|504|connection|"
    r"network|socket|unreachable|overloaded)",
    re.IGNORECASE,
)
_RESOURCE_RE = re.compile(
    r"(credit|quota exceeded|insufficient funds|out of (disk|storage|space)|"
    r"disk full|no space left|billing)",
    re.IGNORECASE,
)
_SAFETY_RE = re.compile(
    r"(safety|content[\s_-]?filter|moderation|blocked|refus|not allowed|"
    r"nsfw|policy)",
    re.IGNORECASE,
)


def _classify_tool_error(message: str) -> str:
    """Bucket a tool/provider error string into an EvaluatorError category."""
    if _RESOURCE_RE.search(message):
        return RESOURCE_ERROR
    if _TRANSIENT_RE.search(message):
        return TRANSIENT
    if _SAFETY_RE.search(message):
        return TOOL_ERROR
    return TOOL_ERROR


def _raise_tool_error(exc: BaseException) -> None:
    """Re-raise ``exc`` as an EvaluatorError with the right category."""
    if isinstance(exc, asyncio.CancelledError):
        # Control-flow signal — engine.py uses task.cancel() to discard
        # in-flight work after invalidation. Must propagate, not be wrapped.
        raise exc
    if isinstance(exc, EvaluatorError):
        raise exc
    if isinstance(exc, (asyncio.TimeoutError, ConnectionError)):
        raise EvaluatorError(str(exc) or type(exc).__name__, category=TRANSIENT) from exc
    msg = str(exc) or type(exc).__name__
    raise EvaluatorError(msg, category=_classify_tool_error(msg)) from exc


# Path prefixes used to strip framework frames from user-code tracebacks so
# the agent sees just the user's program.py frame(s). ``Path(__file__).parent
# .parent`` is ``.../backend/``; stdlib / site-packages frames come from
# asyncio / concurrent.futures plumbing around ``_invoke_code_callable``.
import sys as _sys
import sysconfig as _sysconfig

_STIMMA_BACKEND_DIR = str(Path(__file__).resolve().parent.parent)
_STDLIB_DIR = str(Path(_sysconfig.get_paths()["stdlib"]).resolve())
_SYS_PREFIX = str(Path(_sys.prefix).resolve())


def _is_framework_frame(filename: str) -> bool:
    """True when ``filename`` belongs to stimma, the stdlib, or an installed
    package — i.e. not something the user wrote in their flow."""
    if not filename:
        return True
    if _STIMMA_BACKEND_DIR in filename:
        return True
    if _STDLIB_DIR in filename:
        return True
    if "site-packages" in filename:
        return True
    # Catches venv internals (``.../python3.11/lib/...``) that aren't under
    # the stdlib path when Python is installed non-standard.
    if filename.startswith(_SYS_PREFIX) and "site-packages" not in filename:
        return True
    return False


def _format_user_code_error(exc: BaseException) -> str:
    """Format a user-code exception with a traceback, filtered to user frames.

    The agent needs the failing line number to debug a flow — the bare
    ``AttributeError: …`` string doesn't say which call site raised. We walk
    the traceback, drop framework frames (stimma backend, stdlib, installed
    packages), and keep the user's program.py frames plus the exception line.
    """
    tb = exc.__traceback__
    if tb is None:
        return f"{type(exc).__name__}: {exc}"
    frames = traceback.extract_tb(tb)
    user_frames = [f for f in frames if not _is_framework_frame(f.filename or "")]
    if not user_frames:
        # No user frames survived the filter — fall back to the full trace so
        # we never swallow the useful part.
        user_frames = frames
    parts = ["Traceback (most recent call last):\n"]
    parts.extend(traceback.format_list(user_frames))
    parts.append(f"{type(exc).__name__}: {exc}")
    return "".join(parts)


# =============================================================================
# Session helpers
# =============================================================================


def _open_session():
    """Open a fresh AsyncSession bound to the current profile's DB.

    Each evaluator call gets its own short-lived session — we never share a
    session across concurrent tool invocations (``generation_queue`` writes
    jobs from its own session, and tagging code only needs a single UPDATE).
    """
    from core.profile_context import get_current_profile
    from database_registry import get_database_registry

    profile_id = get_current_profile()
    db = get_database_registry().get_database(profile_id)
    return db.async_session_maker()


# =============================================================================
# Tool-call evaluator
# =============================================================================


async def _extract_compute_duration_ms(media_ids: list[int]) -> Optional[int]:
    """Read tool-reported ``generation_time`` from produced media metadata
    and return the max in milliseconds.

    ``generation_time`` is the tool provider's pure compute time (seconds),
    written to ``MediaItem.generation_metadata`` by the generation queue. The
    flow runtime surfaces this so per-iteration UI can show compute time
    instead of the queue-inclusive wall-clock. For n>1 tool calls we pick the
    max so the equation's duration reflects its slowest output — that's the
    wall-clock bound of the evaluation.
    """
    if not media_ids:
        return None
    try:
        from database import MediaItem  # late import — avoid circular at load
        from sqlalchemy import select
    except Exception:
        log.exception("compute_duration_ms: failed to import library DB")
        return None
    try:
        async with _open_session() as session:
            result = await session.execute(
                select(MediaItem.generation_metadata).where(
                    MediaItem.id.in_(media_ids)
                )
            )
            max_ms: Optional[int] = None
            for (raw,) in result.all():
                if not raw:
                    continue
                try:
                    meta = json.loads(raw) if isinstance(raw, str) else raw
                except (ValueError, TypeError):
                    continue
                if not isinstance(meta, dict):
                    continue
                gt = meta.get("generation_time")
                if gt is None and isinstance(meta.get("parameters"), dict):
                    gt = meta["parameters"].get("generation_time")
                if gt is None:
                    continue
                try:
                    ms = int(float(gt) * 1000)
                except (TypeError, ValueError):
                    continue
                if ms < 0:
                    continue
                if max_ms is None or ms > max_ms:
                    max_ms = ms
            return max_ms
    except Exception:
        log.exception(
            "compute_duration_ms: lookup failed for media_ids=%s", media_ids
        )
        return None


async def _tag_media_with_flow(
    media_ids: list[int],
    *,
    flow_id: Optional[int],
    equation_key: str,
    phase_path: list[str],
) -> None:
    """Merge a flow tag into each produced MediaItem.generation_metadata.

    ``generation_metadata`` is a JSON-encoded string in the DB (see
    ``database.MediaItem``). We load, merge, dump. No-op when nothing to tag.
    """
    if not media_ids or flow_id is None:
        return
    from database import MediaItem  # late import — avoid circular at module load

    tag = {
        "source": "flow",
        "flow_id": flow_id,
        "equation_key": equation_key,
        "phase_path": list(phase_path),
    }
    async with _open_session() as session:
        result = await session.execute(
            select(MediaItem).where(MediaItem.id.in_(media_ids))
        )
        for row in result.scalars().all():
            existing: dict[str, Any] = {}
            if row.generation_metadata:
                try:
                    parsed = json.loads(row.generation_metadata)
                    if isinstance(parsed, dict):
                        existing = parsed
                except ValueError:
                    existing = {}
            existing.update(tag)
            row.generation_metadata = json.dumps(existing)
        await session.commit()


async def restore_trashed_media_silently(media_ids: list[int]) -> None:
    """Clear deleted_at on any of these media that are currently trashed.

    Called from the flow engine's store-hit path: when an equation
    cache-hits and re-asserts a media_id as a current output, that asset
    should not remain trashed. We update only rows where deleted_at is set,
    then broadcast so the trash screen and browse views refresh. Failures
    are logged and swallowed — a problem here must not break the cache hit.
    """
    if not media_ids:
        return
    try:
        from database import MediaItem  # late import — avoid circular at load
    except Exception:
        log.exception("restore_trashed_media: failed to import MediaItem")
        return
    try:
        async with _open_session() as session:
            result = await session.execute(
                select(MediaItem.id).where(
                    MediaItem.id.in_(media_ids),
                    MediaItem.deleted_at.is_not(None),
                )
            )
            restored_ids = [row[0] for row in result.all()]
            if not restored_ids:
                return
            await session.execute(
                update(MediaItem)
                .where(MediaItem.id.in_(restored_ids))
                .values(deleted_at=None)
            )
            await session.commit()
    except Exception:
        log.exception(
            "restore_trashed_media: update failed for media_ids=%s", media_ids
        )
        return

    try:
        from utils.websocket import ws_manager
        await ws_manager.broadcast(
            "media_bulk_restored",
            {"count": len(restored_ids), "media_ids": restored_ids},
        )
    except Exception:
        log.exception("restore_trashed_media: broadcast failed")


_IMAGE_MIME_BY_FORMAT = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "gif": "image/gif",
    "webp": "image/webp",
    "bmp": "image/bmp",
    "tiff": "image/tiff",
    "tif": "image/tiff",
}


async def _default_load_media_image(media_id: int) -> tuple[bytes, str]:
    """Read a library media item's bytes for inline vision attachment.

    Returns ``(data, mime)``. Providers want a data URL with a correct
    ``image/*`` mime; we derive it from the library's ``file_format`` rather
    than sniffing bytes so weirdly-extensioned files still get a sensible
    label. Raises FileNotFoundError when the media row or its file on disk
    is missing — the evaluator maps that to RESOURCE_ERROR.
    """
    from database import MediaItem

    async with _open_session() as session:
        result = await session.execute(
            select(MediaItem.file_path, MediaItem.file_format).where(
                MediaItem.id == media_id
            )
        )
        row = result.one_or_none()
    if row is None or not row[0]:
        raise FileNotFoundError(f"media {media_id} not found")
    file_path, file_format = row[0], (row[1] or "").lower()
    path = Path(file_path)
    if not path.is_file():
        raise FileNotFoundError(f"media {media_id} file missing: {file_path}")
    mime = _IMAGE_MIME_BY_FORMAT.get(file_format, "image/jpeg")
    data = await asyncio.to_thread(path.read_bytes)
    return data, mime


def _validate_tool_inputs(tool_id: str, inputs: dict[str, Any]) -> None:
    """Fail fast when required tool inputs are missing or None.

    Without this the None flows to the provider and comes back as whatever
    cryptic downstream error the worker happens to emit. Validating against
    the tool's own parameter_schema at the flow boundary turns these into a
    clean TOOL_ERROR naming the field.

    Tool-not-found or registry-init failures fall through silently so
    execute_call_tool surfaces them as the real error downstream.
    """
    try:
        from providers.registry import ProviderRegistry
    except ImportError:
        return
    try:
        registry = ProviderRegistry.get_instance()
    except Exception:  # noqa: BLE001 — registry init failures fall through
        return
    pair = registry.get_tool(tool_id)
    if pair is None:
        return
    _, descriptor = pair
    schema = getattr(descriptor, "parameter_schema", None) or {}
    required = schema.get("required") or []
    props = schema.get("properties") or {}
    missing: list[str] = []
    for name in required:
        if name not in inputs or inputs[name] is None:
            missing.append(name)
            continue
        value = inputs[name]
        # Catch the second-most-common variant: required string is present
        # but empty after template rendering / code extraction.
        expected_type = (props.get(name) or {}).get("type")
        if expected_type == "string" and isinstance(value, str) and not value.strip():
            missing.append(name)
    if not missing:
        return
    names = ", ".join(repr(n) for n in missing)
    raise EvaluatorError(
        f"tool {tool_id!r}: required input(s) {names} are missing or empty.",
        category=TOOL_ERROR,
    )


def _tool_is_registered(tool_id: str) -> bool:
    """Return True iff the STP registry currently has this tool.

    Used by ``ToolCallEvaluator`` as a pre-flight check so the evaluator can
    signal TOOL_UNAVAILABLE (park the equation in WAITING_FOR_TOOL) instead
    of letting ``execute_call_tool`` raise a generic "not found" ValueError
    that the engine would surface as a hard error.
    """
    try:
        from providers.registry import ProviderRegistry
    except ImportError:
        return True  # no registry module — can't pre-check, let runtime decide
    try:
        registry = ProviderRegistry.get_instance()
    except Exception:
        return True
    try:
        return registry.get_tool(tool_id) is not None
    except Exception:
        return True


def _merge_tool_inputs(
    definition: dict[str, Any], resolved_inputs: dict[str, Any]
) -> dict[str, Any]:
    """Combine static ``definition['params']`` with evaluator-resolved kwargs.

    The DSL splits a ``tool(...)`` call's kwargs into literal (static) and
    NodeRef-bearing (dynamic) halves at build time. The engine resolves the
    dynamic half before handing us ``resolved_inputs``. The actual tool needs
    both merged back together.
    """
    merged: dict[str, Any] = {}
    static = definition.get("params") or {}
    if isinstance(static, dict):
        merged.update(static)
    merged.update(resolved_inputs)
    return merged


def _normalize_tool_media_inputs(inputs: dict[str, Any]) -> dict[str, Any]:
    """Coerce promoted web-search rows in tool media inputs to media ids.

    ``hitl.select(web_search(..., kind="images"))`` returns the selected row
    with ``media_id`` attached after URL-media promotion. Flow authors should
    be able to pass that selected row directly as an image input without
    adding a second ``fetch_media`` step.
    """
    out = dict(inputs)
    raw_images = out.get("input_images")
    if isinstance(raw_images, (list, tuple)):
        normalized: list[Any] = []
        changed = False
        for item in raw_images:
            if isinstance(item, dict) and isinstance(item.get("media_id"), int):
                normalized.append(item["media_id"])
                changed = True
            else:
                normalized.append(item)
        if changed:
            out["input_images"] = normalized
    elif isinstance(raw_images, dict) and isinstance(raw_images.get("media_id"), int):
        out["input_images"] = [raw_images["media_id"]]

    raw_image = out.get("input_image")
    if isinstance(raw_image, dict) and isinstance(raw_image.get("media_id"), int):
        out["input_image"] = raw_image["media_id"]
    return out


async def _run_single_tool_job(
    tool_id: str,
    inputs: dict[str, Any],
    *,
    seed: Optional[int],
    project_id: Optional[int] = None,
) -> dict[str, Any]:
    """Run one ``execute_call_tool`` invocation in a dedicated session.

    The DSL's ``tool(...)`` takes one flat kwargs space, matching the tool's
    single ``parameter_schema``; ``execute_call_tool`` consumes that same single
    ``parameters`` namespace, so the whole bag passes straight through.
    """
    from agent.v2.tools.call_tool import execute_call_tool

    parameters = dict(inputs)
    if seed is not None and "seed" not in parameters:
        parameters["seed"] = seed
    async with _open_session() as session:
        return await execute_call_tool(
            tool_id=tool_id,
            parameters=parameters,
            session=session,
            project_id=project_id,
        )


class ToolCallEvaluator:
    """Submit a DSL ``tool()`` call through the agent's call-tool path.

    ``n > 1`` fans out ``n`` parallel jobs, each with a distinct seed derived
    from the equation's base seed. That matches the DSL's contract (``n`` is
    a candidate-generation knob, not a batching hint) and keeps the result
    shape simple (``value = [media_id, ...]``).
    """

    def __init__(
        self,
        *,
        run_tool: Optional[
            Callable[..., Awaitable[dict[str, Any]]]
        ] = None,
        tag_media: Optional[Callable[..., Awaitable[None]]] = None,
    ) -> None:
        # Injection points so tests can mock the generation path without
        # touching a real database or queue.
        self._run_tool = run_tool or _run_single_tool_job
        self._tag_media = tag_media or _tag_media_with_flow
        # Only gate on registry availability when we're calling the real
        # generation path. Tests inject ``run_tool`` with stub tool ids that
        # aren't (and shouldn't be) registered.
        self._check_registry = run_tool is None

    async def __call__(self, request: EvaluationRequest) -> EvaluationResult:
        tool_id = request.definition.get("tool_id") or request.definition.get("tool")
        if not tool_id:
            raise EvaluatorError(
                f"tool_call equation {request.equation_key!r} missing tool_id",
                category=TOOL_ERROR,
            )
        if self._check_registry and not _tool_is_registered(tool_id):
            raise EvaluatorError(
                f"Tool {tool_id!r} is not registered yet.",
                category=TOOL_UNAVAILABLE,
            )
        inputs = _normalize_tool_media_inputs(
            _merge_tool_inputs(request.definition, request.resolved_inputs)
        )
        # `params_from`: seed the call from a prior library item's recorded
        # generation parameters, then let the flow's own kwargs win. Resolved
        # the same way as the agent's run_code path so both behave identically.
        params_from = inputs.pop("params_from", None)
        if params_from is not None:
            from agent.v2.tools.library import resolve_params_from
            async with _open_session() as session:
                inputs = await resolve_params_from(session, tool_id, params_from, inputs)
        _validate_tool_inputs(tool_id, inputs)

        try:
            result = await self._run_tool(
                tool_id, inputs, seed=request.seed,
                project_id=request.project_id,
            )
            media_ids = [result["media_id"]]
            value: Any = result["media_id"]
        except EvaluatorError:
            raise
        except Exception as exc:  # noqa: BLE001 — classify + wrap
            _raise_tool_error(exc)
            raise  # unreachable — _raise_tool_error always raises

        try:
            await self._tag_media(
                media_ids,
                flow_id=request.flow_id,
                equation_key=request.equation_key,
                phase_path=request.phase_path,
            )
        except Exception:
            # Tagging is best-effort — don't fail the equation if the library
            # DB update trips. The generation itself succeeded.
            log.exception(
                "flow media tagging failed for %s (flow=%s)",
                request.equation_key,
                request.flow_id,
            )

        compute_duration_ms = await _extract_compute_duration_ms(media_ids)
        return EvaluationResult(
            value=value,
            media_ids=media_ids,
            compute_duration_ms=compute_duration_ms,
        )


# =============================================================================
# LLM evaluator
# =============================================================================


def _render_template(template: str, bindings: dict[str, Any]) -> str:
    """Render a DSL prompt template with ``resolved_inputs`` substitutions.

    ``_template_of`` in the DSL produces either a bare literal string (no
    bindings) or the single placeholder ``"{0}"`` with a ``{"0": noderef}``
    binding. Integer-keyed bindings map to positional ``.format`` args (so
    ``{0}`` works), non-integer keys go through as named substitutions for
    future DSL extensions.
    """
    if not bindings:
        return template
    positional_pairs = sorted(
        ((int(k), v) for k, v in bindings.items() if str(k).isdigit()),
        key=lambda kv: kv[0],
    )
    positional = [v for _, v in positional_pairs]
    named = {k: v for k, v in bindings.items() if not str(k).isdigit()}
    try:
        return template.format(*positional, **named)
    except (IndexError, KeyError) as exc:
        raise EvaluatorError(
            f"prompt template render failed: {exc}", category=LLM_ERROR,
        ) from exc


def _parse_structured_response(content: str, response_format: Any) -> Any:
    """Parse an LLM response string according to ``response_format``.

    The DSL currently accepts an opaque ``response_format`` — for JSON we
    try to decode. On schema-level failures (bad JSON, refusal) we raise
    LLM_ERROR so the engine retries once per policy.
    """
    if response_format is None:
        return content
    text = (content or "").strip()
    if not text:
        raise EvaluatorError("LLM returned empty content", category=LLM_ERROR)
    # Strip trivial ``` fencing agents sometimes emit despite being asked not to.
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.DOTALL).strip()
    try:
        return json.loads(text)
    except ValueError as exc:
        raise EvaluatorError(
            f"LLM response is not valid JSON: {exc}", category=LLM_ERROR,
        ) from exc


def _response_format_schema_for_prompt(response_format: Any) -> Any:
    if not isinstance(response_format, dict):
        return response_format
    schema = response_format.get("schema")
    if schema is not None:
        return schema
    return response_format


def _structured_response_instruction(response_format: Any) -> str:
    """Instruction appended to structured LLM prompts.

    ``response_format`` is a DSL-level simplified schema, not necessarily an
    OpenAI wire-format response_format. Some configured LLM endpoints ignore
    provider-native JSON mode, so prompt-level instruction is the portable
    contract the runtime can rely on before parsing.
    """
    if response_format is None:
        return ""
    schema = _response_format_schema_for_prompt(response_format)
    return (
        "\n\nReturn ONLY valid JSON. Do not include markdown fences, prose, "
        "or commentary. The JSON must match this schema:\n"
        f"{json.dumps(schema, ensure_ascii=False, indent=2)}"
    )


_LLM_VALID_ROLES = ("agent", "agent-fast")

# Hard ceiling on a single llm() evaluation. The underlying llm_completion has
# no timeout of its own, so without this the equation can stay in ``computing``
# forever when a provider wedges. Flow prompts are almost always short
# classification / composition calls; 60s is well past a normal response and
# short enough that a failed call plus its one LLM_ERROR retry still fits in a
# user-tolerable window.
LLM_CALL_TIMEOUT_SECONDS = 60.0


class LLMEvaluator:
    """Call the configured LLM for a DSL ``llm()`` equation.

    The ``model`` field on the equation definition is the Stimma role to
    resolve — either ``agent`` (default, high-quality) or ``agent-fast``
    (latency-optimized). Values outside that set fall back to the evaluator's
    default role. Resolves the effective LLM config via ``llm_resolver``,
    renders the prompt, and returns either the raw text content (no
    ``response_format``) or the parsed JSON payload.
    """

    def __init__(
        self,
        *,
        completion: Optional[
            Callable[..., Awaitable[Any]]
        ] = None,
        resolve_config: Optional[Callable[..., Awaitable[Any]]] = None,
        resolve_image: Optional[
            Callable[[int], Awaitable[tuple[bytes, str]]]
        ] = None,
        role: str = "agent",
    ) -> None:
        self._completion = completion
        self._resolve_config = resolve_config
        self._resolve_image = resolve_image
        self._role = role

    async def __call__(self, request: EvaluationRequest) -> EvaluationResult:
        prompt_tmpl = request.definition.get("prompt_template", "") or ""
        system_tmpl = request.definition.get("system_template", "") or ""
        response_format = request.definition.get("response_format")
        prompt_bindings = request.resolved_inputs.get("prompt") or {}
        system_bindings = request.resolved_inputs.get("system") or {}
        images_binding = request.resolved_inputs.get("images")

        requested_model = request.definition.get("model")
        role = requested_model if requested_model in _LLM_VALID_ROLES else self._role
        think = bool(request.definition.get("think", False))

        prompt = _render_template(prompt_tmpl, prompt_bindings)
        prompt += _structured_response_instruction(response_format)
        system = _render_template(system_tmpl, system_bindings) if system_tmpl else ""

        image_blocks: list[dict[str, Any]] = []
        if images_binding is not None:
            image_blocks = await self._build_image_blocks(images_binding)

        messages: list[dict[str, Any]] = []
        if system:
            messages.append({"role": "system", "content": system})
        if image_blocks:
            messages.append({
                "role": "user",
                "content": [{"type": "text", "text": prompt}, *image_blocks],
            })
        else:
            messages.append({"role": "user", "content": prompt})

        # Flow LLM calls default to no-thinking — most are short classification
        # or prompt-assembly calls where thinking burns latency without improving
        # output. The DSL exposes ``think=True`` for the rare step that needs it
        # (multi-step reasoning, tricky planning).
        completion_kwargs: dict[str, Any] = {
            "extra_body": {"chat_template_kwargs": {"enable_thinking": think}},
        }
        if think:
            completion_kwargs["thinking"] = {"type": "enabled", "budget_tokens": 1024}

        try:
            config = await self._get_config(role)
            completion = await self._get_completion()
            prompt_preview = prompt[:120].replace("\n", " ")
            log.info(
                "flow llm[%s] role=%s think=%s start: %r",
                request.equation_key, role, think, prompt_preview,
            )
            resp = await asyncio.wait_for(
                completion(config, messages, **completion_kwargs),
                timeout=LLM_CALL_TIMEOUT_SECONDS,
            )
            log.info(
                "flow llm[%s] role=%s think=%s done",
                request.equation_key, role, think,
            )
        except asyncio.TimeoutError as exc:
            log.warning(
                "flow llm[%s] role=%s timed out after %.0fs",
                request.equation_key, role, LLM_CALL_TIMEOUT_SECONDS,
            )
            raise EvaluatorError(
                f"LLM call timed out after {LLM_CALL_TIMEOUT_SECONDS:.0f}s",
                category=TRANSIENT,
            ) from exc
        except EvaluatorError:
            raise
        except Exception as exc:  # noqa: BLE001
            _raise_tool_error(exc)
            raise  # unreachable

        content = getattr(resp, "content", None)
        if content is None and isinstance(resp, dict):
            content = resp.get("content", "")
        if content is None:
            content = str(resp)
        value = _parse_structured_response(content, response_format)
        return EvaluationResult(value=value)

    async def _get_config(self, role: str) -> Any:
        if self._resolve_config is not None:
            return await self._resolve_config(role)
        from llm_resolver import get_effective_llm_config
        return await get_effective_llm_config(role)

    async def _get_completion(self) -> Callable[..., Awaitable[Any]]:
        if self._completion is not None:
            return self._completion
        from llm import llm_completion
        return llm_completion

    async def _build_image_blocks(self, binding: Any) -> list[dict[str, Any]]:
        """Turn resolved images= binding into OpenAI-style image content blocks.

        ``binding`` is whatever ``resolved_inputs['images']`` is after the
        engine walks the dynamic structure — a single media id (int) or a
        list of media ids. Each id is loaded from the library, base64-
        encoded, and wrapped in an ``image_url`` block with a matching data
        URL. A missing or unreadable file raises an EvaluatorError so the
        flow's fallback / retry behavior kicks in instead of silently
        sending a text-only call to the provider.
        """
        if binding is None:
            return []
        items = binding if isinstance(binding, list) else [binding]
        blocks: list[dict[str, Any]] = []
        for item in items:
            media_id = _media_id_from_value(item)
            if media_id is None:
                raise EvaluatorError(
                    f"llm(images=): expected media id (int), got "
                    f"{type(item).__name__}",
                    category=LLM_ERROR,
                )
            try:
                data, mime = await self._load_image(media_id)
            except EvaluatorError:
                raise
            except FileNotFoundError as exc:
                raise EvaluatorError(
                    f"llm(images=): media {media_id} file not found on disk",
                    category=RESOURCE_ERROR,
                ) from exc
            except Exception as exc:  # noqa: BLE001
                raise EvaluatorError(
                    f"llm(images=): failed to load media {media_id}: {exc}",
                    category=LLM_ERROR,
                ) from exc
            import base64
            b64 = base64.b64encode(data).decode("ascii")
            blocks.append({
                "type": "image_url",
                "image_url": {"url": f"data:{mime};base64,{b64}"},
            })
        return blocks

    async def _load_image(self, media_id: int) -> tuple[bytes, str]:
        if self._resolve_image is not None:
            return await self._resolve_image(media_id)
        return await _default_load_media_image(media_id)


def _media_id_from_value(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, dict):
        mid = value.get("media_id") or value.get("mediaId")
        if isinstance(mid, int) and not isinstance(mid, bool):
            return mid
        media = value.get("media")
        if isinstance(media, dict):
            nested = media.get("media_id") or media.get("mediaId")
            if isinstance(nested, int) and not isinstance(nested, bool):
                return nested
    return None


def _media_ids_from_code_value(value: Any, output_type: str) -> list[int]:
    """Surface code() media outputs to ``EvaluationResult.media_ids``.

    ``code(output_type="media")`` is an author-declared promise that the
    return value is a media id; ``"list[media]"`` promises a list of them.
    Without surfacing the ids the UI has no way to distinguish "an integer
    that happens to equal a media id" from "an arbitrary scalar" and falls
    back to rendering the raw text — the "best_image shows '1288' instead
    of the image" failure mode.
    """
    if output_type == "media":
        mid = _media_id_from_value(value)
        return [mid] if mid is not None else []
    if output_type == "list[media]":
        if not isinstance(value, list):
            return []
        out: list[int] = []
        for item in value:
            mid = _media_id_from_value(item)
            if mid is not None:
                out.append(mid)
        return out
    return []


# =============================================================================
# LLM batch + slot evaluators (llm(n=N))
# =============================================================================
#
# For llm(n=N), the DSL builds one LLM_BATCH equation plus N LLM_SLOT
# equations depending on it. The batch runs a single LLM call asking for
# all N items (high diversity, one round-trip). Each slot's first evaluation
# just reads batch.result[slot_index] — no extra LLM call. When a slot is
# invalidated directly (attempt > 1), its evaluator runs a "solo-gen" LLM
# call that sees the peer slots' current values and asks for one more item
# meaningfully distinct from them. When the batch itself is invalidated,
# the engine resets all slot attempts to 1 so they re-read from the fresh
# batch result (see FlowRun._invalidate_equation).


_BATCH_INSTRUCTION_JSON = (
    "\n\nReturn a JSON array of exactly {n} items. Each item should match "
    "the schema described below. The array must have exactly {n} elements, "
    "each meaningfully different from the others. Return ONLY valid JSON: "
    "no markdown fences, prose, or commentary.\nSchema for each item:\n{schema}"
)
_BATCH_INSTRUCTION_TEXT = (
    "\n\nReturn exactly {n} numbered items, one per line, prefixed like "
    "\"1. \", \"2. \", etc. Each item should be meaningfully different from "
    "the others."
)
_SOLO_INSTRUCTION_JSON = (
    "\n\nThe following items already exist:\n{peers}\n\n"
    "Generate ONE additional item that is meaningfully distinct from every "
    "existing item above. Return a JSON array containing only that one new "
    "item. Return ONLY valid JSON: no markdown fences, prose, or commentary.\n"
    "Schema for the item:\n{schema}"
)
_SOLO_INSTRUCTION_TEXT = (
    "\n\nThe following items already exist:\n{peers}\n\n"
    "Generate ONE additional item that is meaningfully distinct from every "
    "existing item above. Return only the new item, with no numbering or "
    "preamble."
)


def _llm_batch_prompt_suffix(n: int, response_format: Any) -> str:
    tmpl = _BATCH_INSTRUCTION_JSON if response_format else _BATCH_INSTRUCTION_TEXT
    schema = json.dumps(
        _response_format_schema_for_prompt(response_format),
        ensure_ascii=False,
        indent=2,
    )
    return tmpl.format(n=n, schema=schema)


def _llm_solo_prompt_suffix(peers: list[Any], response_format: Any) -> str:
    tmpl = _SOLO_INSTRUCTION_JSON if response_format else _SOLO_INSTRUCTION_TEXT
    if response_format:
        rendered = json.dumps(peers, ensure_ascii=False, indent=2)
    else:
        rendered = "\n".join(f"- {p}" for p in peers)
    schema = json.dumps(
        _response_format_schema_for_prompt(response_format),
        ensure_ascii=False,
        indent=2,
    )
    return tmpl.format(peers=rendered, schema=schema)


def _parse_batch_response(content: str, response_format: Any, n: int) -> list[Any]:
    """Parse a batch LLM response into exactly N items."""
    text = (content or "").strip()
    if not text:
        raise EvaluatorError("LLM batch returned empty content", category=LLM_ERROR)
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.DOTALL).strip()

    if response_format:
        try:
            parsed = json.loads(text)
        except ValueError as exc:
            raise EvaluatorError(
                f"LLM batch response is not valid JSON: {exc}",
                category=LLM_ERROR,
            ) from exc
        if not isinstance(parsed, list):
            raise EvaluatorError(
                f"LLM batch response must be a JSON array; got "
                f"{type(parsed).__name__}",
                category=LLM_ERROR,
            )
        items = parsed
    else:
        items = _parse_numbered_list(text)

    if len(items) != n:
        raise EvaluatorError(
            f"LLM batch returned {len(items)} items; expected {n}",
            category=LLM_ERROR,
        )
    return items


def _parse_numbered_list(text: str) -> list[str]:
    """Parse a text response formatted as a numbered list into items.

    Accepts "1." / "1)" / "- " style prefixes; strips numbering. Returns the
    items in source order. Blank lines are ignored.
    """
    items: list[str] = []
    current: list[str] = []

    def flush() -> None:
        if current:
            joined = "\n".join(current).strip()
            if joined:
                items.append(joined)
            current.clear()

    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if not line.strip():
            flush()
            continue
        stripped = line.lstrip()
        m = re.match(r"^(?:\d+[.)]|[-*])\s+(.*)$", stripped)
        if m:
            flush()
            current.append(m.group(1))
        else:
            # Continuation of the previous item (wrapped line).
            current.append(stripped)
    flush()
    return items


def _parse_solo_response(content: str, response_format: Any) -> Any:
    """Parse a solo-gen LLM response into a single item."""
    text = (content or "").strip()
    if not text:
        raise EvaluatorError("LLM solo-gen returned empty content", category=LLM_ERROR)
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.DOTALL).strip()

    if response_format:
        try:
            parsed = json.loads(text)
        except ValueError as exc:
            raise EvaluatorError(
                f"LLM solo-gen response is not valid JSON: {exc}",
                category=LLM_ERROR,
            ) from exc
        if isinstance(parsed, list):
            if len(parsed) != 1:
                raise EvaluatorError(
                    f"LLM solo-gen returned {len(parsed)} items; expected 1",
                    category=LLM_ERROR,
                )
            return parsed[0]
        return parsed

    return text


class LLMBatchEvaluator(LLMEvaluator):
    """Single LLM call that produces N items for llm(n=N).

    Inherits image/system/prompt plumbing from ``LLMEvaluator``; overrides
    ``__call__`` to append batch-generation instructions to the user prompt
    and parse N items out of the response. Returns a list as
    ``EvaluationResult.value`` so downstream slot evaluators can index into
    it.
    """

    async def __call__(self, request: EvaluationRequest) -> EvaluationResult:
        n = int(request.definition.get("n", 1) or 1)
        if n < 1:
            raise EvaluatorError(
                f"llm_batch equation {request.equation_key!r} has invalid n={n}",
                category=LLM_ERROR,
            )
        response_format = request.definition.get("response_format")

        prompt_tmpl = (request.definition.get("prompt_template") or "") + (
            _llm_batch_prompt_suffix(n, response_format)
        )
        system_tmpl = request.definition.get("system_template") or ""
        prompt_bindings = request.resolved_inputs.get("prompt") or {}
        system_bindings = request.resolved_inputs.get("system") or {}
        images_binding = request.resolved_inputs.get("images")

        requested_model = request.definition.get("model")
        role = requested_model if requested_model in _LLM_VALID_ROLES else self._role
        think = bool(request.definition.get("think", False))

        prompt = _render_template(prompt_tmpl, prompt_bindings)
        system = _render_template(system_tmpl, system_bindings) if system_tmpl else ""

        image_blocks: list[dict[str, Any]] = []
        if images_binding is not None:
            image_blocks = await self._build_image_blocks(images_binding)

        messages: list[dict[str, Any]] = []
        if system:
            messages.append({"role": "system", "content": system})
        if image_blocks:
            messages.append({
                "role": "user",
                "content": [{"type": "text", "text": prompt}, *image_blocks],
            })
        else:
            messages.append({"role": "user", "content": prompt})

        completion_kwargs: dict[str, Any] = {
            "extra_body": {"chat_template_kwargs": {"enable_thinking": think}},
        }
        if think:
            completion_kwargs["thinking"] = {"type": "enabled", "budget_tokens": 1024}

        content = await self._run_llm(
            role, think, messages, completion_kwargs, request.equation_key,
        )
        items = _parse_batch_response(content, response_format, n)
        return EvaluationResult(value=items)

    async def _run_llm(
        self,
        role: str,
        think: bool,
        messages: list[dict[str, Any]],
        completion_kwargs: dict[str, Any],
        equation_key: str,
    ) -> str:
        try:
            config = await self._get_config(role)
            completion = await self._get_completion()
            log.info(
                "flow llm_batch[%s] role=%s think=%s start",
                equation_key, role, think,
            )
            resp = await asyncio.wait_for(
                completion(config, messages, **completion_kwargs),
                timeout=LLM_CALL_TIMEOUT_SECONDS,
            )
            log.info(
                "flow llm_batch[%s] role=%s think=%s done",
                equation_key, role, think,
            )
        except asyncio.TimeoutError as exc:
            raise EvaluatorError(
                f"LLM batch timed out after {LLM_CALL_TIMEOUT_SECONDS:.0f}s",
                category=TRANSIENT,
            ) from exc
        except EvaluatorError:
            raise
        except Exception as exc:  # noqa: BLE001
            _raise_tool_error(exc)
            raise
        content = getattr(resp, "content", None)
        if content is None and isinstance(resp, dict):
            content = resp.get("content", "")
        if content is None:
            content = str(resp)
        return content


class LLMSlotEvaluator(LLMEvaluator):
    """Per-slot evaluator for llm(n=N) slots.

    Two paths:

    - ``attempt == 1`` — copy ``batch.result[slot_index]``. No LLM call.
    - ``attempt > 1`` — solo-gen: read sibling slot results via the injected
      ``graph_getter`` and call the LLM for one new item distinct from those
      peers. Sibling reads are not declared graph dependencies (that would
      cycle); the read is lazy at eval time and only feeds the prompt.

    ``graph_getter`` is a callable returning the current in-memory
    ``EquationGraph`` so we can look up peer slot equations by key prefix.
    """

    def __init__(
        self,
        *,
        completion: Optional[Callable[..., Awaitable[Any]]] = None,
        resolve_config: Optional[Callable[..., Awaitable[Any]]] = None,
        resolve_image: Optional[
            Callable[[int], Awaitable[tuple[bytes, str]]]
        ] = None,
        role: str = "agent",
        graph_getter: Optional[Callable[[], Any]] = None,
    ) -> None:
        super().__init__(
            completion=completion,
            resolve_config=resolve_config,
            resolve_image=resolve_image,
            role=role,
        )
        self._graph_getter = graph_getter

    def set_graph_getter(self, graph_getter: Callable[[], Any]) -> None:
        """Inject the graph accessor after construction.

        The production runtime can't pass a getter at registry-build time
        because the graph doesn't exist yet (it's built per-run). The
        ``FlowRuntime`` wires this on construction.
        """
        self._graph_getter = graph_getter

    async def __call__(self, request: EvaluationRequest) -> EvaluationResult:
        slot_index = int(request.definition.get("slot_index", -1))
        batch_key = request.definition.get("batch_key")
        if slot_index < 0 or not batch_key:
            raise EvaluatorError(
                f"llm_slot equation {request.equation_key!r} missing slot_index / batch_key",
                category=LLM_ERROR,
            )

        batch_value = request.resolved_inputs.get("batch")
        if not isinstance(batch_value, list):
            raise EvaluatorError(
                f"llm_slot equation {request.equation_key!r}: batch upstream did not "
                f"produce a list (got {type(batch_value).__name__})",
                category=LLM_ERROR,
            )
        if slot_index >= len(batch_value):
            raise EvaluatorError(
                f"llm_slot equation {request.equation_key!r}: slot_index={slot_index} "
                f"out of range for batch of size {len(batch_value)}",
                category=LLM_ERROR,
            )

        if request.attempt <= 1:
            return EvaluationResult(value=batch_value[slot_index])

        # attempt > 1: solo-gen with peer context.
        peer_values = self._read_peer_slot_values(
            batch_key=str(batch_key),
            batch_value=batch_value,
            my_slot_index=slot_index,
        )

        response_format = request.definition.get("response_format")
        if self._graph_getter is None:
            raise EvaluatorError(
                "llm_slot solo-gen requires graph_getter; evaluator misconfigured",
                category=LLM_ERROR,
            )
        graph = self._graph_getter()
        batch_eq = graph.try_get(str(batch_key))
        if batch_eq is None:
            raise EvaluatorError(
                f"llm_slot equation {request.equation_key!r}: batch equation "
                f"{batch_key!r} not found",
                category=LLM_ERROR,
            )

        prompt_tmpl = (batch_eq.definition.get("prompt_template") or "") + (
            _llm_solo_prompt_suffix(peer_values, response_format)
        )
        system_tmpl = batch_eq.definition.get("system_template") or ""
        # Slot carries the same prompt/system/images bindings as its batch
        # (see llm(n=N) in primitives.py) so rendering works without going
        # back to the batch's resolved_inputs.
        prompt_bindings = request.resolved_inputs.get("prompt") or {}
        system_bindings = request.resolved_inputs.get("system") or {}
        images_binding = request.resolved_inputs.get("images")

        requested_model = batch_eq.definition.get("model")
        role = requested_model if requested_model in _LLM_VALID_ROLES else self._role
        think = bool(batch_eq.definition.get("think", False))

        prompt = _render_template(prompt_tmpl, prompt_bindings)
        system = _render_template(system_tmpl, system_bindings) if system_tmpl else ""

        image_blocks: list[dict[str, Any]] = []
        if images_binding is not None:
            image_blocks = await self._build_image_blocks(images_binding)

        messages: list[dict[str, Any]] = []
        if system:
            messages.append({"role": "system", "content": system})
        if image_blocks:
            messages.append({
                "role": "user",
                "content": [{"type": "text", "text": prompt}, *image_blocks],
            })
        else:
            messages.append({"role": "user", "content": prompt})

        completion_kwargs: dict[str, Any] = {
            "extra_body": {"chat_template_kwargs": {"enable_thinking": think}},
        }
        if think:
            completion_kwargs["thinking"] = {"type": "enabled", "budget_tokens": 1024}

        try:
            config = await self._get_config(role)
            completion = await self._get_completion()
            log.info(
                "flow llm_slot[%s] solo-gen role=%s attempt=%s",
                request.equation_key, role, request.attempt,
            )
            resp = await asyncio.wait_for(
                completion(config, messages, **completion_kwargs),
                timeout=LLM_CALL_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError as exc:
            raise EvaluatorError(
                f"LLM slot solo-gen timed out after {LLM_CALL_TIMEOUT_SECONDS:.0f}s",
                category=TRANSIENT,
            ) from exc
        except EvaluatorError:
            raise
        except Exception as exc:  # noqa: BLE001
            _raise_tool_error(exc)
            raise

        content = getattr(resp, "content", None)
        if content is None and isinstance(resp, dict):
            content = resp.get("content", "")
        if content is None:
            content = str(resp)
        value = _parse_solo_response(content, response_format)
        return EvaluationResult(value=value)

    def _read_peer_slot_values(
        self,
        *,
        batch_key: str,
        batch_value: list[Any],
        my_slot_index: int,
    ) -> list[Any]:
        """Collect current peer slot values.

        Preference order per peer index:
          1. The sibling slot equation's current .result (if COMPLETED).
          2. Otherwise the batch's value at that index (the pre-solo-gen
             starting point).
        Returns values in slot-index order with the calling slot omitted.
        """
        from .graph import EquationStatus
        peers: list[Any] = []
        graph = self._graph_getter() if self._graph_getter is not None else None
        prefix = f"{batch_key}/slot:"
        for i, fallback in enumerate(batch_value):
            if i == my_slot_index:
                continue
            peer_value: Any = fallback
            if graph is not None:
                peer_eq = graph.try_get(f"{prefix}{i}")
                if peer_eq is not None and peer_eq.status == EquationStatus.COMPLETED:
                    if peer_eq.result is not None:
                        peer_value = peer_eq.result
            peers.append(peer_value)
        return peers


# =============================================================================
# Code evaluator
# =============================================================================


def _default_workspace_root() -> Path:
    """A writable scratch directory for sandboxed code runs.

    The agent's sandbox expects a real filesystem path (used by
    ``_make_safe_open`` for workspace-scoped file access). Flows don't have
    a persistent workspace, so we use a subdirectory under the flows root
    that we mkdir once per run.
    """
    import tempfile
    root = Path(tempfile.gettempdir()) / "stimma_flow_code"
    root.mkdir(parents=True, exist_ok=True)
    return root


async def _run_code_snippet(
    source: str, inputs: dict[str, Any], *, workspace_dir: Optional[Path] = None,
) -> Any:
    """Execute a flow ``code()`` snippet in the agent's sandbox primitives.

    Shares the allow-listed builtins / safe import / safe open with
    ``run_code_in_sandbox`` (so we're not building a second sandbox). What we
    drop is everything chat-shaped: the ``StimmaSDK`` instance, progress
    tracker, LLM usage capture — flow code doesn't need those. Inputs bind
    into globals directly.

    If the source parses cleanly as a single expression (e.g. ``f"...{n}..."``,
    ``list(range(n))``, ``data["items"]``), it's auto-wrapped with ``return``
    so the value is produced. This matches the DSL's natural authoring style
    — the agent shouldn't need to write ``return x`` around every prompt
    template. Multi-line or statement-shaped sources are run as-is; those
    should use an explicit ``return`` to produce a value.
    """
    import ast

    from agent.v2.code_runtime import build_safe_builtins

    workspace = workspace_dir or _default_workspace_root()

    # Swallow prints — flows aren't a chat context.
    def _noop(*args, **kwargs):
        return None

    builtins = build_safe_builtins(workspace, _noop)

    stripped = source.strip()
    body_source: str
    if not stripped:
        body_source = "return None"
    else:
        try:
            ast.parse(stripped, mode="eval")
        except SyntaxError:
            body_source = source
        else:
            # Pure expression — wrap so its value flows back out.
            body_source = f"return ({stripped})"

    wrapper = "async def __flow_code__():\n"
    for line in body_source.splitlines() or [""]:
        wrapper += f"    {line}\n"

    globals_dict: dict[str, Any] = {
        "__builtins__": builtins,
        "__name__": "__flow_code__",
    }
    globals_dict.update(inputs)

    def _compile() -> Callable[..., Any]:
        exec(compile(wrapper, "<flow_code>", "exec"), globals_dict, globals_dict)
        return globals_dict["__flow_code__"]

    fn = await asyncio.to_thread(_compile)
    return await fn()


async def _invoke_code_callable(fn: Callable[..., Any], inputs: dict[str, Any]) -> Any:
    """Invoke a callable-form code() block with resolved inputs.

    The callable was defined inside the sandboxed module globals during
    graph construction (see ``flow_dsl.loader.build_graph_from_source``),
    so its closure and builtins are already the restricted environment —
    no re-exec needed here. Async callables are awaited; sync callables
    run on a thread to keep the event loop responsive.
    """
    import inspect as _inspect
    if _inspect.iscoroutinefunction(fn):
        return await fn(**inputs)
    return await asyncio.to_thread(lambda: fn(**inputs))


class CodeEvaluator:
    """Evaluate a DSL ``code()`` equation.

    ``resolved_inputs`` for a code equation is ``{"inputs": {name: value}}``
    (see ``flow_runtime.engine._resolve_dynamic_bindings``). Those names
    bind as globals in the sandboxed frame. Any exception from the snippet
    surfaces as CODE_ERROR — the user's repair path is `retry` / `edit flow`.
    """

    def __init__(
        self,
        *,
        run_snippet: Optional[
            Callable[..., Awaitable[Any]]
        ] = None,
    ) -> None:
        self._run_snippet = run_snippet or _run_code_snippet

    async def __call__(self, request: EvaluationRequest) -> EvaluationResult:
        fn = request.definition.get("fn")
        source = request.definition.get("source", "")
        inputs = request.resolved_inputs.get("inputs") or {}
        output_type = request.definition.get("output_type", "json")
        dynamic = request.definition.get("_dynamic") or {}
        dynamic_inputs = dynamic.get("inputs") or {}
        try:
            resolved_inputs, _source_ids, _ = await _resolve_media_inputs_to_objects(
                inputs, dynamic_inputs,
            )
        except EvaluatorError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise EvaluatorError(
                f"code: failed to resolve media inputs: {exc}",
                category=TOOL_ERROR,
            ) from exc
        try:
            if fn is not None:
                value = await _invoke_code_callable(fn, resolved_inputs)
            else:
                value = await self._run_snippet(source, resolved_inputs)
        except EvaluatorError:
            raise
        except Exception as exc:  # noqa: BLE001 — everything from user code
            msg = _format_user_code_error(exc)
            raise EvaluatorError(msg, category=CODE_ERROR) from exc
        # Validate list output types return an actual list. A None return from a
        # list[...] code block silently breaks downstream foreach/hitl.select;
        # catching it here surfaces a clear CODE_ERROR with the original source.
        if output_type.startswith("list[") and not isinstance(value, list):
            raise EvaluatorError(
                f"code() with output_type={output_type!r} must return a list, "
                f"got {type(value).__name__!r} (source: {source!r})",
                category=CODE_ERROR,
            )
        # Media inputs now arrive as Media wrappers; callables may hand them
        # back directly (output_type="media" / "list[media]"). Unwrap to int
        # media ids so downstream equations still see the primitive shape.
        from .media_arg import Media
        if isinstance(value, Media):
            value = value.id
        elif isinstance(value, list):
            value = [v.id if isinstance(v, Media) else v for v in value]
        # When the author declared this code() produces media, surface the
        # ids on the result so the UI renders the actual thumbnail instead
        # of falling back to the integer text preview. Without this, an
        # `is_output` code(output_type="media") returning 1288 shows "1288"
        # in a tile.
        media_ids = _media_ids_from_code_value(value, output_type)
        return EvaluationResult(value=value, media_ids=media_ids)


# =============================================================================
# Info evaluator
# =============================================================================


def _format_info_value(value: Any) -> str:
    """Render a single ``info()`` placeholder as user-friendly markdown.

    Lists/tuples become bullet lists, dicts become ``**key:** value`` bullet
    lines, and other types fall through to ``str()``. Keeps info bodies
    readable when an agent passes a collection straight into a placeholder
    rather than pre-formatting it — Python's default repr (``['a', 'b']``)
    leaks single-quoted syntax into the rendered card.
    """
    if isinstance(value, (list, tuple)):
        if not value:
            return "_(empty)_"
        return "\n".join(f"- {item}" for item in value)
    if isinstance(value, dict):
        if not value:
            return "_(empty)_"
        return "\n".join(f"- **{k}:** {v}" for k, v in value.items())
    return str(value)


class InfoEvaluator:
    """Render an ``info()`` equation's markdown template.

    Pure string substitution over ``resolved_inputs['inputs']`` — no code
    execution. Upstream media ids are propagated by the engine via
    ``resolved_inputs['__upstream_media_ids']`` so the node card can
    display thumbnails next to the rendered text.
    """

    async def __call__(self, request: EvaluationRequest) -> EvaluationResult:
        template = request.definition.get("template", "")
        inputs = request.resolved_inputs.get("inputs") or {}
        media_ids = request.resolved_inputs.get("__upstream_media_ids") or []
        try:
            rendered = template.format_map(
                {k: _format_info_value(v) for k, v in inputs.items()}
            )
        except (KeyError, IndexError) as exc:
            raise EvaluatorError(
                f"info() template placeholder not found: {exc}",
                category=CODE_ERROR,
            ) from exc
        return EvaluationResult(value=rendered, media_ids=list(media_ids))


# =============================================================================
# Library-assembly evaluators (create_set / create_grid / create_document)
# =============================================================================


_RESULT_MEDIA_ID_RE = re.compile(r"<result media_id=(\d+)\s*/>")


def _parse_assembly_result(result_str: str, *, primitive: str) -> int:
    """Pull a media_id out of the string an agent-tool wrapper returns.

    Assemble wrappers (``assemble_set``, ``create_parameter_sweep``) return a
    human-readable string with an embedded ``<result media_id=N />`` tag on
    success and ``Error: ...`` on failure. Parse that here so the evaluator
    can turn it into an ``EvaluationResult`` / ``EvaluatorError``.
    """
    if not isinstance(result_str, str):
        raise EvaluatorError(
            f"{primitive}: unexpected result type {type(result_str).__name__}",
            category=TOOL_ERROR,
        )
    if result_str.startswith("Error:"):
        raise EvaluatorError(result_str, category=TOOL_ERROR)
    m = _RESULT_MEDIA_ID_RE.search(result_str)
    if not m:
        raise EvaluatorError(
            f"{primitive}: could not locate produced media_id in result: "
            f"{result_str!r}",
            category=TOOL_ERROR,
        )
    return int(m.group(1))


def _coerce_media_id(value: Any) -> int:
    """Tolerate resolved upstream values that look like media ids.

    Flow graphs sometimes carry single media ids as dicts (e.g., from a
    tool result or from an llm response_format extraction). Normalize to a
    plain ``int`` so assembly tools receive clean input.
    """
    if isinstance(value, bool):
        raise EvaluatorError(
            f"expected media id (int), got bool", category=TOOL_ERROR,
        )
    if isinstance(value, int):
        return value
    if isinstance(value, dict) and "media_id" in value:
        return int(value["media_id"])
    if isinstance(value, str) and value.isdigit():
        return int(value)
    raise EvaluatorError(
        f"expected media id (int), got {type(value).__name__}",
        category=TOOL_ERROR,
    )


def _coerce_items_list(binding: Any) -> list[int]:
    """Turn the resolved ``items`` binding into ``[media_id, ...]``."""
    if binding is None:
        raise EvaluatorError("items is None", category=TOOL_ERROR)
    if isinstance(binding, list):
        seq = binding
    elif isinstance(binding, tuple):
        seq = list(binding)
    else:
        raise EvaluatorError(
            f"items must resolve to a list; got {type(binding).__name__}",
            category=TOOL_ERROR,
        )
    return [_coerce_media_id(v) for v in seq]


async def _explode_previous_flow_assembly(
    *,
    flow_id: Optional[int],
    equation_key: str,
) -> None:
    """Release members + delete any prior set/grid this flow-equation created.

    The flow "owns" its create_set/create_grid output — on re-run (user
    invalidation, input change, or a re-evaluation that misses the store)
    we produce a fresh grid and the old one becomes orphaned. Its member
    images still carry ``superseded_by = old_grid_id``, so the next
    ``assemble_set`` / ``create_parameter_sweep`` call fails with "Items
    already in a set or grid" when the store returns cached member IDs.

    Find prior assemblies by the flow tag we stamp in
    ``_tag_media_with_flow``, unsupersede their members, drop the file,
    and soft-delete the row. No-op when flow_id is None (unit tests with
    stub evaluators) or no prior assembly exists.
    """
    if flow_id is None:
        return
    from database import MediaItem
    from utils.websocket import broadcast_media_updated

    async with _open_session() as session:
        result = await session.execute(
            select(MediaItem).where(
                MediaItem.file_format.in_(("stimmaset.json", "stimmagrid.json")),
                MediaItem.deleted_at.is_(None),
                func.json_extract(MediaItem.generation_metadata, "$.source") == "flow",
                func.json_extract(MediaItem.generation_metadata, "$.flow_id") == flow_id,
                func.json_extract(MediaItem.generation_metadata, "$.equation_key") == equation_key,
            )
        )
        prior = list(result.scalars().all())
        if not prior:
            return

        freed_member_ids: list[int] = []
        deleted_assembly_ids: list[int] = []
        for assembly in prior:
            members = (await session.execute(
                select(MediaItem).where(MediaItem.superseded_by == assembly.id)
            )).scalars().all()
            member_ids = [m.id for m in members]
            if member_ids:
                await session.execute(
                    update(MediaItem)
                    .where(MediaItem.superseded_by == assembly.id)
                    .values(superseded_by=None, is_hidden=None)
                )
                freed_member_ids.extend(member_ids)

            try:
                if assembly.file_path and os.path.exists(assembly.file_path):
                    os.remove(assembly.file_path)
            except OSError:
                log.warning(
                    "explode prior assembly: failed to delete file %s",
                    assembly.file_path,
                )

            deleted_assembly_ids.append(assembly.id)
            await session.delete(assembly)

        await session.commit()

        if freed_member_ids:
            refreshed = (await session.execute(
                select(MediaItem).where(MediaItem.id.in_(freed_member_ids))
            )).scalars().all()
            if refreshed:
                await broadcast_media_updated(
                    list(refreshed), ["superseded_by", "is_hidden"], session,
                )

    from utils.websocket import ws_manager
    for assembly_id in deleted_assembly_ids:
        await ws_manager.broadcast("media_deleted", {"media_id": assembly_id})
    log.info(
        "flow %s eq %s: exploded %d prior assembl%s, freed %d members",
        flow_id,
        equation_key,
        len(deleted_assembly_ids),
        "y" if len(deleted_assembly_ids) == 1 else "ies",
        len(freed_member_ids),
    )


class CreateSetEvaluator:
    """Evaluate a ``create_set()`` equation.

    Delegates to the same ``assemble_set`` agent tool the LLM uses from
    chat. The tool handles file creation, DB insert, lineage, supersession,
    WebSocket broadcast, and rescan trigger — we just adapt its return.

    Before assembling we explode any set this flow-equation produced on a
    prior run. The flow owns its one output set; a re-run replaces it
    rather than leaving an orphan behind that would block reassembly.
    """

    async def __call__(self, request: EvaluationRequest) -> EvaluationResult:
        from agent.v2.tools.assemble_set import assemble_set

        items_binding = request.resolved_inputs.get("items")
        try:
            media_ids = _coerce_items_list(items_binding)
        except EvaluatorError:
            raise
        title = request.definition.get("title", "") or ""
        description = request.definition.get("description", "") or ""
        if not media_ids:
            raise EvaluatorError("create_set: items list is empty", category=TOOL_ERROR)

        await _explode_previous_flow_assembly(
            flow_id=request.flow_id,
            equation_key=request.equation_key,
        )

        try:
            async with _open_session() as session:
                result_str = await assemble_set(
                    media_ids=media_ids,
                    title=title,
                    description=description,
                    session=session,
                    project_id=request.project_id,
                )
        except EvaluatorError:
            raise
        except Exception as exc:  # noqa: BLE001
            _raise_tool_error(exc)
            raise  # unreachable

        produced = _parse_assembly_result(result_str, primitive="create_set")
        await self._tag([produced], request)
        return EvaluationResult(value=produced, media_ids=[produced])

    async def _tag(self, media_ids: list[int], request: EvaluationRequest) -> None:
        try:
            await _tag_media_with_flow(
                media_ids,
                flow_id=request.flow_id,
                equation_key=request.equation_key,
                phase_path=request.phase_path,
            )
        except Exception:
            log.exception(
                "flow media tagging failed for %s (flow=%s)",
                request.equation_key,
                request.flow_id,
            )


class CreateGridEvaluator:
    """Evaluate a ``create_grid()`` equation.

    Delegates to ``create_parameter_sweep``. Same rationale as
    ``CreateSetEvaluator`` — the flow owns its one grid; a re-run
    explodes the prior grid first so the new one can claim the same cell
    images (otherwise the assemble tool rejects items with non-null
    ``superseded_by``).
    """

    async def __call__(self, request: EvaluationRequest) -> EvaluationResult:
        from agent.v2.tools.assemble_grid import create_parameter_sweep

        items_binding = request.resolved_inputs.get("items")
        try:
            media_ids = _coerce_items_list(items_binding)
        except EvaluatorError:
            raise
        rows = int(request.definition.get("rows", 0) or 0)
        cols = int(request.definition.get("cols", 0) or 0)
        row_headers = list(request.definition.get("row_headers") or [])
        col_headers = list(request.definition.get("col_headers") or [])
        title = request.definition.get("title", "") or ""
        description = request.definition.get("description", "") or ""

        expected = rows * cols
        if len(media_ids) != expected:
            raise EvaluatorError(
                f"create_grid: expected {expected} items ({rows}x{cols}), "
                f"got {len(media_ids)}",
                category=TOOL_ERROR,
            )

        await _explode_previous_flow_assembly(
            flow_id=request.flow_id,
            equation_key=request.equation_key,
        )

        try:
            async with _open_session() as session:
                result_str = await create_parameter_sweep(
                    media_ids=media_ids,
                    rows=rows,
                    cols=cols,
                    row_headers=row_headers,
                    col_headers=col_headers,
                    title=title,
                    description=description,
                    session=session,
                    project_id=request.project_id,
                )
        except EvaluatorError:
            raise
        except Exception as exc:  # noqa: BLE001
            _raise_tool_error(exc)
            raise  # unreachable

        produced = _parse_assembly_result(result_str, primitive="create_grid")
        await self._tag([produced], request)
        return EvaluationResult(value=produced, media_ids=[produced])

    async def _tag(self, media_ids: list[int], request: EvaluationRequest) -> None:
        try:
            await _tag_media_with_flow(
                media_ids,
                flow_id=request.flow_id,
                equation_key=request.equation_key,
                phase_path=request.phase_path,
            )
        except Exception:
            log.exception(
                "flow media tagging failed for %s (flow=%s)",
                request.equation_key,
                request.flow_id,
            )


class CreateDocumentEvaluator:
    """Evaluate a ``create_document()`` equation.

    Writes rendered text to a ``.md`` file under the current profile's
    generation folder, registers a MediaItem for it, broadcasts
    ``media_added``, and triggers the rescan flag. No supersession
    semantics — documents stand alone.
    """

    async def __call__(self, request: EvaluationRequest) -> EvaluationResult:
        title = request.definition.get("title", "") or ""
        fmt = request.definition.get("format", "markdown")
        static_content = request.definition.get("static_content")
        dynamic_content = request.resolved_inputs.get("content")
        if dynamic_content is not None:
            content = dynamic_content
        else:
            content = static_content
        if not isinstance(content, str):
            raise EvaluatorError(
                f"create_document: content resolved to "
                f"{type(content).__name__}, expected str",
                category=TOOL_ERROR,
            )

        try:
            produced = await _save_document_media(
                title=title,
                content=content,
                fmt=fmt,
                project_id=request.project_id,
            )
        except EvaluatorError:
            raise
        except Exception as exc:  # noqa: BLE001
            _raise_tool_error(exc)
            raise  # unreachable

        try:
            await _tag_media_with_flow(
                [produced],
                flow_id=request.flow_id,
                equation_key=request.equation_key,
                phase_path=request.phase_path,
            )
        except Exception:
            log.exception(
                "flow media tagging failed for %s (flow=%s)",
                request.equation_key,
                request.flow_id,
            )
        return EvaluationResult(value=produced, media_ids=[produced])


async def _save_document_media(
    *,
    title: str,
    content: str,
    fmt: str,
    project_id: Optional[int] = None,
) -> int:
    """Write a markdown document into the library and return its media id.

    Side effects mirror what the assemble tools do: file write, DB insert,
    WS broadcast, rescan trigger. Kept here (rather than in an agent tool)
    because flows are the only caller today — no point adding a new
    surface to the STP agent tool registry for a flow-only capability.
    """
    import hashlib as _hashlib
    from datetime import datetime

    from config import get_settings
    from config_version import get_config_version_manager
    from core.profile_context import get_current_profile
    from database import MediaItem
    from utils.websocket import ws_manager

    if fmt != "markdown":
        raise EvaluatorError(
            f"create_document: unsupported format {fmt!r}",
            category=TOOL_ERROR,
        )

    settings = get_settings()
    profile_id = get_current_profile()
    try:
        base_folder = settings.get_generation_folder_for_profile(profile_id)
    except ValueError as exc:
        raise EvaluatorError(
            f"create_document: no writable generation folder: {exc}",
            category=RESOURCE_ERROR,
        ) from exc

    output_folder = Path(base_folder.path)
    output_folder.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base_name = (title or "document").replace(" ", "_").replace("/", "-")[:50] or "document"
    file_path = output_folder / f"{base_name}_{timestamp}.md"
    counter = 1
    while file_path.exists():
        file_path = output_folder / f"{base_name}_{timestamp}_{counter}.md"
        counter += 1

    await asyncio.to_thread(file_path.write_text, content, "utf-8")
    data = await asyncio.to_thread(file_path.read_bytes)
    file_hash = _hashlib.sha256(data).hexdigest()
    stat_info = file_path.stat()

    async with _open_session() as session:
        media = MediaItem(
            file_path=str(file_path),
            file_hash=file_hash,
            file_size=stat_info.st_size,
            file_format="md",
            created_date=datetime.utcfromtimestamp(stat_info.st_ctime),
            modified_date=datetime.utcfromtimestamp(stat_info.st_mtime),
            indexed_date=datetime.utcnow(),
            metadata_status="completed",
            metadata_processed_at=datetime.utcnow(),
            metadata_config_version=get_config_version_manager().get_version("metadata"),
            width=0,
            height=0,
            megapixels=0,
            raw_metadata=json.dumps({"title": title, "format": fmt}),
            generation_metadata=dump_generation_metadata(
                task_type="document-creation",
                source="flow",
                extra={"format": fmt},
            ),
        )
        session.add(media)
        await session.flush()
        media_id = media.id
        if project_id is not None:
            from project_service import attach_media_to_project
            await attach_media_to_project(session, project_id, media_id)
        await session.commit()

    try:
        await ws_manager.broadcast("media_added", {
            "media_id": media_id,
            "count": 1,
        })
    except Exception:
        log.exception("create_document: media_added broadcast failed")

    try:
        from datetime import datetime as _dt

        from core.app import get_rescan_event
        from database import ControlFlag
        from sqlalchemy.dialects.sqlite import insert

        async with _open_session() as session:
            stmt = insert(ControlFlag).values(
                key="rescan_requested", value="true", updated_at=_dt.utcnow()
            ).on_conflict_do_update(
                index_elements=["key"],
                set_=dict(value="true", updated_at=_dt.utcnow()),
            )
            await session.execute(stmt)
            await session.commit()
        rescan_event = get_rescan_event()
        if rescan_event:
            rescan_event.set()
    except Exception:
        log.exception("create_document: rescan trigger failed")

    return media_id


# =============================================================================
# Create-image evaluator
# =============================================================================


def _shape_is_media(shape: Any) -> bool:
    """Duck-type check for Scalar(kind='media') without importing flow_dsl."""
    return shape is not None and getattr(shape, "kind", None) == "media"


def _shape_is_media_list(shape: Any) -> bool:
    """Duck-type check for ListShape(element=Scalar(kind='media'))."""
    if shape is None:
        return False
    element = getattr(shape, "element", None)
    return element is not None and getattr(element, "kind", None) == "media"


def _shape_is_unknown_element_list(shape: Any) -> bool:
    """Duck-type check for ListShape(element=Unknown()).

    ``foreach`` in v1 doesn't dry-run its callback so the returned NodeRef
    carries ``ListShape(element=Unknown)`` even when the callback just wraps
    ``tool(...)`` (which produces media). Downstream media-hungry primitives
    like ``create_image`` need to recognize this case or they'll pass raw
    media ids through to the user's callable, producing a confusing
    ``'int' object has no attribute 'resize'`` at runtime.

    A concrete ``Scalar`` exposes ``kind``; a nested ``ListShape`` exposes
    ``element``; a ``DictShape`` exposes ``fields``. The ``Unknown`` sentinel
    has none of those — that's our duck-type signature.
    """
    if shape is None:
        return False
    element = getattr(shape, "element", None)
    if element is None:
        return False
    return (
        not hasattr(element, "kind")
        and not hasattr(element, "element")
        and not hasattr(element, "fields")
    )


def _values_look_like_media_ids(values: Any) -> bool:
    """True when every element of ``values`` is an int or ``{media_id: int}``.

    Used only as a fallback when the declared element shape is Unknown — we
    don't want to auto-load plain int lists that a user genuinely meant as
    integers, so we require the shape to be unknown AND every runtime value
    to match the media-id signature before coercing.
    """
    if not isinstance(values, (list, tuple)) or not values:
        return False
    for item in values:
        if isinstance(item, int) and not isinstance(item, bool):
            continue
        if isinstance(item, dict) and "media_id" in item:
            continue
        return False
    return True


async def _load_media_row(media_id: int) -> tuple[str, str]:
    """Return ``(file_format, file_path)`` for a library media id.

    Raises ``EvaluatorError`` (RESOURCE_ERROR) if the row is missing or the
    file path is empty. Single source of truth for the flow evaluators'
    media lookups.
    """
    from database import MediaItem

    async with _open_session() as session:
        result = await session.execute(
            select(MediaItem.file_format, MediaItem.file_path)
            .where(MediaItem.id == media_id)
        )
        row = result.first()
    if row is None or not row[1]:
        raise EvaluatorError(
            f"media {media_id} not found",
            category=RESOURCE_ERROR,
        )
    return row[0] or "", row[1]


async def _resolve_media_inputs_to_objects(
    resolved_inputs: dict[str, Any],
    dynamic_bindings: dict[str, Any],
    *,
    staging_dir: Optional[Path] = None,
) -> tuple[dict[str, Any], list[int], dict[str, int]]:
    """Replace media-id scalars / lists with ``Media`` objects.

    Scans ``dynamic_bindings`` for shapes marked ``media`` or ``list[media]``
    (plus Unknown-element lists that look like media ids at runtime — same
    rule as before) and wraps each id in a ``Media`` object. Inputs whose
    upstream NodeRef has a different shape pass through untouched.

    When ``staging_dir`` is supplied (``create_layout``), each referenced
    media file is copied into that dir and the Media's ``filename`` is the
    staged basename (``avatar.png``, ``panels_0.jpg``). When it isn't
    (``code``, ``create_image``), Media's ``filename`` is the library
    file's basename and ``path`` points into the library directly.

    Returns ``(new_inputs, source_media_ids, staged_by_filename)``:

      - ``source_media_ids`` — de-duplicated, order-preserving media ids
        that were bound as inputs, for lineage.
      - ``staged_by_filename`` — ``{staged_name: media_id}``, empty when
        no staging.
    """
    from .media_arg import Media

    out = dict(resolved_inputs)
    source_ids: list[int] = []
    seen: set[int] = set()
    staged_by_filename: dict[str, int] = {}

    def _track(mid: int) -> None:
        if mid not in seen:
            seen.add(mid)
            source_ids.append(mid)

    async def _build(media_id: int, staged_stem: str) -> Media:
        fmt, path = await _load_media_row(media_id)
        if staging_dir is not None:
            ext = _media_ext_from_format(fmt, path)
            staged_filename = f"{staged_stem}.{ext}"
            dest = staging_dir / staged_filename
            await _stage_media_file_for_layout(media_id, dest)
            staged_by_filename[staged_filename] = media_id
            return Media(media_id, path=str(dest), filename=staged_filename)
        return Media(media_id, path=path)

    for name, binding in dynamic_bindings.items():
        shape = getattr(binding, "shape", None)
        raw = out.get(name)
        safe_key = _sanitize_input_key(name) if staging_dir is not None else name
        if _shape_is_media(shape):
            mid: Optional[int] = None
            if isinstance(raw, int) and not isinstance(raw, bool):
                mid = raw
            elif isinstance(raw, dict) and "media_id" in raw:
                mid = int(raw["media_id"])
            if mid is not None:
                _track(mid)
                out[name] = await _build(mid, safe_key)
            continue
        resolve_list = _shape_is_media_list(shape) or (
            _shape_is_unknown_element_list(shape)
            and _values_look_like_media_ids(raw)
        )
        if resolve_list and isinstance(raw, (list, tuple)):
            items: list[Any] = []
            for i, item in enumerate(raw):
                item_mid: Optional[int] = None
                if isinstance(item, int) and not isinstance(item, bool):
                    item_mid = item
                elif isinstance(item, dict) and "media_id" in item:
                    item_mid = int(item["media_id"])
                if item_mid is not None:
                    _track(item_mid)
                    stem = f"{safe_key}_{i}" if staging_dir is not None else safe_key
                    items.append(await _build(item_mid, stem))
                else:
                    items.append(item)
            out[name] = items
    return out, source_ids, staged_by_filename


async def _save_pil_image_media(
    *,
    img: Any,
    title: str,
    fmt: str,
    project_id: Optional[int] = None,
    source_media_ids: Optional[list[int]] = None,
) -> int:
    """Save a PIL.Image to the library and return its media id.

    Mirrors ``_save_document_media``'s plumbing (file write, DB insert, WS
    broadcast, rescan trigger), but writes image pixels rather than text.

    ``source_media_ids`` are the upstream media items that were loaded as PIL
    inputs to the user's callable. When supplied, they get recorded in
    ``media_lineage`` (and propagated through ``media_tool_lineage``) so the
    produced image's Lineage panel shows where it came from.
    """
    import hashlib as _hashlib
    from datetime import datetime

    from PIL import Image  # noqa: F401 — imported for type context

    from config import get_settings
    from config_version import get_config_version_manager
    from core.profile_context import get_current_profile
    from database import MediaItem
    from utils.lineage import propagate_tool_lineage, record_lineage
    from utils.websocket import ws_manager

    ext_map = {"png": "png", "jpeg": "jpg", "webp": "webp"}
    if fmt not in ext_map:
        raise EvaluatorError(
            f"create_image: unsupported format {fmt!r}",
            category=TOOL_ERROR,
        )
    ext = ext_map[fmt]

    settings = get_settings()
    profile_id = get_current_profile()
    try:
        base_folder = settings.get_generation_folder_for_profile(profile_id)
    except ValueError as exc:
        raise EvaluatorError(
            f"create_image: no writable generation folder: {exc}",
            category=RESOURCE_ERROR,
        ) from exc

    output_folder = Path(base_folder.path)
    output_folder.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base_name = (title or "image").replace(" ", "_").replace("/", "-")[:50] or "image"
    file_path = output_folder / f"{base_name}_{timestamp}.{ext}"
    counter = 1
    while file_path.exists():
        file_path = output_folder / f"{base_name}_{timestamp}_{counter}.{ext}"
        counter += 1

    save_kwargs: dict[str, Any] = {"format": fmt.upper()}
    if fmt == "jpeg":
        save_kwargs["quality"] = 95
        if img.mode in ("RGBA", "LA", "P"):
            img = img.convert("RGB")

    def _write() -> tuple[int, int]:
        img.save(file_path, **save_kwargs)
        return img.width, img.height

    try:
        width, height = await asyncio.to_thread(_write)
    except Exception as exc:  # noqa: BLE001
        raise EvaluatorError(
            f"create_image: failed to save image: {exc}",
            category=TOOL_ERROR,
        ) from exc

    data = await asyncio.to_thread(file_path.read_bytes)
    file_hash = _hashlib.sha256(data).hexdigest()
    stat_info = file_path.stat()

    async with _open_session() as session:
        media = MediaItem(
            file_path=str(file_path),
            file_hash=file_hash,
            file_size=stat_info.st_size,
            file_format=ext,
            created_date=datetime.utcfromtimestamp(stat_info.st_ctime),
            modified_date=datetime.utcfromtimestamp(stat_info.st_mtime),
            indexed_date=datetime.utcnow(),
            metadata_status="completed",
            metadata_processed_at=datetime.utcnow(),
            metadata_config_version=get_config_version_manager().get_version("metadata"),
            width=width,
            height=height,
            megapixels=round((width * height) / 1_000_000, 3),
            raw_metadata=json.dumps({"title": title, "format": fmt}),
            generation_metadata=dump_generation_metadata(
                task_type="image-composition",
                source="flow",
                source_inputs=[
                    {"media_id": mid, "role": "input_image"}
                    for mid in (source_media_ids or [])
                ],
                extra={"format": fmt},
            ),
        )
        session.add(media)
        await session.flush()
        media_id = media.id
        if source_media_ids:
            await record_lineage(
                session, media_id, source_media_ids, "image-composition",
            )
            await propagate_tool_lineage(session, media_id, source_media_ids)
        if project_id is not None:
            from project_service import attach_media_to_project
            await attach_media_to_project(session, project_id, media_id)
        await session.commit()

    try:
        await ws_manager.broadcast("media_added", {
            "media_id": media_id,
            "count": 1,
        })
    except Exception:
        log.exception("create_image: media_added broadcast failed")

    try:
        from datetime import datetime as _dt

        from core.app import get_rescan_event
        from database import ControlFlag
        from sqlalchemy.dialects.sqlite import insert

        async with _open_session() as session:
            stmt = insert(ControlFlag).values(
                key="rescan_requested", value="true", updated_at=_dt.utcnow()
            ).on_conflict_do_update(
                index_elements=["key"],
                set_=dict(value="true", updated_at=_dt.utcnow()),
            )
            await session.execute(stmt)
            await session.commit()
        rescan_event = get_rescan_event()
        if rescan_event:
            rescan_event.set()
    except Exception:
        log.exception("create_image: rescan trigger failed")

    return media_id


class CreateImageEvaluator:
    """Evaluate a ``create_image()`` equation.

    Runs the user's callable with resolved inputs (media-typed inputs
    auto-loaded as PIL Images), expects a ``PIL.Image.Image`` back, and
    saves it as a library MediaItem. No supersession — the source images
    stay visible alongside the composed result.
    """

    async def __call__(self, request: EvaluationRequest) -> EvaluationResult:
        from PIL import Image

        fn = request.definition.get("fn")
        if fn is None:
            raise EvaluatorError(
                "create_image: missing callable (fn) in definition",
                category=TOOL_ERROR,
            )
        title = request.definition.get("title", "") or ""
        fmt = request.definition.get("format", "png")
        dynamic = request.definition.get("_dynamic") or {}
        dynamic_inputs = dynamic.get("inputs") or {}

        raw_inputs = request.resolved_inputs.get("inputs") or {}
        try:
            call_inputs, source_media_ids, _ = await _resolve_media_inputs_to_objects(
                raw_inputs, dynamic_inputs,
            )
        except EvaluatorError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise EvaluatorError(
                f"create_image: failed to load media inputs: {exc}",
                category=TOOL_ERROR,
            ) from exc

        try:
            value = await _invoke_code_callable(fn, call_inputs)
        except EvaluatorError:
            raise
        except Exception as exc:  # noqa: BLE001
            msg = _format_user_code_error(exc)
            raise EvaluatorError(msg, category=CODE_ERROR) from exc

        if not isinstance(value, Image.Image):
            raise EvaluatorError(
                f"create_image: callable must return a PIL.Image.Image, "
                f"got {type(value).__name__}",
                category=CODE_ERROR,
            )

        try:
            produced = await _save_pil_image_media(
                img=value,
                title=title,
                fmt=fmt,
                project_id=request.project_id,
                source_media_ids=source_media_ids,
            )
        except EvaluatorError:
            raise
        except Exception as exc:  # noqa: BLE001
            _raise_tool_error(exc)
            raise  # unreachable

        try:
            await _tag_media_with_flow(
                [produced],
                flow_id=request.flow_id,
                equation_key=request.equation_key,
                phase_path=request.phase_path,
            )
        except Exception:
            log.exception(
                "flow media tagging failed for %s (flow=%s)",
                request.equation_key,
                request.flow_id,
            )
        return EvaluationResult(value=produced, media_ids=[produced])


# =============================================================================
# Create-layout / rasterize-layout evaluators
# =============================================================================


_MAX_LAYOUT_HTML_BYTES = 2 * 1024 * 1024  # 2 MB — guard against runaway codegen


_SAFE_KEY_RE = re.compile(r'[^a-zA-Z0-9_-]')


def _sanitize_input_key(key: str) -> str:
    return _SAFE_KEY_RE.sub('_', key) or "input"


def _media_ext_from_format(file_format: Optional[str], file_path: Optional[str]) -> str:
    """Pick a filesystem extension for a staged media file.

    Prefer the library MediaItem's ``file_format`` (e.g. "png", "jpg") since
    it reflects the actual encoding; fall back to the on-disk path suffix;
    default to ``.bin`` when both are missing. Extensions are returned
    without a leading dot.
    """
    if file_format:
        fmt = file_format.lower().lstrip('.')
        if fmt and '/' not in fmt:
            return fmt
    if file_path:
        suffix = Path(file_path).suffix.lstrip('.').lower()
        if suffix:
            return suffix
    return "bin"


async def _lookup_media_info(media_id: int) -> Optional[tuple[str, str]]:
    """Return ``(file_format, file_path)`` for a MediaItem id, or None if absent.

    Used by the post-callable ref recovery path — we only treat a bare-int
    src ref as media if it actually maps to a MediaItem, otherwise we let
    the regular "missing ref" error fire.
    """
    from database import MediaItem

    async with _open_session() as session:
        result = await session.execute(
            select(MediaItem.file_format, MediaItem.file_path)
            .where(MediaItem.id == media_id)
        )
        row = result.first()
    if row is None:
        return None
    fmt, path = row
    if not path:
        return None
    return (fmt or "", path)


def _rewrite_ref_in_html(html: str, old_ref: str, new_ref: str) -> str:
    """Replace an ``src="{old_ref}"`` / ``url(old_ref)`` occurrence with ``new_ref``.

    Only rewrites exact matches — we deliberately don't do substring replace,
    since ``42`` as a ref could otherwise collide with ``1042`` elsewhere.
    """
    def _replace_src(match):
        attr = match.group(1)
        quote = match.group("quote") or '"'
        ref = match.group("ref") or match.group("ref_bare") or ""
        if ref != old_ref:
            return match.group(0)
        return f'{attr}={quote}{new_ref}{quote}'

    def _replace_url(match):
        keyword = match.group(1)
        quote = match.group("quote") or ''
        ref = match.group("ref") or match.group("ref_bare") or ""
        if ref != old_ref:
            return match.group(0)
        return f'{keyword}({quote}{new_ref}{quote})'

    from .layout_bundle import CSS_URL_RE, SRC_ATTR_RE
    html = SRC_ATTR_RE.sub(_replace_src, html)
    html = CSS_URL_RE.sub(_replace_url, html)
    return html


async def _stage_media_file_for_layout(
    media_id: int, dest_path: Path,
) -> None:
    """Copy a library MediaItem's bytes into the layout bundle staging dir."""
    import shutil as _shutil

    from database import MediaItem

    async with _open_session() as session:
        result = await session.execute(
            select(MediaItem).where(MediaItem.id == media_id)
        )
        media = result.scalar_one_or_none()
    if media is None or not media.file_path:
        raise EvaluatorError(
            f"create_layout: media {media_id} not found",
            category=RESOURCE_ERROR,
        )
    src = Path(media.file_path)
    if not src.exists():
        raise EvaluatorError(
            f"create_layout: media {media_id} file missing: {src}",
            category=RESOURCE_ERROR,
        )
    await asyncio.to_thread(_shutil.copy2, src, dest_path)


# _resolve_media_inputs_to_filenames was replaced by the unified
# _resolve_media_inputs_to_objects(staging_dir=...) above. create_layout
# reads ``.filename`` / ``.pil`` off the Media objects it receives.


async def _save_layout_media(
    *,
    bundle_dir: Path,
    title: str,
    description: str,
    project_id: Optional[int] = None,
    source_media_ids: Optional[list[int]] = None,
) -> int:
    """Copy a staged ``.stimmalayout`` bundle into the library and return its id.

    Parallels ``_save_document_media`` (non-visual MediaItem, skipped AI
    processing statuses), but copies a whole directory instead of writing a
    single file. Hashes ``index.html`` for the MediaItem's ``file_hash``.
    Records ``MediaLineage`` from every staged source media id so the
    library's Lineage panel reflects which library inputs this layout
    derived from.
    """
    import hashlib as _hashlib
    import shutil as _shutil
    from datetime import datetime

    from config import get_settings
    from config_version import get_config_version_manager
    from core.profile_context import get_current_profile
    from database import MediaItem
    from utils.lineage import record_lineage
    from utils.websocket import ws_manager

    settings = get_settings()
    profile_id = get_current_profile()
    try:
        base_folder = settings.get_generation_folder_for_profile(profile_id)
    except ValueError as exc:
        raise EvaluatorError(
            f"create_layout: no writable generation folder: {exc}",
            category=RESOURCE_ERROR,
        ) from exc

    output_folder = Path(base_folder.path)
    output_folder.mkdir(parents=True, exist_ok=True)

    base_name = (title or "layout").replace(" ", "_").replace("/", "-")[:50] or "layout"
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = output_folder / f"{base_name}_{timestamp}.stimmalayout"
    counter = 1
    while dest.exists():
        dest = output_folder / f"{base_name}_{timestamp}_{counter}.stimmalayout"
        counter += 1

    await asyncio.to_thread(_shutil.copytree, str(bundle_dir), str(dest))

    index_path = dest / "index.html"
    if not index_path.exists():
        raise EvaluatorError(
            "create_layout: bundle is missing index.html",
            category=TOOL_ERROR,
        )
    index_bytes = await asyncio.to_thread(index_path.read_bytes)
    file_hash = _hashlib.sha256(index_bytes).hexdigest()
    stat_info = dest.stat()

    async with _open_session() as session:
        media = MediaItem(
            file_path=str(dest),
            file_hash=file_hash,
            file_size=len(index_bytes),
            file_format="stimmalayout",
            created_date=datetime.utcfromtimestamp(stat_info.st_ctime),
            modified_date=datetime.utcfromtimestamp(stat_info.st_mtime),
            indexed_date=datetime.utcnow(),
            metadata_status="completed",
            metadata_processed_at=datetime.utcnow(),
            metadata_config_version=get_config_version_manager().get_version("metadata"),
            clip_status="skipped",
            face_detection_status="skipped",
            vlm_caption_status="skipped",
            width=0,
            height=0,
            megapixels=0,
            raw_metadata=json.dumps({"title": title, "description": description}),
            generation_metadata=dump_generation_metadata(
                task_type="layout-creation",
                source="flow_create_layout",
                source_inputs=[
                    {"media_id": mid, "role": "source_image"}
                    for mid in (source_media_ids or [])
                ],
            ),
        )
        session.add(media)
        await session.flush()
        media_id = media.id
        if source_media_ids:
            await record_lineage(
                session, media_id, source_media_ids, "layout-creation",
            )
        if project_id is not None:
            from project_service import attach_media_to_project
            await attach_media_to_project(session, project_id, media_id)
        await session.commit()

    try:
        await ws_manager.broadcast("media_added", {
            "media_id": media_id,
            "count": 1,
        })
    except Exception:
        log.exception("create_layout: media_added broadcast failed")

    try:
        from datetime import datetime as _dt

        from core.app import get_rescan_event
        from database import ControlFlag
        from sqlalchemy.dialects.sqlite import insert

        async with _open_session() as session:
            stmt = insert(ControlFlag).values(
                key="rescan_requested", value="true", updated_at=_dt.utcnow()
            ).on_conflict_do_update(
                index_elements=["key"],
                set_=dict(value="true", updated_at=_dt.utcnow()),
            )
            await session.execute(stmt)
            await session.commit()
        rescan_event = get_rescan_event()
        if rescan_event:
            rescan_event.set()
    except Exception:
        log.exception("create_layout: rescan trigger failed")

    return media_id


class CreateLayoutEvaluator:
    """Evaluate a ``create_layout()`` equation.

    Stages media inputs into a temp bundle directory as local filenames,
    invokes the user callable to get an HTML string, wraps the HTML into a
    self-contained ``.stimmalayout`` bundle, and persists the bundle as a
    library MediaItem.
    """

    async def __call__(self, request: EvaluationRequest) -> EvaluationResult:
        import tempfile
        import shutil as _shutil

        from .layout_bundle import assemble_index_html, extract_all_refs

        fn = request.definition.get("fn")
        if fn is None:
            raise EvaluatorError(
                "create_layout: missing callable (fn) in definition",
                category=TOOL_ERROR,
            )
        title = request.definition.get("title", "") or ""
        description = request.definition.get("description", "") or ""
        width = int(request.definition.get("width") or 1200)
        height_raw = request.definition.get("height")
        height = None if height_raw is None else int(height_raw)
        dynamic = request.definition.get("_dynamic") or {}
        dynamic_inputs = dynamic.get("inputs") or {}

        raw_inputs = request.resolved_inputs.get("inputs") or {}

        staging_dir = Path(tempfile.mkdtemp(prefix="stimma_layout_"))
        try:
            try:
                call_inputs, _source_ids, staged_by_filename = await _resolve_media_inputs_to_objects(
                    raw_inputs, dynamic_inputs, staging_dir=staging_dir,
                )
            except EvaluatorError:
                raise
            except Exception as exc:  # noqa: BLE001
                raise EvaluatorError(
                    f"create_layout: failed to stage media inputs: {exc}",
                    category=TOOL_ERROR,
                ) from exc

            try:
                value = await _invoke_code_callable(fn, call_inputs)
            except EvaluatorError:
                raise
            except Exception as exc:  # noqa: BLE001
                msg = _format_user_code_error(exc)
                raise EvaluatorError(msg, category=CODE_ERROR) from exc

            if not isinstance(value, str):
                raise EvaluatorError(
                    f"create_layout: callable must return an HTML string, "
                    f"got {type(value).__name__}",
                    category=CODE_ERROR,
                )
            if len(value.encode("utf-8")) > _MAX_LAYOUT_HTML_BYTES:
                raise EvaluatorError(
                    f"create_layout: HTML exceeds "
                    f"{_MAX_LAYOUT_HTML_BYTES // (1024 * 1024)} MB limit",
                    category=CODE_ERROR,
                )

            # Validate that every local image ref in the returned HTML points
            # at a staged file. Two cases need extra work:
            #
            #  1. Per-iteration foreach items (or values resolved through
            #     code() etc.) reach the callable as raw ints, not NodeRefs.
            #     My stager's first pass only stages dynamic bindings with
            #     media shape info, so a bare int gets interpolated as
            #     ``<img src="42">``. Try to rescue it post-hoc: if the ref
            #     is an int that maps to a real MediaItem, stage the file now
            #     and rewrite the ref to that filename. Scoped to refs the
            #     HTML actually uses, so a numeric input like ``font_size=42``
            #     isn't misinterpreted as media.
            #
            #  2. Agent mistakes like interpolating a ``list[media]`` into an
            #     ``src`` (Python stringifies to "['a.png', 'b.png']") still
            #     fail loudly with a CODE_ERROR so the flow author sees it.
            refs = extract_all_refs(value)
            rewritten_html = value
            for ref in list(set(refs)):
                if ref in staged_by_filename:
                    continue
                if (staging_dir / ref).exists():
                    continue
                if not ref.isdigit():
                    continue
                candidate_id = int(ref)
                info = await _lookup_media_info(candidate_id)
                if info is None:
                    continue
                fmt, path = info
                ext = _media_ext_from_format(fmt, path)
                new_filename = f"media_{candidate_id}.{ext}"
                if new_filename not in staged_by_filename:
                    await _stage_media_file_for_layout(
                        candidate_id, staging_dir / new_filename,
                    )
                    staged_by_filename[new_filename] = candidate_id
                rewritten_html = _rewrite_ref_in_html(
                    rewritten_html, ref, new_filename,
                )

            refs_after = extract_all_refs(rewritten_html)
            missing = [
                r for r in refs_after
                if r not in staged_by_filename
                and not (staging_dir / r).exists()
            ]
            if missing:
                staged_list = ", ".join(sorted(staged_by_filename.keys())) or "(none)"
                unique_missing = sorted(set(missing))
                raise EvaluatorError(
                    f"create_layout: HTML references image(s) that couldn't "
                    f"be resolved: {unique_missing}. Staged files: "
                    f"{staged_list}. Media inputs resolve to a filename "
                    f"string matching the input key (e.g. an input named "
                    f"'avatar' becomes 'avatar.png') — interpolate that "
                    f"string into <img src=...>. Never interpolate a "
                    f"list[media] directly; Python stringifies it to a "
                    f"bogus list-literal. If you're fanning a flow input "
                    f"list out over iterations, do the pairing with code() "
                    f"upstream so each iteration receives a single media id.",
                    category=CODE_ERROR,
                )

            # Lineage reflects what the layout actually uses, not everything
            # that was staged. A list[media] input stages N files; if the
            # callable only references one, only that one should show up in
            # the library's Lineage panel.
            used_source_ids: list[int] = []
            seen_ids: set[int] = set()
            for ref in refs_after:
                mid = staged_by_filename.get(ref)
                if mid is None or mid in seen_ids:
                    continue
                seen_ids.add(mid)
                used_source_ids.append(mid)

            index_html = assemble_index_html(
                rewritten_html, width=width, height=height,
            )
            index_path = staging_dir / "index.html"
            await asyncio.to_thread(index_path.write_text, index_html, "utf-8")

            try:
                produced = await _save_layout_media(
                    bundle_dir=staging_dir,
                    title=title,
                    description=description,
                    project_id=request.project_id,
                    source_media_ids=used_source_ids,
                )
            except EvaluatorError:
                raise
            except Exception as exc:  # noqa: BLE001
                _raise_tool_error(exc)
                raise  # unreachable
        finally:
            try:
                await asyncio.to_thread(_shutil.rmtree, str(staging_dir), True)
            except Exception:
                log.exception("create_layout: failed to clean up staging dir")

        try:
            await _tag_media_with_flow(
                [produced],
                flow_id=request.flow_id,
                equation_key=request.equation_key,
                phase_path=request.phase_path,
            )
        except Exception:
            log.exception(
                "flow media tagging failed for %s (flow=%s)",
                request.equation_key,
                request.flow_id,
            )
        return EvaluationResult(value=produced, media_ids=[produced])


class RasterizeLayoutEvaluator:
    """Evaluate a ``rasterize_layout()`` equation.

    Loads the upstream layout bundle, renders it to a PIL image via the
    library preview pipeline, and saves the rendered PNG as a new MediaItem.
    """

    async def __call__(self, request: EvaluationRequest) -> EvaluationResult:
        from database import MediaItem

        layout_media_id = request.resolved_inputs.get("layout")
        if isinstance(layout_media_id, dict) and "media_id" in layout_media_id:
            layout_media_id = int(layout_media_id["media_id"])
        if not isinstance(layout_media_id, int) or isinstance(layout_media_id, bool):
            raise EvaluatorError(
                f"rasterize_layout: expected a media id, got "
                f"{type(layout_media_id).__name__}",
                category=TOOL_ERROR,
            )

        async with _open_session() as session:
            result = await session.execute(
                select(MediaItem).where(MediaItem.id == layout_media_id)
            )
            media = result.scalar_one_or_none()
        if media is None or not media.file_path:
            raise EvaluatorError(
                f"rasterize_layout: media {layout_media_id} not found",
                category=RESOURCE_ERROR,
            )
        if media.file_format != "stimmalayout":
            raise EvaluatorError(
                f"rasterize_layout: media {layout_media_id} is "
                f"{media.file_format!r}, not a layout bundle",
                category=TOOL_ERROR,
            )

        target_width = request.definition.get("width") or 2048

        try:
            from routes.media_files import _generate_layout_preview
            # A flow deliverable render: wait properly for the render slot (the
            # default 0.25s waits drop the render the instant the slot is busy,
            # which is the same too-short-timeout failure that plagued thumbnails
            # and agent vision) and give the heavier full-res render more time.
            img = await _generate_layout_preview(
                media.file_path,
                int(target_width),
                wait_for_client_timeout_s=5.0,
                queue_timeout_s=10.0,
                render_timeout_s=60.0,
            )
        except Exception as exc:  # noqa: BLE001
            raise EvaluatorError(
                f"rasterize_layout: render failed: {exc}",
                category=TOOL_ERROR,
            ) from exc
        if img is None:
            raise EvaluatorError(
                "rasterize_layout: renderer produced no image",
                category=TOOL_ERROR,
            )

        raw_title = ""
        if media.raw_metadata:
            try:
                raw_title = (json.loads(media.raw_metadata) or {}).get("title", "") or ""
            except Exception:
                raw_title = ""
        out_title = raw_title or f"layout_{layout_media_id}_raster"

        try:
            produced = await _save_pil_image_media(
                img=img,
                title=out_title,
                fmt="png",
                project_id=request.project_id,
                source_media_ids=[layout_media_id],
            )
        except EvaluatorError:
            raise
        except Exception as exc:  # noqa: BLE001
            _raise_tool_error(exc)
            raise  # unreachable

        try:
            await _tag_media_with_flow(
                [produced],
                flow_id=request.flow_id,
                equation_key=request.equation_key,
                phase_path=request.phase_path,
            )
        except Exception:
            log.exception(
                "flow media tagging failed for %s (flow=%s)",
                request.equation_key,
                request.flow_id,
            )
        return EvaluationResult(value=produced, media_ids=[produced])


# =============================================================================
# Registry factory
# =============================================================================


# =============================================================================
# Web-search / fetch-media evaluators
# =============================================================================


class WebSearchEvaluator:
    """Evaluate a ``web_search()`` equation.

    Delegates the cloud→DuckDuckGo ladder to ``web_search_core.search``;
    returns the structured list of result dicts directly. Empty result is a
    valid output (the flow author can decide whether to error out
    downstream via code() or hitl).
    """

    def __init__(
        self,
        *,
        searcher: Optional[Callable[..., Awaitable[list[dict]]]] = None,
    ) -> None:
        self._searcher = searcher

    async def __call__(self, request: EvaluationRequest) -> EvaluationResult:
        kind = request.definition.get("kind", "text")
        n = int(request.definition.get("n", 10))
        template = request.definition.get("query_template", "") or ""
        bindings = request.resolved_inputs.get("query") or {}
        try:
            query = _render_template(template, bindings)
        except EvaluatorError:
            raise
        query = (query or "").strip()
        if not query:
            raise EvaluatorError(
                "web_search: query resolved to empty string",
                category=TOOL_ERROR,
            )

        searcher = self._searcher
        if searcher is None:
            from agent.v2.web_search_core import search as core_search
            searcher = core_search

        try:
            results = await searcher(query, kind=kind, n=n)
        except EvaluatorError:
            raise
        except Exception as exc:  # noqa: BLE001
            _raise_tool_error(exc)
            raise  # unreachable
        if kind == "images":
            results = [_with_url_media_result(r) for r in results]
            # Pre-filter unreachable hosts. The user otherwise sees a tile
            # in the picker, picks it, and only THEN finds out the URL 403s
            # on download — confusing and breaks the implicit promise that
            # everything in the picker is selectable. A parallel ranged-GET
            # probe drops the bad ones before they ever surface.
            results = await _filter_reachable_image_results(results)
        return EvaluationResult(value=results)


def _with_url_media_result(result: dict[str, Any]) -> dict[str, Any]:
    """Attach a previewable, non-library media descriptor to an image result."""
    if not isinstance(result, dict):
        return result
    image_url = (result.get("image_url") or "").strip()
    if not image_url:
        return result
    out = dict(result)
    if not isinstance(out.get("media"), dict):
        out["media"] = {
            "type": "url_media",
            "url": image_url,
            "mime_type": "image/*",
            "title": out.get("title") or "",
            "source": out.get("source") or "",
        }
    return out


async def _filter_reachable_image_results(
    results: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Drop image results whose URL we can't actually fetch from the backend.

    Run probes in parallel — for n=20 candidates the wall-clock cost is one
    slow host's timeout, not 20×. Order is preserved so search relevance
    isn't shuffled by the filter.
    """
    if not results:
        return results
    from agent.v2.web_search_core import probe_url_reachable

    urls = [(r.get("image_url") or "").strip() for r in results]
    probes = await asyncio.gather(
        *(probe_url_reachable(u) if u else _async_false() for u in urls),
        return_exceptions=False,
    )
    return [r for r, ok in zip(results, probes) if ok]


async def _async_false() -> bool:
    return False


class FetchMediaEvaluator:
    """Evaluate a ``fetch_media()`` equation.

    Downloads ``url`` (size-capped), sniffs an image format from magic bytes,
    saves the bytes into the library as a MediaItem, tags ``source_url`` into
    ``generation_metadata`` for lineage, and returns the new media id.
    Non-image content / oversize / HTTP errors raise per-iteration TOOL_ERROR
    — sibling iterations of an enclosing ``foreach`` are unaffected.
    """

    def __init__(
        self,
        *,
        fetcher: Optional[Callable[..., Awaitable[tuple[bytes, Optional[str]]]]] = None,
    ) -> None:
        self._fetcher = fetcher

    async def __call__(self, request: EvaluationRequest) -> EvaluationResult:
        url = request.resolved_inputs.get("url")
        if not isinstance(url, str) or not url.strip():
            raise EvaluatorError(
                f"fetch_media: url resolved to {url!r}, expected non-empty string",
                category=TOOL_ERROR,
            )
        max_size_mb = int(request.definition.get("max_size_mb", 10))

        fetcher = self._fetcher
        if fetcher is None:
            from agent.v2.web_search_core import fetch_url_bytes
            fetcher = fetch_url_bytes

        try:
            data, http_content_type = await fetcher(url, max_size_mb=max_size_mb)
        except EvaluatorError:
            raise
        except Exception as exc:  # noqa: BLE001
            from agent.v2.web_search_core import WebFetchError
            if isinstance(exc, WebFetchError):
                raise EvaluatorError(str(exc), category=TOOL_ERROR) from exc
            _raise_tool_error(exc)
            raise  # unreachable

        from agent.v2.web_search_core import sniff_image_format
        fmt = sniff_image_format(data)
        if fmt is None:
            raise EvaluatorError(
                f"fetch_media: {url} returned non-image bytes "
                f"(http content-type {http_content_type!r})",
                category=TOOL_ERROR,
            )

        try:
            produced = await _save_fetched_media(
                data=data,
                fmt=fmt,
                source_url=url,
                project_id=request.project_id,
            )
        except EvaluatorError:
            raise
        except Exception as exc:  # noqa: BLE001
            _raise_tool_error(exc)
            raise  # unreachable

        try:
            await _tag_media_with_flow(
                [produced],
                flow_id=request.flow_id,
                equation_key=request.equation_key,
                phase_path=request.phase_path,
            )
        except Exception:
            log.exception(
                "flow media tagging failed for %s (flow=%s)",
                request.equation_key,
                request.flow_id,
            )
        return EvaluationResult(value=produced, media_ids=[produced])


async def promote_url_media_value(
    value: Any,
    *,
    flow_id: Optional[int],
    project_id: Optional[int],
    equation_key: str,
    phase_path: list[str],
    max_size_mb: int = 10,
) -> Any:
    """Promote URL media descriptors inside a HITL resolution to library media.

    Web image search can produce many previewable URL media descriptors. They
    stay out of the library while the user browses. This function is called at
    the boundary where a descriptor becomes part of flow state (select,
    reselect, or approve result), downloads only the chosen remote resource,
    and replaces the descriptor with a stable library media id.
    """
    if _is_url_media(value):
        return await _promote_one_url_media(
            value,
            flow_id=flow_id,
            project_id=project_id,
            equation_key=equation_key,
            phase_path=phase_path,
            max_size_mb=max_size_mb,
        )
    if isinstance(value, list):
        return await asyncio.gather(*[
            promote_url_media_value(
                item,
                flow_id=flow_id,
                project_id=project_id,
                equation_key=equation_key,
                phase_path=phase_path,
                max_size_mb=max_size_mb,
            )
            for item in value
        ])
    if isinstance(value, dict):
        out = dict(value)
        media = out.get("media")
        if _is_url_media(media):
            media_id = await _promote_one_url_media(
                media,
                flow_id=flow_id,
                project_id=project_id,
                equation_key=equation_key,
                phase_path=phase_path,
                max_size_mb=max_size_mb,
            )
            out["media_id"] = media_id
            out["media"] = {
                "type": "library_media",
                "media_id": media_id,
                "source_url": media.get("url"),
            }
            return out
        return {
            key: await promote_url_media_value(
                item,
                flow_id=flow_id,
                project_id=project_id,
                equation_key=equation_key,
                phase_path=phase_path,
                max_size_mb=max_size_mb,
            )
            for key, item in out.items()
        }
    return value


def _is_url_media(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    kind = value.get("type") or value.get("media_type")
    url = value.get("url") or value.get("image_url")
    return kind in {"url_media", "remote_media", "url"} and isinstance(url, str) and bool(url.strip())


async def _promote_one_url_media(
    media: dict[str, Any],
    *,
    flow_id: Optional[int],
    project_id: Optional[int],
    equation_key: str,
    phase_path: list[str],
    max_size_mb: int,
) -> int:
    url = (media.get("url") or media.get("image_url") or "").strip()
    if not url:
        raise EvaluatorError("url_media: missing url", category=TOOL_ERROR)
    from agent.v2.web_search_core import fetch_url_bytes, sniff_image_format, WebFetchError

    try:
        data, http_content_type = await fetch_url_bytes(url, max_size_mb=max_size_mb)
    except WebFetchError as exc:
        raise EvaluatorError(str(exc), category=TOOL_ERROR) from exc

    fmt = sniff_image_format(data)
    if fmt is None:
        raise EvaluatorError(
            f"url_media: {url} returned non-image bytes "
            f"(http content-type {http_content_type!r})",
            category=TOOL_ERROR,
        )
    media_id = await _save_fetched_media(
        data=data,
        fmt=fmt,
        source_url=url,
        project_id=project_id,
    )
    await _tag_media_with_flow(
        [media_id],
        flow_id=flow_id,
        equation_key=equation_key,
        phase_path=phase_path,
    )
    return media_id


async def _save_fetched_media(
    *,
    data: bytes,
    fmt: str,
    source_url: str,
    project_id: Optional[int] = None,
) -> int:
    """Persist downloaded bytes as a library MediaItem and return its id.

    Mirrors the create_image / create_document save path so library views,
    lineage panels, and ingestion behave identically. ``source_url`` lives
    in ``generation_metadata`` (the existing provenance bag) — no schema
    change needed.
    """
    import hashlib as _hashlib
    from datetime import datetime

    from PIL import Image

    from config import get_settings
    from config_version import get_config_version_manager
    from core.profile_context import get_current_profile
    from database import MediaItem
    from utils.websocket import ws_manager

    settings = get_settings()
    profile_id = get_current_profile()
    try:
        base_folder = settings.get_generation_folder_for_profile(profile_id)
    except ValueError as exc:
        raise EvaluatorError(
            f"fetch_media: no writable generation folder: {exc}",
            category=RESOURCE_ERROR,
        ) from exc

    output_folder = Path(base_folder.path)
    output_folder.mkdir(parents=True, exist_ok=True)

    ext = "jpg" if fmt == "jpeg" else fmt
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base_name = "fetched"
    file_path = output_folder / f"{base_name}_{timestamp}.{ext}"
    counter = 1
    while file_path.exists():
        file_path = output_folder / f"{base_name}_{timestamp}_{counter}.{ext}"
        counter += 1

    await asyncio.to_thread(file_path.write_bytes, data)

    width = 0
    height = 0
    try:
        def _measure() -> tuple[int, int]:
            from utils.image_ops import open_oriented
            with open_oriented(file_path) as img:
                return img.width, img.height
        width, height = await asyncio.to_thread(_measure)
    except Exception:
        log.warning("fetch_media: could not read image dimensions for %s", file_path)

    file_hash = _hashlib.sha256(data).hexdigest()
    stat_info = file_path.stat()

    async with _open_session() as session:
        media = MediaItem(
            file_path=str(file_path),
            file_hash=file_hash,
            file_size=stat_info.st_size,
            file_format=ext,
            created_date=datetime.utcfromtimestamp(stat_info.st_ctime),
            modified_date=datetime.utcfromtimestamp(stat_info.st_mtime),
            indexed_date=datetime.utcnow(),
            metadata_status="completed",
            metadata_processed_at=datetime.utcnow(),
            metadata_config_version=get_config_version_manager().get_version("metadata"),
            width=width,
            height=height,
            megapixels=round((width * height) / 1_000_000, 3) if width and height else 0.0,
            raw_metadata=json.dumps({"source_url": source_url, "format": fmt}),
            generation_metadata=dump_generation_metadata(
                task_type="fetch-media",
                source="flow",
                extra={"format": fmt, "source_url": source_url},
            ),
        )
        session.add(media)
        await session.flush()
        media_id = media.id
        if project_id is not None:
            from project_service import attach_media_to_project
            await attach_media_to_project(session, project_id, media_id)
        await session.commit()

    try:
        await ws_manager.broadcast("media_added", {
            "media_id": media_id,
            "count": 1,
        })
    except Exception:
        log.exception("fetch_media: media_added broadcast failed")

    try:
        from datetime import datetime as _dt

        from core.app import get_rescan_event
        from database import ControlFlag
        from sqlalchemy.dialects.sqlite import insert

        async with _open_session() as session:
            stmt = insert(ControlFlag).values(
                key="rescan_requested", value="true", updated_at=_dt.utcnow()
            ).on_conflict_do_update(
                index_elements=["key"],
                set_=dict(value="true", updated_at=_dt.utcnow()),
            )
            await session.execute(stmt)
            await session.commit()
        rescan_event = get_rescan_event()
        if rescan_event:
            rescan_event.set()
    except Exception:
        log.exception("fetch_media: rescan trigger failed")

    return media_id


def build_production_registry(
    *,
    tool_evaluator: Optional[Evaluator] = None,
    llm_evaluator: Optional[Evaluator] = None,
    code_evaluator: Optional[Evaluator] = None,
    info_evaluator: Optional[Evaluator] = None,
    create_set_evaluator: Optional[Evaluator] = None,
    create_grid_evaluator: Optional[Evaluator] = None,
    create_document_evaluator: Optional[Evaluator] = None,
    create_image_evaluator: Optional[Evaluator] = None,
    create_layout_evaluator: Optional[Evaluator] = None,
    rasterize_layout_evaluator: Optional[Evaluator] = None,
    web_search_evaluator: Optional[Evaluator] = None,
    fetch_media_evaluator: Optional[Evaluator] = None,
    graph_getter: Optional[Callable[[], Any]] = None,
) -> EvaluatorRegistry:
    """Return a registry wired for production use.

    Kwargs let callers (tests, specialised callers) override any evaluator
    without rebuilding the registry by hand — the common case is "I need the
    two production ones plus a stub third".
    """
    reg = EvaluatorRegistry()
    reg.register("tool_call", tool_evaluator or ToolCallEvaluator())
    reg.register("llm_call", llm_evaluator or LLMEvaluator())
    reg.register("llm_batch", LLMBatchEvaluator())
    reg.register("llm_slot", LLMSlotEvaluator(graph_getter=graph_getter))
    reg.register("code", code_evaluator or CodeEvaluator())
    reg.register("info", info_evaluator or InfoEvaluator())
    reg.register("create_set", create_set_evaluator or CreateSetEvaluator())
    reg.register("create_grid", create_grid_evaluator or CreateGridEvaluator())
    reg.register(
        "create_document",
        create_document_evaluator or CreateDocumentEvaluator(),
    )
    reg.register(
        "create_image",
        create_image_evaluator or CreateImageEvaluator(),
    )
    reg.register(
        "create_layout",
        create_layout_evaluator or CreateLayoutEvaluator(),
    )
    reg.register(
        "rasterize_layout",
        rasterize_layout_evaluator or RasterizeLayoutEvaluator(),
    )
    reg.register(
        "web_search",
        web_search_evaluator or WebSearchEvaluator(),
    )
    reg.register(
        "fetch_media",
        fetch_media_evaluator or FetchMediaEvaluator(),
    )
    return reg


__all__ = [
    "CodeEvaluator",
    "CreateDocumentEvaluator",
    "CreateGridEvaluator",
    "CreateImageEvaluator",
    "CreateLayoutEvaluator",
    "CreateSetEvaluator",
    "FetchMediaEvaluator",
    "InfoEvaluator",
    "LLMEvaluator",
    "RasterizeLayoutEvaluator",
    "ToolCallEvaluator",
    "WebSearchEvaluator",
    "build_production_registry",
]
