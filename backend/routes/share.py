"""
Share routes: public links for library items, via the signed-in Stimma account.

What gets uploaded is built in ``share_payloads`` (one builder per media type)
and the optional "how it was made" sidecar in ``share_provenance``. Nothing
published carries local paths, library ids or raw generation metadata.
"""
import json
import re
import time
from pathlib import Path
from typing import Any, Optional

import httpx
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from cloud_runtime import with_cloud_access_headers
from config import get_settings
from core.dependencies import get_db_session
from core.logging import get_logger
from database import MediaItem
from privacy_lockdown import disabled_message, is_privacy_lockdown_enabled
from share_payloads import (
    CLOUD_LIMITS,
    MAX_UPLOAD_BYTES,
    ShareBuildError,
    build_payload,
    cloud_limit_problem,
    composite_member_path,
    estimate_upload_bytes,
    form_bytes,
    share_media_type,
    too_large_message,
)
from share_provenance import ProvenanceError, build_public_sidecar, parse_provenance

router = APIRouter(prefix="/api/share", tags=["share"])
log = get_logger(__name__)

VIDEO_FORMATS = {"mp4", "webm", "mov", "avi", "mkv"}

GUIDELINES_MESSAGE = "This content cannot be shared because it violates community guidelines."
SIGNED_OUT_MESSAGE = "Sign in to your Stimma account to share links."
EXPIRED_MESSAGE = "Your Stimma sign-in has expired. Sign in again to continue."
BANNED_MESSAGE = "Your sharing privileges have been suspended."
UNREACHABLE_MESSAGE = "Couldn't reach your Stimma account. Check your connection and try again."
LIMIT_MESSAGE = "You've reached today's share limit. Try again tomorrow."
UNAVAILABLE_MESSAGE = "Sharing is temporarily unavailable. Try again in a moment."

_SHORTCODE_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def _cloud_client(timeout: float) -> httpx.AsyncClient:
    """Client for Stimma Cloud calls (a seam for tests)."""
    return httpx.AsyncClient(timeout=timeout)


def _cloud_headers(token: str, *, json_body: bool = False) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {token}"}
    if json_body:
        headers["Content-Type"] = "application/json"
    return with_cloud_access_headers(headers)


async def _token() -> Optional[str]:
    from firebase_auth import get_valid_id_token

    try:
        return await get_valid_id_token()
    except Exception:  # noqa: BLE001
        return None


def _cloud_error_detail(response: httpx.Response) -> str:
    """The cloud's error text plus its machine code (``{error, code}``), for matching only."""
    try:
        body = response.json()
        if isinstance(body, dict):
            return " ".join(str(body.get(k)) for k in ("code", "error", "message") if body.get(k))
    except Exception:  # noqa: BLE001
        pass
    return ""


def _friendly_cloud_error(status: int, detail: str, *, action: str = "share") -> str:
    """User-facing text for a cloud error. Raw cloud strings are never shown."""
    lowered = (detail or "").lower()
    if status == 401:
        return EXPIRED_MESSAGE
    if status == 403:
        if "identity" in lowered or "profile" in lowered:
            return "Set up your profile before sharing."
        if "suspend" in lowered or "ban" in lowered:
            return BANNED_MESSAGE
        return "Your account can't do that right now."
    if status == 404:
        return "That link no longer exists."
    if status == 413:
        return f"This is too large to share as a link. Links can hold up to {MAX_UPLOAD_BYTES // 1_000_000} MB."
    if status == 429:
        return LIMIT_MESSAGE
    if status == 400:
        if "characters or less" in lowered:
            return "Titles can be up to 100 characters and descriptions up to 500."
        if "unsupported" in lowered:
            return "This kind of file can't be shared as a link yet."
        if action == "share":
            return "This item couldn't be shared. Try again, or share the file instead."
        return "That change couldn't be saved."
    return UNAVAILABLE_MESSAGE


class ShareRequest(BaseModel):
    media_id: int
    title: Optional[str] = None
    description: Optional[str] = None
    nsfw_override: bool = False
    # Public "how it was made" (sidecar v2 request shape), or null to omit it.
    provenance: Optional[Any] = None


