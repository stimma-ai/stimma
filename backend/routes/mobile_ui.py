"""Authenticated, immutable frontend delivery for the mobile shell.

The remote listener's ServingGate authenticates these routes like all app APIs.
They are profile independent so a shell can load before selecting a library.
"""
import json
import re

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response

from mobile_ui_package import package_directory

router = APIRouter(prefix="/api/mobile-ui", tags=["mobile-ui"])
HASH = re.compile(r"^[a-f0-9]{64}$")


def _not_modified(request: Request, etag: str) -> bool:
    return any(value.strip().removeprefix("W/") in (etag, "*")
               for value in request.headers.get("if-none-match", "").split(","))


@router.get("/manifest")
def manifest(request: Request):
    directory = package_directory()
    try:
        snapshot = json.loads((directory / "manifest.json").read_bytes())
        digest = snapshot["hash"]
        if not isinstance(digest, str) or not HASH.fullmatch(digest):
            raise ValueError("Invalid package hash")
        if not (directory / "packages" / f"{digest}.tar.gz").is_file():
            raise ValueError("Missing package archive")
    except (OSError, ValueError, KeyError, TypeError):
        raise HTTPException(503, "Mobile UI package is not available") from None
    etag = f'"{digest}"'
    headers = {"ETag": etag, "Cache-Control": "private, no-cache"}
    if _not_modified(request, etag):
        return Response(status_code=304, headers=headers)
    return JSONResponse(snapshot, headers=headers)


@router.get("/packages/{digest}.tar.gz")
def package(digest: str, request: Request):
    if not HASH.fullmatch(digest):
        raise HTTPException(404, "UI package not found")
    path = package_directory() / "packages" / f"{digest}.tar.gz"
    if path.is_symlink() or not path.is_file():
        raise HTTPException(404, "UI package not found")
    etag = f'"{digest}"'
    headers = {"ETag": etag, "Cache-Control": "private, max-age=31536000, immutable"}
    if _not_modified(request, etag):
        return Response(status_code=304, headers=headers)
    return FileResponse(path, media_type="application/gzip", headers=headers)
