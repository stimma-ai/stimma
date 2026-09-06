"""Authenticated transfers. Handles require both client identity and live unlock."""

import hashlib
import json
import time
import zipfile
from contextvars import ContextVar
from pathlib import Path
from urllib.parse import unquote
from starlette.responses import FileResponse, JSONResponse
from database_registry import get_database_registry
from .access import access, Caller, McpError
from .workspace import media_row

MAX_UPLOAD = 512 * 1024 * 1024
# Agents run for hours; a link handed out at the start of a job should still
# work when the job ends.
LINK_TTL = 4 * 3600

# The origin the current MCP request arrived on (through the desktop relay,
# that is the relay's address). Set by the gateway; links are built on it.
request_origin: ContextVar[str] = ContextVar("mcp_request_origin", default="")


def download_link(caller, media_id):
    """A URL that serves this media with a plain GET, no key or headers.

    The link must work on its own: an assistant usually cannot see its own
    MCP key (the client holds it) and often cannot see the server URL either.
    The handle is a signed capability bound to this connection's live grant
    and an expiry, so it is safe to hand out inline and it dies when the
    connection is locked or removed.
    """
    from datetime import datetime, timezone
    from urllib.parse import quote

    unlock = access.require(caller, activity=False)
    expires = time.time() + LINK_TTL
    handle = access.ref(
        caller,
        "transfer",
        json.dumps(
            {
                "media": media_id,
                "grant": unlock.grant,
                "client": caller.client_id,
                "expires": expires,
            },
            separators=(",", ":"),
        ),
    )
    # The expiry inside the handle is what the server checks. It is repeated
    # in plain sight as a query parameter so an assistant reading the URL
    # knows when it stops working without being told.
    stamp = datetime.fromtimestamp(expires, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    path = f"/mcp/profiles/{caller.profile_id}/download/{quote(handle, safe='')}?expires={stamp}"
    return request_origin.get() + path, handle


def upload_link(caller):
    """A URL that accepts a file with a plain POST, no key or headers.

    Same idea as download_link: the assistant cannot see its own key, so the
    link carries a signed, expiring handle bound to this connection's grant.
    """
    from datetime import datetime, timezone
    from urllib.parse import quote

    unlock = access.require(caller, activity=False)
    expires = time.time() + LINK_TTL
    handle = access.ref(
        caller,
        "upload",
        json.dumps(
            {"grant": unlock.grant, "client": caller.client_id, "expires": expires},
            separators=(",", ":"),
        ),
    )
    stamp = datetime.fromtimestamp(expires, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    path = f"/mcp/profiles/{caller.profile_id}/upload/{quote(handle, safe='')}?expires={stamp}"
    return request_origin.get() + path


HOW_TO_UPLOAD = (
    "POST the file body to upload_url, no key or headers needed beyond the filename: "
    "curl -X POST --data-binary @<file> -H 'X-Filename: <name.ext>' '<upload_url>'. "
    "For an edit or composite, add -H 'X-Stimma-Stage: true' to retain the upload without creating a library asset. "
    "Then call content_update with format file, source_ref set to the returned media_ref, source_refs naming the original library inputs, and a note. "
    "Add target_asset_ref and expected_current_revision to revise an existing asset. Without the stage header, uploads create a new asset immediately. "
    "The link stops working at the UTC time in its expires parameter."
)


async def upload(profile_id, handle_text, request):
    """Store a file behind an upload link; the handle is the whole credential."""
    profile, db, stamp = access.stamp(profile_id)
    probe = Caller(profile_id, "", db.db_guid, stamp)
    try:
        spec = json.loads(access.resolve(probe, unquote(handle_text), "upload"))
        client_id, grant, expires = spec["client"], spec["grant"], spec["expires"]
    except (ValueError, KeyError, TypeError):
        raise McpError(
            "not_found", "This upload link is invalid or expired; call workspace_get for a new one."
        ) from None
    unlock = access.unlocks.get((profile_id, client_id))
    if not unlock or unlock.stamp != stamp or grant != unlock.grant or expires < time.time():
        raise McpError(
            "transfer_expired", "This upload link expired; call workspace_get for a new one."
        )
    caller = Caller(profile_id, client_id, db.db_guid, stamp)
    return await _store_upload(caller, db, request)


async def _store_upload(caller, db, request):
    filename = Path(unquote(request.headers.get("x-filename", "upload"))).name
    stage = request.headers.get("x-stimma-stage", "false").lower()
    if stage not in ("true", "false"):
        raise McpError("invalid_arguments", "X-Stimma-Stage must be true or false.")
    from upload_service import UploadService

    service = UploadService(caller.profile_id)
    service.validate_file(filename)
    content = bytearray()
    async for chunk in request.stream():
        if len(content) + len(chunk) > MAX_UPLOAD:
            raise McpError("upload_too_large", "Upload exceeds 512 MiB.")
        content.extend(chunk)
    access.require(caller)
    media, _ = await service.upload_file(bytes(content), filename, materialize_asset=stage != "true")
    async with db.async_session_maker() as session:
        from asset_service import create_asset_from_media

        asset = None if stage == "true" else await create_asset_from_media(session, media_id=media.id)
        await session.commit()
        return JSONResponse(
            {
                **({"asset_ref": access.ref(caller, "asset", asset.id)} if asset else {}),
                "media_ref": access.ref(caller, "media", media.id),
                "sha256": media.file_hash,
            }
        )


async def offer(caller, reference, session):
    media = await media_row(caller, reference, session)
    url, handle = download_link(caller, media.id)
    return {
        "transfer_handle": handle,
        "media_ref": access.ref(caller, "media", media.id),
        "filename": Path(media.file_path).name
        + (".zip" if Path(media.file_path).is_dir() else ""),
        "expires_in_seconds": LINK_TTL,
        "download_url": url,
        "how_to_download": "The file is not on your machine yet. Plain GET, no headers or key needed: curl -o '<filename>' '<download_url>'. The same URL opens directly in a browser. It stops working at the UTC time in its expires parameter (4 hours from now).",
    }


async def download(profile_id, handle_text):
    """Serve the file behind a media_export handle. The handle is the whole
    credential: it is signed, names the connection and its live grant, and
    expires. Locking or removing the connection kills it."""
    profile, db, stamp = access.stamp(profile_id)
    probe = Caller(profile_id, "", db.db_guid, stamp)
    try:
        spec = json.loads(access.resolve(probe, unquote(handle_text), "transfer"))
        client_id, grant, expires, media_id = (
            spec["client"], spec["grant"], spec["expires"], spec["media"]
        )
    except (ValueError, KeyError, TypeError):
        raise McpError(
            "not_found", "This download link is invalid or expired; call media_export again."
        ) from None
    unlock = access.unlocks.get((profile_id, client_id))
    if (
        not unlock
        or unlock.stamp != stamp
        or grant != unlock.grant
        or expires < time.time()
    ):
        raise McpError(
            "transfer_expired",
            "This download link expired; call media_export again for a new one.",
        )
    caller = Caller(profile_id, client_id, db.db_guid, stamp)
    async with db.async_session_maker() as session:
        media = await media_row(caller, access.ref(caller, "media", media_id), session)
        path = Path(media.file_path)
        if not path.exists():
            raise McpError("not_found", "The original file is unavailable.")
        if path.is_dir():
            path = _bundle(profile_id, media, path)
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        return FileResponse(
            path,
            filename=path.name,
            headers={
                "Cache-Control": "no-store",
                "X-Content-SHA256": digest,
                "X-Content-Type-Options": "nosniff",
            },
        )


def _bundle(profile_id, media, path):
    from app_dirs import get_profile_dir

    cache = get_profile_dir(profile_id) / "mcp-exports"
    cache.mkdir(parents=True, exist_ok=True)
    bundle = cache / f"{media.file_hash}.zip"
    if not bundle.exists():
        import os, uuid

        temporary = cache / f"{uuid.uuid4().hex}.tmp"
        try:
            with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as archive:
                for member in sorted(path.rglob("*")):
                    if member.is_symlink():
                        raise McpError(
                            "unsupported_bundle", "Bundle contains a symbolic link."
                        )
                    if member.is_file():
                        archive.write(member, member.relative_to(path))
            os.replace(temporary, bundle)
        finally:
            temporary.unlink(missing_ok=True)
    return bundle


async def handle(caller, suffix, request):
    unlock = access.require(caller)
    db = get_database_registry().get_database(caller.profile_id)
    if suffix == ["upload"] and request.method == "POST":
        return await _store_upload(caller, db, request)
    raise McpError("not_found", "No such endpoint. Uploads are POST /upload with the connection key; downloads use the link from media_export.")
