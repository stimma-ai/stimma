"""Execute STP provider tools directly with media save."""

import asyncio
import json
import os
import random
import re
import shutil
import time
from typing import Any, Dict, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from ..tools_registry import tool, ToolParameter

import app_dirs
from core.logging import get_logger
from core.profile_context import get_current_profile
from database import MediaItem
from providers.registry import ProviderRegistry
from generation_queue import get_generation_queue
from agent.jobs import wait_for_jobs
from agent.tools.stp_utils import (
    _resolve_lora_paths,
    _get_allowed_dimensions,
    _snap_to_allowed,
)

log = get_logger(__name__)

CONTROLNET_PREPROCESSORS = {"canny", "depth", "lineart", "lineart_realistic", "lineart_anime", "pose", "pose_hands"}

# Keys the agent uses to request controlnet preprocessing inline
_CONTROLNET_TYPE_KEYS = {"x-controlnet", "controlnet", "controlnet_type",
                          "controlnet_preprocessor", "control_net"}
# Hallucinated keys that should be stripped silently (not errors, just noise)
_CONTROLNET_STRIP_KEYS = {"controlnet_strength", "cn_strength"}


def _json_safe_pathlikes(value: Any) -> Any:
    """Recursively normalize PathLike tool arguments before JSON transport.

    ``ToolResult.path`` is intentionally a ``Path``, and agent code commonly
    feeds it straight into a later media parameter. Once normalized, the media
    resolver treats it like an agent-written string path and imports it for
    durable lineage where appropriate.
    """
    if isinstance(value, os.PathLike):
        return os.fsdecode(os.fspath(value))
    if isinstance(value, dict):
        return {key: _json_safe_pathlikes(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe_pathlikes(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_json_safe_pathlikes(item) for item in value)
    return value


def _coerce_dict_arg(value: Any) -> Any:
    """If ``value`` is a JSON-encoded dict, decode it; otherwise return unchanged.

    Some model/runtime combinations (notably vLLM tool-call templates and weaker
    models that double-encode JSON) deliver an object-valued arg as a quoted
    string like ``'{"k": 1}'`` instead of an actual dict. Caller still validates
    the type — this helper only un-strings, it doesn't coerce non-JSON.
    """
    if not isinstance(value, str):
        return value
    stripped = value.strip()
    if not (stripped.startswith("{") and stripped.endswith("}")):
        return value
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        return value


def _extract_controlnet_config(
    params: Dict[str, Any],
) -> tuple[Optional[str], Optional[Dict[str, Any]]]:
    """Extract and remove controlnet config from the parameters dict.

    Returns (preprocessor_name, cn_params) or (None, None).
    """
    # Strip hallucinated keys silently
    for key in _CONTROLNET_STRIP_KEYS:
        params.pop(key, None)

    # Find the preprocessor name
    preprocessor = None
    for key in _CONTROLNET_TYPE_KEYS:
        if key in params:
            preprocessor = params.pop(key)

    if preprocessor is None:
        return None, None

    # Also extract optional controlnet_params
    cn_params = params.pop("controlnet_params", None)

    # Validate
    if preprocessor not in CONTROLNET_PREPROCESSORS:
        raise ValueError(
            f"Unknown controlnet preprocessor '{preprocessor}'. "
            f"Available: {', '.join(sorted(CONTROLNET_PREPROCESSORS))}"
        )

    return preprocessor, cn_params


def _resolve_effective_task_type(tool_descriptor, params: Dict[str, Any]) -> str:
    """Mirror ToolView task-type resolution for multi-task tools."""
    task_types = list(tool_descriptor.task_types or [])
    primary = tool_descriptor.task_type or (task_types[0] if task_types else "unknown")

    input_images = params.get("input_images", []) or []
    has_input_images = isinstance(input_images, list) and len(input_images) > 0
    input_videos = params.get("input_videos", []) or []
    has_input_videos = isinstance(input_videos, list) and len(input_videos) > 0

    if has_input_images and "image-to-image" in task_types:
        return "image-to-image"

    # Dual-mode video tools: text-to-video can become image-to-video when image input exists.
    if has_input_images and primary == "text-to-video" and "image-to-video" in task_types:
        return "image-to-video"

    if has_input_videos and "video-to-video" in task_types:
        return "video-to-video"

    return primary


def _get_default_folder(workspace_dir: Optional[str] = None) -> str:
    """Get private managed staging for generated tool payloads."""
    profile_id = get_current_profile()
    folder = app_dirs.get_managed_staging_dir(profile_id, "generated")
    folder.mkdir(parents=True, exist_ok=True)
    return str(folder)


# Consecutive-failure streaks per (workspace, tool) AND per (workspace,
# task_type). LLMs will otherwise retry a hard-failing tool indefinitely;
# escalating error text alone proved insufficient (models retried through
# explicit "STOP retrying" guidance), so past the hard cap we refuse to
# submit at all — instant, costless, and unambiguous. The task-type streak
# exists because alternating between sibling models (draft vs quality tier)
# resets nothing about a backend that is down — without it, each variant
# gets its own full retry budget. Streaks reset on any success for that
# tool / task type.
_failure_streaks: Dict[tuple, int] = {}
_FAILURE_STREAK_WARN = 2
_FAILURE_STREAK_MAX = 4
_FAILURE_STREAK_BLOCK = 5
_TASK_TYPE_STREAK_BLOCK = 8


def _type_key(workspace_dir: Optional[str], task_type: Optional[str]) -> Optional[tuple]:
    return (str(workspace_dir), f"type:{task_type}") if task_type else None


def _with_retry_guidance(
    workspace_dir: Optional[str], tool_id: str, error_msg: str,
    task_type: Optional[str] = None,
) -> str:
    key = (str(workspace_dir), tool_id)
    streak = _failure_streaks.get(key, 0) + 1
    _failure_streaks[key] = streak
    type_streak = 0
    tkey = _type_key(workspace_dir, task_type)
    if tkey:
        type_streak = _failure_streaks.get(tkey, 0) + 1
        _failure_streaks[tkey] = type_streak
    if len(_failure_streaks) > 4096:
        _failure_streaks.clear()
    if streak >= _FAILURE_STREAK_MAX:
        return (
            f"{error_msg}\n\nThis tool has now failed {streak} times in a row. "
            "STOP retrying it — the failure is not transient. Report the failure to the user "
            "plainly (what you tried, what error came back) and, only if one exists, offer a "
            "genuinely different tool or approach."
        )
    if type_streak >= _FAILURE_STREAK_MAX and type_streak > streak:
        return (
            f"{error_msg}\n\nThis is the {type_streak}th consecutive failure across "
            f"{task_type} tools in this session. Switching to a sibling model does not fix a "
            "backend that is down — STOP retrying this task type and report the failure to "
            "the user plainly (what you tried, what error came back)."
        )
    if streak >= _FAILURE_STREAK_WARN:
        return (
            f"{error_msg}\n\nThis tool has failed {streak} times in a row. "
            "At most one more retry is reasonable; if that fails too, stop and report the "
            "failure to the user instead of retrying again."
        )
    return error_msg


def _clear_failure_streak(
    workspace_dir: Optional[str], tool_id: str, task_type: Optional[str] = None
) -> None:
    _failure_streaks.pop((str(workspace_dir), tool_id), None)
    tkey = _type_key(workspace_dir, task_type)
    if tkey:
        _failure_streaks.pop(tkey, None)


def _check_failure_block(
    workspace_dir: Optional[str], tool_id: str, task_type: Optional[str] = None
) -> None:
    """Refuse execution outright once a tool (or its whole task type) has
    hard-failed repeatedly."""
    streak = _failure_streaks.get((str(workspace_dir), tool_id), 0)
    if streak >= _FAILURE_STREAK_BLOCK:
        raise RuntimeError(
            f"Refusing to run '{tool_id}': it has failed {streak} times in a row and further "
            "retries are blocked. Report the failure to the user (what you tried and the error "
            "that came back); it becomes available again once the user weighs in."
        )
    tkey = _type_key(workspace_dir, task_type)
    type_streak = _failure_streaks.get(tkey, 0) if tkey else 0
    if type_streak >= _TASK_TYPE_STREAK_BLOCK:
        raise RuntimeError(
            f"Refusing to run '{tool_id}': {task_type} tools have failed {type_streak} times "
            "in a row in this session (across model variants) and further retries are blocked. "
            "Report the failure to the user (what you tried and the error that came back); "
            "generation becomes available again once the user weighs in."
        )


async def _execute_metadata_only_tool(
    provider,
    tool_descriptor,
    tool_id: str,
    task_type: str,
    final_params: Dict[str, Any],
    started_at: float,
) -> Dict[str, Any]:
    """Execute a builtin metadata-only tool (detect-objects, ...) in-process.

    These tools return data (bounding boxes, scores), not media, so the
    generation queue — whose whole pipeline assumes an output file to ingest —
    is the wrong transport. Execute directly and hand the provider's result
    metadata back as the tool result.
    """
    from providers.base import ExecutionResult

    parameters = {
        k: v for k, v in final_params.items()
        if not k.startswith("_") and k != "input_media_ids"
    }

    # The provider needs real file paths; resolve any library media ids.
    input_images = parameters.get("input_images")
    if isinstance(input_images, list):
        resolved_paths = []
        for img in input_images:
            media_id = None
            if isinstance(img, int) and not isinstance(img, bool):
                media_id = img
            elif isinstance(img, str) and img.isdigit():
                media_id = int(img)
            if media_id is None:
                resolved_paths.append(img)
                continue
            from database_registry import get_database_registry
            db = get_database_registry().get_database(get_current_profile())
            async with db.async_session_maker() as resolve_session:
                result = await resolve_session.execute(
                    select(MediaItem.file_path).where(MediaItem.id == media_id)
                )
                file_path = result.scalar_one_or_none()
            if not file_path:
                raise ValueError(f"Media {media_id} not found in library")
            resolved_paths.append(file_path)
        parameters["input_images"] = resolved_paths

    exec_result = None
    async for progress_or_result in provider.execute(
        tool_id=tool_descriptor.id,
        parameters=parameters,
    ):
        if isinstance(progress_or_result, ExecutionResult):
            exec_result = progress_or_result

    if exec_result is None:
        raise RuntimeError(f"Tool '{tool_id}' did not return a result")
    if not exec_result.success:
        raise RuntimeError(exec_result.error or f"Tool '{tool_id}' failed")

    return {
        "metadata_only": True,
        "tool_id": tool_id,
        "tool_name": tool_descriptor.name,
        "task_type": task_type,
        "duration_ms": int((time.perf_counter() - started_at) * 1000),
        **(exec_result.metadata or {}),
    }


async def execute_call_tool(
    tool_id: str,
    parameters: Optional[Dict[str, Any]] = None,
    task_type_override: Optional[str] = None,
    **kwargs,
) -> Dict[str, Any]:
    # STP tools have a SINGLE parameter namespace: prompt, input_images, mask,
    # width/height, seed, loras and every tool-specific knob live together in one
    # dict keyed by name (matching the tool's parameter_schema).
    params: Dict[str, Any] = _json_safe_pathlikes(dict(parameters or {}))

    # Extract controlnet config if the agent passed it inline
    cn_preprocessor, cn_params = _extract_controlnet_config(params)

    session: AsyncSession = kwargs.get("session")

    if not session:
        raise ValueError("No database session available")

    started_at = time.perf_counter()

    # 1. Look up tool
    registry = ProviderRegistry.get_instance()
    provider_tool = registry.get_tool(tool_id)
    if not provider_tool:
        raise ValueError(
            f"Tool '{tool_id}' not found. Browse .stimma/tools/ (or import from stimma.tools.<category>) for valid tools."
        )

    provider, tool_descriptor = provider_tool
    if task_type_override and task_type_override in (tool_descriptor.task_types or []):
        # Explicit namespace import (stimma.tools.<task>.<tool>) pins the task type
        # deterministically rather than inferring it from input shape.
        task_type = task_type_override
    else:
        task_type = _resolve_effective_task_type(tool_descriptor, params)

    log.info(f"[call_tool_v2] Executing {tool_id} ({tool_descriptor.name}), task_type={task_type}")

    # 2. Overlay the caller's parameters on top of the tool's schema defaults so
    #    omitted knobs fall back to defaults while any provided value always wins.
    param_schema = tool_descriptor.parameter_schema or {}
    final_params: Dict[str, Any] = {}
    for prop_name, prop_info in param_schema.get("properties", {}).items():
        if "default" in prop_info:
            final_params[prop_name] = prop_info["default"]
    final_params.update(params)

    # 3. Resolve LoRAs
    loras = final_params.get("loras", [])
    if loras:
        # Accept either the input shape ({path, weight}) or the stored/recorded
        # shape ({lora, weight} / {name, weight}) so a flow read back from an
        # existing image's metadata resubmits without manual key renaming.
        filtered = []
        for l in loras:
            if not isinstance(l, dict):
                continue
            path = l.get("path") or l.get("lora") or l.get("name")
            if not path:
                continue
            filtered.append({"path": path, "weight": l.get("weight", 1.0)})
        try:
            resolved = _resolve_lora_paths(tool_id, filtered)
            final_params["loras"] = resolved
        except ValueError as e:
            raise ValueError(f"Error resolving LoRAs: {e}") from e

    # 4. Handle dimensions
    width = final_params.pop("width", None) or 1024
    height = final_params.pop("height", None) or 1024

    allowed_dims = _get_allowed_dimensions(tool_descriptor)
    if allowed_dims:
        width, height = _snap_to_allowed(width, height, allowed_dims)

    # 5. Capture input media IDs for lineage parity with ToolView payloads
    input_images = final_params.get("input_images", [])
    input_media_ids = final_params.get("input_media_ids")
    metadata_only = (
        getattr(provider, "provider_type", None) == "builtin"
        and (getattr(tool_descriptor, "metadata", None) or {}).get("metadata_only")
    )
    if isinstance(input_images, list) and not input_media_ids:
        derived_ids = []
        resolved_inputs = []
        for img in input_images:
            if isinstance(img, int):
                derived_ids.append(img)
                resolved_inputs.append(img)
            elif isinstance(img, str) and img.isdigit():
                derived_ids.append(int(img))
                resolved_inputs.append(img)
            elif isinstance(img, str):
                # Tolerate a `media:<id>` / `media_<id>` reference — the agent
                # reasonably reaches for it, and silently dropping it surfaces
                # downstream as the opaque "No input media provided".
                prefix_match = re.match(r'^media[:_](.*)$', img.strip(), flags=re.IGNORECASE)
                if prefix_match is not None:
                    ref = prefix_match.group(1)
                    if ref.isdigit():
                        derived_ids.append(int(ref))
                        resolved_inputs.append(int(ref))
                        continue
                    # A media-prefixed ref with a non-numeric id is malformed —
                    # fail fast and name it rather than treating it as a path.
                    raise ValueError(
                        f"Invalid media reference {img!r}: expected 'media:<id>' "
                        "with a numeric library media id."
                    )
                # A file that exists on disk (workspace-relative or absolute) is
                # a valid input in its own right — files the agent just wrote
                # with PIL are not in the library yet, and requiring a
                # library.save roundtrip first is an artificial boundary.
                # Implicitly import it into the library (deduped by path and
                # content hash) so the generated asset's lineage references a
                # durable media id — a raw workspace path in source_inputs
                # outlives the workspace and renders as "Unavailable".
                workspace_dir = kwargs.get("workspace_dir")
                candidate = img
                if not os.path.isabs(candidate) and workspace_dir:
                    candidate = os.path.join(str(workspace_dir), candidate)
                if os.path.isfile(candidate):
                    abs_candidate = os.path.abspath(candidate)
                    if metadata_only:
                        # Data-only tools have no generated asset whose lineage
                        # needs a durable source. Keep temporary/workspace files
                        # as paths instead of mutating the user's library merely
                        # to inspect them.
                        resolved_inputs.append(abs_candidate)
                        continue
                    imported_id = None
                    try:
                        from database_registry import get_database_registry
                        from pathlib import Path as _Path
                        from .library import resolve_or_import_input_file
                        import_db = get_database_registry().get_database(get_current_profile())
                        async with import_db.async_session_maker() as import_session:
                            imported_id = await resolve_or_import_input_file(
                                import_session,
                                abs_candidate,
                                _Path(str(workspace_dir)) if workspace_dir else None,
                                project_id=kwargs.get("project_id"),
                            )
                    except Exception as e:
                        log.warning(f"[call_tool_v2] Could not import input file '{img}' into library: {e}")
                    if imported_id:
                        derived_ids.append(imported_id)
                        resolved_inputs.append(imported_id)
                        log.info(f"[call_tool_v2] Imported on-disk input '{img}' as media_id {imported_id}")
                    else:
                        # Import failed — fall back to the raw path so the
                        # generation itself still runs.
                        resolved_inputs.append(abs_candidate)
                        log.info(f"[call_tool_v2] Using on-disk input file '{img}'")
                    continue
                # Not on disk — resolve to a library media_id by matching filename
                basename = os.path.basename(img)
                from database_registry import get_database_registry
                db_for_resolve = get_database_registry().get_database(get_current_profile())
                async with db_for_resolve.async_session_maker() as resolve_session:
                    result = await resolve_session.execute(
                        select(MediaItem.id).where(
                            MediaItem.file_path.like(f'%/{basename}')
                        ).order_by(MediaItem.id.desc()).limit(1)
                    )
                    row = result.first()
                    if row:
                        derived_ids.append(row[0])
                        resolved_inputs.append(img)
                        log.info(f"[call_tool_v2] Resolved workspace path '{basename}' to media_id {row[0]}")
                    else:
                        # Don't drop it silently — an unresolved entry becomes an
                        # empty input list and the provider reports the misleading
                        # "No input media provided". Fail loudly, naming the value.
                        raise ValueError(
                            f"Could not resolve input image {img!r}: not an existing "
                            "file (checked relative to the workspace) and no library "
                            "media has that filename. Pass a library media id (int), "
                            "a digit string, or a path to a file that exists."
                        )
            else:
                resolved_inputs.append(img)
        final_params["input_images"] = resolved_inputs
        if derived_ids:
            final_params["input_media_ids"] = derived_ids

    # 5a. Metadata-only builtin tools (e.g. detect-objects) don't produce media —
    #     the generation queue is image-shaped end to end (output file, ingest,
    #     result_media_id), so route them around it and execute in-process,
    #     returning the provider's metadata (detections, image_size, ...) directly.
    if metadata_only:
        return await _execute_metadata_only_tool(
            provider, tool_descriptor, tool_id, task_type, final_params, started_at,
        )

    # 5b. Inline controlnet preprocessing when the agent passed controlnet=
    if cn_preprocessor:
        # Validate that the tool actually supports this controlnet preprocessor
        param_schema = tool_descriptor.parameter_schema or {}
        param_props = param_schema.get("properties", {})
        img_prop = param_props.get("input_images", {})
        supported_cn = img_prop.get("x-controlnet", [])
        if not supported_cn:
            raise ValueError(
                f"Tool '{tool_id}' does not support controlnet. "
                f"Browse .stimma/tools/ for a tool whose stub lists controlnet preprocessors, "
                f"or use an image-to-image tool that supports controlnet."
            )
        if cn_preprocessor not in supported_cn:
            raise ValueError(
                f"Tool '{tool_id}' does not support controlnet preprocessor '{cn_preprocessor}'. "
                f"Supported: {', '.join(sorted(supported_cn))}."
            )

        raw_images = final_params.get("input_images", []) or []
        if not raw_images:
            raise ValueError(
                f"controlnet='{cn_preprocessor}' requires input_images with at least one media_id."
            )
        from .preprocess_controlnet import _resolve_media_path

        preprocessed_images = []
        original_paths = []
        preprocessors_list = []
        preprocessor_params_list = []
        workspace_dir = kwargs.get("workspace_dir")

        for img in raw_images:
            media_id_val = int(img) if isinstance(img, (int, str)) and str(img).isdigit() else None
            if media_id_val is None:
                # Not a media_id (already a path) — pass through
                preprocessed_images.append(img)
                original_paths.append(None)
                preprocessors_list.append(None)
                preprocessor_params_list.append(None)
                continue

            # Use a fresh session for this read to avoid concurrent-use errors on
            # the shared SDK session when multiple call_tool invocations run
            # concurrently via asyncio.gather().
            from database_registry import get_database_registry
            cn_db = get_database_registry().get_database(get_current_profile())
            async with cn_db.async_session_maker() as cn_session:
                source_path = await _resolve_media_path(cn_session, media_id_val)
            from controlnet import preprocess
            output_path, w, h = await preprocess(source_path, cn_preprocessor, cn_params)

            # Copy to workspace
            if workspace_dir:
                filename = f"controlnet_{cn_preprocessor}_{media_id_val}_{os.path.basename(output_path)}"
                ws_path = os.path.join(str(workspace_dir), filename)
                shutil.copy2(output_path, ws_path)
                output_path = ws_path

            preprocessed_images.append(output_path)
            original_paths.append(media_id_val)
            preprocessors_list.append(cn_preprocessor)
            preprocessor_params_list.append(cn_params)

        final_params["input_images"] = preprocessed_images
        final_params["_original_input_paths"] = original_paths
        final_params["_input_preprocessors"] = preprocessors_list
        final_params["_input_preprocessor_params"] = preprocessor_params_list
        log.info(f"[call_tool_v2] Inline controlnet preprocessing: {cn_preprocessor} on {len(raw_images)} image(s)")

    # Re-read input_images in case controlnet preprocessing rewrote it.
    input_images = final_params.get("input_images", [])

    # Extract prompt before building the job params
    prompt = final_params.get("prompt", "")
    seed = final_params.get("seed")
    # Always ensure a concrete seed for reproducibility tracking
    if seed is None or seed == -1:
        seed = random.randint(0, 2**32 - 1)

    # 6. Build the flat job-params dict and execute via the generation queue
    #    (same lineage path as ToolView). Schema-gated well-known fields first,
    #    then every remaining tool-specific param, then generation knobs, then
    #    controlnet lineage metadata.
    param_props = param_schema.get("properties", {})
    _GEN_KEYS = {"steps", "cfg", "guidance", "sampler", "scheduler", "loras", "negative_prompt"}
    _CONTROLNET_META_KEYS = {
        '_original_input_paths', '_input_preprocessors',
        '_input_preprocessor_params', '_original_input_hashes',
    }
    _SET_EXPLICITLY = {"prompt", "input_images", "width", "height", "seed"}

    job_params: Dict[str, Any] = {}
    if "prompt" in param_props:
        job_params["prompt"] = prompt
    if "width" in param_props:
        job_params["width"] = width
        job_params["height"] = height
    if input_images and "input_images" in param_props:
        job_params["input_images"] = final_params["input_images"]
    job_params["seed"] = seed

    # Remaining tool-specific params (mask, input_media_ids, strength, ...).
    for key, value in final_params.items():
        if key in _SET_EXPLICITLY or key in _GEN_KEYS or key in _CONTROLNET_META_KEYS:
            continue
        job_params[key] = value

    # Generation parameters (steps, cfg, loras, etc.). Only emit knobs the
    # tool actually exposes, and never send nulls as explicit "defaults".
    for gen_key in ("steps", "cfg", "guidance", "sampler", "scheduler"):
        if gen_key not in param_props:
            continue
        value = final_params.get(gen_key)
        if value is not None:
            job_params[gen_key] = value

    if "loras" in param_props:
        loras_payload = [
            {"lora": l["path"], "weight": l.get("weight", 1.0)}
            for l in final_params.get("loras", [])
            if l and l.get("path")
        ]
        if loras_payload:
            job_params["loras"] = loras_payload

    if "negative_prompt" in param_props:
        value = final_params.get("negative_prompt")
        if value is not None:
            job_params["negative_prompt"] = value

    # Forward controlnet metadata so lineage resolution picks it up
    for meta_key in _CONTROLNET_META_KEYS:
        val = final_params.get(meta_key)
        if val is not None:
            job_params[meta_key] = val

    _check_failure_block(kwargs.get("workspace_dir"), tool_id, task_type)

    queue = get_generation_queue()
    chat_id = kwargs.get("chat_id")
    auto_delete_duration = kwargs.get("auto_delete_duration")
    if auto_delete_duration is None and chat_id is not None:
        # V2 tool execution runs outside the legacy generation helpers, so read
        # the chat's canonical generation preference explicitly.
        from database import Chat
        from database_registry import get_database_registry

        settings_db = get_database_registry().get_database(get_current_profile())
        async with settings_db.async_session_maker() as settings_session:
            chat = await settings_session.get(Chat, int(chat_id))
            if chat and chat.generation_settings:
                try:
                    chat_settings = json.loads(chat.generation_settings)
                    auto_delete_duration = chat_settings.get("auto_delete_duration")
                except (json.JSONDecodeError, TypeError):
                    pass
    disposition_kwargs = {}
    if kwargs.get("output_disposition") is not None:
        disposition_kwargs = {
            "output_disposition": kwargs["output_disposition"],
            "output_context_kind": kwargs.get("output_context_kind"),
            "output_context_id": kwargs.get("output_context_id"),
        }
    elif chat_id is not None:
        disposition_kwargs = {
            "output_disposition": "context",
            "output_context_kind": "chat",
            "output_context_id": str(chat_id),
        }
    job_id = await queue.submit_job(
        generator_name=provider.provider_id,
        model_name=tool_descriptor.name,
        folder_path=_get_default_folder(kwargs.get("workspace_dir")),
        parameters=job_params,
        tool_id=tool_id,
        task_type=task_type,
        generator_instance_id=kwargs.get("generator_instance_id") or "agent",
        project_id=kwargs.get("project_id"),
        auto_delete_duration=auto_delete_duration,
        **disposition_kwargs,
    )

    # Resolve backend_name for logging and dispatch
    backend_name = queue._resolve_backend_info(tool_id, None, provider.provider_id)[0]
    log.info(f"[call_tool_v2] Submitted job {job_id}, backend_name={backend_name}")

    interrupt_checker = kwargs.get("interrupt_checker")

    try:
        async def _status_checker():
            if callable(interrupt_checker) and interrupt_checker():
                return "interrupted"
            return "running"

        # wait_for_jobs polls for the full generation duration — the biggest
        # collision window for the shared SDK session under concurrent
        # asyncio.gather() calls. It never actually issues queries on the
        # `session` argument itself (it derives its own session_maker and
        # opens a fresh short-lived session per poll internally) — the param
        # only needs to exist for API compatibility. Hand it a session of its
        # own, created the same way as the workspace-copy fresh session
        # below, so the shared SDK session is never referenced while this
        # potentially multi-minute wait is in flight.
        from database_registry import get_database_registry
        wait_db = get_database_registry().get_database(get_current_profile())
        async with wait_db.async_session_maker() as wait_session:
            media_ids, errors, cancelled_count, _job_to_media = await wait_for_jobs(
                [job_id],
                wait_session,
                status_checker=_status_checker,
            )
    except asyncio.CancelledError:
        await queue.cancel_job(job_id)
        raise

    # 8. Handle failure
    if errors and not media_ids and cancelled_count == 0:
        error_msg = "; ".join(errors)
        raise RuntimeError(_with_retry_guidance(kwargs.get("workspace_dir"), tool_id, error_msg, task_type))

    if cancelled_count > 0 and not media_ids:
        raise RuntimeError("Generation cancelled by user")

    if not media_ids:
        raise RuntimeError("Generation completed without media output")

    _clear_failure_streak(kwargs.get("workspace_dir"), tool_id, task_type)
    media_id = media_ids[0]

    # 9. Copy output to workspace so the agent can reference/manipulate it
    # Use a fresh session to avoid conflicts when multiple call_tool run concurrently
    workspace_dir = kwargs.get("workspace_dir")
    media_file_path = None
    workspace_path = None
    width = None
    height = None
    from database_registry import get_database_registry
    db = get_database_registry().get_database(get_current_profile())
    async with db.async_session_maker() as fresh_session:
        result = await fresh_session.execute(
            select(MediaItem.file_path, MediaItem.width, MediaItem.height).where(MediaItem.id == media_id)
        )
        row = result.one_or_none()
        if row:
            media_file_path, width, height = row

    if workspace_dir and media_file_path:
        try:
            filename = os.path.basename(media_file_path)
            workspace_path = os.path.join(str(workspace_dir), filename)
            shutil.copy2(media_file_path, workspace_path)
        except Exception as e:
            log.warning(f"[call_tool_v2] Failed to copy to workspace: {e}")
    elif not media_file_path:
        log.warning(f"[call_tool_v2] Could not find file path for media {media_id}")

    # The recorded "parameters" echo (→ generation_metadata.parameters) is the
    # generation-knob view: drop the positional well-known input fields and the
    # internal controlnet lineage keys so the metadata shape stays stable.
    _INPUT_POSITION_KEYS = {"prompt", "input_images", "width", "height", "seed", "input_media_ids"}
    recorded_params = {
        k: v for k, v in final_params.items()
        if k not in _INPUT_POSITION_KEYS and not k.startswith("_")
    }

    return {
        "media_id": media_id,
        "path": workspace_path or media_file_path,
        "width": width,
        "height": height,
        "seed": seed,
        "tool_id": tool_id,
        "tool_name": tool_descriptor.name,
        "task_type": task_type,
        "parameters": recorded_params,
        "input_media_ids": list(final_params.get("input_media_ids") or []),
        "duration_ms": int((time.perf_counter() - started_at) * 1000),
    }


@tool(
    name="call_tool",
    description=(
        "Execute an STP generation tool. Use discover first to find tool_id and check schema. "
        "Pass all tool arguments in a single `parameters` object: prompt, input_images (list of "
        "media_id ints or preprocessed paths), width, height (for aspect ratio), seed, loras, plus "
        "any tool-specific generation knobs (steps, cfg, guidance, ...). Omitted parameters use "
        "schema defaults automatically. Omit seed for random results (the default). Only pass seed "
        "for reproducibility. For controlnet, pass controlnet='pose' (or canny, depth, lineart, etc.) "
        "alongside input_images — preprocessing happens automatically."
    ),
    parameters=[
        ToolParameter(
            name="tool_id",
            type="string",
            description="Full tool ID (e.g. 'comfyui:flux-schnell')",
        ),
        ToolParameter(
            name="parameters",
            type="object",
            description="All tool arguments in one object: prompt (required), input_images, width, height, seed, loras, and any tool-specific generation params (steps, cfg, guidance, ...). Omit seed for random.",
        ),
        ToolParameter(
            name="controlnet",
            type="string",
            description="Controlnet preprocessor to apply to input_images: canny, depth, lineart, lineart_realistic, lineart_anime, pose, pose_hands",
            required=False,
            enum=["canny", "depth", "lineart", "lineart_realistic", "lineart_anime", "pose", "pose_hands"],
        ),
    ],
)
async def call_tool(
    tool_id: Optional[str] = None,
    parameters: Optional[Dict[str, Any]] = None,
    controlnet: Optional[str] = None,
    **kwargs,
) -> str:
    # Some models wrap every arg under "parameters" so that ``tool_id`` lands
    # nested ({"parameters": {"tool_id": ..., "prompt": ..., ...}}). Lift it
    # back out before the missing-arg check below fires.
    if tool_id is None and isinstance(parameters, dict) and isinstance(parameters.get("tool_id"), str):
        tool_id = parameters.pop("tool_id")

    if tool_id is None:
        return "Error: call_tool() missing required argument: 'tool_id'"

    # Some models (e.g. GPT-5.4) flatten args to top-level instead of nesting under
    # "parameters". Recover: if parameters is missing but known fields appear in
    # kwargs, rebuild the parameters object from them.
    if parameters is None:
        _known_keys = {"prompt", "input_images", "width", "height", "seed"}
        flat = {k: kwargs.pop(k) for k in list(kwargs) if k in _known_keys}
        if flat:
            parameters = flat
        else:
            return "Error: call_tool() missing required argument: 'parameters'"
    # Some models pass dict-valued args as JSON-encoded strings (vLLM tool-call
    # template hiccups, Claude-XML "<parameter=...>" escapes, weaker models that
    # double-encode). Try to recover by json-decoding; only error out if the
    # decoded value still isn't a dict, so the agent gets a clear next step.
    parameters = _coerce_dict_arg(parameters)
    if not isinstance(parameters, dict):
        return (
            f"Error: 'parameters' must be a JSON object, got {type(parameters).__name__}. "
            'Example: parameters={"prompt": "a golden retriever in a meadow"}'
        )
    # Route top-level controlnet param into parameters so execute_call_tool sees it
    if controlnet:
        parameters["controlnet"] = controlnet
    try:
        result = await execute_call_tool(
            tool_id=tool_id,
            parameters=parameters,
            **kwargs,
        )
    except Exception as e:
        return f"Error: {e}"

    if result.get("metadata_only"):
        # Data tool (detect-objects, ...): no media output — return the result
        # data (detections, image_size, ...) directly.
        payload = {k: v for k, v in result.items() if k not in ("metadata_only", "tool_name")}
        return json.dumps(payload)

    media_id = result["media_id"]
    workspace_filename = os.path.basename(result["path"]) if result.get("path") else None
    parts = [f"<result media_id={media_id}"]
    if workspace_filename:
        parts.append(f' workspace_file="{workspace_filename}"')
    parts.append(" />")
    parts.append(f"Not yet shown to the user. Call show(media_id={media_id}, role='final') for a committed result or role='intermediate' for inspection. ")
    parts.append(f"Use media_id {media_id} if you need to reference this output in a follow-up call_tool.")
    if workspace_filename:
        parts.append(f' For create_layout, use src="{workspace_filename}".')
    return "".join(parts)
