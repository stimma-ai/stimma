"""
Share routes for uploading media to Stimma Cloud.
"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import Optional
import json
from pathlib import Path

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from core.logging import get_logger
from core.dependencies import get_db_session
from database import MediaItem
from privacy_lockdown import disabled_message, is_privacy_lockdown_enabled

router = APIRouter(prefix="/api/share", tags=["share"])
log = get_logger(__name__)

VIDEO_FORMATS = {"mp4", "webm", "mov", "avi", "mkv"}

# Max dimensions for OG thumbnail (optimized for social sharing)
OG_THUMB_MAX_WIDTH = 1200
OG_THUMB_MAX_HEIGHT = 630
OG_THUMB_QUALITY = 80

CONTENT_TYPES = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "gif": "image/gif",
    "webp": "image/webp",
    "bmp": "image/bmp",
    "tiff": "image/tiff",
    "tif": "image/tiff",
    "mp4": "video/mp4",
    "webm": "video/webm",
    "mov": "video/quicktime",
    "avi": "video/x-msvideo",
    "mkv": "video/x-matroska",
    "html": "text/html",
}


HISTORY_THUMB_SIZE = 128
HISTORY_THUMB_QUALITY = 75


class ShareRequest(BaseModel):
    media_id: int
    title: Optional[str] = None
    description: Optional[str] = None
    nsfw_override: bool = False


class ShareResponse(BaseModel):
    success: bool
    shortcode: Optional[str] = None
    url: Optional[str] = None
    status: Optional[str] = None  # 'approved', 'quarantined', etc.
    error: Optional[str] = None


class PreCheckRequest(BaseModel):
    media_id: int
    title: Optional[str] = None
    description: Optional[str] = None


class PreCheckResponse(BaseModel):
    blocked: bool
    decision: Optional[str] = None  # 'approved', 'quarantined', 'rejected'
    nsfw: bool = False
    reason: Optional[str] = None


class ShareStatusResponse(BaseModel):
    can_share: bool
    reason: Optional[str] = None
    username: Optional[str] = None
    identity_required: bool = False


def _get_media_type(file_format: str) -> str:
    """Determine the share media type from the file format."""
    fmt = file_format.lower()
    if fmt == "stimmaset.json":
        return "set"
    elif fmt == "stimmagrid.json":
        return "grid"
    elif fmt == "stimmalayout":
        return "layout"
    elif fmt in VIDEO_FORMATS:
        return "video"
    else:
        return "image"


def _content_type_for(filename: str) -> str:
    """Get MIME content type for a filename."""
    ext = Path(filename).suffix.lstrip(".").lower()
    return CONTENT_TYPES.get(ext, "application/octet-stream")


def _build_metadata(media_item: MediaItem, media_type: str, title: Optional[str], description: Optional[str], extra: Optional[dict] = None, nsfw_override: bool = False) -> dict:
    """Build the metadata dict for the cloud API."""
    metadata = {
        "mediaType": media_type,
        "title": title or "",
        "description": description or "",
        "width": media_item.width,
        "height": media_item.height,
        "duration": media_item.duration,
        "toolId": media_item.tool_id,
        "extractedPrompt": media_item.extracted_prompt,
        "vlmCaption": media_item.vlm_caption,
    }
    if nsfw_override:
        metadata["nsfwOverride"] = True
    if extra:
        metadata.update(extra)
    return metadata


@router.post("", response_model=ShareResponse)
async def share_media(request: ShareRequest, session: AsyncSession = Depends(get_db_session)):
    """Share a media item to Stimma Cloud."""
    from firebase_auth import get_valid_id_token
    from utils.keyword_blocklist import check_blocklist, gather_texts_for_blocklist

    if is_privacy_lockdown_enabled():
        return ShareResponse(success=False, error=disabled_message("Stimma Cloud sharing"))

    # Load media item
    media_item = await session.get(MediaItem, request.media_id)
    if not media_item:
        return ShareResponse(success=False, error="Media item not found")

    media_type = _get_media_type(media_item.file_format)

    # Keyword blocklist safety net — check all text including composite members
    if media_type in ("set", "grid"):
        texts, _ = await _gather_composite_moderation_data(
            session, media_item, media_type, request.title, request.description,
        )
    elif media_type == "layout":
        texts, _ = await _gather_layout_moderation_data(
            media_item, request.title, request.description,
        )
    else:
        texts = gather_texts_for_blocklist(media_item, request.title, request.description)

    blocklist_result = check_blocklist(texts)
    if blocklist_result.blocked:
        log.warning("share blocked by keyword blocklist", media_id=request.media_id, pattern=blocklist_result.matched_pattern)
        return ShareResponse(success=False, error="This content cannot be shared because it violates community guidelines.")

    # Get auth token
    try:
        token = await get_valid_id_token()
    except Exception:
        token = None

    if not token:
        return ShareResponse(success=False, error="Not signed in to Stimma Cloud")
    file_path = Path(media_item.file_path)
    settings = get_settings()
    cloud_base_url = settings.cloud.base_url

    try:
        files = []
        data = {}

        if media_type in ("set", "grid"):
            files, data = await _build_composite_upload(session, media_item, media_type, request.title, request.description, request.nsfw_override)
        elif media_type == "layout":
            files, data = _build_layout_upload(media_item, file_path, request.title, request.description, request.nsfw_override)
        else:
            # Atomic media (image/video)
            if not file_path.exists():
                return ShareResponse(success=False, error="Media file not found on disk")

            file_bytes = file_path.read_bytes()
            content_type = _content_type_for(file_path.name)
            files.append(("file", (file_path.name, file_bytes, content_type)))
            data["metadata"] = json.dumps(_build_metadata(media_item, media_type, request.title, request.description, nsfw_override=request.nsfw_override))

            # Generate OG thumbnail for social sharing previews
            thumb_bytes = _generate_og_thumbnail(file_path, media_type)
            if thumb_bytes:
                files.append(("thumbnail", ("thumb.webp", thumb_bytes, "image/webp")))

        # Build history sidecar (generation metadata + source input thumbnails)
        try:
            history_sidecar = await _build_history_sidecar(session, media_item)
            if history_sidecar:
                data["historySidecar"] = history_sidecar
        except Exception as e:
            log.warning("history sidecar generation failed, sharing without it", media_id=request.media_id, error=str(e))

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{cloud_base_url}/api/shares",
                headers={"Authorization": f"Bearer {token}"},
                files=files,
                data=data,
                timeout=120.0,
            )

        if response.status_code >= 400:
            error_detail = response.text
            try:
                error_json = response.json()
                error_detail = error_json.get("error", error_json.get("message", error_detail))
            except Exception:
                pass
            log.warning("cloud share failed", status=response.status_code, error=error_detail)
            return ShareResponse(success=False, error=f"Cloud API error: {error_detail}")

        result = response.json()
        share_url = result.get("url") or f"{cloud_base_url}/s/{result.get('shortcode', '')}"

        from telemetry import get_telemetry_client
        get_telemetry_client().track(
            "media_shared_to_cloud", {"count": 1}, category="share"
        )

        return ShareResponse(
            success=True,
            shortcode=result.get("shortcode"),
            url=share_url,
            status=result.get("status"),
        )

    except httpx.TimeoutException:
        log.error("cloud share timed out", media_id=request.media_id)
        return ShareResponse(success=False, error="Upload timed out - the file may be too large")
    except Exception as e:
        log.error("cloud share failed", media_id=request.media_id, error=str(e))
        return ShareResponse(success=False, error=str(e))


def _image_to_base64_payload(img) -> dict:
    """Convert a PIL Image to a base64 payload dict for cloud moderation."""
    import base64
    import io
    from PIL import Image

    if img.mode in ("RGBA", "LA", "PA", "P"):
        img = img.convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=80)
    return {
        "data": base64.b64encode(buf.getvalue()).decode("utf-8"),
        "mediaType": "image/jpeg",
    }


def _rasterize_composite_for_moderation(member_paths: list[Path], max_size: int = 1024) -> Optional[dict]:
    """Rasterize composite member images into a single grid image for moderation.

    Creates a simple contact-sheet style grid so all member images are visible
    in a single moderation API call.
    """
    import math
    from PIL import Image

    valid_paths = [p for p in member_paths if p.exists() and p.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}]
    if not valid_paths:
        return None

    try:
        n = len(valid_paths)
        cols = min(n, math.ceil(math.sqrt(n)))
        rows = math.ceil(n / cols)
        cell_size = max_size // max(cols, rows)

        canvas = Image.new("RGB", (cols * cell_size, rows * cell_size), (24, 24, 24))

        for i, path in enumerate(valid_paths):
            try:
                from utils.image_ops import open_oriented
                img = open_oriented(path)
                img.thumbnail((cell_size, cell_size))
                if img.mode in ("RGBA", "LA", "PA", "P"):
                    img = img.convert("RGB")
                col = i % cols
                row = i // cols
                # Center the image in its cell
                x_offset = col * cell_size + (cell_size - img.width) // 2
                y_offset = row * cell_size + (cell_size - img.height) // 2
                canvas.paste(img, (x_offset, y_offset))
                img.close()
            except Exception:
                continue

        payload = _image_to_base64_payload(canvas)
        canvas.close()
        return payload
    except Exception as e:
        log.debug("composite rasterization failed", error=str(e))
        return None


async def _gather_composite_moderation_data(
    session: AsyncSession,
    media_item: MediaItem,
    media_type: str,
    title: Optional[str] = None,
    description: Optional[str] = None,
) -> tuple[list[str], list[Path]]:
    """Gather all text and member image paths from a composite media item.

    Returns (texts_for_blocklist, member_image_paths).
    """
    from structured_media import read_composite_content, resolve_set_references, resolve_grid_references

    texts = [title, description, media_item.extracted_prompt, media_item.vlm_caption]
    member_paths = []

    content = await read_composite_content(session, media_item)
    if not content:
        return texts, member_paths

    file_path = Path(media_item.file_path)
    parent_dir = file_path.parent

    # Resolve members to get their MediaItem data (prompts, captions)
    if media_type == "set":
        resolved = await resolve_set_references(session, content, file_path)
        members = resolved.get("items", [])
    elif media_type == "grid":
        resolved = await resolve_grid_references(session, content, file_path)
        members = resolved.get("cells", [])
        # Include grid headers
        for header in content.get("row_headers", []):
            texts.append(header)
        for header in content.get("col_headers", []):
            texts.append(header)
    else:
        members = []

    for member in members:
        # Collect member image path
        member_path_str = member.get("path")
        if member_path_str:
            member_path = parent_dir / member_path_str
            member_paths.append(member_path)

        # Collect member text from resolved MediaItem data
        resolved_data = member.get("resolved")
        if resolved_data:
            if resolved_data.get("vlm_caption"):
                texts.append(resolved_data["vlm_caption"])
            # Extract prompts from member's generation_metadata
            gen_meta = resolved_data.get("generation_metadata")
            if gen_meta:
                try:
                    meta = json.loads(gen_meta) if isinstance(gen_meta, str) else gen_meta
                    if meta.get("prompt"):
                        texts.append(meta["prompt"])
                    if meta.get("negative_prompt"):
                        texts.append(meta["negative_prompt"])
                    params = meta.get("parameters", {})
                    if params.get("prompt"):
                        texts.append(params["prompt"])
                except (json.JSONDecodeError, TypeError):
                    pass

    return texts, member_paths


async def _gather_layout_moderation_data(
    media_item: MediaItem,
    title: Optional[str] = None,
    description: Optional[str] = None,
) -> tuple[list[str], list[Path]]:
    """Gather text and member image paths from a layout media item."""
    texts = [title, description, media_item.extracted_prompt, media_item.vlm_caption]
    member_paths = []

    layout_dir = Path(media_item.file_path)
    if layout_dir.is_dir():
        image_extensions = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
        for child in layout_dir.iterdir():
            if child.suffix.lower() in image_extensions and child.is_file():
                member_paths.append(child)

    return texts, member_paths


@router.post("/pre-check", response_model=PreCheckResponse)
async def pre_check_media(request: PreCheckRequest, session: AsyncSession = Depends(get_db_session)):
    """Run moderation checks without creating a share.

    Runs the keyword blocklist locally (instant), then calls the cloud
    moderation API for image + text analysis. For composites (sets/grids/layouts),
    rasterizes all member images into a single grid and aggregates all member text.
    """
    if is_privacy_lockdown_enabled():
        return PreCheckResponse(blocked=False)

    from firebase_auth import get_valid_id_token
    from utils.keyword_blocklist import check_blocklist, gather_texts_for_blocklist

    media_item = await session.get(MediaItem, request.media_id)
    if not media_item:
        return PreCheckResponse(blocked=False, reason="Media item not found")

    media_type = _get_media_type(media_item.file_format)
    file_path = Path(media_item.file_path)

    # 1. Gather text + image data based on media type
    if media_type in ("set", "grid"):
        texts, member_paths = await _gather_composite_moderation_data(
            session, media_item, media_type, request.title, request.description,
        )
    elif media_type == "layout":
        texts, member_paths = await _gather_layout_moderation_data(
            media_item, request.title, request.description,
        )
    else:
        texts = gather_texts_for_blocklist(media_item, request.title, request.description)
        member_paths = []

    # Include lineage_trace prompts in moderation text
    if media_item.generation_metadata:
        try:
            gen_meta = json.loads(media_item.generation_metadata) if isinstance(media_item.generation_metadata, str) else media_item.generation_metadata
            for ancestor in (gen_meta.get("lineage_trace") or []):
                if not ancestor:
                    continue
                if ancestor.get("prompt"):
                    texts.append(ancestor["prompt"])
                if ancestor.get("negative_prompt"):
                    texts.append(ancestor["negative_prompt"])
        except (json.JSONDecodeError, TypeError):
            pass

    # 2. Keyword blocklist (instant, local)
    blocklist_result = check_blocklist(texts)
    if blocklist_result.blocked:
        log.info("pre-check blocked by keyword blocklist", media_id=request.media_id, pattern=blocklist_result.matched_pattern)
        return PreCheckResponse(
            blocked=True,
            decision="rejected",
            reason="This content cannot be shared because it violates community guidelines.",
        )

    # 3. Cloud moderation (OpenAI omni-moderation via cloud API)
    try:
        token = await get_valid_id_token()
    except Exception:
        token = None

    if not token:
        return PreCheckResponse(blocked=False)

    settings = get_settings()
    cloud_base_url = settings.cloud.base_url

    # Build moderation text
    mod_text_parts = [t for t in texts if t]
    mod_text = "\n".join(mod_text_parts) if mod_text_parts else None

    # Prepare image for moderation
    image_payload = None
    if media_type in ("set", "grid", "layout") and member_paths:
        # Rasterize all members into a single composite image
        image_payload = _rasterize_composite_for_moderation(member_paths)
    elif media_type == "image" and file_path.exists():
        try:
            from utils.image_ops import open_oriented
            img = open_oriented(file_path)
            img.thumbnail((512, 512))
            image_payload = _image_to_base64_payload(img)
            img.close()
        except Exception as e:
            log.debug("pre-check image preparation failed", error=str(e))

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{cloud_base_url}/api/shares/pre-check",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                json={
                    "text": mod_text,
                    "imageBase64": image_payload,
                },
                timeout=30.0,
            )

        if response.status_code >= 400:
            log.warning("cloud pre-check failed", status=response.status_code)
            return PreCheckResponse(blocked=False)

        result = response.json()
        decision = result.get("decision", "approved")
        nsfw = result.get("nsfw", False)

        reason = None
        if decision == "rejected":
            reason = "This content cannot be shared because it violates community guidelines."
        elif decision == "quarantined":
            reason = "This content may require review before becoming publicly visible."

        return PreCheckResponse(
            blocked=(decision == "rejected"),
            decision=decision,
            nsfw=nsfw,
            reason=reason,
        )

    except httpx.TimeoutException:
        log.warning("cloud pre-check timed out", media_id=request.media_id)
        return PreCheckResponse(blocked=False)
    except Exception as e:
        log.warning("cloud pre-check failed", media_id=request.media_id, error=str(e))
        return PreCheckResponse(blocked=False)


async def _build_composite_upload(
    session: AsyncSession,
    media_item: MediaItem,
    media_type: str,
    title: Optional[str],
    description: Optional[str],
    nsfw_override: bool = False,
) -> tuple[list, dict]:
    """Build multipart upload data for a set or grid.

    Rasterizes all member images into a single composite thumbnail for moderation,
    and aggregates member prompts/captions so the cloud moderates all content.
    """
    from structured_media import read_composite_content

    content = await read_composite_content(session, media_item)
    if not content:
        raise ValueError(f"Could not read {media_type} content")

    file_path = Path(media_item.file_path)
    parent_dir = file_path.parent

    files = []
    data = {}

    # Add structured content JSON
    data["structuredContent"] = json.dumps(content)

    # Resolve member paths and add member files
    members = []
    if media_type == "set":
        members = content.get("items", [])
    elif media_type == "grid":
        members = content.get("cells", [])

    member_image_paths = []
    for member in members:
        member_path_str = member.get("path")
        if not member_path_str:
            continue

        member_path = parent_dir / member_path_str
        if not member_path.exists():
            log.warning("composite member file missing", path=str(member_path))
            continue

        member_bytes = member_path.read_bytes()
        content_type = _content_type_for(member_path.name)
        files.append(("members", (member_path.name, member_bytes, content_type)))
        member_image_paths.append(member_path)

    # Generate composite thumbnail: rasterize all members into a single image
    composite_thumb = _rasterize_composite_for_moderation(member_image_paths)
    if composite_thumb:
        import base64
        thumb_bytes = base64.b64decode(composite_thumb["data"])
        files.append(("thumbnail", ("thumb.jpg", thumb_bytes, "image/jpeg")))
    elif member_image_paths:
        # Fallback: use first member as thumbnail
        first_path = member_image_paths[0]
        files.append(("thumbnail", (first_path.name, first_path.read_bytes(), _content_type_for(first_path.name))))

    # Gather member text for moderation (prompts, captions from resolved members)
    member_texts = await _gather_composite_moderation_data(
        session, media_item, media_type, title, description,
    )
    member_text_parts = [t for t in member_texts[0] if t]

    # Build metadata, include grid headers and aggregated member text
    extra = {}
    if media_type == "grid":
        if content.get("row_headers"):
            extra["rowHeaders"] = content["row_headers"]
        if content.get("col_headers"):
            extra["colHeaders"] = content["col_headers"]

    # Include aggregated member prompts as extractedPrompt so cloud moderation
    # checks all text, not just the parent item's prompt
    if member_text_parts:
        extra["extractedPrompt"] = "\n".join(member_text_parts)

    data["metadata"] = json.dumps(_build_metadata(media_item, media_type, title, description, extra, nsfw_override=nsfw_override))

    return files, data


def _build_layout_upload(
    media_item: MediaItem,
    layout_dir: Path,
    title: Optional[str],
    description: Optional[str],
    nsfw_override: bool = False,
) -> tuple[list, dict]:
    """Build multipart upload data for a .stimmalayout bundle."""
    files = []
    data = {}

    index_html = layout_dir / "index.html"
    if not index_html.exists():
        raise ValueError("Layout bundle missing index.html")

    # Add index.html as the primary file
    files.append(("file", ("index.html", index_html.read_bytes(), "text/html")))

    # Add any images in the layout directory as members
    image_extensions = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg"}
    thumbnail_added = False
    for child in layout_dir.iterdir():
        if child.suffix.lower() in image_extensions and child.is_file():
            content_type = _content_type_for(child.name)
            member_bytes = child.read_bytes()
            files.append(("members", (child.name, member_bytes, content_type)))

            # Use first image as OG thumbnail
            if not thumbnail_added and child.suffix.lower() != ".svg":
                thumb_bytes = _generate_og_thumbnail(child, "image")
                if thumb_bytes:
                    files.append(("thumbnail", ("thumb.webp", thumb_bytes, "image/webp")))
                    thumbnail_added = True

    data["metadata"] = json.dumps(_build_metadata(media_item, "layout", title, description, nsfw_override=nsfw_override))

    return files, data


def _generate_og_thumbnail(file_path: Path, media_type: str) -> Optional[bytes]:
    """Generate an OG-optimized thumbnail for social sharing previews.

    Returns WebP bytes sized for social cards, or None on failure.
    """
    import io
    from PIL import Image

    try:
        if media_type == "video":
            import ffmpeg
            out, _ = (
                ffmpeg
                .input(str(file_path), ss=0)
                .output('pipe:', vframes=1, format='image2', vcodec='mjpeg')
                .run(capture_stdout=True, capture_stderr=True, quiet=True)
            )
            img = Image.open(io.BytesIO(out))
        else:
            from utils.image_ops import open_oriented
            img = open_oriented(file_path)

        # Convert to RGB (strip alpha)
        if img.mode in ("RGBA", "LA", "PA", "P"):
            img = img.convert("RGB")

        # Resize to fit within OG dimensions, preserving aspect ratio
        img.thumbnail((OG_THUMB_MAX_WIDTH, OG_THUMB_MAX_HEIGHT), Image.LANCZOS)

        buf = io.BytesIO()
        img.save(buf, format="WEBP", quality=OG_THUMB_QUALITY)
        img.close()

        return buf.getvalue()
    except Exception as e:
        log.debug("OG thumbnail generation failed", error=str(e), path=str(file_path))
        return None


async def _build_history_sidecar(session: AsyncSession, media_item: MediaItem) -> Optional[str]:
    """Build a JSON sidecar with generation history + base64 thumbnails for source inputs.

    Returns a JSON string containing:
    - generationMetadata: the full generation_metadata from the media item
    - thumbnails: dict mapping media_id (str) → data URI for source input thumbnails

    Returns None if the media has no generation history.
    """
    import base64
    import io
    from PIL import Image

    # Parse generation metadata
    if not media_item.generation_metadata:
        return None
    try:
        gen_meta = json.loads(media_item.generation_metadata) if isinstance(media_item.generation_metadata, str) else media_item.generation_metadata
    except (json.JSONDecodeError, TypeError):
        return None

    if not gen_meta:
        return None

    # Collect all source_input media_ids from current step + lineage_trace
    media_ids_needed = set()
    file_paths_needed = set()

    def _collect_source_refs(step):
        for source in (step.get("source_inputs") or []):
            if source.get("media_id"):
                media_ids_needed.add(source["media_id"])
            elif source.get("file_path"):
                file_paths_needed.add(source["file_path"])

    _collect_source_refs(gen_meta)
    for ancestor in (gen_meta.get("lineage_trace") or []):
        if ancestor:
            _collect_source_refs(ancestor)

    # Generate thumbnails for referenced media
    thumbnails = {}

    # Thumbnails for media_id references
    if media_ids_needed:
        from sqlalchemy import select
        result = await session.execute(
            select(MediaItem).where(MediaItem.id.in_(list(media_ids_needed)))
        )
        ref_items = {item.id: item for item in result.scalars().all()}

        for mid in media_ids_needed:
            ref = ref_items.get(mid)
            if not ref:
                continue
            thumb_data = _generate_source_thumbnail(ref)
            if thumb_data:
                thumbnails[str(mid)] = thumb_data

    # Thumbnails for file_path references (external/non-library files)
    for fp in file_paths_needed:
        p = Path(fp)
        if not p.exists():
            continue
        try:
            from utils.image_ops import open_oriented
            img = open_oriented(p)
            img.thumbnail((HISTORY_THUMB_SIZE, HISTORY_THUMB_SIZE), Image.LANCZOS)
            if img.mode in ("RGBA", "LA", "PA", "P"):
                img = img.convert("RGB")
            buf = io.BytesIO()
            img.save(buf, format="WEBP", quality=HISTORY_THUMB_QUALITY)
            img.close()
            thumbnails[fp] = f"data:image/webp;base64,{base64.b64encode(buf.getvalue()).decode('utf-8')}"
        except Exception:
            continue

    sidecar = {
        "generationMetadata": gen_meta,
        "thumbnails": thumbnails,
    }

    result_json = json.dumps(sidecar)
    # Cap at 2MB to prevent oversized uploads
    if len(result_json) > 2 * 1024 * 1024:
        # Strip thumbnails if too large
        sidecar["thumbnails"] = {}
        result_json = json.dumps(sidecar)

    return result_json


def _generate_source_thumbnail(media_item: MediaItem) -> Optional[str]:
    """Generate a base64 data URI thumbnail for a source input media item."""
    import base64
    import io
    from PIL import Image

    file_path = Path(media_item.file_path)
    if not file_path.exists():
        return None

    fmt = media_item.file_format.lower() if media_item.file_format else ""

    try:
        if fmt in VIDEO_FORMATS:
            import ffmpeg
            out, _ = (
                ffmpeg
                .input(str(file_path), ss=0)
                .output('pipe:', vframes=1, format='image2', vcodec='mjpeg')
                .run(capture_stdout=True, capture_stderr=True, quiet=True)
            )
            img = Image.open(io.BytesIO(out))
        else:
            from utils.image_ops import open_oriented
            img = open_oriented(file_path)

        img.thumbnail((HISTORY_THUMB_SIZE, HISTORY_THUMB_SIZE), Image.LANCZOS)
        if img.mode in ("RGBA", "LA", "PA", "P"):
            img = img.convert("RGB")
        buf = io.BytesIO()
        img.save(buf, format="WEBP", quality=HISTORY_THUMB_QUALITY)
        img.close()
        return f"data:image/webp;base64,{base64.b64encode(buf.getvalue()).decode('utf-8')}"
    except Exception as e:
        log.debug("source thumbnail generation failed", media_id=media_item.id, error=str(e))
        return None


class SuggestTitleRequest(BaseModel):
    media_id: int


class SuggestTitleResponse(BaseModel):
    title: Optional[str] = None
    source: Optional[str] = None  # 'existing', 'llm', or None if failed


@router.post("/suggest-title", response_model=SuggestTitleResponse)
async def suggest_share_title(request: SuggestTitleRequest, session: AsyncSession = Depends(get_db_session)):
    """Suggest a share title using available metadata or LLM.

    Per-type strategy:
    - Sets/grids: use existing title if present, otherwise fall through to LLM
    - Images/videos: use extracted prompt or VLM caption; VLM the image if neither exists
    - Layouts: extract text content from the HTML for LLM context
    """
    import time as _time
    t_start = _time.monotonic()

    media_item = await session.get(MediaItem, request.media_id)
    if not media_item:
        return SuggestTitleResponse()

    media_type = _get_media_type(media_item.file_format)
    log.info("share title suggest", media_id=request.media_id, media_type=media_type, format=media_item.file_format)

    # --- Sets & grids: use existing title if available ---
    if media_type in ("set", "grid") and media_item.raw_metadata:
        try:
            content = json.loads(media_item.raw_metadata)
            existing_title = content.get("title")
            if existing_title and existing_title != "Untitled":
                return SuggestTitleResponse(title=existing_title, source="existing")
        except json.JSONDecodeError:
            pass

    # --- Per-type context gathering ---
    context_parts = []

    if media_type == "layout":
        context_parts = _gather_layout_context(media_item)
    elif media_type in ("set", "grid"):
        # No existing title — describe the structure
        context_parts = _gather_composite_context(media_item)
    else:
        # Image or video — use prompt/caption if available
        context_parts = await _gather_atomic_context(media_item)

    # If we have text context, generate title from it (one LLM call)
    if context_parts:
        return await _llm_generate_title(context_parts)

    # No text context — for images, VLM directly to title in one call
    if media_type == "image":
        vlm_result = await _vlm_generate_title(media_item)
        if vlm_result.title:
            return vlm_result

    # Final fallback: clean up filename
    filename = Path(media_item.file_path).stem
    if filename and len(filename) > 2:
        return SuggestTitleResponse(title=_clean_filename_title(filename), source="filename")
    return SuggestTitleResponse()


def _gather_layout_context(media_item) -> list[str]:
    """Extract text content from a layout's index.html for title context."""
    layout_dir = Path(media_item.file_path)
    index_html = layout_dir / "index.html"
    if not index_html.exists():
        return []

    try:
        import re as _re
        html = index_html.read_text(encoding="utf-8")[:5000]
        # Strip tags to get visible text content
        text = _re.sub(r'<style[^>]*>.*?</style>', '', html, flags=_re.DOTALL)
        text = _re.sub(r'<script[^>]*>.*?</script>', '', text, flags=_re.DOTALL)
        text = _re.sub(r'<[^>]+>', ' ', text)
        text = _re.sub(r'\s+', ' ', text).strip()[:500]
        if text:
            return [f"Layout content: {text}"]
    except Exception:
        pass
    return []


