"""Authenticated transfers. Handles require both client identity and live unlock."""

import hashlib
import json
import time
import zipfile
from pathlib import Path
from urllib.parse import unquote
from starlette.responses import FileResponse, JSONResponse
from database_registry import get_database_registry
from .access import access, McpError
from .workspace import media_row

MAX_UPLOAD = 512 * 1024 * 1024


async def offer(caller, reference, session):
    unlock = access.require(caller)
    media = await media_row(caller, reference, session)
    handle = access.ref(
        caller,
        "transfer",
        json.dumps(
            {
                "media": media.id,
                "grant": unlock.grant,
                "client": caller.client_id,
                "expires": time.time() + 900,
            },
            separators=(",", ":"),
        ),
    )
    return {
        "transfer_handle": handle,
        "media_ref": access.ref(caller, "media", media.id),
        "filename": Path(media.file_path).name
        + (".zip" if Path(media.file_path).is_dir() else ""),
        "expires_in_seconds": 900,
        "delivery": "authenticated_download",
    }


async def handle(caller, suffix, request):
    unlock = access.require(caller)
    db = get_database_registry().get_database(caller.profile_id)
    if suffix == ["upload"] and request.method == "POST":
        filename = Path(unquote(request.headers.get("x-filename", "upload"))).name
        from upload_service import UploadService

        service = UploadService(caller.profile_id)
        service.validate_file(filename)
        content = bytearray()
        async for chunk in request.stream():
            if len(content) + len(chunk) > MAX_UPLOAD:
                raise McpError("upload_too_large", "Upload exceeds 512 MiB.")
            content.extend(chunk)
        access.require(caller)
        media, _ = await service.upload_file(bytes(content), filename)
        async with db.async_session_maker() as session:
            from asset_service import create_asset_from_media

            asset = await create_asset_from_media(session, media_id=media.id)
            await session.commit()
            return JSONResponse(
                {
                    "asset_ref": access.ref(caller, "asset", asset.id),
                    "media_ref": access.ref(caller, "media", media.id),
                    "sha256": hashlib.sha256(content).hexdigest(),
                }
            )
    if (
        len(suffix) == 2
        and suffix[0] == "download"
        and request.method in ("GET", "HEAD")
    ):
        try:
            spec = json.loads(access.resolve(caller, unquote(suffix[1]), "transfer"))
        except (ValueError, KeyError):
            raise McpError("not_found", "Transfer is unavailable.") from None
        if (
            spec["grant"] != unlock.grant
            or spec["client"] != caller.client_id
            or spec["expires"] < time.time()
        ):
            raise McpError(
                "transfer_expired",
                "Request a fresh export handle; media will not be regenerated.",
            )
        async with db.async_session_maker() as session:
            media = await media_row(
                caller, access.ref(caller, "media", spec["media"]), session
            )
            path = Path(media.file_path)
            if not path.exists():
                raise McpError("not_found", "The original file is unavailable.")
            if path.is_dir():
                from app_dirs import get_profile_dir

                cache = get_profile_dir(caller.profile_id) / "mcp-exports"
                cache.mkdir(parents=True, exist_ok=True)
                bundle = cache / f"{media.file_hash}.zip"
                if not bundle.exists():
                    import os, uuid

                    temporary = cache / f"{uuid.uuid4().hex}.tmp"
                    try:
                        with zipfile.ZipFile(
                            temporary, "w", zipfile.ZIP_DEFLATED
                        ) as archive:
                            for member in sorted(path.rglob("*")):
                                if member.is_symlink():
                                    raise McpError(
                                        "unsupported_bundle",
                                        "Bundle contains a symbolic link.",
                                    )
                                if member.is_file():
                                    archive.write(member, member.relative_to(path))
                        os.replace(temporary, bundle)
                    finally:
                        temporary.unlink(missing_ok=True)
                path = bundle
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
    raise McpError("not_found", "Transfer endpoint is unavailable.")
