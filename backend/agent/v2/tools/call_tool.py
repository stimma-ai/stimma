"""Execute STP provider tools directly with media save."""

import asyncio
import json
import os
import random
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
    inputs: Dict[str, Any],
    parameters: Optional[Dict[str, Any]],
) -> tuple[Optional[str], Optional[Dict[str, Any]]]:
    """Extract and remove controlnet config from inputs/parameters.

    Returns (preprocessor_name, cn_params) or (None, None).
    """
    # Strip hallucinated keys silently
    for key in _CONTROLNET_STRIP_KEYS:
        if inputs:
            inputs.pop(key, None)
        if parameters:
            parameters.pop(key, None)

    # Find the preprocessor name from either dict
    preprocessor = None
    for key in _CONTROLNET_TYPE_KEYS:
        if inputs and key in inputs:
            preprocessor = inputs.pop(key)
        if parameters and key in parameters:
            val = parameters.pop(key)
            if preprocessor is None:
                preprocessor = val

    if preprocessor is None:
        return None, None

    # Also extract optional controlnet_params
    cn_params = None
    for d in (inputs, parameters):
        if d and "controlnet_params" in d:
            cn_params = d.pop("controlnet_params")

    # Validate
    if preprocessor not in CONTROLNET_PREPROCESSORS:
        raise ValueError(
            f"Unknown controlnet preprocessor '{preprocessor}'. "
            f"Available: {', '.join(sorted(CONTROLNET_PREPROCESSORS))}"
        )

    return preprocessor, cn_params


def _resolve_effective_task_type(tool_descriptor, inputs: Dict[str, Any]) -> str:
    """Mirror ToolView task-type resolution for multi-task tools."""
    task_types = list(tool_descriptor.task_types or [])
    primary = tool_descriptor.task_type or (task_types[0] if task_types else "unknown")

    input_images = inputs.get("input_images", []) or []
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