def _gather_composite_context(media_item) -> list[str]:
    """Gather context for a set/grid that has no title."""
    parts = []
    if media_item.raw_metadata:
        try:
            content = json.loads(media_item.raw_metadata)
            # Grids have row/col headers
            row_headers = content.get("row_headers", [])
            col_headers = content.get("col_headers", [])
            if row_headers or col_headers:
                parts.append(f"Grid parameters: rows={row_headers}, columns={col_headers}")
            # Sets/grids may have item count
            items = content.get("items", content.get("cells", []))
            if items:
                parts.append(f"Contains {len(items)} items")
        except json.JSONDecodeError:
            pass

    if media_item.vlm_caption:
        parts.append(f"Visual description: {media_item.vlm_caption[:300]}")

    return parts


async def _gather_atomic_context(media_item) -> list[str]:
    """Gather context for an image or video. Falls back to VLM if needed."""
    parts = []

    if media_item.extracted_prompt:
        parts.append(f"Generation prompt: {media_item.extracted_prompt[:300]}")

    if media_item.vlm_caption:
        parts.append(f"Image description: {media_item.vlm_caption[:300]}")

    if not parts and media_item.generation_metadata:
        try:
            gen_meta = json.loads(media_item.generation_metadata)
            prompt = gen_meta.get("prompt") or gen_meta.get("parameters", {}).get("prompt")
            if prompt:
                parts.append(f"Generation prompt: {prompt[:300]}")
        except json.JSONDecodeError:
            pass

    return parts