class ShareResponse(BaseModel):
    success: bool
    shortcode: Optional[str] = None
    url: Optional[str] = None
    status: Optional[str] = None  # 'approved', 'quarantined', etc.
    media_type: Optional[str] = None
    error: Optional[str] = None
    # Machine-readable failure: signed_out | auth_expired | privacy_lockdown |
    # too_large | blocked | unsupported | invalid_provenance | cloud | not_found
    error_code: Optional[str] = None


class PreCheckRequest(BaseModel):
    media_id: int
    title: Optional[str] = None
    description: Optional[str] = None


class PreCheckResponse(BaseModel):
    blocked: bool
    decision: Optional[str] = None  # 'approved', 'quarantined', 'rejected'
    nsfw: bool = False
    reason: Optional[str] = None
    size_bytes: Optional[int] = None
    too_large: bool = False
    media_type: Optional[str] = None
    unsupported_reason: Optional[str] = None


class ShareAccount(BaseModel):
    username: Optional[str] = None
    display_name: Optional[str] = None
    avatar_url: Optional[str] = None


class ShareStatusResponse(BaseModel):
    can_share: bool
    # signed_out | auth_expired | privacy_lockdown | banned | None
    reason_code: Optional[str] = None
    reason: Optional[str] = None
    identity_required: bool = False
    account: Optional[ShareAccount] = None
    # Kept for older clients; same as account.username.
    username: Optional[str] = None


def _get_media_type(file_format: str) -> str:
    """Share media type, with unknown formats treated as images (title suggestion)."""
    return share_media_type(file_format) or "image"


# Status ───────────────────────────────────────────────────────────────────────

# Account lookups are cached briefly per token so opening the dialog is fast.
_ACCOUNT_CACHE_TTL_S = 60.0
_account_cache: dict[str, tuple[float, dict]] = {}


async def _cached_account(token: str) -> dict:
    from cloud_api import fetch_user_account

    now = time.monotonic()
    hit = _account_cache.get(token)
    if hit and now - hit[0] < _ACCOUNT_CACHE_TTL_S:
        return hit[1]
    account = dict(await fetch_user_account(token))
    _account_cache.clear()
    _account_cache[token] = (now, account)
    return account


def _local_profile() -> dict:
    """Display name / photo from the stored sign-in, when the cloud has none."""
    try:
        from auth_storage import load_auth_state

        return dict((load_auth_state() or {}).get("user") or {})
    except Exception:  # noqa: BLE001
        return {}


@router.get("/status", response_model=ShareStatusResponse)
async def get_share_status():
    """Whether this machine can publish links, and the account that will publish them."""
    from firebase_auth import AuthSessionExpiredError, get_valid_id_token

    if is_privacy_lockdown_enabled():
        return ShareStatusResponse(
            can_share=False, reason_code="privacy_lockdown", reason=disabled_message("Stimma sharing"),
        )

    try:
        token = await get_valid_id_token(raise_on_failure=True)
    except AuthSessionExpiredError:
        return ShareStatusResponse(can_share=False, reason_code="auth_expired", reason=EXPIRED_MESSAGE)
    except Exception:  # noqa: BLE001
        return ShareStatusResponse(can_share=False, reason=UNREACHABLE_MESSAGE)

    if not token:
        # The share surface's sign-in gate moment (conversion-funnel start).
        from telemetry import get_telemetry_client
        get_telemetry_client().track("gate_encountered", {
            "gate": "signin_required",
            "surface": "share",
        }, category="account")
        return ShareStatusResponse(can_share=False, reason_code="signed_out", reason=SIGNED_OUT_MESSAGE)

    try:
        account = await _cached_account(token)
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 401:
            return ShareStatusResponse(can_share=False, reason_code="auth_expired", reason=EXPIRED_MESSAGE)
        return ShareStatusResponse(can_share=False, reason=UNREACHABLE_MESSAGE)
    except Exception as e:  # noqa: BLE001
        log.warning("share status check failed", error=type(e).__name__)
        return ShareStatusResponse(can_share=False, reason=UNREACHABLE_MESSAGE)

    profile = _local_profile()
    username = account.get("username")
    info = ShareAccount(
        username=username,
        display_name=account.get("displayName") or profile.get("displayName") or username,
        avatar_url=account.get("avatarUrl") or profile.get("photoURL"),
    )
    if account.get("sharingBanned"):
        return ShareStatusResponse(
            can_share=False, reason_code="banned", reason=BANNED_MESSAGE, account=info, username=username,
        )
    if not username:
        return ShareStatusResponse(
            can_share=False,
            reason="Choose a username before sharing links.",
            identity_required=True,
            account=info,
        )
    return ShareStatusResponse(can_share=True, account=info, username=username)


