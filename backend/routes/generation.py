"""Image generation routes."""
import asyncio
import json
import os
import uuid
import shutil
from pathlib import Path
from typing import Any, List, Optional, Dict
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Form
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import MediaItem, MediaLineage, GenerationJob, Tool, CachedProviderTool
from database_registry import get_database_registry
from core.dependencies import get_db_session
from core.profile_context import get_current_profile
from core.logging import get_logger
from models.api_models import GenerationJobRequest, GenerationJobResponse, BatchJobRequest, BatchJobResponse, MediaBatchJobRequest
from config import get_settings
from prompts import get_prompt
from utils.websocket import ws_manager
from utils.background_tasks import generation_input_media_ids
from project_service import get_project_or_404
from llm import EntitlementError

router = APIRouter(prefix="/api/generate", tags=["generation"])
log = get_logger(__name__)


def _entitlement_http_exception(e) -> HTTPException:
    """Enhance-at-submit hit EntitlementError (llm.py) — no active Stimma
    Cloud subscription. 402 + a typed code so the frontend can classify
    without matching the message string."""
    return HTTPException(
        status_code=402,
        detail={"code": "subscription_required", "message": str(e)},
    )


# Task types whose output is audio; mirrors the prompt enhancer routing used
# by post-processing chain steps.
_AUDIO_TASK_TYPES = {"text-to-audio", "text-to-music", "text-to-speech"}
_IMAGE_INPUT_CONTROLS = {"image_picker"}
_IMAGE_FILE_FORMATS = {"file-path", "image-file"}
_NON_INPUT_IMAGE_FIELDS = {
    "aspect_ratio",
    "height",
    "image_size",
    "megapixels",
    "resolution",
    "target_resolution",
    "width",
}
_IMAGE_INPUT_FIELD_NAMES = {
    "image",
    "images",
    "input_image",
    "input_images",
    "source_image",
    "source_images",
    "pose_image",
    "reference_image",
    "reference_images",
}


def _provider_id_for_tool(tool_id: str) -> str:
    return tool_id.split(":")[0] if ":" in tool_id else tool_id


def _model_name_for_tool(tool_id: str) -> str:
    return tool_id.split(":")[-1] if ":" in tool_id else tool_id


def _count_value(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, list):
        return sum(_count_value(item) for item in value)
    if isinstance(value, dict):
        # Set references are expanded before prompt routing. A dict here is not
        # a concrete media item for this single job.
        return 0
    if isinstance(value, str):
        return 1 if value.strip() else 0
    return 0


def _first_int(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, list):
        for item in value:
            found = _first_int(item)
            if found is not None:
                return found
    return None


def _first_slot_int(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, list):
        if not value:
            return None
        return _first_slot_int(value[0])
    return None


def _optional_int(parameters: Dict[str, Any], name: str) -> Optional[int]:
    try:
        value = parameters.get(name)
        return int(value) if value else None
    except (TypeError, ValueError):
        return None


def _field_can_carry_image_input(field: str, schema_props: Dict[str, Any]) -> bool:
    lowered = field.lower()
    if (
        field.startswith("_")
        or field.endswith("_media_id")
        or field.endswith("_media_ids")
        or lowered in _NON_INPUT_IMAGE_FIELDS
    ):
        return False
    prop = schema_props.get(field) or {}
    control = str(prop.get("x-control") or "")
    if control in _IMAGE_INPUT_CONTROLS:
        return True
    if control in {"video_picker", "video_frame_picker", "audio_picker"}:
        return False

    if lowered in _IMAGE_INPUT_FIELD_NAMES or lowered.endswith("_image") or lowered.endswith("_images"):
        fmt = str(prop.get("format") or prop.get("x-format") or "").lower()
        content_type = str(prop.get("contentMediaType") or "").lower()
        item_schema = prop.get("items") if isinstance(prop.get("items"), dict) else {}
        item_fmt = str(item_schema.get("format") or item_schema.get("x-format") or "").lower()
        item_content_type = str(item_schema.get("contentMediaType") or "").lower()
        if (
            fmt in _IMAGE_FILE_FORMATS
            or item_fmt in _IMAGE_FILE_FORMATS
            or content_type.startswith("image/")
            or item_content_type.startswith("image/")
        ):
            return True
        # Historical/local tools sometimes declare media by conventional name
        # only. Keep the fallback name-based, but not description-based.
        return True
    return False


def _prompt_input_image_count(
    parameters: Dict[str, Any],
    schema_props: Dict[str, Any],
    effective_task: str,
) -> int:
    # The enhancer's video style is task-authoritative; don't let the source
    # frame make image-to-video look like an image edit.
    if "video" in (effective_task or ""):
        return 0
    return sum(
        _count_value(value)
        for field, value in parameters.items()
        if _field_can_carry_image_input(field, schema_props)
    )


def _prompt_media_id(parameters: Dict[str, Any], effective_task: str) -> Optional[int]:
    if "video" in (effective_task or ""):
        # i2v enhancement may include the start frame as visual context. Keep
        # positional media-id arrays positional: [None, end_id] must not promote
        # the end frame into the "first frame" slot.
        for key in (
            "input_media_ids",
            "input_image_media_ids",
            "input_images_media_id",
            "input_image_media_id",
            "image_media_id",
            "source_image_media_id",
        ):
            found = _first_slot_int(parameters.get(key))
            if found is not None:
                return found
        return None

    priority = (
        "input_media_ids",
        "input_image_media_ids",
        "input_images_media_id",
        "input_image_media_id",
        "image_media_id",
        "source_image_media_id",
    )
    for key in priority:
        found = _first_int(parameters.get(key))
        if found is not None:
            return found
    for key, value in parameters.items():
        if key.endswith("_media_id") or key.endswith("_media_ids"):
            found = _first_int(value)
            if found is not None:
                return found
    return None


async def _retain_generation_inputs(
    session: AsyncSession, parameters: Dict[str, Any]
) -> None:
    """First use makes every referenced Asset durable before work begins."""
    media_ids = generation_input_media_ids(parameters)
    if not media_ids:
        return
    from utils.background_tasks import clear_auto_delete_for_media

    await clear_auto_delete_for_media(session, media_ids, ws_manager)


def _model_from_prompt_options(prompt_options: Optional[Dict[str, Any]]) -> Optional[str]:
    if not isinstance(prompt_options, dict):
        return None
    auto_improve = prompt_options.get("autoImprove")
    if not isinstance(auto_improve, dict):
        return None
    model = auto_improve.get("model")
    return str(model) if isinstance(model, str) and model.strip() else None


def _prompt_pipeline_context(
    tool_id: str,
    task_type: Optional[str],
    prompt_options: Optional[Dict[str, Any]],
) -> tuple[Optional[str], Optional[str], str, Dict[str, Any]]:
    model: Optional[str] = None
    model_vendor: Optional[str] = None
    effective_task = task_type or ""
    schema_props: Dict[str, Any] = {}
    try:
        from providers.registry import ProviderRegistry
        provider_tool = ProviderRegistry.get_instance().get_tool(tool_id)
        if provider_tool:
            descriptor = provider_tool[1]
            metadata = getattr(descriptor, "metadata", None) or {}
            model = (
                getattr(descriptor, "model", None)
                or metadata.get("model_name")
                or metadata.get("model")
            )
            model_vendor = getattr(descriptor, "model_vendor", None) or metadata.get("model_vendor")
            effective_task = task_type or descriptor.task_type or ""
            schema_props = (descriptor.parameter_schema or {}).get("properties", {})
            if not model:
                model = _model_from_prompt_options(prompt_options) or getattr(descriptor, "name", None)
    except Exception as e:
        log.warning(f"Could not resolve tool descriptor for prompt pipeline ({tool_id}): {e}")
    model = model or _model_from_prompt_options(prompt_options) or _model_name_for_tool(tool_id)
    return model, model_vendor, effective_task, schema_props


def _should_consume_forever_reservation(request) -> bool:
    # New clients send true only for a reserved forever work request and false
    # for manual/local submits. Omitted preserves legacy submit semantics.
    return getattr(request, "forever_work_reserved", None) is not False


def _prompt_preload_for_batch_index(request, idx: int) -> Optional[Dict[str, Any]]:
    preloads = getattr(request, "prompt_preloads", None)
    if not isinstance(preloads, list) or idx >= len(preloads):
        return None
    preload = preloads[idx]
    return preload if isinstance(preload, dict) else None


async def _apply_generation_prompt_pipeline(
    parameters: Dict[str, Any],
    *,
    tool_id: str,
    task_type: Optional[str],
    prompt_options: Optional[Dict[str, Any]],
    prompt_preload: Optional[Dict[str, Any]],
    generator_instance_id: Optional[str] = None,
) -> Dict[str, Any]:
    prompt = parameters.get("prompt")
    if not isinstance(prompt, str):
        return parameters

    from prompt_pipeline import run_prompt_pipeline

    # A client-supplied preload wins if present (manual/legacy submits). Forever
    # mode no longer sends one - it registers intent via the prompt warm pool
    # instead, so fall back to whatever the server has kept warm for this
    # generator instance. Either way, a miss just means the synchronous
    # enhance-at-submit path below runs, exactly like today with no preload.
    effective_preload = prompt_preload
    if effective_preload is None and generator_instance_id:
        from generation_queue import get_generation_queue
        try:
            effective_preload = get_generation_queue().consume_prompt_warm_pool(generator_instance_id)
        except Exception as e:
            # A miss must never regress a submit - if the warm pool itself is
            # broken, fall through to the synchronous enhance-at-submit path
            # exactly as if no preload existed, same as a normal cache miss.
            log.warning(f"Prompt warm pool consume failed for {generator_instance_id}: {e}")
            effective_preload = None

    profile_id = get_current_profile()
    db = get_database_registry().get_database(profile_id)
    model, model_vendor, effective_task, schema_props = _prompt_pipeline_context(tool_id, task_type, prompt_options)
    processed_prompt = await run_prompt_pipeline(
        db,
        prompt,
        prompt_options,
        model=model,
        model_vendor=model_vendor,
        is_video="video" in effective_task,
        is_audio=effective_task in _AUDIO_TASK_TYPES,
        input_image_count=_prompt_input_image_count(parameters, schema_props, effective_task),
        media_id=_prompt_media_id(parameters, effective_task),
        width=_optional_int(parameters, "width"),
        height=_optional_int(parameters, "height"),
        profile_id=profile_id,
        prompt_preload=effective_preload,
    )

    updated = dict(parameters)
    updated["prompt"] = processed_prompt
    return updated


async def _decline_unqueued_reserved_work(
    generation_queue,
    request,
    provider_id: Optional[str],
    reservation_handed_to_queue: bool,
) -> None:
    if reservation_handed_to_queue or not _should_consume_forever_reservation(request):
        return
    if not request.generator_instance_id or not provider_id:
        return
    try:
        await generation_queue.decline_work_request(request.generator_instance_id, provider_id)
    except Exception as e:
        log.warning(
            "Failed to decline reserved forever work after pre-queue submit failure: "
            f"generator_instance_id={request.generator_instance_id}, backend={provider_id}: {e}"
        )


# NOTE: Legacy endpoints removed:
# - /tasks - use /api/tools/providers/tools instead
# - /generators - use /api/tools/providers instead
# - /loras/refresh - use /api/tools/refresh instead


@router.get("/folder")
async def get_generation_folder(
    project_id: Optional[int] = Query(None),
    session: AsyncSession = Depends(get_db_session),
):
    """Compatibility endpoint returning server-owned generation staging."""
    import app_dirs

    profile_id = get_current_profile()
    if project_id is not None:
        await get_project_or_404(session, project_id)
    folder = app_dirs.get_managed_staging_dir(profile_id, "generated")
    folder.mkdir(parents=True, exist_ok=True)
    return {"path": str(folder)}


@router.post("/upload-reference")
async def upload_reference_image(file: UploadFile = File(...)):
    """
    Upload a reference image for image-to-image tasks.

    The image is uploaded directly into the library with a database record,
    so it won't be lost if referenced in generation data.

    Returns the path and metadata of the uploaded file.
    """
    from upload_service import get_upload_service, UploadError

    try:
        upload_service = get_upload_service()
        content = await file.read()
        media_item, file_path = await upload_service.upload_file(content, file.filename or "upload.png")

        return {
            "path": file_path,
            "filename": Path(file_path).name,
            "media_id": media_item.id,
            "file_hash": media_item.file_hash,
            "width": media_item.width,
            "height": media_item.height,
        }
    except UploadError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        log.error(f"Failed to upload reference image: {e}")
        raise HTTPException(status_code=500, detail="Failed to upload file")


@router.post("/copy-to-reference")
async def copy_to_reference_image(source_path: str):
    """
    Copy an existing image into managed storage for use as a reference.

    This creates a library copy that won't be affected if the original
    is deleted or trashed. Used when sending images to the edit tab.

    Args:
        source_path: Path to the existing image file

    Returns:
        The path, filename, and metadata of the copied file
    """
    from upload_service import get_upload_service, UploadError

    try:
        upload_service = get_upload_service()
        media_item, file_path = await upload_service.copy_existing_to_library(source_path)

        return {
            "path": file_path,
            "filename": Path(file_path).name,
            "media_id": media_item.id,
            "file_hash": media_item.file_hash,
            "width": media_item.width,
            "height": media_item.height,
        }
    except UploadError as e:
        if "not found" in str(e).lower():
            raise HTTPException(status_code=404, detail=str(e))
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        log.error(f"Failed to copy reference image: {e}")
        raise HTTPException(status_code=500, detail="Failed to copy file")