async def _vlm_generate_title(media_item) -> SuggestTitleResponse:
    """For images with no text context, VLM the image directly to get a title in one call."""
    if media_item.file_format.lower() in VIDEO_FORMATS:
        return SuggestTitleResponse()

    file_path = Path(media_item.file_path)
    if not file_path.exists():
        return SuggestTitleResponse()

    try:
        import time as _time
        from llm import llm_complete_vision
        from llm_resolver import get_effective_llm_config

        config = await get_effective_llm_config("agent-fast")
        if not config:
            return SuggestTitleResponse()

        import base64
        import io
        from utils.image_ops import open_oriented

        img = open_oriented(file_path)
        img.thumbnail((512, 512))
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85)
        img.close()
        image_b64 = base64.b64encode(buf.getvalue()).decode("utf-8")

        log.info("share title VLM direct", model=config.get_model(), image_size=len(image_b64))
        t0 = _time.monotonic()
        result, error = await llm_complete_vision(
            config,
            "Generate a short title (2-6 words) for this image. Reply with ONLY the title, no quotes or punctuation.",
            image_b64,
            max_tokens=30, temperature=0.5,
        )
        elapsed = _time.monotonic() - t0
        log.info("share title VLM direct response", elapsed_s=round(elapsed, 2), result=result[:200] if result else None, error=error)

        if result and not error:
            result = result.strip().strip('"\'').strip()
            words = result.split()
            if 1 <= len(words) <= 8 and len(result) <= 80:
                return SuggestTitleResponse(title=result, source="vlm")
    except Exception as e:
        log.debug("VLM direct title generation failed", error=str(e))

    return SuggestTitleResponse()


