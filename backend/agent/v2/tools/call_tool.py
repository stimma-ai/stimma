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

from config import get_settings
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

    if has_input_images and "image-to-image" in task_types:
        return "image-to-image"

    # Dual-mode video tools: text-to-video can become image-to-video when image input exists.
    if has_input_images and primary == "text-to-video" and "image-to-video" in task_types:
        return "image-to-video"

    return primary


def _get_default_folder(workspace_dir: Optional[str] = None) -> str:
    """Get default generation folder for the current profile."""
    settings = get_settings()
    profile_id = get_current_profile()
    try:
        folder = settings.get_generation_folder_for_profile(profile_id)
        return folder.path
    except ValueError:
        for folder in settings.folders:
            if folder.allow_generate:
                return folder.path
        return "./output"


# Consecutive-failure streaks per (workspace, tool). LLMs will otherwise
# retry a hard-failing tool indefinitely; escalating error text alone proved
# insufficient (models retried through explicit "STOP retrying" guidance), so
# past the hard cap we refuse to submit at all — instant, costless, and
# unambiguous. Streaks reset on any success for that tool.
_failure_streaks: Dict[tuple, int] = {}
_FAILURE_STREAK_WARN = 2
_FAILURE_STREAK_MAX = 4
_FAILURE_STREAK_BLOCK = 5


def _with_retry_guidance(workspace_dir: Optional[str], tool_id: str, error_msg: str) -> str:
    key = (str(workspace_dir), tool_id)
    streak = _failure_streaks.get(key, 0) + 1
    _failure_streaks[key] = streak
    if len(_failure_streaks) > 4096:
        _failure_streaks.clear()
    if streak >= _FAILURE_STREAK_MAX:
        return (
            f"{error_msg}\n\nThis tool has now failed {streak} times in a row. "
            "STOP retrying it — the failure is not transient. Report the failure to the user "
            "plainly (what you tried, what error came back) and, only if one exists, offer a "
            "genuinely different tool or approach."
        )
    if streak >= _FAILURE_STREAK_WARN:
        return (
            f"{error_msg}\n\nThis tool has failed {streak} times in a row. "
            "At most one more retry is reasonable; if that fails too, stop and report the "
            "failure to the user instead of retrying again."
        )
    return error_msg


def _clear_failure_streak(workspace_dir: Optional[str], tool_id: str) -> None:
    _failure_streaks.pop((str(workspace_dir), tool_id), None)


def _check_failure_block(workspace_dir: Optional[str], tool_id: str) -> None:
    """Refuse execution outright once a tool has hard-failed repeatedly."""
    streak = _failure_streaks.get((str(workspace_dir), tool_id), 0)
    if streak >= _FAILURE_STREAK_BLOCK:
        raise RuntimeError(
            f"Refusing to run '{tool_id}': it has failed {streak} times in a row and further "
            "retries are blocked. Report the failure to the user (what you tried and the error "
            "that came back); it becomes available again once the user weighs in."
        )


async def execute_call_tool(
    tool_id: str,
    parameters: Optional[Dict[str, Any]] = None,
    task_type_override: Optional[str] = None,
    **kwargs,
) -> Dict[str, Any]:
    # STP tools have a SINGLE parameter namespace: prompt, input_images, mask,
    # width/height, seed, loras and every tool-specific knob live together in one
    # dict keyed by name (matching the tool's parameter_schema).
    params: Dict[str, Any] = dict(parameters or {})

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
    if isinstance(input_images, list) and not input_media_ids:
        derived_ids = []
        for img in input_images:
            if isinstance(img, int):
                derived_ids.append(img)
            elif isinstance(img, str) and img.isdigit():
                derived_ids.append(int(img))
            elif isinstance(img, str):
                # Tolerate a `media:<id>` / `media_<id>` reference — the agent
                # reasonably reaches for it, and silently dropping it surfaces
                # downstream as the opaque "No input media provided".
                prefix_match = re.match(r'^media[:_](.*)$', img.strip(), flags=re.IGNORECASE)
                if prefix_match is not None:
                    ref = prefix_match.group(1)
                    if ref.isdigit():
                        derived_ids.append(int(ref))
                        continue
                    # A media-prefixed ref with a non-numeric id is malformed —
                    # fail fast and name it rather than treating it as a path.
                    raise ValueError(
                        f"Invalid media reference {img!r}: expected 'media:<id>' "
                        "with a numeric library media id."
                    )
                # Workspace path — resolve to media_id by matching filename
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
                        log.info(f"[call_tool_v2] Resolved workspace path '{basename}' to media_id {row[0]}")
                    else:
                        # Don't drop it silently — an unresolved entry becomes an
                        # empty input list and the provider reports the misleading
                        # "No input media provided". Fail loudly, naming the value.
                        raise ValueError(
                            f"Could not resolve input image {img!r} to a library media. "
                            "Pass a library media id (int), a digit string, or an existing "
                            "workspace filename — not a 'media:<id>'-style ref with a non-numeric id."
                        )
        if derived_ids:
            final_params["input_media_ids"] = derived_ids

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

            source_path = await _resolve_media_path(session, media_id_val)
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

    _check_failure_block(kwargs.get("workspace_dir"), tool_id)

    queue = get_generation_queue()
    job_id = await queue.submit_job(
        generator_name=provider.provider_id,
        model_name=tool_descriptor.name,
        folder_path=_get_default_folder(kwargs.get("workspace_dir")),
        parameters=job_params,
        tool_id=tool_id,
        task_type=task_type,
        generator_instance_id=kwargs.get("generator_instance_id") or "agent",
        project_id=kwargs.get("project_id"),
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

        media_ids, errors, cancelled_count, _job_to_media = await wait_for_jobs(
            [job_id],
            session,
            status_checker=_status_checker,
        )
    except asyncio.CancelledError:
        await queue.cancel_job(job_id)
        raise

    # 8. Handle failure
    if errors and not media_ids and cancelled_count == 0:
        error_msg = "; ".join(errors)
        raise RuntimeError(_with_retry_guidance(kwargs.get("workspace_dir"), tool_id, error_msg))

    if cancelled_count > 0 and not media_ids:
        raise RuntimeError("Generation cancelled by user")

    if not media_ids:
        raise RuntimeError("Generation completed without media output")

    _clear_failure_streak(kwargs.get("workspace_dir"), tool_id)
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

    media_id = result["media_id"]
    workspace_filename = os.path.basename(result["path"]) if result.get("path") else None
    parts = [f"<result media_id={media_id}"]
    if workspace_filename:
        parts.append(f' workspace_file="{workspace_filename}"')
    parts.append(" />")
    parts.append(f"Not yet shown to the user. Call show(media_id={media_id}) to display it, or use ![caption](media_id={media_id}) in your response to embed it inline. ")
    parts.append(f"Use media_id {media_id} if you need to reference this output in a follow-up call_tool.")
    if workspace_filename:
        parts.append(f' For create_layout, use src="{workspace_filename}".')
    return "".join(parts)