@router.post("/copy-video-to-reference")
async def copy_video_to_reference(source_path: str):
    """
    Copy an existing video into managed storage for use as a reference.

    This creates a library copy that won't be affected if the original
    is deleted or trashed. Used when sending videos to the upscale tab.

    Args:
        source_path: Path to the existing video file

    Returns:
        The path, filename, and metadata of the copied file
    """
    from upload_service import get_upload_service, UploadError

    try:
        upload_service = get_upload_service()
        media_item, file_path = await upload_service.copy_existing_to_library(source_path)

        return {
            "path": file_path,
            "filename": Path(file_path).name,
            "media_id": media_item.id,
            "file_hash": media_item.file_hash,
            "width": media_item.width,
            "height": media_item.height,
        }
    except UploadError as e:
        if "not found" in str(e).lower():
            raise HTTPException(status_code=404, detail=str(e))
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        log.error(f"Failed to copy reference video: {e}")
        raise HTTPException(status_code=500, detail="Failed to copy file")


@router.delete("/upload-reference/{filename}")
async def delete_reference_image(filename: str):
    """Delete an uploaded reference image."""
    settings = get_settings()
    upload_dir = Path(settings.get_upload_directory())

    # Validate filename (prevent path traversal)
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")

    file_path = upload_dir / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")

    try:
        file_path.unlink()
        log.info(f"Deleted reference image: {file_path}")
        return {"success": True}
    except Exception as e:
        log.error(f"Failed to delete file: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete file")


@router.get("/reference-file")
async def get_reference_file(path: str):
    """Serve a reference image file from the library."""
    from fastapi.responses import FileResponse
    from core.profile_context import get_current_profile

    settings = get_settings()
    profile_id = get_current_profile()

    # Resolve the path
    file_path = Path(path).resolve()

    # Security check: ensure the file is within a configured profile folder or controlnet cache
    import app_dirs

    allowed = False
    for folder in settings.get_folders_for_profile(profile_id):
        try:
            folder_path = Path(folder.path).resolve()
            file_path.relative_to(folder_path)
            allowed = True
            break
        except ValueError:
            continue

    if not allowed:
        from storage_service import managed_object_root
        try:
            file_path.relative_to(managed_object_root(profile_id).resolve())
            allowed = True
        except ValueError:
            pass

    # Also allow controlnet cache, reference prep cache, and upload directories
    if not allowed:
        for cache_name in ("controlnet-cache", "reference-prep-cache"):
            try:
                cache_dir = app_dirs.get_cache_dir() / cache_name
                file_path.relative_to(cache_dir.resolve())
                allowed = True
                break
            except ValueError:
                continue

    if not allowed:
        try:
            upload_dir = Path(settings.get_upload_directory()).resolve()
            file_path.relative_to(upload_dir)
            allowed = True
        except ValueError:
            pass

    if not allowed:
        raise HTTPException(status_code=403, detail="Access denied")

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")

    # Determine media type
    suffix = file_path.suffix.lower()
    media_types = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
        ".gif": "image/gif",
    }
    media_type = media_types.get(suffix, "application/octet-stream")

    return FileResponse(file_path, media_type=media_type)


@router.get("/reference-video-file")
async def get_reference_video_file(path: str):
    """Serve a reference video file from the library."""
    from fastapi.responses import FileResponse
    from core.profile_context import get_current_profile

    settings = get_settings()
    profile_id = get_current_profile()

    # Resolve the path
    file_path = Path(path).resolve()

    # Security check: ensure the file is within a configured profile folder
    allowed = False
    for folder in settings.get_folders_for_profile(profile_id):
        try:
            folder_path = Path(folder.path).resolve()
            file_path.relative_to(folder_path)
            allowed = True
            break
        except ValueError:
            continue

    if not allowed:
        from storage_service import managed_object_root
        try:
            file_path.relative_to(managed_object_root(profile_id).resolve())
            allowed = True
        except ValueError:
            pass

    if not allowed:
        raise HTTPException(status_code=403, detail="Access denied")

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")

    # Determine media type
    suffix = file_path.suffix.lower()
    media_types = {
        ".mp4": "video/mp4",
        ".webm": "video/webm",
        ".mov": "video/quicktime",
        ".avi": "video/x-msvideo",
        ".mkv": "video/x-matroska"
    }
    media_type = media_types.get(suffix, "video/mp4")

    return FileResponse(file_path, media_type=media_type)


@router.post("/upload-reference-video")
async def upload_reference_video(file: UploadFile = File(...)):
    """
    Upload a reference video for video upscale tasks.

    The video is uploaded directly into the library with a database record,
    so it won't be lost if referenced in generation data.

    Returns the path and metadata of the uploaded file.
    """
    from upload_service import get_upload_service, UploadError

    try:
        upload_service = get_upload_service()
        content = await file.read()
        media_item, file_path = await upload_service.upload_file(content, file.filename or "upload.mp4")

        return {
            "path": file_path,
            "filename": Path(file_path).name,
            "media_id": media_item.id,
            "file_hash": media_item.file_hash,
            "width": media_item.width,
            "height": media_item.height,
        }
    except UploadError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        log.error(f"Failed to upload reference video: {e}")
        raise HTTPException(status_code=500, detail="Failed to upload file")


@router.get("/reference-audio-file")
async def get_reference_audio_file(path: str):
    """Serve a reference audio file from the library."""
    from fastapi.responses import FileResponse
    from core.profile_context import get_current_profile

    settings = get_settings()
    profile_id = get_current_profile()

    # Resolve the path
    file_path = Path(path).resolve()

    # Security check: ensure the file is within a configured profile folder
    allowed = False
    for folder in settings.get_folders_for_profile(profile_id):
        try:
            folder_path = Path(folder.path).resolve()
            file_path.relative_to(folder_path)
            allowed = True
            break
        except ValueError:
            continue

    if not allowed:
        from storage_service import managed_object_root
        try:
            file_path.relative_to(managed_object_root(profile_id).resolve())
            allowed = True
        except ValueError:
            pass

    if not allowed:
        raise HTTPException(status_code=403, detail="Access denied")

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")

    # Determine media type
    suffix = file_path.suffix.lower()
    media_types = {
        ".mp3": "audio/mpeg",
        ".wav": "audio/wav",
        ".flac": "audio/flac",
        ".m4a": "audio/mp4",
        ".aac": "audio/aac",
        ".ogg": "audio/ogg",
        ".opus": "audio/opus",
    }
    media_type = media_types.get(suffix, "application/octet-stream")

    return FileResponse(file_path, media_type=media_type)


@router.post("/upload-reference-audio")
async def upload_reference_audio(file: UploadFile = File(...)):
    """
    Upload a reference audio file for audio-input tasks (lip-sync, avatar, etc.).

    The audio is uploaded directly into the library with a database record,
    so it won't be lost if referenced in generation data.

    Returns the path and metadata of the uploaded file.
    """
    from upload_service import get_upload_service, UploadError

    try:
        upload_service = get_upload_service()
        content = await file.read()
        media_item, file_path = await upload_service.upload_file(content, file.filename or "upload.mp3")

        return {
            "path": file_path,
            "filename": Path(file_path).name,
            "media_id": media_item.id,
            "file_hash": media_item.file_hash,
            "width": media_item.width,
            "height": media_item.height,
        }
    except UploadError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        log.error(f"Failed to upload reference audio: {e}")
        raise HTTPException(status_code=500, detail="Failed to upload file")


@router.post("/copy-audio-to-reference")
async def copy_audio_to_reference(source_path: str):
    """
    Copy an existing audio file into managed storage for use as a reference.

    This creates a library copy that won't be affected if the original
    is deleted or trashed. Used when sending audio to an audio-input tool.

    Args:
        source_path: Path to the existing audio file

    Returns:
        The path, filename, and metadata of the copied file
    """
    from upload_service import get_upload_service, UploadError

    try:
        upload_service = get_upload_service()
        media_item, file_path = await upload_service.copy_existing_to_library(source_path)

        return {
            "path": file_path,
            "filename": Path(file_path).name,
            "media_id": media_item.id,
            "file_hash": media_item.file_hash,
            "width": media_item.width,
            "height": media_item.height,
        }
    except UploadError as e:
        if "not found" in str(e).lower():
            raise HTTPException(status_code=404, detail=str(e))
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        log.error(f"Failed to copy reference audio: {e}")
        raise HTTPException(status_code=500, detail="Failed to copy file")


@router.delete("/upload-reference-video/{filename}")
async def delete_reference_video(filename: str):
    """Delete an uploaded reference video."""
    settings = get_settings()
    upload_dir = Path(settings.get_upload_directory())

    # Validate filename (prevent path traversal)
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")

    file_path = upload_dir / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")

    try:
        file_path.unlink()
        log.info(f"Deleted reference video: {file_path}")
        return {"success": True}
    except Exception as e:
        log.error(f"Failed to delete video file: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete file")


@router.post("/upload-mask")
async def upload_mask_image(file: UploadFile = File(...)):
    """
    Upload a mask image for inpainting tasks.

    The mask should be:
    - White (255, 255, 255) = area to inpaint
    - Black (0, 0, 0) = area to preserve

    Returns the path of the uploaded file.
    """
    settings = get_settings()
    upload_dir = Path(settings.get_upload_directory())
    upload_dir.mkdir(parents=True, exist_ok=True)

    # Generate unique filename
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    ext = Path(file.filename).suffix if file.filename else ".png"
    filename = f"mask_{timestamp}_{uuid.uuid4().hex[:8]}{ext}"
    file_path = upload_dir / filename

    try:
        # Save file
        content = await file.read()
        with open(file_path, "wb") as f:
            f.write(content)

        log.info(f"Uploaded mask image: {file_path}")
        return {"path": str(file_path), "filename": filename}
    except Exception as e:
        log.error(f"Failed to upload mask image: {e}")
        raise HTTPException(status_code=500, detail="Failed to upload mask")


@router.post("/upload-paint-layer")
async def upload_paint_layer(file: UploadFile = File(...)):
    """
    Upload a paint layer image (transparent PNG with paint strokes).
    Used for per-reference-image painting before generation.
    Returns the path of the uploaded file.
    """
    settings = get_settings()
    upload_dir = Path(settings.get_upload_directory())
    upload_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"paint_layer_{timestamp}_{uuid.uuid4().hex[:8]}.png"
    file_path = upload_dir / filename

    try:
        content = await file.read()
        with open(file_path, "wb") as f:
            f.write(content)

        log.info(f"Uploaded paint layer: {file_path}")
        return {"path": str(file_path), "filename": filename}
    except Exception as e:
        log.error(f"Failed to upload paint layer: {e}")
        raise HTTPException(status_code=500, detail="Failed to upload paint layer")


def _validate_media_source_path(path: str) -> Path:
    """Resolve a source path and ensure it lives in an allowed media location.

    Mirrors the allow-list used by /reference-file: a configured profile folder,
    the controlnet / reference-prep caches, or the upload directory. Raises 403
    for anything outside those, 404 if it doesn't exist.
    """
    import app_dirs

    settings = get_settings()
    profile_id = get_current_profile()
    file_path = Path(path).resolve()

    allowed = False
    for folder in settings.get_folders_for_profile(profile_id):
        try:
            file_path.relative_to(Path(folder.path).resolve())
            allowed = True
            break
        except ValueError:
            continue
    if not allowed:
        from storage_service import managed_object_root
        try:
            file_path.relative_to(managed_object_root(profile_id).resolve())
            allowed = True
        except ValueError:
            pass
    if not allowed:
        for cache_name in ("controlnet-cache", "reference-prep-cache"):
            try:
                file_path.relative_to((app_dirs.get_cache_dir() / cache_name).resolve())
                allowed = True
                break
            except ValueError:
                continue
    if not allowed:
        try:
            file_path.relative_to(Path(settings.get_upload_directory()).resolve())
            allowed = True
        except ValueError:
            pass

    if not allowed:
        raise HTTPException(status_code=403, detail="Access denied")
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    return file_path


@router.post("/extract-frame")
async def extract_video_frame(
    file: UploadFile | None = File(None),
    source_path: str | None = Form(None),
    position: str = Form("first"),
    time_seconds: float | None = Form(None),
):
    """
    Extract a still frame from a video and store it as a reference image.

    Frame grab happens at the UI ingestion point (when a video lands in an image
    slot): we turn the video into a still here, cache it in the non-library
    reference-prep cache, and from then on it behaves exactly like an image (prep,
    paint, etc. all apply to the still, and the still is what feeds the job).

    Source is either an uploaded file (e.g. an OS file drop) or a `source_path`
    pointing at a library/reference video. `position` is first | last | middle |
    custom (with `time_seconds`).

    Returns the path, filename, dimensions, captured timestamp, and source duration.
    """
    import os
    import tempfile
    import app_dirs
    from utils.video_frames import extract_frame_to_image

    tmp_path: str | None = None
    try:
        if file is not None:
            suffix = Path(file.filename or "video.mp4").suffix or ".mp4"
            fd, tmp_path = tempfile.mkstemp(suffix=suffix)
            with os.fdopen(fd, "wb") as f:
                f.write(await file.read())
            video_path: str | Path = tmp_path
        elif source_path:
            video_path = _validate_media_source_path(source_path)
        else:
            raise HTTPException(status_code=400, detail="Provide a file or source_path")

        try:
            img, time_used, duration, fps = await asyncio.to_thread(
                extract_frame_to_image, video_path, position, time_seconds  # type: ignore[arg-type]
            )
        except RuntimeError as e:
            # ffmpeg unavailable — factual message, surfaced to the user.
            raise HTTPException(status_code=422, detail=str(e))
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))

        cache_dir = app_dirs.get_cache_dir() / "reference-prep-cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        filename = f"video_frame_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}.png"
        out_path = cache_dir / filename
        img.convert("RGB").save(out_path, "PNG")

        log.info(f"Extracted video frame ({position}@{time_used:.2f}s): {out_path} ({img.width}x{img.height})")
        return {
            "path": str(out_path),
            "filename": filename,
            "width": img.width,
            "height": img.height,
            "time_seconds": time_used,
            "duration": duration,
            "fps": fps,
        }
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Failed to extract video frame: {e}")
        raise HTTPException(status_code=500, detail="Failed to extract video frame")
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