# Moderation inputs ────────────────────────────────────────────────────────────

def _image_to_base64_payload(img) -> dict:
    """Convert a PIL Image to a base64 payload dict for cloud moderation."""
    import base64
    import io

    if img.mode in ("RGBA", "LA", "PA", "P"):
        img = img.convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=80)
    return {
        "data": base64.b64encode(buf.getvalue()).decode("utf-8"),
        "mediaType": "image/jpeg",
    }


def _rasterize_composite_for_moderation(member_paths: list[Path], max_size: int = 1024) -> Optional[dict]:
    """Contact sheet of composite member images, so one moderation call sees them all."""
    import math
    from PIL import Image

    valid_paths = [p for p in member_paths if p.exists() and p.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tif", ".tiff"}]
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
    """All text and member image paths of a set or grid: (texts, member_paths)."""
    from share_payloads import _composite_content

    texts = [title, description, media_item.extracted_prompt, media_item.vlm_caption]
    member_paths: list[Path] = []
    try:
        content = await _composite_content(session, media_item, media_type)
    except ShareBuildError:
        return texts, member_paths

    base = Path(media_item.file_path)
    if media_type == "grid":
        texts.extend(str(h) for h in content.get("row_headers") or [])
        texts.extend(str(h) for h in content.get("col_headers") or [])
    for entry in content.get("items" if media_type == "set" else "cells") or []:
        if not isinstance(entry, dict):
            continue
        path = composite_member_path(entry, base)
        if path is not None:
            member_paths.append(path)
        texts.extend([entry.get("title"), entry.get("caption")])
        resolved = entry.get("resolved") or {}
        texts.append(resolved.get("vlm_caption"))
        gen_meta = resolved.get("generation_metadata")
        if gen_meta:
            try:
                meta = json.loads(gen_meta) if isinstance(gen_meta, str) else gen_meta
                texts.extend([meta.get("prompt"), meta.get("negative_prompt"), (meta.get("parameters") or {}).get("prompt")])
            except (json.JSONDecodeError, TypeError, AttributeError):
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


def _markdown_text(media_item: MediaItem) -> Optional[str]:
    from structured_media import read_markdown_file

    parsed = read_markdown_file(Path(media_item.file_path))
    return (parsed or {}).get("content", "")[:4000] or None


async def _moderation_texts(
    session: AsyncSession, media_item: MediaItem, media_type: str, title: Optional[str], description: Optional[str],
) -> tuple[list[str], list[Path]]:
    from utils.keyword_blocklist import gather_texts_for_blocklist

    if media_type in ("set", "grid"):
        return await _gather_composite_moderation_data(session, media_item, media_type, title, description)
    if media_type == "layout":
        return await _gather_layout_moderation_data(media_item, title, description)
    texts = gather_texts_for_blocklist(media_item, title, description)
    if media_type == "text":
        texts.append(_markdown_text(media_item))
    return texts, []


def _provenance_texts(provenance) -> list[str]:
    texts: list[str] = []
    for step in provenance.steps if provenance is not None else []:
        texts.extend([step.prompt, step.negativePrompt, step.originalPrompt])
    return texts


# Pre-check ────────────────────────────────────────────────────────────────────

@router.post("/pre-check", response_model=PreCheckResponse)
async def pre_check_media(request: PreCheckRequest, session: AsyncSession = Depends(get_db_session)):
    """Size, type support and moderation, without creating a share.

    The keyword blocklist runs locally; the cloud moderation API then sees the
    text plus an image (for composites, a contact sheet of every member).
    """
    if is_privacy_lockdown_enabled():
        return PreCheckResponse(blocked=False)

    from utils.keyword_blocklist import check_blocklist

    media_item = await session.get(MediaItem, request.media_id)
    if not media_item or media_item.deleted_at is not None:
        return PreCheckResponse(blocked=False, reason="Media item not found", unsupported_reason="Media item not found")

    media_type = share_media_type(media_item.file_format)
    if media_type is None:
        msg = "This kind of file can't be shared as a link yet."
        return PreCheckResponse(blocked=True, reason=msg, unsupported_reason=msg)

    file_path = Path(media_item.file_path)
    if not file_path.exists():
        msg = "The file for this item is missing from disk."
        return PreCheckResponse(blocked=True, reason=msg, media_type=media_type, unsupported_reason=msg)

    try:
        size_bytes = await estimate_upload_bytes(session, media_item)
    except Exception as e:  # noqa: BLE001
        log.debug("share size estimate failed", error=type(e).__name__)
        size_bytes = None
    if size_bytes is not None and size_bytes > MAX_UPLOAD_BYTES:
        return PreCheckResponse(
            blocked=False,
            reason=too_large_message(size_bytes),
            size_bytes=size_bytes,
            too_large=True,
            media_type=media_type,
        )
    base = {"size_bytes": size_bytes, "media_type": media_type}

    # 1. Gather text + image data based on media type
    texts, member_paths = await _moderation_texts(
        session, media_item, media_type, request.title, request.description,
    )

    # 2. Keyword blocklist (instant, local)
    blocklist_result = check_blocklist(texts)
    if blocklist_result.blocked:
        log.info("pre-check blocked by keyword blocklist", media_id=request.media_id, pattern=blocklist_result.matched_pattern)
        return PreCheckResponse(blocked=True, decision="rejected", reason=GUIDELINES_MESSAGE, **base)

    # 3. Cloud moderation
    token = await _token()
    if not token:
        return PreCheckResponse(blocked=False, **base)

    mod_text_parts = [t for t in texts if t]
    mod_text = "\n".join(mod_text_parts) if mod_text_parts else None

    image_payload = None
    if media_type in ("set", "grid", "layout") and member_paths:
        image_payload = _rasterize_composite_for_moderation(member_paths)
    elif media_type == "image":
        try:
            from utils.image_ops import open_oriented
            img = open_oriented(file_path)
            img.thumbnail((512, 512))
            image_payload = _image_to_base64_payload(img)
            img.close()
        except Exception as e:
            log.debug("pre-check image preparation failed", error=str(e))

    try:
        async with _cloud_client(30.0) as client:
            response = await client.post(
                f"{get_settings().cloud.base_url}/api/shares/pre-check",
                headers=_cloud_headers(token, json_body=True),
                json={"text": mod_text, "imageBase64": image_payload},
            )

        if response.status_code >= 400:
            log.warning("cloud pre-check failed", status=response.status_code)
            return PreCheckResponse(blocked=False, **base)

        result = response.json()
        decision = result.get("decision", "approved")
        nsfw = result.get("nsfw", False)

        reason = None
        if decision == "rejected":
            reason = GUIDELINES_MESSAGE
        elif decision == "quarantined":
            reason = "This content may require review before becoming publicly visible."

        return PreCheckResponse(
            blocked=(decision == "rejected"), decision=decision, nsfw=nsfw, reason=reason, **base,
        )

    except httpx.TimeoutException:
        log.warning("cloud pre-check timed out", media_id=request.media_id)
        return PreCheckResponse(blocked=False, **base)
    except Exception as e:
        log.warning("cloud pre-check failed", media_id=request.media_id, error=str(e))
        return PreCheckResponse(blocked=False, **base)


# Create ───────────────────────────────────────────────────────────────────────

@router.post("", response_model=ShareResponse)
async def share_media(request: ShareRequest, session: AsyncSession = Depends(get_db_session)):
    """Publish a library item as a public link."""
    from utils.keyword_blocklist import check_blocklist

    if is_privacy_lockdown_enabled():
        return ShareResponse(success=False, error=disabled_message("Stimma sharing"), error_code="privacy_lockdown")

    media_item = await session.get(MediaItem, request.media_id)
    if not media_item or media_item.deleted_at is not None:
        return ShareResponse(success=False, error="Media item not found", error_code="not_found")

    media_type = share_media_type(media_item.file_format)
    if media_type is None:
        return ShareResponse(
            success=False, error="This kind of file can't be shared as a link yet.", error_code="unsupported",
        )

    try:
        provenance = parse_provenance(request.provenance)
    except ProvenanceError as e:
        return ShareResponse(success=False, media_type=media_type, error=str(e), error_code="invalid_provenance")

    # Keyword blocklist safety net — all text including composite members and
    # the "how it was made" prompts that would be published.
    texts, _ = await _moderation_texts(session, media_item, media_type, request.title, request.description)
    texts.extend(_provenance_texts(provenance))
    blocklist_result = check_blocklist(texts)
    if blocklist_result.blocked:
        log.warning("share blocked by keyword blocklist", media_id=request.media_id, pattern=blocklist_result.matched_pattern)
        return ShareResponse(success=False, media_type=media_type, error=GUIDELINES_MESSAGE, error_code="blocked")

    token = await _token()
    if not token:
        return ShareResponse(success=False, media_type=media_type, error=SIGNED_OUT_MESSAGE, error_code="signed_out")

    try:
        payload = await build_payload(session, media_item)
    except ShareBuildError as e:
        return ShareResponse(success=False, media_type=media_type, error=str(e), error_code="unsupported")
    except Exception as e:  # noqa: BLE001
        log.error("share payload build failed", media_id=request.media_id, error_type=type(e).__name__)
        return ShareResponse(
            success=False, media_type=media_type, error="This item couldn't be prepared for sharing.", error_code="unsupported",
        )

    sidecar = None
    if provenance is not None:
        try:
            sidecar = await build_public_sidecar(session, provenance)
        except Exception as e:  # noqa: BLE001
            log.warning("share provenance build failed, sharing without it", error_type=type(e).__name__)

    data = _share_form_fields(media_item, payload, request, sidecar)
    if "historySidecar" in data and len(data["historySidecar"].encode("utf-8")) > CLOUD_LIMITS["historySidecar"]:
        log.info("share provenance sidecar over the cloud limit, sharing without it")
        data.pop("historySidecar")
    problem = cloud_limit_problem(payload, data)
    if problem:
        return ShareResponse(success=False, media_type=media_type, error=problem, error_code="too_large")
    total = form_bytes(payload, data)
    if total > MAX_UPLOAD_BYTES:
        return ShareResponse(success=False, media_type=media_type, error=too_large_message(total), error_code="too_large")

    cloud_base_url = get_settings().cloud.base_url
    try:
        async with _cloud_client(300.0) as client:
            response = await client.post(
                f"{cloud_base_url}/api/shares",
                headers=_cloud_headers(token),
                files=payload.files(),
                data=data,
            )
    except httpx.TimeoutException:
        log.error("cloud share timed out", media_id=request.media_id)
        return ShareResponse(
            success=False, media_type=media_type,
            error="The upload timed out. Check your connection and try again.", error_code="cloud",
        )
    except Exception as e:  # noqa: BLE001
        log.error("cloud share failed", media_id=request.media_id, error_type=type(e).__name__)
        return ShareResponse(success=False, media_type=media_type, error=UNAVAILABLE_MESSAGE, error_code="cloud")

    if response.status_code >= 400:
        detail = _cloud_error_detail(response)
        log.warning("cloud share failed", status=response.status_code, error=detail[:200])
        code = {401: "auth_expired", 413: "too_large"}.get(response.status_code, "cloud")
        return ShareResponse(
            success=False, media_type=media_type,
            error=_friendly_cloud_error(response.status_code, detail), error_code=code,
        )

    result = response.json()
    shortcode = result.get("shortcode")
    share_url = result.get("url") or f"{cloud_base_url}/s/{shortcode or ''}"

    from telemetry import get_telemetry_client
    get_telemetry_client().track("media_shared_to_cloud", {"count": 1}, category="share")

    return ShareResponse(
        success=True,
        shortcode=shortcode,
        url=share_url,
        status=result.get("status"),
        media_type=media_type,
    )


def _share_form_fields(media_item: MediaItem, payload, request: ShareRequest, sidecar: Optional[dict]) -> dict[str, str]:
    """Text fields of the cloud multipart form."""
    metadata = dict(payload.metadata)
    metadata["title"] = request.title or ""
    metadata["description"] = request.description or ""
    if request.nsfw_override:
        metadata["nsfwOverride"] = True
    # Moderation inputs (the cloud moderates these; they are not published).
    moderation_prompt = "\n".join(t for t in [media_item.extracted_prompt, payload.moderation_text] if t)
    if moderation_prompt:
        metadata["extractedPrompt"] = moderation_prompt
    if media_item.vlm_caption:
        metadata["vlmCaption"] = media_item.vlm_caption
    data = {"metadata": json.dumps(metadata)}
    if payload.structured_content is not None:
        data["structuredContent"] = json.dumps(payload.structured_content)
    if sidecar is not None:
        data["historySidecar"] = json.dumps(sidecar)
    return data


# Links ────────────────────────────────────────────────────────────────────────

class ShareLink(BaseModel):
    shortcode: str
    url: str
    title: Optional[str] = None
    status: Optional[str] = None
    media_type: Optional[str] = None
    view_count: int = 0
    created_at: Optional[str] = None
    thumbnail_url: Optional[str] = None


class ShareLinksResponse(BaseModel):
    links: list[ShareLink] = []
    total: int = 0
    limit: int = 25
    offset: int = 0
    error: Optional[str] = None


class UpdateLinkRequest(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None


class UpdatedLink(BaseModel):
    shortcode: str
    title: Optional[str] = None
    description: Optional[str] = None


class UpdateLinkResponse(BaseModel):
    success: bool
    link: Optional[UpdatedLink] = None
    error: Optional[str] = None


class DeleteLinkResponse(BaseModel):
    success: bool
    shortcode: Optional[str] = None
    error: Optional[str] = None


def _normalize_link(row: dict, cloud_base_url: str) -> Optional[ShareLink]:
    shortcode = row.get("shortcode")
    if not isinstance(shortcode, str) or not shortcode:
        return None
    created = row.get("createdAt")
    return ShareLink(
        shortcode=shortcode,
        url=row.get("url") or f"{cloud_base_url}/s/{shortcode}",
        title=row.get("title"),
        status=row.get("status"),
        media_type=row.get("mediaType"),
        view_count=int(row.get("viewCount") or 0),
        created_at=str(created) if created is not None else None,
        thumbnail_url=row.get("thumbnailUrl"),
    )


@router.get("/links", response_model=ShareLinksResponse)
async def list_links(
    media_id: Optional[int] = None,
    limit: int = Query(25, ge=1, le=100),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_db_session),
):
    """This account's links: all of them, or only those of one library item."""
    empty = ShareLinksResponse(limit=limit, offset=offset)
    if is_privacy_lockdown_enabled():
        empty.error = disabled_message("Stimma sharing")
        return empty

    params: dict[str, Any] = {"limit": limit, "offset": offset}
    if media_id is not None:
        media_item = await session.get(MediaItem, media_id)
        if media_item is None or not media_item.file_hash:
            return empty
        params["sourceHash"] = media_item.file_hash

    token = await _token()
    if not token:
        empty.error = SIGNED_OUT_MESSAGE
        return empty

    cloud_base_url = get_settings().cloud.base_url
    try:
        async with _cloud_client(15.0) as client:
            response = await client.get(
                f"{cloud_base_url}/api/shares", params=params, headers=_cloud_headers(token),
            )
    except Exception as e:  # noqa: BLE001
        log.warning("list share links failed", error_type=type(e).__name__)
        empty.error = UNAVAILABLE_MESSAGE
        return empty
    if response.status_code >= 400:
        empty.error = _friendly_cloud_error(response.status_code, _cloud_error_detail(response), action="list")
        return empty

    body = response.json() if response.content else {}
    rows = body.get("shares") or []
    links = [link for link in (_normalize_link(r, cloud_base_url) for r in rows if isinstance(r, dict)) if link]
    return ShareLinksResponse(
        links=links,
        total=int(body.get("total") or len(links)),
        limit=int(body.get("limit") or limit),
        offset=int(body.get("offset") or offset),
    )


@router.patch("/links/{shortcode}", response_model=UpdateLinkResponse)
async def update_link(shortcode: str, request: UpdateLinkRequest):
    """Edit a link's title and/or description (only the fields sent)."""
    if is_privacy_lockdown_enabled():
        return UpdateLinkResponse(success=False, error=disabled_message("Stimma sharing"))
    if not _SHORTCODE_RE.match(shortcode):
        return UpdateLinkResponse(success=False, error="That link no longer exists.")
    body = {k: getattr(request, k) for k in ("title", "description") if k in request.model_fields_set}
    if not body:
        return UpdateLinkResponse(success=False, error="Nothing to change.")

    token = await _token()
    if not token:
        return UpdateLinkResponse(success=False, error=SIGNED_OUT_MESSAGE)
    try:
        async with _cloud_client(15.0) as client:
            response = await client.patch(
                f"{get_settings().cloud.base_url}/api/shares/{shortcode}",
                json=body,
                headers=_cloud_headers(token, json_body=True),
            )
    except Exception as e:  # noqa: BLE001
        log.warning("update share link failed", error_type=type(e).__name__)
        return UpdateLinkResponse(success=False, error=UNAVAILABLE_MESSAGE)
    if response.status_code >= 400:
        return UpdateLinkResponse(
            success=False,
            error=_friendly_cloud_error(response.status_code, _cloud_error_detail(response), action="update"),
        )
    result = response.json()
    return UpdateLinkResponse(
        success=True,
        link=UpdatedLink(
            shortcode=result.get("shortcode") or shortcode,
            title=result.get("title"),
            description=result.get("description"),
        ),
    )


@router.delete("/links/{shortcode}", response_model=DeleteLinkResponse)
async def delete_link(shortcode: str):
    """Take a link down."""
    if is_privacy_lockdown_enabled():
        return DeleteLinkResponse(success=False, error=disabled_message("Stimma sharing"))
    if not _SHORTCODE_RE.match(shortcode):
        return DeleteLinkResponse(success=False, error="That link no longer exists.")
    token = await _token()
    if not token:
        return DeleteLinkResponse(success=False, error=SIGNED_OUT_MESSAGE)
    try:
        async with _cloud_client(15.0) as client:
            response = await client.delete(
                f"{get_settings().cloud.base_url}/api/shares/{shortcode}", headers=_cloud_headers(token),
            )
    except Exception as e:  # noqa: BLE001
        log.warning("delete share link failed", error_type=type(e).__name__)
        return DeleteLinkResponse(success=False, error=UNAVAILABLE_MESSAGE)
    if response.status_code >= 400:
        return DeleteLinkResponse(
            success=False,
            error=_friendly_cloud_error(response.status_code, _cloud_error_detail(response), action="delete"),
        )
    return DeleteLinkResponse(success=True, shortcode=shortcode)


# Title suggestion ─────────────────────────────────────────────────────────────

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
    if media_type in ("set", "grid"):
        from container_service import container_title_for_media

        existing_title = await container_title_for_media(
            session, media_id=request.media_id
        )
        if existing_title and existing_title != "Untitled":
            return SuggestTitleResponse(title=existing_title, source="existing")

    # --- Documents that carry their own title: use it as written ---
    own_title = _own_title(media_item, media_type)
    if own_title:
        return SuggestTitleResponse(title=own_title, source="existing")

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


def _own_title(media_item, media_type: str) -> Optional[str]:
    """The title a markdown, set, grid, sprite or package already gives itself, if any."""
    try:
        path = Path(media_item.file_path)
        if media_type == "text":
            from structured_media import read_markdown_file

            doc = read_markdown_file(path) or {}
            title = str((doc.get("frontmatter") or {}).get("title") or "").strip()
            if not title:
                heading = re.search(r"^#\s+(.+?)\s*#*\s*$", doc.get("content") or "", re.MULTILINE)
                title = heading.group(1).strip() if heading else ""
        elif media_type in ("set", "grid"):
            title = str(json.loads(path.read_text(encoding="utf-8")).get("title") or "").strip()
        elif media_type == "sprite":
            from sprite_document import load_sprite_document

            title = str((load_sprite_document(path) or {}).get("title") or "").strip()
        elif media_type == "package":
            manifest = json.loads((path / "stimma-package.json").read_text(encoding="utf-8"))
            title = str(manifest.get("title") or "").strip()
        else:
            return None
    except (OSError, ValueError, TypeError):
        return None
    return title[:100] if title and title.lower() not in {"untitled", "package", "sprite"} else None


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

        config = await get_effective_llm_config("quick_task")
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
        log.info(
            "share title VLM direct response",
            elapsed_s=round(elapsed, 2),
            output_chars=len(result or ""),
            has_error=bool(error),
        )

        if result and not error:
            result = result.strip().strip('"\'').strip()
            words = result.split()
            if 1 <= len(words) <= 8 and len(result) <= 80:
                return SuggestTitleResponse(title=result, source="vlm")
    except Exception as e:
        log.debug(
            "VLM direct title generation failed",
            error_type=type(e).__name__,
        )

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

        config = await get_effective_llm_config("quick_task")
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

        log.info(
            "share title LLM request",
            model=config.get_model(),
            input_chars=len(messages[1]["content"]),
        )
        t0 = _time.monotonic()
        result = await llm_complete_text(config, messages, max_tokens=30, temperature=0.5)
        elapsed = _time.monotonic() - t0
        log.info(
            "share title LLM response",
            elapsed_s=round(elapsed, 2),
            output_chars=len(result or ""),
        )

        result = result.strip().strip('"\'').strip()

        # Validate: 1-8 words, max 80 chars
        words = result.split()
        if 1 <= len(words) <= 8 and len(result) <= 80:
            return SuggestTitleResponse(title=result, source="llm")

    except Exception as e:
        log.warning(
            "share title suggestion failed",
            error_type=type(e).__name__,
        )

    return SuggestTitleResponse()



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
            error=disabled_message("Stimma identity"),
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
                headers=with_cloud_access_headers({"Authorization": f"Bearer {token}"}),
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
            error=disabled_message("Stimma identity"),
        )

    try:
        token = await get_valid_id_token()
    except Exception:
        token = None

    if not token:
        return SetupIdentityResponse(success=False, error="Not signed in to your Stimma account")

    settings = get_settings()
    cloud_base_url = settings.cloud.base_url

    try:
        async with httpx.AsyncClient() as client:
            response = await client.put(
                f"{cloud_base_url}/api/accounts/identity",
                headers=with_cloud_access_headers({
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                }),
                json={"username": request.username},
                timeout=15.0,
            )

        data = response.json()

        if response.status_code >= 400:
            return SetupIdentityResponse(
                success=False,
                error=data.get("error", "Failed to set up identity"),
            )

        # The cached account predates the new username.
        _account_cache.clear()
        return SetupIdentityResponse(
            success=True,
            username=data.get("username"),
        )
    except Exception as e:
        log.warning("setup identity failed", error=str(e))
        return SetupIdentityResponse(success=False, error="Unable to set up identity")