def _clean_filename_title(stem: str) -> str:
    """Turn a filename stem into a passable title."""
    import re as _re
    # Replace separators with spaces
    title = _re.sub(r'[-_]+', ' ', stem)
    # Remove long hex/hash sequences
    title = _re.sub(r'\b[a-f0-9]{8,}\b', '', title)
    title = _re.sub(r'\s+', ' ', title).strip()
    # Title case
    if title:
        title = title.title()
    return title if title and len(title) > 2 else ""


async def _llm_generate_title(context_parts: list[str]) -> SuggestTitleResponse:
    """Generate a short title from context parts using agent-fast."""
    import time as _time
    try:
        from llm import llm_complete_text
        from llm_resolver import get_effective_llm_config

        config = await get_effective_llm_config("agent-fast")
        if not config:
            return SuggestTitleResponse()

        messages = [
            {
                "role": "system",
                "content": "You generate short, descriptive titles (2-6 words) for shared images/media. Reply with ONLY the title, no quotes or punctuation. The title should describe what's in the image or content, not how it was made.",
            },
            {
                "role": "user",
                "content": "\n".join(context_parts) + "\n\nTitle:",
            },
        ]

        log.info("share title LLM request", model=config.get_model(), user_content=messages[1]["content"][:200])
        t0 = _time.monotonic()
        result = await llm_complete_text(config, messages, max_tokens=30, temperature=0.5)
        elapsed = _time.monotonic() - t0
        log.info("share title LLM response", elapsed_s=round(elapsed, 2), raw_result=result[:200])

        result = result.strip().strip('"\'').strip()

        # Validate: 1-8 words, max 80 chars
        words = result.split()
        if 1 <= len(words) <= 8 and len(result) <= 80:
            return SuggestTitleResponse(title=result, source="llm")

    except Exception as e:
        log.warning("share title suggestion failed", error=str(e))

    return SuggestTitleResponse()