@router.get("/frame-preview")
async def frame_preview(source_path: str, t: float = 0.0, w: int = 512):
    """
    Downscaled JPEG of the frame at time `t` in a video, for live scrubbing in the
    frame picker. Returns bytes directly (no caching) — the committed frame is taken
    via /extract-frame. Uses the same seek as extract-frame so the preview matches
    what you'll get.
    """
    from io import BytesIO
    from fastapi.responses import StreamingResponse
    from PIL import Image
    from utils.video_frames import extract_frame_to_image

    video_path = _validate_media_source_path(source_path)
    try:
        # to_thread: the ffmpeg extraction would otherwise block the event loop
        img, _, _, _ = await asyncio.to_thread(extract_frame_to_image, video_path, "custom", t)
    except (RuntimeError, ValueError) as e:
        raise HTTPException(status_code=422, detail=str(e))

    if img.width > w:
        height = max(1, round(img.height * w / img.width))
        img = img.resize((w, height), Image.LANCZOS)

    buf = BytesIO()
    img.convert("RGB").save(buf, "JPEG", quality=80)
    buf.seek(0)
    return StreamingResponse(buf, media_type="image/jpeg")


@router.get("/frame-strip")
async def frame_strip(source_path: str, count: int = 12, w: int = 96):
    """
    A cached horizontal montage of ~`count` frames sampled across a video, used as
    the frame-picker timeline. Generated once per (video, count, w) and reused.
    """
    import hashlib
    import app_dirs
    from fastapi.responses import FileResponse
    from utils.video_frames import build_filmstrip

    video_path = _validate_media_source_path(source_path)
    count = max(2, min(count, 24))
    w = max(32, min(w, 160))

    st = video_path.stat()
    key = hashlib.sha256(f"{video_path}|{st.st_mtime}|{st.st_size}|{count}|{w}".encode()).hexdigest()[:16]
    cache_dir = app_dirs.get_cache_dir() / "frame-strip-cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    out_path = cache_dir / f"{key}.jpg"

    if not out_path.exists():
        # Off the event loop: building the montage shells out to ffmpeg ~count
        # times and takes seconds — inline it and every other request (including
        # the video file itself) stalls behind it.
        try:
            strip = await asyncio.to_thread(build_filmstrip, video_path, count, w)
        except (RuntimeError, ValueError) as e:
            raise HTTPException(status_code=422, detail=str(e))
        strip.save(out_path, "JPEG", quality=78)

    return FileResponse(out_path, media_type="image/jpeg")


@router.get("/video-info")
async def video_info(source_path: str):
    """
    Duration + fps for a library video. Drives the slideshow transport readout
    (frames mode needs the source frame rate, which media rows don't carry).
    """
    from utils.video_frames import probe_video_info

    video_path = _validate_media_source_path(source_path)
    duration, fps = await asyncio.to_thread(probe_video_info, video_path)
    return {"duration": duration, "fps": fps}


class ReferencePreprocessRequest(BaseModel):
    """Request body for full reference image preprocessing pipeline."""
    source_path: str
    flip: dict[str, bool | int] | None = None  # { horizontal?: bool, vertical?: bool, rotation?: 0|90|180|270 }
    crop: dict[str, float] | None = None  # { x, y, width, height, rotation? } normalized 0-1 rect (post-flip image) + optional rect rotation in clockwise degrees
    scale: dict[str, str | float | int] | None = None  # { mode: "factor"|"min_edge", factor?: float, min_edge?: int }
    preprocessor: str | None = None
    preprocessor_params: dict[str, int | float] | None = None
    extend_padding: dict[str, int | float] | None = None  # { top, bottom, left, right } as %
    extend_bg_color: str | None = None  # hex color e.g. "#000000"
    paint_layer_path: str | None = None


async def preprocess_reference_pipeline(request: ReferencePreprocessRequest) -> dict:
    """
    Full reference image preprocessing pipeline (cached).

    Applies in order:
    1. Flip / rotate (if flip provided)
    2. Crop (normalized rect of the post-flip image)
    3. Scale (resize by factor or min-edge)
    4. ControlNet preprocessor (if preprocessor provided)
    5. Canvas extension (if extend_padding provided, with bg color)
    6. Paint layer compositing (if paint_layer_path provided)

    Also returns base_path (result after steps 1-3, before paint) for the paint editor.

    Shared by the POST /preprocess-reference endpoint and the media-batch
    submission path (which applies uniform batch-safe prep per item server-side).

    Returns:
        { path, width, height, base_path?, base_width?, base_height? }
    """
    import hashlib
    import app_dirs
    from PIL import Image

    source = Path(request.source_path)
    if not source.exists():
        raise HTTPException(status_code=404, detail="Source image not found")

    # Build cache key from all inputs
    # v2: EXIF orientation applied to source — invalidates pre-fix entries
    # v3: crop rotation — pre-rotation code cached unrotated output under
    #     rotation-inclusive keys, so those entries must not be served
    cache_parts = ["v3", str(source.stat().st_mtime), str(source.stat().st_size)]
    if request.flip:
        cache_parts.append(f"flip:{json.dumps(request.flip, sort_keys=True)}")
    if request.crop:
        cache_parts.append(f"crop:{json.dumps(request.crop, sort_keys=True)}")
    if request.scale:
        cache_parts.append(f"scale:{json.dumps(request.scale, sort_keys=True)}")
    if request.preprocessor:
        cache_parts.append(f"preprocess:{request.preprocessor}")
        if request.preprocessor_params:
            cache_parts.append(f"params:{json.dumps(request.preprocessor_params, sort_keys=True)}")
    if request.extend_padding:
        cache_parts.append(f"extend:{json.dumps(request.extend_padding, sort_keys=True)}")
    if request.extend_bg_color:
        cache_parts.append(f"bg:{request.extend_bg_color}")
    if request.paint_layer_path:
        paint_path = Path(request.paint_layer_path)
        if paint_path.exists():
            cache_parts.append(f"paint:{paint_path.stat().st_mtime}:{paint_path.stat().st_size}")

    cache_hash = hashlib.sha256("|".join(cache_parts).encode()).hexdigest()[:16]
    cache_dir = app_dirs.get_cache_dir() / "reference-prep-cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / f"{cache_hash}.png"

    # Also compute base cache key (everything except paint)
    base_cache_parts = [p for p in cache_parts if not p.startswith("paint:")]
    base_cache_hash = hashlib.sha256("|".join(base_cache_parts).encode()).hexdigest()[:16]
    base_cache_path = cache_dir / f"{base_cache_hash}.png"

    has_paint = bool(request.paint_layer_path and Path(request.paint_layer_path).exists())

    # Check if fully cached
    if cache_path.exists() and (not has_paint or base_cache_path.exists()):
        img = Image.open(cache_path)
        result = {"path": str(cache_path), "width": img.width, "height": img.height}
        if has_paint and base_cache_path.exists():
            base_img = Image.open(base_cache_path)
            result["base_path"] = str(base_cache_path)
            result["base_width"] = base_img.width
            result["base_height"] = base_img.height
        return result

    try:
        # Step 1: Load source image (EXIF-oriented to match how the UI displays it)
        from utils.image_ops import open_oriented
        img = open_oriented(source).convert("RGBA")

        # Step 2: Flip / rotate (applied first so downstream stages see final orientation)
        if request.flip:
            if request.flip.get("horizontal"):
                img = img.transpose(Image.FLIP_LEFT_RIGHT)
            if request.flip.get("vertical"):
                img = img.transpose(Image.FLIP_TOP_BOTTOM)
            rotation = int(request.flip.get("rotation", 0)) % 360
            if rotation:
                # PIL rotate() is counter-clockwise; negate for clockwise degrees.
                img = img.rotate(-rotation, expand=True)

        # Step 3: Crop — normalized left/top-anchored rect of the post-flip image,
        # optionally rotated (clockwise degrees) about its own center.
        if request.crop:
            cx = float(request.crop.get("x", 0.0))
            cy = float(request.crop.get("y", 0.0))
            cw = float(request.crop.get("width", 1.0))
            ch = float(request.crop.get("height", 1.0))
            rot = float(request.crop.get("rotation", 0.0) or 0.0)
            left = max(0, min(round(img.width * cx), img.width - 1))
            top = max(0, min(round(img.height * cy), img.height - 1))
            right = max(left + 1, min(round(img.width * (cx + cw)), img.width))
            bottom = max(top + 1, min(round(img.height * (cy + ch)), img.height))
            if rot:
                # Rotate the image about the rect center so the rotated rect
                # becomes the axis-aligned box below. PIL rotates content
                # counter-clockwise for positive angles, which is exactly the
                # inverse of the rect's clockwise rotation. Areas revealed by
                # the rotation fill transparent (black once flattened to RGB).
                center = ((left + right) / 2, (top + bottom) / 2)
                img = img.rotate(rot, center=center, resample=Image.BICUBIC)
            if rot or (left, top, right, bottom) != (0, 0, img.width, img.height):
                img = img.crop((left, top, right, bottom))

        # Step 4: Scale
        if request.scale:
            mode = request.scale.get("mode", "factor")
            if mode == "factor":
                factor = float(request.scale.get("factor", 1.0))
                if factor != 1.0:
                    new_w = max(1, round(img.width * factor))
                    new_h = max(1, round(img.height * factor))
                    img = img.resize((new_w, new_h), Image.LANCZOS)
            elif mode == "min_edge":
                min_edge = int(request.scale.get("min_edge", 512))
                current_min = min(img.width, img.height)
                if current_min != min_edge and current_min > 0:
                    factor = min_edge / current_min
                    new_w = max(1, round(img.width * factor))
                    new_h = max(1, round(img.height * factor))
                    img = img.resize((new_w, new_h), Image.LANCZOS)
            elif mode == "megapixels":
                target_mp = float(request.scale.get("megapixels", 1.0))
                current_mp = (img.width * img.height) / 1_000_000
                if current_mp > 0 and abs(current_mp - target_mp) > 0.01:
                    factor = (target_mp / current_mp) ** 0.5
                    new_w = max(1, round(img.width * factor))
                    new_h = max(1, round(img.height * factor))
                    img = img.resize((new_w, new_h), Image.LANCZOS)

        # Step 5: Apply controlnet preprocessor
        if request.preprocessor:
            intermediate_path = cache_dir / f"{cache_hash}_intermediate.png"
            img.convert("RGB").save(intermediate_path)

            from controlnet import preprocess, PREPROCESSORS
            if request.preprocessor not in PREPROCESSORS:
                raise HTTPException(
                    status_code=400,
                    detail=f"Unknown preprocessor: {request.preprocessor}. Available: {sorted(PREPROCESSORS)}"
                )
            output_path, width, height = await preprocess(
                str(intermediate_path), request.preprocessor, request.preprocessor_params
            )
            intermediate_path.unlink(missing_ok=True)
            img = Image.open(output_path).convert("RGBA")

        # Step 6: Extend canvas
        if request.extend_padding:
            p = request.extend_padding
            top = int(img.height * p.get("top", 0) / 100)
            bottom = int(img.height * p.get("bottom", 0) / 100)
            left = int(img.width * p.get("left", 0) / 100)
            right = int(img.width * p.get("right", 0) / 100)

            if top > 0 or bottom > 0 or left > 0 or right > 0:
                new_width = img.width + left + right
                new_height = img.height + top + bottom
                # Parse background color
                bg_rgba = (0, 0, 0, 255)  # default black
                if request.extend_bg_color:
                    hex_color = request.extend_bg_color.lstrip("#")
                    if len(hex_color) == 6:
                        r, g, b = int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)
                        bg_rgba = (r, g, b, 255)
                extended = Image.new("RGBA", (new_width, new_height), bg_rgba)
                extended.paste(img, (left, top), img if img.mode == "RGBA" else None)
                img = extended

        # Save base image (before paint) for the paint editor
        base_result = {}
        if has_paint:
            if not base_cache_path.exists():
                img.convert("RGB").save(base_cache_path, "PNG")
            base_result = {
                "base_path": str(base_cache_path),
                "base_width": img.width,
                "base_height": img.height,
            }

        # Step 7: Composite paint layer
        if has_paint:
            paint_path = Path(request.paint_layer_path)
            paint_layer = Image.open(paint_path).convert("RGBA")
            # Resize paint layer to match current image if needed
            if paint_layer.size != img.size:
                paint_layer = paint_layer.resize(img.size, Image.LANCZOS)
            img = Image.alpha_composite(img, paint_layer)

        # Save final result
        img.convert("RGB").save(cache_path, "PNG")
        result = {"path": str(cache_path), "width": img.width, "height": img.height}
        result.update(base_result)
        return result

    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Reference preprocessing failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Reference preprocessing failed: {e}")