async def execute_call_tool(
    tool_id: str,
    inputs: Dict[str, Any],
    parameters: Optional[Dict[str, Any]] = None,
    task_type_override: Optional[str] = None,
    **kwargs,
) -> Dict[str, Any]:
    # Extract controlnet config if the agent passed it inline
    cn_preprocessor, cn_params = _extract_controlnet_config(inputs, parameters)

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
        task_type = _resolve_effective_task_type(tool_descriptor, inputs)

    log.info(f"[call_tool_v2] Executing {tool_id} ({tool_descriptor.name}), task_type={task_type}")

    # 2. Build parameters from schema defaults + overrides
    param_schema = tool_descriptor.parameter_schema or {}
    default_params = {}
    for prop_name, prop_info in param_schema.get("properties", {}).items():
        if "default" in prop_info:
            default_params[prop_name] = prop_info["default"]

    final_params = default_params.copy()
    if parameters:
        final_params.update(parameters)

    # 3. Move param-like keys from inputs to params
    PARAM_KEYS = {"steps", "cfg", "guidance", "sampler", "scheduler", "loras", "negative_prompt"}
    for key in PARAM_KEYS:
        if key in inputs:
            final_params[key] = inputs.pop(key)

    # 4. Resolve LoRAs
    loras = final_params.get("loras", [])
    if loras:
        # Accept either the input shape ({path, weight}) or the stored/recorded
        # shape ({lora, weight} / {name, weight}) so a recipe read back from an
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

    # 5. Handle dimensions
    width = inputs.pop("width", None) or final_params.pop("width", 1024)
    height = inputs.pop("height", None) or final_params.pop("height", 1024)

    allowed_dims = _get_allowed_dimensions(tool_descriptor)
    if allowed_dims:
        width, height = _snap_to_allowed(width, height, allowed_dims)

    # 6. Capture input media IDs for lineage parity with ToolView payloads
    input_images = inputs.get("input_images", [])
    input_media_ids = inputs.get("input_media_ids")
    if isinstance(input_images, list) and not input_media_ids:
        derived_ids = []
        for img in input_images:
            if isinstance(img, int):
                derived_ids.append(img)
            elif isinstance(img, str) and img.isdigit():
                derived_ids.append(int(img))
            elif isinstance(img, str):
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
                        log.warning(f"[call_tool_v2] Could not resolve input path to media_id: {img}")
        if derived_ids:
            inputs["input_media_ids"] = derived_ids

    # 6b. Inline controlnet preprocessing when the agent passed controlnet=
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

        raw_images = inputs.get("input_images", []) or []
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

        inputs["input_images"] = preprocessed_images
        inputs["_original_input_paths"] = original_paths
        inputs["_input_preprocessors"] = preprocessors_list
        inputs["_input_preprocessor_params"] = preprocessor_params_list
        log.info(f"[call_tool_v2] Inline controlnet preprocessing: {cn_preprocessor} on {len(raw_images)} image(s)")

    # Extract prompt before building the job params
    prompt = inputs.get("prompt", "")
    seed = inputs.get("seed") or final_params.get("seed")
    # Always ensure a concrete seed for reproducibility tracking
    if seed is None or seed == -1:
        seed = random.randint(0, 2**32 - 1)

    # 7. Build the single flat parameters dict and execute via generation queue
    #    (same lineage path as ToolView). Everything — inputs and generation
    #    params alike — lives in one dict matching the tool's parameter_schema.
    param_props = (tool_descriptor.parameter_schema or {}).get("properties", {})
    job_params: Dict[str, Any] = {}
    if "prompt" in param_props:
        job_params["prompt"] = prompt
    if "width" in param_props:
        job_params["width"] = width
        job_params["height"] = height
    if input_images and "input_images" in param_props:
        job_params["input_images"] = inputs["input_images"]
    job_params["seed"] = seed

    # Add remaining inputs (excluding controlnet metadata which is appended last)
    _CONTROLNET_META_KEYS = {
        '_original_input_paths', '_input_preprocessors',
        '_input_preprocessor_params', '_original_input_hashes',
    }
    for key, value in inputs.items():
        if key not in ("prompt", "input_images", "width", "height", "seed"):
            job_params[key] = value

    # Generation parameters (steps, cfg, loras, etc.)
    job_params.update({
        "steps": final_params.get("steps"),
        "cfg": final_params.get("cfg"),
        "guidance": final_params.get("guidance"),
        "sampler": final_params.get("sampler"),
        "scheduler": final_params.get("scheduler"),
        "loras": [
            {"lora": l["path"], "weight": l.get("weight", 1.0)}
            for l in final_params.get("loras", [])
            if l and l.get("path")
        ],
        "negative_prompt": final_params.get("negative_prompt", ""),
        # Pass through any remaining tool-specific generation params, but NEVER
        # the input-bucket keys: those are set explicitly above from `inputs`,
        # and final_params still holds their schema DEFAULTS (e.g. prompt="",
        # width=1024) which would otherwise clobber the real values and produce
        # empty-prompt / default-dimension (unconditional) generations.
        **{k: v for k, v in final_params.items() if k not in (
            "steps", "cfg", "guidance", "sampler", "scheduler", "loras", "negative_prompt",
            "prompt", "width", "height", "seed", "input_images",
        )},
    })

    # Forward controlnet metadata so lineage resolution picks it up
    for meta_key in _CONTROLNET_META_KEYS:
        val = job_params.pop(meta_key, None) or inputs.get(meta_key)
        if val is not None:
            job_params[meta_key] = val

    queue = get_generation_queue()
    job_id = await queue.submit_job(
        generator_name=provider.provider_id,
        model_name=tool_descriptor.name,
        folder_path=_get_default_folder(kwargs.get("workspace_dir")),
        parameters=job_params,
        tool_id=tool_id,
        task_type=task_type,
        generator_instance_id="agent",
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
        raise RuntimeError(error_msg)

    if cancelled_count > 0 and not media_ids:
        raise RuntimeError("Generation cancelled by user")

    if not media_ids:
        raise RuntimeError("Generation completed without media output")

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

    return {
        "media_id": media_id,
        "path": workspace_path or media_file_path,
        "width": width,
        "height": height,
        "seed": seed,
        "tool_id": tool_id,
        "tool_name": tool_descriptor.name,
        "task_type": task_type,
        "parameters": final_params,
        "input_media_ids": list(inputs.get("input_media_ids") or []),
        "duration_ms": int((time.perf_counter() - started_at) * 1000),
    }


@tool(
    name="call_tool",
    description=(
        "Execute an STP generation tool. Use discover first to find tool_id and check schema. "
        "Inputs: prompt, input_images (list of media_id ints or preprocessed paths), width, height (for aspect ratio). "
        "Only pass: prompt, seed, loras, input_images, width, height. All other parameters use schema defaults automatically. "
        "Omit seed for random results (the default). Only pass seed for reproducibility. "
        "For controlnet, pass controlnet='pose' (or canny, depth, lineart, etc.) alongside input_images — preprocessing happens automatically."
    ),
    parameters=[
        ToolParameter(
            name="tool_id",
            type="string",
            description="Full tool ID (e.g. 'comfyui:flux-schnell')",
        ),
        ToolParameter(
            name="inputs",
            type="object",
            description="Tool inputs: prompt (required), input_images, width, height, controlnet. Omit seed for random.",
        ),
        ToolParameter(
            name="parameters",
            type="object",
            description="Override generation parameters: steps, cfg, guidance, loras, etc.",
            required=False,
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
    inputs: Optional[Dict[str, Any]] = None,
    parameters: Optional[Dict[str, Any]] = None,
    controlnet: Optional[str] = None,
    **kwargs,
) -> str:
    # Some models wrap every arg under "inputs" so that ``tool_id`` lands
    # nested ({"inputs": {"tool_id": ..., "prompt": ..., ...}}). Lift it
    # back out before the missing-arg check below fires.
    if tool_id is None and isinstance(inputs, dict) and isinstance(inputs.get("tool_id"), str):
        tool_id = inputs.pop("tool_id")

    if tool_id is None:
        return "Error: call_tool() missing required argument: 'tool_id'"

    # Some models (e.g. GPT-5.4) flatten inputs to top-level args instead of nesting under "inputs".
    # Detect and recover: if inputs is missing but known input keys appear in kwargs, rebuild inputs.
    if inputs is None:
        _input_keys = {"prompt", "input_images", "width", "height", "seed"}
        flat = {k: kwargs.pop(k) for k in list(kwargs) if k in _input_keys}
        if flat:
            inputs = flat
        else:
            return "Error: call_tool() missing required argument: 'inputs'"
    # Some models pass dict-valued args as JSON-encoded strings (vLLM tool-call
    # template hiccups, Claude-XML "<parameter=...>" escapes, weaker models that
    # double-encode). Try to recover by json-decoding; only error out if the
    # decoded value still isn't a dict, so the agent gets a clear next step.
    inputs = _coerce_dict_arg(inputs)
    if not isinstance(inputs, dict):
        return (
            f"Error: 'inputs' must be a JSON object, got {type(inputs).__name__}. "
            'Example: inputs={"prompt": "a golden retriever in a meadow"}'
        )
    parameters = _coerce_dict_arg(parameters)
    if parameters is not None and not isinstance(parameters, dict):
        return (
            f"Error: 'parameters' must be a JSON object or omitted, got {type(parameters).__name__}. "
            'Example: parameters={"steps": 8, "guidance": 1}'
        )
    # Route top-level controlnet param into inputs so execute_call_tool sees it
    if controlnet:
        inputs["controlnet"] = controlnet
    try:
        result = await execute_call_tool(
            tool_id=tool_id,
            inputs=inputs,
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