@router.get("/status", response_model=ShareStatusResponse)
async def get_share_status():
    """Check if the current user can share to Stimma Cloud."""
    from firebase_auth import get_valid_id_token
    from cloud_api import fetch_user_account

    if is_privacy_lockdown_enabled():
        return ShareStatusResponse(can_share=False, reason=disabled_message("Stimma Cloud sharing"))

    try:
        token = await get_valid_id_token()
    except Exception:
        token = None

    if not token:
        # The share surface's sign-in gate moment (conversion-funnel start).
        from telemetry import get_telemetry_client
        get_telemetry_client().track("gate_encountered", {
            "gate": "signin_required",
            "surface": "share",
        }, category="account")
        return ShareStatusResponse(can_share=False, reason="Not signed in to Stimma Cloud")

    try:
        account = await fetch_user_account(token)
        username = account.get("username")
        sharing_banned = account.get("sharingBanned", False)

        if sharing_banned:
            return ShareStatusResponse(can_share=False, reason="Your sharing privileges have been suspended", username=username)

        if not username:
            return ShareStatusResponse(can_share=False, reason="You need to set up your profile before sharing", identity_required=True)

        return ShareStatusResponse(can_share=True, username=username)

    except httpx.HTTPStatusError as e:
        if e.response.status_code == 401:
            return ShareStatusResponse(can_share=False, reason="Authentication expired - please sign in again")
        return ShareStatusResponse(can_share=False, reason="Unable to verify account status")
    except Exception as e:
        log.warning("share status check failed", error=str(e))
        return ShareStatusResponse(can_share=False, reason="Unable to check share status")