@router.post("/preprocess-reference")
async def preprocess_reference(request: ReferencePreprocessRequest):
    """Full reference image preprocessing pipeline. See preprocess_reference_pipeline."""
    return await preprocess_reference_pipeline(request)


@router.post("/upload-bulk")
async def upload_bulk(
    files: List[UploadFile] = File(...),
    marker_ids: Optional[str] = Form(None),
    project_id: Optional[int] = Form(None),
    session: AsyncSession = Depends(get_db_session),
):
    """
    Upload multiple files to the library.

    Used by the drag-drop feature to upload multiple files at once.
    Returns success/failure for each file.

    Args:
        files: List of files to upload
        marker_ids: Comma-separated list of marker IDs to apply to uploaded media
    """
    from upload_service import get_upload_service, UploadError
    from database import Marker
    from sqlalchemy import select

    try:
        upload_service = get_upload_service()
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    if project_id is not None:
        await get_project_or_404(session, project_id)

    # Parse marker IDs
    auto_marker_ids = []
    if marker_ids:
        try:
            auto_marker_ids = [int(id.strip()) for id in marker_ids.split(',') if id.strip()]
        except ValueError:
            pass  # Ignore invalid marker IDs

    # Validate markers exist
    valid_marker_ids = []
    if auto_marker_ids:
        result = await session.execute(
            select(Marker.id).where(Marker.id.in_(auto_marker_ids))
        )
        valid_marker_ids = [row[0] for row in result.fetchall()]

    results = []
    for file in files:
        try:
            content = await file.read()
            media_item, file_path = await upload_service.upload_file(
                content,
                file.filename or "upload.png",
                project_id=project_id,
            )

            # Apply markers if specified
            if valid_marker_ids:
                from asset_association_service import asset_for_media, set_asset_marker

                asset = await asset_for_media(
                    session,
                    media_item.id,
                    promote=True,
                    origin_type="upload",
                )
                if asset is None:
                    raise RuntimeError("Uploaded Asset was not materialized")
                for marker_id in valid_marker_ids:
                    await set_asset_marker(
                        session,
                        asset_id=asset.id,
                        marker_id=marker_id,
                        add=True,
                    )
                await session.commit()

            results.append({
                "filename": file.filename,
                "status": "success",
                "path": file_path,
                "media_id": media_item.id,
                "file_hash": media_item.file_hash,
                "width": media_item.width,
                "height": media_item.height,
            })
        except Exception as e:
            results.append({
                "filename": file.filename,
                "status": "error",
                "error": str(e),
            })

    total = len(results)
    success = len([r for r in results if r["status"] == "success"])
    errors = total - success

    if success > 0:
        from telemetry import get_telemetry_client
        get_telemetry_client().track("media_uploaded", {
            "fileCount": success,
        }, category="library")

    return {
        "total": total,
        "success": success,
        "errors": errors,
        "results": results,
    }


class ControlnetPreprocessRequest(BaseModel):
    """Request body for controlnet preprocessing."""
    source_path: str
    preprocessor: str
    preprocessor_params: dict[str, int | float] | None = None


@router.post("/preprocess-controlnet")
async def preprocess_controlnet(request: ControlnetPreprocessRequest):
    """
    Preprocess an image for controlnet workflows.

    Applies the specified preprocessor (canny, depth, lineart, pose) to the
    source image and returns the path to the processed result. Results are
    cached by file hash + preprocessor type.

    Args:
        request: source_path (image file path) and preprocessor (canny/depth/lineart/pose)

    Returns:
        { path, width, height }
    """
    from controlnet import preprocess, PREPROCESSORS

    if request.preprocessor not in PREPROCESSORS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown preprocessor: {request.preprocessor}. Available: {sorted(PREPROCESSORS)}"
        )

    source = Path(request.source_path)
    if not source.exists():
        raise HTTPException(status_code=404, detail="Source image not found")

    try:
        output_path, width, height = await preprocess(str(source), request.preprocessor, request.preprocessor_params)

        from telemetry import get_telemetry_client
        get_telemetry_client().track("controlnet_preview_used", category="generation")

        return {"path": output_path, "width": width, "height": height}
    except Exception as e:
        log.error(f"Controlnet preprocessing failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Preprocessing failed: {e}")


@router.get("/controlnet-preview")
async def get_controlnet_preview(path: str):
    """Serve a controlnet preprocessed preview image from the cache."""
    from fastapi.responses import FileResponse

    file_path = Path(path).resolve()

    # Security: only serve files from cache directories
    import app_dirs
    allowed = False
    for cache_name in ("controlnet-cache", "reference-prep-cache"):
        try:
            cache_dir = app_dirs.get_cache_dir() / cache_name
            file_path.relative_to(cache_dir.resolve())
            allowed = True
            break
        except ValueError:
            continue
    if not allowed:
        raise HTTPException(status_code=403, detail="Access denied")

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Preview not found")

    return FileResponse(file_path, media_type="image/png")