class CheckUsernameResponse(BaseModel):
    available: bool
    username: str
    error: Optional[str] = None


@router.get("/check-username", response_model=CheckUsernameResponse)
async def check_username(username: str):
    """Check if a username is available on Stimma Cloud."""
    from firebase_auth import get_valid_id_token

    if is_privacy_lockdown_enabled():
        return CheckUsernameResponse(
            available=False,
            username=username,
            error=disabled_message("Stimma Cloud identity"),
        )

    try:
        token = await get_valid_id_token()
    except Exception:
        token = None

    if not token:
        return CheckUsernameResponse(available=False, username=username, error="Not signed in")

    settings = get_settings()
    cloud_base_url = settings.cloud.base_url

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{cloud_base_url}/api/accounts/identity/check-username",
                params={"username": username},
                headers={"Authorization": f"Bearer {token}"},
                timeout=15.0,
            )
        data = response.json()
        return CheckUsernameResponse(
            available=data.get("available", False),
            username=data.get("username", username),
            error=data.get("error"),
        )
    except Exception as e:
        log.warning("check username failed", error=str(e))
        return CheckUsernameResponse(available=False, username=username, error="Unable to check username")


class SetupIdentityRequest(BaseModel):
    username: str


class SetupIdentityResponse(BaseModel):
    success: bool
    username: Optional[str] = None
    error: Optional[str] = None


@router.post("/setup-identity", response_model=SetupIdentityResponse)
async def setup_identity(request: SetupIdentityRequest):
    """Set up user identity (username) on Stimma Cloud."""
    from firebase_auth import get_valid_id_token

    if is_privacy_lockdown_enabled():
        return SetupIdentityResponse(
            success=False,
            error=disabled_message("Stimma Cloud identity"),
        )

    try:
        token = await get_valid_id_token()
    except Exception:
        token = None

    if not token:
        return SetupIdentityResponse(success=False, error="Not signed in to Stimma Cloud")

    settings = get_settings()
    cloud_base_url = settings.cloud.base_url

    try:
        async with httpx.AsyncClient() as client:
            response = await client.put(
                f"{cloud_base_url}/api/accounts/identity",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                json={"username": request.username},
                timeout=15.0,
            )

        data = response.json()

        if response.status_code >= 400:
            return SetupIdentityResponse(
                success=False,
                error=data.get("error", "Failed to set up identity"),
            )

        return SetupIdentityResponse(
            success=True,
            username=data.get("username"),
        )
    except Exception as e:
        log.warning("setup identity failed", error=str(e))
        return SetupIdentityResponse(success=False, error="Unable to set up identity")