@router.post("/submit")
async def submit_generation_job(
    request: GenerationJobRequest,
    session: AsyncSession = Depends(get_db_session),
):
    """Submit a new generation job to the queue."""
    from generation_queue import get_generation_queue
    generation_queue = get_generation_queue()
    provider_id = _provider_id_for_tool(request.tool_id)
    reservation_handed_to_queue = False

    log.info(f"Received generation request: tool_id={request.tool_id}, task_type={request.task_type}")

    try:
        # Build the single flat parameters dict with job metadata that needs tracking
        parameters = dict(request.parameters) if request.parameters else {}
        parameters = await _apply_generation_prompt_pipeline(
            parameters,
            tool_id=request.tool_id,
            task_type=request.task_type,
            prompt_options=request.prompt_options,
            prompt_preload=request.prompt_preload,
            generator_instance_id=request.generator_instance_id,
        )
        if request.prompt_metadata:
            parameters["prompt_metadata"] = request.prompt_metadata.model_dump()
        if request.auto_marker_ids:
            parameters["auto_marker_ids"] = request.auto_marker_ids

        if request.auto_delete_duration is not None:
            from generation_queue import parse_duration
            from telemetry import get_telemetry_client
            delta = parse_duration(request.auto_delete_duration)
            auto_delete_props = {"enabled": delta is not None}
            if delta is not None:
                auto_delete_props["durationMinutes"] = int(delta.total_seconds() // 60)
            get_telemetry_client().track(
                "auto_delete_configured", auto_delete_props, category="generation"
            )

        await _retain_generation_inputs(session, parameters)

        reservation_handed_to_queue = True
        job_id = await generation_queue.submit_job(
            generator_name=provider_id,  # Legacy field, use provider_id
            model_name=_model_name_for_tool(request.tool_id),
            folder_path=request.folder_path,
            parameters=parameters,
            auto_delete_duration=request.auto_delete_duration,
            generator_instance_id=request.generator_instance_id,
            backend_name=provider_id,  # Use provider_id as backend_name
            task_type=request.task_type,
            tool_id=request.tool_id,
            preset_id=request.preset_id,
            project_id=request.project_id,
            consume_pending_request=_should_consume_forever_reservation(request),
        )

        return {"job_id": job_id, "status": "queued"}
    except HTTPException:
        await _decline_unqueued_reserved_work(generation_queue, request, provider_id, reservation_handed_to_queue)
        raise
    except ValueError as e:
        await _decline_unqueued_reserved_work(generation_queue, request, provider_id, reservation_handed_to_queue)
        raise HTTPException(status_code=400, detail=str(e))
    except EntitlementError as e:
        await _decline_unqueued_reserved_work(generation_queue, request, provider_id, reservation_handed_to_queue)
        raise _entitlement_http_exception(e)
    except Exception as e:
        await _decline_unqueued_reserved_work(generation_queue, request, provider_id, reservation_handed_to_queue)
        log.error(f"Error submitting generation job: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/submit-batch")
async def submit_batch_jobs(
    request: BatchJobRequest,
    session: AsyncSession = Depends(get_db_session)
):
    """Submit a batch of generation jobs from set inputs.

    When a set is provided for an input, the system expands it and creates
    individual jobs for each item. All jobs share a batch_id and results
    are collected into an output set.

    For multiple set inputs, computes the cartesian product of all items.
    """
    from generation_queue import get_generation_queue
    from structured_media import get_set_item_ids
    import itertools

    generation_queue = get_generation_queue()
    provider_id = _provider_id_for_tool(request.tool_id)
    reservation_handed_to_queue = False

    log.info(f"Received batch generation request: tool_id={request.tool_id}, task_type={request.task_type}")

    try:
        # Find all set inputs and expand them
        set_inputs = {}  # input_name -> list of media_ids
        regular_inputs = {}  # input_name -> value

        input_set_ids = []  # Track input set IDs for smart title generation

        for input_name, input_value in request.parameters.items():
            if isinstance(input_value, dict) and 'set_id' in input_value:
                # This is a set input - expand it
                set_id = input_value['set_id']

                # Validate the set exists and get its items
                result = await session.execute(
                    select(MediaItem).where(
                        MediaItem.id == set_id,
                        MediaItem.deleted_at.is_(None)
                    )
                )
                set_item = result.scalar_one_or_none()
                if not set_item:
                    raise HTTPException(status_code=404, detail=f"Set {set_id} not found")
                if set_item.file_format != 'stimmaset.json':
                    raise HTTPException(status_code=400, detail=f"Asset {set_id} is not a set")

                # Get the media IDs of items in the set
                item_ids = await get_set_item_ids(session, set_id)
                if not item_ids:
                    raise HTTPException(status_code=400, detail=f"Set {set_id} is empty")

                set_inputs[input_name] = item_ids
                input_set_ids.append(set_id)  # Track for smart title generation
                log.info(f"Expanded set input '{input_name}' (set_id={set_id}) to {len(item_ids)} items")
            else:
                regular_inputs[input_name] = input_value

        if not set_inputs:
            raise HTTPException(status_code=400, detail="No set inputs found. Use /submit for single-item jobs.")

        # Compute cartesian product of all set inputs
        set_names = list(set_inputs.keys())
        set_values = [set_inputs[name] for name in set_names]
        combinations = list(itertools.product(*set_values))

        total_jobs = len(combinations)
        if total_jobs > 100:
            raise HTTPException(
                status_code=400,
                detail=f"Batch too large: {total_jobs} jobs. Maximum is 100. Consider smaller sets."
            )

        log.info(f"Creating {total_jobs} jobs from cartesian product of {len(set_inputs)} set inputs")

        # Generate batch_id
        batch_id = str(uuid.uuid4())

        # Generate smart title upfront if user didn't provide one
        output_title = request.output_set_title
        log.info(f"BATCH TITLE DEBUG: output_set_title={request.output_set_title}, input_set_ids={input_set_ids}")
        if not output_title and input_set_ids:
            from structured_media import generate_smart_batch_title
            tool_name = _model_name_for_tool(request.tool_id)
            log.info(f"BATCH TITLE DEBUG: Calling generate_smart_batch_title with tool={tool_name}, task={request.task_type}")
            try:
                output_title = await generate_smart_batch_title(
                    session=session,
                    tool_name=tool_name,
                    task_type=request.task_type or "unknown",
                    input_set_ids=input_set_ids,
                )
                log.info(f"BATCH TITLE DEBUG: generate_smart_batch_title returned: {output_title}")
            except Exception as e:
                log.error(f"BATCH TITLE DEBUG: generate_smart_batch_title failed: {e}", exc_info=True)
            if output_title:
                log.info(f"Generated smart batch title upfront: '{output_title}'")

        # Prepare every child before queueing any of them. Prompt enhancement
        # failures are pre-queue failures; they should not leave a partial batch
        # running behind a failed HTTP response.
        prepared_jobs = []
        for idx, combination in enumerate(combinations):
            # Build the single flat parameters dict for this combination.
            # regular_inputs already carries every non-set param (prompt, steps,
            # cfg, loras, ...) since they all come from request.parameters.
            parameters = dict(regular_inputs)

            # Add the set items for this combination
            for i, input_name in enumerate(set_names):
                media_id = combination[i]
                # Get the media item to get its file path
                result = await session.execute(
                    select(MediaItem).where(MediaItem.id == media_id)
                )
                media_item = result.scalar_one_or_none()
                if media_item:
                    # Store both media_id and file_path for flexibility
                    parameters[input_name] = media_item.file_path
                    parameters[f"{input_name}_media_id"] = media_id

            # Store batch index for output ordering (0-based position in input)
            parameters["_batch_index"] = idx

            parameters = await _apply_generation_prompt_pipeline(
                parameters,
                tool_id=request.tool_id,
                task_type=request.task_type,
                prompt_options=request.prompt_options,
                prompt_preload=_prompt_preload_for_batch_index(request, idx),
                generator_instance_id=request.generator_instance_id,
            )

            # Add prompt metadata if provided
            if request.prompt_metadata:
                parameters["prompt_metadata"] = request.prompt_metadata.model_dump()
            if request.auto_marker_ids:
                parameters["auto_marker_ids"] = request.auto_marker_ids

            prepared_jobs.append(parameters)

        retained_ids = set(input_set_ids)
        for parameters in prepared_jobs:
            retained_ids.update(generation_input_media_ids(parameters))
        await _retain_generation_inputs(
            session, {"input_media_ids": sorted(retained_ids)}
        )

        # Create jobs for each prepared combination.
        job_ids = []
        consume_reserved_work = _should_consume_forever_reservation(request)
        for idx, parameters in enumerate(prepared_jobs):
            # Submit job with batch tracking
            reservation_handed_to_queue = True
            job_id = await generation_queue.submit_batch_job(
                generator_name=provider_id,
                model_name=_model_name_for_tool(request.tool_id),
                folder_path=request.folder_path,
                parameters=parameters,
                auto_delete_duration=request.auto_delete_duration,
                generator_instance_id=request.generator_instance_id,
                backend_name=provider_id,
                task_type=request.task_type,
                tool_id=request.tool_id,
                preset_id=request.preset_id,
                project_id=request.project_id,
                batch_id=batch_id,
                batch_total=total_jobs if idx == 0 else None,  # Only first job stores total
                batch_output_title=output_title,
                batch_input_set_ids=input_set_ids if idx == 0 else None,  # Kept for backwards compat
                output_disposition="container_member",
                output_context_kind="batch",
                output_context_id=batch_id,
                consume_pending_request=consume_reserved_work and idx == 0,
            )
            job_ids.append(job_id)

        log.info(f"Created batch {batch_id} with {len(job_ids)} jobs")

        from telemetry import get_telemetry_client
        from pipeline_telemetry import tool_identity_props
        get_telemetry_client().track("batch_submitted", {
            "toolRef": tool_identity_props(request.tool_id).get("toolRef"),
            "jobCount": len(job_ids),
            "expandedFromSets": bool(set_inputs),
        }, category="generation")

        return BatchJobResponse(
            batch_id=batch_id,
            total_jobs=total_jobs,
            job_ids=job_ids
        )

    except HTTPException:
        await _decline_unqueued_reserved_work(generation_queue, request, provider_id, reservation_handed_to_queue)
        raise
    except ValueError as e:
        await _decline_unqueued_reserved_work(generation_queue, request, provider_id, reservation_handed_to_queue)
        raise HTTPException(status_code=400, detail=str(e))
    except EntitlementError as e:
        await _decline_unqueued_reserved_work(generation_queue, request, provider_id, reservation_handed_to_queue)
        raise _entitlement_http_exception(e)
    except Exception as e:
        await _decline_unqueued_reserved_work(generation_queue, request, provider_id, reservation_handed_to_queue)
        log.error(f"Error submitting batch generation jobs: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# Media fields whose lineage media-id companion uses a non-default name.
_BATCH_MEDIA_ID_FIELDS = {
    "input_images": "input_media_ids",
    "input_videos": "input_video_media_ids",
}

MEDIA_BATCH_MAX_JOBS = 100
_MEDIA_BATCH_FIELDS = {"input_images", "input_videos"}
_IMAGE_FORMATS = {"jpg", "jpeg", "png", "gif", "webp", "bmp", "tiff", "heic", "heif"}
_VIDEO_FORMATS = {"mp4", "mov", "avi", "mkv", "webm", "m4v", "mpg", "mpeg"}


async def _get_tool_parameter_schema(tool_id: str, session: AsyncSession) -> dict:
    from providers import ProviderRegistry

    registry = ProviderRegistry.get_instance()
    live = registry.get_tool(tool_id)
    if live:
        return live[1].parameter_schema or {}

    result = await session.execute(
        select(CachedProviderTool).where(
            CachedProviderTool.full_tool_id == tool_id,
            CachedProviderTool.deleted_at.is_(None),
        )
    )
    cached = result.scalar_one_or_none()
    if cached and cached.parameter_schema:
        try:
            return json.loads(cached.parameter_schema)
        except json.JSONDecodeError:
            log.warning(f"Cached parameter_schema for {tool_id} is invalid JSON")
    return {}


def _schema_media_type_for_field(field: str, schema: dict | None) -> str | None:
    if field == "input_images":
        return "image"
    if field == "input_videos":
        return "video"
    if not schema:
        return None
    text = " ".join(
        str(schema.get(k, ""))
        for k in ("format", "x-format", "x-control", "contentMediaType", "description")
    ).lower()
    if "video" in text or field.endswith("video") or field.endswith("videos"):
        return "video"
    if "image" in text or field.endswith("image") or field.endswith("images"):
        return "image"
    return None


def _media_item_type(item: MediaItem) -> str | None:
    fmt = (item.file_format or "").lower().lstrip(".")
    if fmt in _VIDEO_FORMATS:
        return "video"
    if fmt in _IMAGE_FORMATS:
        return "image"
    return None


@router.post("/submit-media-batch")
async def submit_media_batch_jobs(
    request: MediaBatchJobRequest,
    session: AsyncSession = Depends(get_db_session)
):
    """Submit a media-batch: run a tool once per item in one media slot.

    Sources the batch from media IDs (not a set). For each item the backend
    resolves the path, applies uniform batch-safe prep, injects that single item
    into the batched media field along with the constant inputs, and submits a
    normal generation job under a shared ``batch_id``.

    Outputs stay as individual library assets — grouping is presentation-only,
    so no output set is created (``_batch_presentation_only`` marker).
    """
    from generation_queue import get_generation_queue

    generation_queue = get_generation_queue()

    field = request.batch_input.field
    media_ids = request.batch_input.media_ids
    provider_id = _provider_id_for_tool(request.tool_id)
    reservation_handed_to_queue = False

    log.info(
        f"Received media-batch request: tool_id={request.tool_id}, "
        f"task_type={request.task_type}, field={field}, items={len(media_ids)}"
    )

    if not media_ids:
        await _decline_unqueued_reserved_work(generation_queue, request, provider_id, reservation_handed_to_queue)
        raise HTTPException(status_code=400, detail="batch_input.media_ids is empty")
    if len(media_ids) > MEDIA_BATCH_MAX_JOBS:
        await _decline_unqueued_reserved_work(generation_queue, request, provider_id, reservation_handed_to_queue)
        raise HTTPException(
            status_code=400,
            detail=f"Batch too large: {len(media_ids)} jobs. Maximum is {MEDIA_BATCH_MAX_JOBS}."
        )

    try:
        parameter_schema = await _get_tool_parameter_schema(request.tool_id, session)
        props = parameter_schema.get("properties") or {}
        if not props:
            raise HTTPException(status_code=400, detail=f"Tool schema not found for {request.tool_id}")
        if "mask" in props:
            raise HTTPException(status_code=400, detail="Mask tools are not supported in media-batch mode")
        if field not in _MEDIA_BATCH_FIELDS or field not in props:
            raise HTTPException(status_code=400, detail=f"Unsupported media-batch field: {field}")
        if props.get(field, {}).get("x-control") == "video_frame_picker":
            raise HTTPException(status_code=400, detail="Video frame picker inputs are not supported in media-batch mode")
        expected_batch_type = _schema_media_type_for_field(field, props.get(field))

        # Resolve every batched media item up front.
        id_to_path: dict[int, str] = {}
        for media_id in media_ids:
            result = await session.execute(
                select(MediaItem).where(
                    MediaItem.id == media_id,
                    MediaItem.deleted_at.is_(None),
                )
            )
            item = result.scalar_one_or_none()
            if not item:
                raise HTTPException(status_code=404, detail=f"Media item {media_id} not found")
            actual_type = _media_item_type(item)
            if expected_batch_type and actual_type and actual_type != expected_batch_type:
                raise HTTPException(
                    status_code=400,
                    detail=f"Media item {media_id} is a {actual_type}, but {field} expects {expected_batch_type}s",
                )
            id_to_path[media_id] = item.file_path

        # Resolve constant media inputs (same for every run).
        resolved_constants: dict[str, object] = {}
        for const_field, const_media_id in (request.constant_inputs or {}).items():
            if const_field == field:
                raise HTTPException(status_code=400, detail=f"Constant input cannot reuse batch field: {const_field}")
            if const_field not in props:
                raise HTTPException(status_code=400, detail=f"Unknown constant media field: {const_field}")
            expected_const_type = _schema_media_type_for_field(const_field, props.get(const_field))
            if expected_const_type is None:
                raise HTTPException(status_code=400, detail=f"Field is not a media input: {const_field}")
            if isinstance(const_media_id, bool) or not isinstance(const_media_id, int):
                raise HTTPException(status_code=400, detail=f"Constant media id for {const_field} must be an integer")
            result = await session.execute(
                select(MediaItem).where(
                    MediaItem.id == const_media_id,
                    MediaItem.deleted_at.is_(None),
                )
            )
            item = result.scalar_one_or_none()
            if not item:
                raise HTTPException(status_code=404, detail=f"Constant media item {const_media_id} not found")
            actual_type = _media_item_type(item)
            if actual_type and actual_type != expected_const_type:
                raise HTTPException(
                    status_code=400,
                    detail=f"Constant media item {const_media_id} is a {actual_type}, but {const_field} expects {expected_const_type}s",
                )
            const_media_id_field = _BATCH_MEDIA_ID_FIELDS.get(const_field, f"{const_field}_media_id")
            if const_field in _BATCH_MEDIA_ID_FIELDS:
                resolved_constants[const_field] = [item.file_path]
                resolved_constants[const_media_id_field] = [const_media_id]
            else:
                resolved_constants[const_field] = item.file_path
                resolved_constants[const_media_id_field] = const_media_id

        prep = request.prep or {}
        has_prep = any(
            prep.get(k) for k in (
                "scale", "flip", "crop", "preprocessor", "extend_padding",
            )
        )

        batch_id = str(uuid.uuid4())
        model_name = _model_name_for_tool(request.tool_id)
        media_id_field = _BATCH_MEDIA_ID_FIELDS.get(field, "input_media_ids")
        total_jobs = len(media_ids)

        prepared_jobs = []
        for idx, media_id in enumerate(media_ids):
            source_path = id_to_path[media_id]

            # Apply uniform batch-safe prep to this item (cached per source+settings).
            processed_path = source_path
            if has_prep:
                prep_req = ReferencePreprocessRequest(
                    source_path=source_path,
                    flip=prep.get("flip"),
                    crop=prep.get("crop"),
                    scale=prep.get("scale"),
                    preprocessor=prep.get("preprocessor"),
                    preprocessor_params=prep.get("preprocessor_params"),
                    extend_padding=prep.get("extend_padding"),
                    extend_bg_color=prep.get("extend_bg_color"),
                    # No paint layer in batch mode — painting is per-item.
                )
                prep_result = await preprocess_reference_pipeline(prep_req)
                processed_path = prep_result["path"]

            # Build the flat parameters dict for this single run.
            parameters = dict(request.parameters)
            parameters.update(resolved_constants)
            parameters[field] = [processed_path]
            parameters[media_id_field] = [media_id]

            # Preserve original media + prep metadata for lineage (one-element arrays,
            # matching the single-job shape produced by the frontend payload builder).
            if has_prep:
                parameters["_original_input_paths"] = [source_path]
                parameters["_input_preprocessors"] = [prep.get("preprocessor")]
                parameters["_input_preprocessor_params"] = [prep.get("preprocessor_params")]
                parameters["_input_scales"] = [prep.get("scale")]
                parameters["_input_flips"] = [prep.get("flip")]
                parameters["_input_crops"] = [prep.get("crop")]
                parameters["_input_extend_padding"] = [prep.get("extend_padding")]
                parameters["_input_extend_bg_colors"] = [prep.get("extend_bg_color")]
                parameters["_input_paint_layers"] = [None]

            parameters["_batch_index"] = idx
            # Presentation-only grouping: keep individuals in the library, no set.
            parameters["_batch_presentation_only"] = True

            parameters = await _apply_generation_prompt_pipeline(
                parameters,
                tool_id=request.tool_id,
                task_type=request.task_type,
                prompt_options=request.prompt_options,
                prompt_preload=_prompt_preload_for_batch_index(request, idx),
                generator_instance_id=request.generator_instance_id,
            )

            if request.prompt_metadata:
                parameters["prompt_metadata"] = request.prompt_metadata.model_dump()
            if request.auto_marker_ids:
                parameters["auto_marker_ids"] = request.auto_marker_ids

            prepared_jobs.append(parameters)

        retained_ids = set(media_ids)
        retained_ids.update(request.constant_inputs.values())
        for parameters in prepared_jobs:
            retained_ids.update(generation_input_media_ids(parameters))
        await _retain_generation_inputs(
            session, {"input_media_ids": sorted(retained_ids)}
        )

        job_ids = []
        consume_reserved_work = _should_consume_forever_reservation(request)
        for idx, parameters in enumerate(prepared_jobs):
            reservation_handed_to_queue = True
            job_id = await generation_queue.submit_batch_job(
                generator_name=provider_id,
                model_name=model_name,
                folder_path=request.folder_path,
                parameters=parameters,
                auto_delete_duration=request.auto_delete_duration,
                generator_instance_id=request.generator_instance_id,
                backend_name=provider_id,
                task_type=request.task_type,
                tool_id=request.tool_id,
                preset_id=request.preset_id,
                project_id=request.project_id,
                batch_id=batch_id,
                batch_total=total_jobs if idx == 0 else None,  # Only first job stores total
                batch_output_title=None,
                batch_input_set_ids=None,
                consume_pending_request=consume_reserved_work and idx == 0,
            )
            job_ids.append(job_id)

        log.info(f"Created media-batch {batch_id} with {len(job_ids)} jobs")

        from telemetry import get_telemetry_client
        from pipeline_telemetry import tool_identity_props
        get_telemetry_client().track("batch_submitted", {
            "toolRef": tool_identity_props(request.tool_id).get("toolRef"),
            "jobCount": len(job_ids),
            "expandedFromSets": False,
        }, category="generation")

        return BatchJobResponse(
            batch_id=batch_id,
            total_jobs=total_jobs,
            job_ids=job_ids,
        )

    except HTTPException:
        await _decline_unqueued_reserved_work(generation_queue, request, provider_id, reservation_handed_to_queue)
        raise
    except ValueError as e:
        await _decline_unqueued_reserved_work(generation_queue, request, provider_id, reservation_handed_to_queue)
        raise HTTPException(status_code=400, detail=str(e))
    except EntitlementError as e:
        await _decline_unqueued_reserved_work(generation_queue, request, provider_id, reservation_handed_to_queue)
        raise _entitlement_http_exception(e)
    except Exception as e:
        await _decline_unqueued_reserved_work(generation_queue, request, provider_id, reservation_handed_to_queue)
        log.error(f"Error submitting media-batch jobs: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/jobs")
async def list_generation_jobs(
    status: Optional[str] = None,
    generator_instance_id: Optional[str] = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0)
):
    """List generation jobs with optional filters."""
    from generation_queue import get_generation_queue
    generation_queue = get_generation_queue()
    jobs = await generation_queue.list_jobs(
        status=status,
        generator_instance_id=generator_instance_id,
        limit=limit,
        offset=offset
    )
    return {"jobs": jobs, "count": len(jobs)}


@router.get("/jobs/status")
async def get_job_statuses(
    ids: str = Query(..., description="Comma-separated list of job IDs"),
    session: AsyncSession = Depends(get_db_session)
):
    """Get status for multiple generation jobs."""
    try:
        job_ids = [int(id.strip()) for id in ids.split(',') if id.strip()]
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid job ID format")

    if not job_ids:
        return []

    # Query jobs with their exact Media and canonical Asset expiration.
    # Internal one-shot flow-as-tool jobs (stamped with _ephemeral_run_id in their
    # params) are never surfaced to the user, even when polled by explicit id.
    from sqlalchemy.orm import selectinload
    from sqlalchemy import func
    from database import Asset

    result = await session.execute(
        select(GenerationJob, MediaItem, Asset)
        .outerjoin(MediaItem, GenerationJob.result_media_id == MediaItem.id)
        .outerjoin(Asset, GenerationJob.result_asset_id == Asset.id)
        .where(GenerationJob.id.in_(job_ids))
        .where(func.json_extract(GenerationJob.parameters, '$._ephemeral_run_id').is_(None))
    )
    rows = result.all()

    # Helper to extract generation_time from media's generation_metadata
    def get_generation_time(media):
        if not media or not media.generation_metadata:
            return None
        try:
            gen_meta = json.loads(media.generation_metadata) if isinstance(media.generation_metadata, str) else media.generation_metadata
            # Check both direct and nested in parameters
            return gen_meta.get('generation_time') or (gen_meta.get('parameters') or {}).get('generation_time')
        except (json.JSONDecodeError, TypeError):
            return None

    # Return status for each job with full details for info/error modals
    return [
        {
            "id": job.id,
            "status": job.status,
            "result_media_id": job.result_media_id,
            "result_asset_id": job.result_asset_id,
            "task_type": job.task_type,
            "media_trashed": media.deleted_at is not None if media else False,
            "media_deleted": media is None and job.result_media_id is not None,  # Had media but now gone
            "asset_trashed": bool(
                asset and (asset.state != "active" or asset.deleted_at is not None)
            ),
            "error": job.error,
            "model_name": job.model_name,
            "parameters": job.parameters,
            "created_at": job.created_at.isoformat() if job.created_at else None,
            "expires_at": asset.expires_at.isoformat() if asset and asset.expires_at else None,
            # Transitional alias; the canonical deadline belongs to the Asset.
            "auto_delete_at": asset.expires_at.isoformat() if asset and asset.expires_at else None,
            "generation_time": get_generation_time(media),
            "file_format": media.file_format if media else None
        }
        for job, media, asset in rows
    ]


@router.get("/jobs/{job_id}")
async def get_generation_job(job_id: int):
    """Get details of a specific generation job."""
    from generation_queue import get_generation_queue
    generation_queue = get_generation_queue()
    job = await generation_queue.get_job(job_id)

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    return job


@router.delete("/jobs/{job_id}")
async def cancel_generation_job(job_id: int, hard_delete: bool = Query(False)):
    """
    Cancel or delete a generation job.

    If hard_delete=false (default): Cancel a job if it's still queued or processing.
    If hard_delete=true: Permanently delete a failed or cancelled job from the database.
    """
    from generation_queue import get_generation_queue
    generation_queue = get_generation_queue()

    if hard_delete:
        success = await generation_queue.delete_job(job_id)
        if not success:
            raise HTTPException(
                status_code=400,
                detail="Job not found or not in a deletable state (must be failed or cancelled)"
            )
        return {"success": True, "job_id": job_id, "deleted": True}
    else:
        success = await generation_queue.cancel_job(job_id)
        if not success:
            raise HTTPException(
                status_code=400,
                detail="Job not found or already completed"
            )
        return {"success": True, "job_id": job_id}


@router.post("/jobs/{job_id}/retry")
async def retry_generation_job(job_id: int, session: AsyncSession = Depends(get_db_session)):
    """Retry a failed generation job by resetting it to queued status with a new seed."""
    # Get the original job
    result = await session.execute(
        select(GenerationJob).where(GenerationJob.id == job_id)
    )
    job = result.scalar_one_or_none()

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.status not in ('failed', 'cancelled'):
        raise HTTPException(
            status_code=400,
            detail=f"Can only retry failed or cancelled jobs. Current status: {job.status}"
        )

    # Update the job with a new seed and reset status
    import random
    params = json.loads(job.parameters)
    params['seed'] = random.randint(0, 2**32 - 1)  # New random seed

    # Telemetry run correlation: a retry is a new pipeline run launched from
    # a retry affordance — fresh runId, isRetry on the settle event.
    from pipeline_telemetry import new_run_id, reset_for_retry
    params['_run_id'] = new_run_id()
    params['_is_retry'] = True
    reset_for_retry(job.id)

    job.status = 'queued'
    job.parameters = json.dumps(params)
    job.error = None
    job.created_at = datetime.utcnow()
    job.started_at = None
    job.completed_at = None
    job.result_media_id = None

    await session.commit()
    await session.refresh(job)

    # Broadcast job queued event
    await ws_manager.broadcast('generation_job_queued', {
        'job': job.to_dict(),
        'generator_instance_id': job.generator_instance_id
    })

    return {
        "success": True,
        "job_id": job_id,
        "job": job.to_dict()
    }


@router.get("/api/media/{media_id}/generation-job")
async def get_media_generation_job(media_id: int, session: AsyncSession = Depends(get_db_session)):
    """Get the generation job that created this media item."""
    from database import Asset, GenerationJob
    from generation_queue import generation_job_payload

    # Find the generation job for this media item
    result = await session.execute(
        select(GenerationJob, Asset)
        .outerjoin(Asset, GenerationJob.result_asset_id == Asset.id)
        .where(GenerationJob.result_media_id == media_id)
    )
    row = result.one_or_none()

    if not row:
        return None

    return generation_job_payload(*row)


# Helper functions for LoRA matching

def exact_match_loras(extracted_loras: List[Dict], available_loras: List[Dict]) -> List[Dict]:
    """
    Match extracted LoRAs against available LoRAs by exact name/path only.

    Args:
        extracted_loras: List of {"lora": "name", "weight": float}
        available_loras: List of lora configs from generator

    Returns:
        List of matched loras with proper names
    """
    import os

    matched = []

    for extracted in extracted_loras:
        extracted_name = (extracted.get("lora") or extracted.get("path") or "").lower()
        weight = extracted.get("weight", 1.0)

        if not extracted_name:
            continue

        # Extract basename from the extracted name (handles paths)
        extracted_basename = os.path.basename(extracted_name)

        # Try exact match (case insensitive) against name, path, or path suffix
        exact_match = next(
            (lora for lora in available_loras
             if lora['name'].lower() == extracted_name or
                lora.get('path', '').lower() == extracted_name or
                lora.get('path', '').lower().endswith(extracted_name)),
            None
        )

        if exact_match:
            matched.append({"lora": exact_match['name'], "weight": weight})
            log.info(f"Exact matched LoRA '{extracted_name}' -> '{exact_match['name']}'")
            continue

        # Try basename exact match (very common case - same file, different directory)
        basename_match = next(
            (lora for lora in available_loras
             if os.path.basename(lora.get('path', '')).lower() == extracted_basename),
            None
        )

        if basename_match:
            matched.append({"lora": basename_match['name'], "weight": weight})
            log.info(f"Basename matched LoRA '{extracted_name}' -> '{basename_match['name']}'")
            continue

        log.info(f"No exact match for LoRA '{extracted_name}', skipping")

    return matched




async def _resolve_source_inputs(db: AsyncSession, source_inputs: list) -> list:
    """Resolve source_inputs media_ids to current file_paths (stored paths may be stale)."""
    if not source_inputs:
        return []
    resolved = []
    for source in source_inputs:
        entry = dict(source)
        media_id = source.get("media_id")
        if media_id:
            result = await db.execute(
                select(MediaItem.file_path).filter(MediaItem.id == media_id, MediaItem.deleted_at.is_(None))
            )
            row = result.scalar_one_or_none()
            if row:
                entry["file_path"] = row
                resolved.append(entry)
            else:
                log.warning(f"Source input media_id={media_id} not found or deleted, skipping")
        elif source.get("file_path"):
            # No media_id, keep original file_path as fallback
            resolved.append(entry)
    return resolved


@router.post("/config-from-media/{media_id}")
async def generate_config_from_media(
    media_id: int,
    target_tool_id: Optional[str] = Query(None, description="Target tool ID for compatibility filtering (full tool ID or database ID)"),
    db: AsyncSession = Depends(get_db_session)
):
    """
    Generate a generation config from an image's metadata or caption.

    This endpoint handles three cases:
    1. Image has generation_metadata from our system -> parse and return it
    2. Image has raw_metadata from other software -> use LLM to extract settings
    3. Image only has vlm_caption -> create default T2I config with caption as prompt

    For videos, we only return the prompt (not model/params) since there's no
    "generate video" feature yet - the user will be sent to "Generate Image"
    which uses different models and parameters.

    When target_tool_id is provided, parameters are filtered based on model
    compatibility and preserve_seed is set appropriately.

    Always includes input_media_id for potential img2img use.
    """
    settings = get_settings()
    from providers import ProviderRegistry

    from telemetry import get_telemetry_client
    get_telemetry_client().track("config_from_media_used", category="generation")

    # Get the media item
    result = await db.execute(select(MediaItem).filter(MediaItem.id == media_id))
    media_item = result.scalar_one_or_none()
    if not media_item:
        raise HTTPException(status_code=404, detail="Asset not found")

    # Check if this is a video
    video_formats = {'mp4', 'webm', 'mov', 'avi', 'mkv', 'gif'}
    is_video = media_item.file_format.lower() in video_formats if media_item.file_format else False

    # Base config with the remix source image available as an input
    base_config = {
        "input_media_id": media_id,
        # The remix source image itself, for tools that accept input images
        "remix_source_input": {
            "media_id": media_id,
            "file_path": media_item.file_path,
            "filename": Path(media_item.file_path).name if media_item.file_path else None,
        },
    }

    registry = ProviderRegistry.get_instance()

    # Get target tool info and LoRAs from provider
    target_tool_descriptor = None
    available_loras = []

    if target_tool_id:
        # Check if it's a full provider tool ID (contains colon) or a database ID
        if ':' in target_tool_id:
            # Full provider tool ID like "builtin:comfyui:text-to-image:z-image-turbo"
            result = registry.get_tool(target_tool_id)
            if result:
                _, target_tool_descriptor = result
                # Get LoRAs from the tool's parameter_schema
                loras_schema = target_tool_descriptor.parameter_schema.get('properties', {}).get('loras', {})
                path_enum = loras_schema.get('items', {}).get('properties', {}).get('path', {}).get('enum', [])
                name_enum = loras_schema.get('items', {}).get('properties', {}).get('name', {}).get('enum', [])
                available_loras = [
                    {'path': path, 'name': name_enum[i] if i < len(name_enum) else path}
                    for i, path in enumerate(path_enum)
                ]
        else:
            # Legacy database ID - try parsing as int
            try:
                db_tool_id = int(target_tool_id)
                target_tool_result = await db.execute(
                    select(Tool).where(Tool.id == db_tool_id)
                )
                target_tool = target_tool_result.scalar_one_or_none()
                if target_tool and target_tool.full_tool_id:
                    # Look up the provider tool to get LoRAs
                    result = registry.get_tool(target_tool.full_tool_id)
                    if result:
                        _, target_tool_descriptor = result
                        loras_schema = target_tool_descriptor.parameter_schema.get('properties', {}).get('loras', {})
                        path_enum = loras_schema.get('items', {}).get('properties', {}).get('path', {}).get('enum', [])
                        name_enum = loras_schema.get('items', {}).get('properties', {}).get('name', {}).get('enum', [])
                        available_loras = [
                            {'path': path, 'name': name_enum[i] if i < len(name_enum) else path}
                            for i, path in enumerate(path_enum)
                        ]
            except ValueError:
                log.warning(f"Invalid target_tool_id format: {target_tool_id}")

    # If no target tool, get LoRAs from all text-to-image tools (for general matching)
    if not available_loras:
        all_tools = registry.list_all_tools()
        seen_paths = set()
        for _, _, tool in all_tools:
            if tool.task_type in ('text-to-image', 'image-to-image'):
                loras_schema = tool.parameter_schema.get('properties', {}).get('loras', {})
                path_enum = loras_schema.get('items', {}).get('properties', {}).get('path', {}).get('enum', [])
                name_enum = loras_schema.get('items', {}).get('properties', {}).get('name', {}).get('enum', [])
                for i, path in enumerate(path_enum):
                    if path not in seen_paths:
                        seen_paths.add(path)
                        available_loras.append({
                            'path': path,
                            'name': name_enum[i] if i < len(name_enum) else path
                        })

    log.info(f"Available LoRAs: {len(available_loras)}, is_video: {is_video}, target_tool_id: {target_tool_id}")

    # Case 1: Already has generation metadata from our system
    if media_item.generation_metadata:
        try:
            gen_meta = json.loads(media_item.generation_metadata)
            params = gen_meta.get("parameters", {})

            # Extract source info for compatibility checking
            source_tool_id = gen_meta.get("tool_id")

            # Extract prompt_metadata if available (for "generate more" restoration)
            prompt_metadata = gen_meta.get("prompt_metadata")

            # Use original prompt (with wildcards) if available, otherwise use rendered prompt
            original_prompt = prompt_metadata.get("original_prompt") if prompt_metadata else None
            effective_prompt = original_prompt or gen_meta.get("prompt", "")

            # For videos, return prompt + video-specific params + source inputs
            if is_video:
                rendered_prompt = gen_meta.get("prompt", "")
                video_config = {
                    **base_config,
                    "prompt": effective_prompt,
                    "negative_prompt": gen_meta.get("negative_prompt") or params.get("negative_prompt", ""),
                    "width": params.get("width"),
                    "height": params.get("height"),
                    "prompt_metadata": prompt_metadata,
                    "prompt_variants": {
                        "original": original_prompt or rendered_prompt,
                        "rendered": rendered_prompt,
                    },
                    "source_thumbnail_url": f"/api/media/file/{media_id}?size=thumbnail",
                    "source_prompt_snippet": (effective_prompt or ""),
                    "source_tool_id": source_tool_id,
                    # Surface the recorded seed so the remix banner can offer "Use Seed".
                    # preserve_seed stays False (videos default to a fresh seed); the
                    # button lets the user opt into reproducing the exact frame.
                    "seed": params.get("seed"),
                    "preserve_seed": False,
                }
                # Include video-specific params
                if params.get("frame_count") is not None:
                    video_config["frame_count"] = params["frame_count"]
                if params.get("fps") is not None:
                    video_config["fps"] = params["fps"]
                # Include loras
                video_config["loras"] = params.get("loras", [])
                # Post-processing chain recorded in lineage (the steps that ran)
                if params.get("post_processing_chain"):
                    video_config["post_processing_chain"] = params["post_processing_chain"]
                # Include original source inputs (start/end frames) with resolved file paths
                raw_source_inputs = gen_meta.get("source_inputs", [])
                resolved = await _resolve_source_inputs(db, raw_source_inputs)

                # Fallback: if no source_inputs in metadata, look up parent via media_lineage
                if not resolved:
                    try:
                        lineage_result = await db.execute(
                            select(MediaLineage.source_media_id)
                            .filter(MediaLineage.media_id == media_id)
                        )
                        parent_ids = [row[0] for row in lineage_result.fetchall() if row[0]]
                        log.debug(f"Remix video {media_id}: lineage fallback found parent_ids: {parent_ids}")
                        for parent_id in parent_ids:
                            parent_result = await db.execute(
                                select(MediaItem).filter(MediaItem.id == parent_id, MediaItem.deleted_at.is_(None))
                            )
                            parent = parent_result.scalar_one_or_none()
                            if not parent:
                                continue
                            parent_is_video = parent.file_format and parent.file_format.lower() in video_formats if parent.file_format else False
                            if not parent_is_video:
                                resolved.append({
                                    "media_id": parent.id,
                                    "file_path": parent.file_path,
                                    "role": "start_image",
                                })
                                break  # Use first non-video parent as start frame
                    except Exception as e:
                        log.warning(f"Lineage fallback failed for media {media_id}: {e}")

                video_config["source_inputs"] = resolved
                return video_config

            # Build full params dict for filtering
            # Check both top-level and parameters dict for negative_prompt (backward compatibility)
            full_params = {
                "prompt": effective_prompt,
                "negative_prompt": gen_meta.get("negative_prompt") or params.get("negative_prompt", ""),
                "width": params.get("width", 848),
                "height": params.get("height", 1152),
                "cfg": params.get("cfg", 3.5),
                "steps": params.get("steps", 20),
                "sampler": params.get("sampler", "euler"),
                "scheduler": params.get("scheduler", "simple"),
                "seed": params.get("seed"),
                "denoise": params.get("denoise", 1.0),
                "shift": params.get("shift", 3.1),
                "loras": params.get("loras", []),
            }

            # Include video params if present
            if params.get("frame_count") is not None:
                full_params["frame_count"] = params["frame_count"]
            if params.get("fps") is not None:
                full_params["fps"] = params["fps"]

            # Post-processing chain recorded in lineage (the steps that ran) —
            # Remix merges it back into the on-screen chain.
            if params.get("post_processing_chain"):
                full_params["post_processing_chain"] = params["post_processing_chain"]

            # Determine compatibility and filter params if needed
            is_exact_match = source_tool_id is not None and source_tool_id == target_tool_id
            preserve_seed = is_exact_match
            filter_reason = None

            log.info(f"Compatibility check: source_tool_id={source_tool_id}, target_tool_id={target_tool_id}, "
                     f"is_exact_match={is_exact_match}")

            # Re-match loras when using a different tool
            source_loras = params.get("loras", [])
            if is_exact_match:
                # Same tool - use loras exactly as-is
                final_loras = source_loras
                log.info(f"Same tool - preserving {len(final_loras)} loras as-is")
            elif source_loras and available_loras:
                # Different tool - exact match loras against target tool's available loras
                final_loras = exact_match_loras(source_loras, available_loras)
                log.info(f"Different tool - exact matched {len(source_loras)} source loras to {len(final_loras)} target loras")
            else:
                final_loras = source_loras
                log.info(f"No loras to match or no available loras")

            # Update full_params with the matched loras
            full_params["loras"] = final_loras

            # Pass through all params — no model_family-based filtering
            final_params = full_params

            # Build prompt_variants for frontend flexibility
            rendered_prompt = gen_meta.get("prompt", "")
            prompt_variants = {
                "original": original_prompt or rendered_prompt,
                "rendered": rendered_prompt,
            }

            return {
                **base_config,
                "generator_name": gen_meta.get("generator"),
                "model_name": gen_meta.get("model"),
                **final_params,
                # Include prompt metadata for restoring enhancement settings
                "prompt_metadata": prompt_metadata,
                # Prompt variants for remix feature
                "prompt_variants": prompt_variants,
                # Source thumbnail and prompt snippet for remix banner
                "source_thumbnail_url": f"/api/media/file/{media_id}?size=thumbnail",
                "source_prompt_snippet": (effective_prompt or ""),
                # Original source inputs (start/end frames, input images) with resolved file paths
                "source_inputs": await _resolve_source_inputs(db, gen_meta.get("source_inputs", [])),
                # Compatibility info
                "preserve_seed": preserve_seed,
                "source_tool_id": source_tool_id,
            }
        except json.JSONDecodeError:
            log.error(f"Failed to parse generation_metadata for media {media_id}")

    # Case 2: Has raw metadata from other software - use LLM to parse
    if media_item.raw_metadata:
        try:
            from llm import llm_complete_text

            # Call LLM to parse metadata
            prompt = get_prompt("metadata_to_generation") + "\n\n" + media_item.raw_metadata

            llm_output = await llm_complete_text(
                config=settings.agent_fast_llm,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=1000,
                temperature=0.1,
            )
            log.info(f"Raw LLM output for metadata parsing:\n{llm_output}")

            # Try to parse the JSON output from LLM
            try:
                # Extract JSON from markdown code blocks if present
                if "```json" in llm_output:
                    llm_output = llm_output.split("```json")[1].split("```")[0].strip()
                elif "```" in llm_output:
                    llm_output = llm_output.split("```")[1].split("```")[0].strip()

                parsed_config = json.loads(llm_output)
                log.info(f"Parsed config from LLM: {json.dumps(parsed_config, indent=2)}")

                extracted_model = parsed_config.get("model_name")

                # For videos, only return the prompt
                if is_video:
                    return {
                        **base_config,
                        "prompt": parsed_config.get("prompt") or "",
                        "prompt_only": True,
                    }

                log.info(f"Case 2 (raw metadata): extracted_model={extracted_model}")

                # Build params dict from parsed external metadata
                full_params = {
                    "prompt": parsed_config.get("prompt") or "",
                    "negative_prompt": parsed_config.get("negative_prompt") or "",
                    "width": parsed_config.get("width") or 848,
                    "height": parsed_config.get("height") or 1152,
                    "cfg": parsed_config.get("cfg") or 3.5,
                    "steps": parsed_config.get("steps") or 20,
                    "sampler": parsed_config.get("sampler") or "euler",
                    "scheduler": parsed_config.get("scheduler") or "simple",
                    "seed": parsed_config.get("seed"),
                    "denoise": parsed_config.get("denoise") or 1.0,
                }
                final_params = full_params

                # Fuzzy match extracted loras against target model's available loras
                # Use target model's loras if available, otherwise fall back to default
                extracted_loras = parsed_config.get("loras") or []
                log.info(f"LLM extracted {len(extracted_loras)} LoRAs from metadata: {extracted_loras}")
                matched_loras = exact_match_loras(extracted_loras, available_loras)
                log.info(f"Exact matching resulted in {len(matched_loras)} matched LoRAs: {matched_loras}")

                _ext_prompt = parsed_config.get("prompt") or ""
                return {
                    **base_config,
                    # generator_name and model_name not known for external metadata
                    **final_params,
                    "loras": matched_loras,
                    # Prompt variants
                    "prompt_variants": {
                        "original": _ext_prompt,
                        "rendered": _ext_prompt,
                    },
                    # Source thumbnail and prompt snippet for remix banner
                    "source_thumbnail_url": f"/api/media/file/{media_id}?size=thumbnail",
                    "source_prompt_snippet": _ext_prompt,
                    # External source - never preserve seed
                    "preserve_seed": False,
                }
            except json.JSONDecodeError as e:
                log.error(f"Failed to parse LLM output as JSON: {llm_output[:200]}")
                log.error(f"Error: {e}")
        except Exception as e:
            log.error(f"Error calling LLM for metadata parsing: {e}", exc_info=True)

    # Case 3: Has extracted prompt or AI caption - use as prompt only
    # Prefer extracted_prompt (from external metadata) over vlm_caption (AI-generated)
    # DO NOT include sampling params - let the target tool use its own defaults
    prompt_text = media_item.extracted_prompt or media_item.vlm_caption
    if prompt_text:
        # For videos, only return the prompt
        if is_video:
            return {
                **base_config,
                "prompt": prompt_text,
                "prompt_only": True,
            }

        return {
            **base_config,
            # No generator/model info from prompt/caption only
            "prompt": prompt_text,
            "negative_prompt": "",
            # Only include dimensions, NOT sampling params (cfg, steps, sampler, etc.)
            # Let the target tool keep its own defaults
            "width": 848,
            "height": 1152,
            "loras": [],
            # Prompt variants
            "prompt_variants": {
                "original": prompt_text,
                "rendered": prompt_text,
            },
            # Source thumbnail and prompt snippet for remix banner
            "source_thumbnail_url": f"/api/media/file/{media_id}?size=thumbnail",
            "source_prompt_snippet": prompt_text,
            # Signal frontend to disable all existing loras since we don't know what the image needs
            "disable_all_loras": True,
            "preserve_seed": False,
        }

    # No usable data found
    raise HTTPException(
        status_code=400,
        detail="No generation metadata, raw metadata, extracted prompt, or AI caption found for this image"
    )


@router.get("/config-from-media/{media_id}/compatibility")
async def get_media_compatibility(media_id: int, db: AsyncSession = Depends(get_db_session)):
    """
    Get compatibility info for a media item with all available text-to-image tools.

    Used by the frontend to rank/highlight tools in the "Generate more like this" menu.

    Returns tool compatibility rankings:
    - exact: Same tool that created the image
    - other: Different tool
    """
    # Get the media item
    result = await db.execute(select(MediaItem).filter(MediaItem.id == media_id))
    media_item = result.scalar_one_or_none()
    if not media_item:
        raise HTTPException(status_code=404, detail="Asset not found")

    # Extract source tool ID from metadata
    source_tool_id = None
    if media_item.generation_metadata:
        try:
            gen_meta = json.loads(media_item.generation_metadata)
            source_tool_id = gen_meta.get("tool_id")
        except json.JSONDecodeError:
            pass

    # Get all text-to-image tools
    tools_result = await db.execute(
        select(Tool)
        .where(Tool.task_type == "text-to-image")
        .where(Tool.deleted_at == None)
    )
    tools = tools_result.scalars().all()

    # Compute compatibility for each tool (simple: exact match or other)
    tool_compatibility = []
    for tool in tools:
        is_exact = (source_tool_id is not None and
                    tool.full_tool_id is not None and
                    source_tool_id == tool.full_tool_id)
        match_type = "exact" if is_exact else "other"
        label = "Exact match" if is_exact else None

        tool_compatibility.append({
            "tool_id": tool.id,
            "match_type": match_type,
            "label": label,
        })

    # Sort: exact matches first
    tool_compatibility.sort(key=lambda x: 0 if x["match_type"] == "exact" else 1)

    return {
        "source_tool_id": source_tool_id,
        "tool_compatibility": tool_compatibility,
    }


# Task Defaults API Endpoints

@router.get("/defaults/{task_type}")
async def get_task_defaults(task_type: str, scope: str = "global", session: AsyncSession = Depends(get_db_session)):
    """
    Get user default parameters for a task type.

    Args:
        task_type: The task type (text-to-image, image-to-image, etc.)
        scope: The scope for defaults ("global" or specific scope like "chat-xyz")
    """
    from database import TaskDefaults

    result = await session.execute(
        select(TaskDefaults).where(
            TaskDefaults.task_type == task_type,
            TaskDefaults.scope == scope
        )
    )
    defaults = result.scalar_one_or_none()

    if not defaults:
        # Return empty defaults, not an error
        return {"task_type": task_type, "scope": scope, "parameters": {}}

    return {
        "task_type": defaults.task_type,
        "scope": defaults.scope,
        "parameters": json.loads(defaults.parameters)
    }


@router.put("/defaults/{task_type}")
async def set_task_defaults(task_type: str, parameters: dict, scope: str = "global", session: AsyncSession = Depends(get_db_session)):
    """
    Set user default parameters for a task type.

    Args:
        task_type: The task type (text-to-image, image-to-image, etc.)
        parameters: The default parameters to save
        scope: The scope for defaults ("global" or specific scope like "chat-xyz")
    """
    from database import TaskDefaults
    from datetime import datetime

    # Check if defaults exist for this task/scope
    result = await session.execute(
        select(TaskDefaults).where(
            TaskDefaults.task_type == task_type,
            TaskDefaults.scope == scope
        )
    )
    defaults = result.scalar_one_or_none()

    if defaults:
        # Update existing
        defaults.parameters = json.dumps(parameters)
        defaults.updated_at = datetime.utcnow()
    else:
        # Create new
        defaults = TaskDefaults(
            task_type=task_type,
            scope=scope,
            parameters=json.dumps(parameters),
            updated_at=datetime.utcnow()
        )
        session.add(defaults)

    await session.commit()
    return {"status": "success", "task_type": task_type, "scope": scope}


@router.delete("/defaults/{task_type}")
async def delete_task_defaults(task_type: str, scope: str = "global", session: AsyncSession = Depends(get_db_session)):
    """
    Delete user default parameters for a task type.

    Args:
        task_type: The task type (text-to-image, image-to-image, etc.)
        scope: The scope for defaults ("global" or specific scope like "chat-xyz")
    """
    from database import TaskDefaults

    result = await session.execute(
        select(TaskDefaults).where(
            TaskDefaults.task_type == task_type,
            TaskDefaults.scope == scope
        )
    )
    defaults = result.scalar_one_or_none()

    if defaults:
        await session.delete(defaults)
        await session.commit()

    return {"status": "success", "task_type": task_type, "scope": scope}


@router.post("/forever/register")
async def register_forever_mode(
    generator_instance_id: str = Query(..., description="Unique ID of the generator instance (tab)"),
    backend_name: str = Query(..., description="Name of the backend to generate with"),
    max_concurrency: int = Query(0, description="Maximum concurrent jobs for this client (0 = unlimited)"),
    tool_id: Optional[str] = Query(None, description="Full tool id (telemetry only)"),
):
    """
    Register a client for continuous generation (forever mode).

    When registered, the backend will request work from this client via WebSocket
    whenever it has capacity, using round-robin fairness across all registered clients.
    """
    from generation_queue import get_generation_queue
    queue = get_generation_queue()
    await queue.register_forever_mode(generator_instance_id, backend_name, max_concurrency)

    from telemetry import get_telemetry_client
    from pipeline_telemetry import tool_identity_props
    get_telemetry_client().track("forever_mode_used", {
        "toolRef": tool_identity_props(tool_id).get("toolRef"),
        "action": "started",
    }, category="generation")

    return {"status": "registered", "generator_instance_id": generator_instance_id, "backend_name": backend_name, "max_concurrency": max_concurrency}


@router.post("/forever/unregister")
async def unregister_forever_mode(
    generator_instance_id: str = Query(..., description="Unique ID of the generator instance (tab)"),
    backend_name: str = Query(..., description="Name of the backend"),
    tool_id: Optional[str] = Query(None, description="Full tool id (telemetry only)"),
):
    """
    Unregister a client from continuous generation (forever mode).
    """
    from generation_queue import get_generation_queue
    queue = get_generation_queue()
    await queue.unregister_forever_mode(generator_instance_id, backend_name)

    from telemetry import get_telemetry_client
    from pipeline_telemetry import tool_identity_props
    get_telemetry_client().track("forever_mode_used", {
        "toolRef": tool_identity_props(tool_id).get("toolRef"),
        "action": "stopped",
    }, category="generation")

    return {"status": "unregistered", "generator_instance_id": generator_instance_id, "backend_name": backend_name}


class PromptWarmPoolUpdateRequest(BaseModel):
    generator_instance_id: str
    tool_id: str
    prompt: str
    instructions: Optional[str] = None
    model: Optional[str] = None
    is_video: bool = False
    is_audio: bool = False
    input_image_count: int = 0
    prompt_sources_signature: str = ""
    # How many enhanced variants to keep warm. Client authority - it's the one
    # that knows the forever-mode concurrency it's driving toward. 0 clears
    # the pool for this instance without waiting for unregister/TTL.
    concurrency: int = 0


@router.post("/prompt-warm-pool/update")
async def update_prompt_warm_pool(request: PromptWarmPoolUpdateRequest):
    """Fire-and-forget: keep `concurrency` LLM-enhanced variants of this prompt
    warm for this generator instance, so generate-forever submits can pick up
    an already-enhanced prompt with zero added latency.

    Returns immediately - the actual LLM work happens in server-owned
    background tasks, never on this request's connection. Scoped to the
    generator instance's forever-mode registration; only meaningful while that
    registration is active (see GenerationQueue's prompt warm pool docs).
    """
    from generation_queue import get_generation_queue
    queue = get_generation_queue()
    await queue.update_prompt_warm_pool(
        request.generator_instance_id,
        tool_id=request.tool_id,
        prompt=request.prompt,
        instructions=request.instructions,
        model=request.model,
        is_video=request.is_video,
        is_audio=request.is_audio,
        input_image_count=request.input_image_count,
        prompt_sources_signature=request.prompt_sources_signature,
        concurrency=request.concurrency,
        profile_id=get_current_profile(),
    )
    return {"status": "ok"}


@router.post("/cancel-queued")
async def cancel_queued_jobs(
    generator_instance_id: str = Query(..., description="Unique ID of the generator instance (tab)")
):
    """
    Cancel all queued jobs for a specific generator instance.
    Useful for cleaning up stale jobs when reconnecting.
    """
    from generation_queue import get_generation_queue
    queue = get_generation_queue()
    cancelled_count = await queue.cancel_queued_jobs_for_instance(generator_instance_id)
    return {"status": "success", "cancelled_count": cancelled_count, "generator_instance_id": generator_instance_id}


class ToolHopRequest(BaseModel):
    """Request body for config-for-tool-hop endpoint."""
    target_tool_id: str
    prompt: str = ""
    negative_prompt: str = ""
    input_images: List[dict] = []  # [{path, filename, hash, mediaId, width, height}]
    current_loras: List[dict] = []  # [{lora, weight, enabled}]


@router.post("/config-for-tool-hop")
async def get_config_for_tool_hop(request: ToolHopRequest):
    """
    Get generation config for hopping from one tool to another.

    Transfers prompt, negative_prompt, input_images, and exact-matched loras.
    Sampling parameters (steps, cfg, sampler, etc.) are NOT transferred -
    the target tool should use its own defaults.
    """
    settings = get_settings()
    from providers import ProviderRegistry

    registry = ProviderRegistry.get_instance()

    # Get target tool to access its available LoRAs
    target_tool_descriptor = None
    available_loras = []

    if request.target_tool_id and ':' in request.target_tool_id:
        result = registry.get_tool(request.target_tool_id)
        if result:
            _, target_tool_descriptor = result
            # Get LoRAs from the tool's parameter_schema
            loras_schema = target_tool_descriptor.parameter_schema.get('properties', {}).get('loras', {})
            path_enum = loras_schema.get('items', {}).get('properties', {}).get('path', {}).get('enum', [])
            name_enum = loras_schema.get('items', {}).get('properties', {}).get('name', {}).get('enum', [])
            available_loras = [
                {'path': path, 'name': name_enum[i] if i < len(name_enum) else path}
                for i, path in enumerate(path_enum)
            ]

    if not target_tool_descriptor:
        raise HTTPException(status_code=404, detail=f"Target tool not found: {request.target_tool_id}")

    # Filter enabled loras and fuzzy match them to target tool's available loras
    enabled_loras = [
        {'lora': l['lora'], 'weight': l.get('weight', 1.0)}
        for l in request.current_loras
        if l.get('enabled', True) and l.get('lora')
    ]

    matched_loras = []
    if enabled_loras and available_loras:
        matched_loras = exact_match_loras(enabled_loras, available_loras)
        log.info(f"Tool hop: exact matched {len(enabled_loras)} source loras to {len(matched_loras)} target loras")
    else:
        log.info(f"Tool hop: no loras to match (enabled: {len(enabled_loras)}, available: {len(available_loras)})")

    return {
        "prompt": request.prompt,
        "negative_prompt": request.negative_prompt,
        "input_images": request.input_images,
        "matched_loras": matched_loras,
    }


@router.post("/reproduce/{media_id}", response_model=GenerationJobResponse)
async def reproduce_generation(
    media_id: int,
    generator_instance_id: str = Query(..., description="Unique ID of the generator instance (tab)"),
    new_seed: bool = Query(False, description="Use a new random seed instead of original"),
    session: AsyncSession = Depends(get_db_session),
):
    """
    Reproduce a generation from a media item's stored metadata.

    Queues a new job with the same parameters used to generate the original.
    Optionally uses a new random seed.

    Args:
        media_id: ID of the media item to reproduce
        generator_instance_id: Unique ID for the generator tab/instance
        new_seed: If true, use -1 (random) for seed instead of original

    Returns:
        The created generation job
    """
    from generation_queue import get_generation_queue, GenerationRequest

    # Get the media item
    result = await session.execute(
        select(MediaItem).where(MediaItem.id == media_id)
    )
    media = result.scalar_one_or_none()

    if not media:
        raise HTTPException(status_code=404, detail="Asset not found")

    if not media.generation_metadata:
        raise HTTPException(
            status_code=400,
            detail="Asset has no generation metadata - cannot reproduce"
        )

    # Parse the generation metadata
    try:
        meta = json.loads(media.generation_metadata) if isinstance(media.generation_metadata, str) else media.generation_metadata
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid generation metadata format")

    # Extract required fields
    task_type = meta.get("task_type")
    if not task_type:
        raise HTTPException(status_code=400, detail="Missing task_type in metadata")

    generator_name = meta.get("generator")
    model_name = meta.get("model")
    prompt = meta.get("prompt", "")
    negative_prompt = meta.get("negative_prompt", "")
    parameters = meta.get("parameters", {})

    # Find a matching generator config
    settings = get_settings()
    generator_config = None
    for gen in settings.generators:
        if gen.name == generator_name:
            generator_config = gen
            break

    if not generator_config:
        # Try to find any generator that has this model
        for gen in settings.generators:
            if gen.get_model_by_name(model_name):
                generator_config = gen
                break

    if not generator_config:
        raise HTTPException(
            status_code=400,
            detail=f"No configured generator found for model '{model_name}'"
        )

    # Build the generation request
    # Handle seed
    seed = parameters.get("seed", -1)
    if new_seed:
        seed = -1

    # Create the job request
    queue = get_generation_queue()

    request = GenerationRequest(
        generator_name=generator_config.name,
        backend_name=generator_config.name,
        model_name=model_name,
        task_type=task_type,
        parameters=json.dumps({
            "prompt": prompt,
            "negative_prompt": negative_prompt,
            "width": parameters.get("width", 1024),
            "height": parameters.get("height", 1024),
            "steps": parameters.get("steps", 30),
            "cfg": parameters.get("cfg", 7.5),
            "seed": seed,
            "sampler": parameters.get("sampler", "euler"),
            "scheduler": parameters.get("scheduler", "simple"),
            # Pass through any other parameters
            **{k: v for k, v in parameters.items() if k not in [
                "width", "height", "steps", "cfg", "seed", "sampler",
                "scheduler", "generation_time"
            ]}
        }),
        generator_instance_id=generator_instance_id,
        source_media_id=media_id,  # Link back to original for lineage
    )

    job = await queue.add_job(request)

    # Broadcast the job to the UI
    await ws_manager.broadcast("generation_started", {
        "job": {
            "id": job.id,
            "task_type": task_type,
            "model_name": model_name,
            "status": "queued",
            "generator_instance_id": generator_instance_id,
            "reproduced_from": media_id,
        }
    })

    return GenerationJobResponse(
        id=job.id,
        task_type=task_type,
        model_name=model_name,
        status=job.status,
        created_at=job.created_at.isoformat() if job.created_at else None,
        generator_instance_id=generator_instance_id,
    )
