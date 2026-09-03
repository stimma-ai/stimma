"""Directory browsing for the in-app folder picker.

The desktop shell's native folder dialog only ever sees the machine the
window runs on. When the window is driving a remote server, folder paths
are interpreted on that server, so the picker has to browse the server's
filesystem instead. This is the surface it browses.

Directories only, no files: every caller wants a folder. Names starting
with a dot are hidden, matching what a native picker shows by default.
"""
from __future__ import annotations

import os
import string
import sys
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from core.logging import get_logger

log = get_logger(__name__)

router = APIRouter(prefix="/api/fs", tags=["filesystem"])

# Past this many subfolders, per-entry counts stop being worth the extra
# directory reads (a big volume root can hold thousands).
ITEM_COUNT_MAX_ENTRIES = 400


class DirectoryEntry(BaseModel):
    name: str
    path: str
    is_dir: bool = True
    # Only set on roots: "home" | "place" | "volume"
    kind: Optional[str] = None
    # Number of visible subfolders; omitted when unreadable or skipped.
    item_count: Optional[int] = None


class PathSegment(BaseModel):
    name: str
    path: str


class DirectoryListing(BaseModel):
    # "" for the root-of-roots listing
    path: str
    parent: Optional[str] = None
    segments: List[PathSegment] = []
    entries: List[DirectoryEntry] = []


def _is_hidden(name: str) -> bool:
    return name.startswith(".")


def _place_roots() -> List[DirectoryEntry]:
    """Home plus the standard user folders that exist on this machine."""
    home = Path.home()
    roots = [DirectoryEntry(name="Home", path=str(home), kind="home")]
    for name in ("Desktop", "Pictures", "Movies", "Videos", "Music", "Documents", "Downloads"):
        candidate = home / name
        if candidate.is_dir():
            roots.append(DirectoryEntry(name=name, path=str(candidate), kind="place"))
    return roots


def _volume_roots() -> List[DirectoryEntry]:
    """Mounted drives and volumes, per platform. Best effort, never raises."""
    volumes: List[DirectoryEntry] = []
    seen = set()

    def add(name: str, path: str) -> None:
        if path in seen:
            return
        seen.add(path)
        volumes.append(DirectoryEntry(name=name, path=path, kind="volume"))

    def add_children(parent: str) -> None:
        try:
            with os.scandir(parent) as it:
                for entry in it:
                    if _is_hidden(entry.name):
                        continue
                    try:
                        if entry.is_dir():
                            add(entry.name, entry.path)
                    except OSError:
                        continue
        except OSError:
            return

    if sys.platform == "win32":
        for letter in string.ascii_uppercase:
            drive = f"{letter}:\\"
            if os.path.isdir(drive):
                add(f"{letter}:", drive)
    elif sys.platform == "darwin":
        add_children("/Volumes")
    else:
        add("Filesystem", "/")
        add_children("/mnt")
        add_children("/media")
        user = os.environ.get("USER") or os.environ.get("LOGNAME")
        if user:
            add_children(os.path.join("/media", user))
            add_children(os.path.join("/run/media", user))
    return volumes


def get_root_directories() -> List[DirectoryEntry]:
    return _place_roots() + _volume_roots()


def _same_or_descendant(path: str, root: str) -> bool:
    if path == root:
        return True
    root_with_sep = root if root.endswith(os.sep) else root + os.sep
    return path.startswith(root_with_sep)


def path_segments(path: str, roots: List[DirectoryEntry]) -> List[PathSegment]:
    """Breadcrumbs anchored at the longest matching root.

    The root keeps its display name ("Home" rather than the user's login),
    and every component below it is walkable.
    """
    anchor: Optional[DirectoryEntry] = None
    for root in roots:
        if _same_or_descendant(path, root.path) and (
            anchor is None or len(root.path) > len(anchor.path)
        ):
            anchor = root

    segments: List[PathSegment] = []
    if anchor is not None:
        segments.append(PathSegment(name=anchor.name, path=anchor.path))
        remainder = path[len(anchor.path):].strip(os.sep)
        acc = anchor.path
    else:
        drive, tail = os.path.splitdrive(path)
        top = drive + os.sep if drive else os.sep
        segments.append(PathSegment(name=drive or os.sep, path=top))
        remainder = tail.strip(os.sep)
        acc = top

    for part in [p for p in remainder.split(os.sep) if p]:
        acc = os.path.join(acc, part)
        segments.append(PathSegment(name=part, path=acc))
    return segments


def _count_subdirs(path: str) -> Optional[int]:
    try:
        count = 0
        with os.scandir(path) as it:
            for entry in it:
                if _is_hidden(entry.name):
                    continue
                try:
                    if entry.is_dir():
                        count += 1
                except OSError:
                    continue
        return count
    except OSError:
        return None


def normalize_path(raw: str) -> str:
    """Expand ~ and normalize; reject anything that is not absolute."""
    expanded = os.path.expanduser(raw.strip())
    if not os.path.isabs(expanded):
        raise HTTPException(status_code=400, detail=f"Path must be absolute: {raw}")
    normalized = os.path.normpath(expanded)
    # normpath strips the trailing separator from a drive root on Windows
    # ("C:" is a relative path there), so put it back.
    drive, tail = os.path.splitdrive(normalized)
    if drive and not tail:
        normalized = drive + os.sep
    return normalized


def list_directory(path: Optional[str]) -> DirectoryListing:
    roots = get_root_directories()
    if not path:
        return DirectoryListing(path="", parent=None, segments=[], entries=roots)

    target = normalize_path(path)
    if not os.path.exists(target):
        raise HTTPException(status_code=404, detail=f"Folder not found: {target}")
    if not os.path.isdir(target):
        raise HTTPException(status_code=400, detail=f"Not a folder: {target}")

    entries: List[DirectoryEntry] = []
    try:
        with os.scandir(target) as it:
            for entry in it:
                if _is_hidden(entry.name):
                    continue
                try:
                    if not entry.is_dir():
                        continue
                except OSError:
                    continue
                entries.append(DirectoryEntry(name=entry.name, path=entry.path))
    except PermissionError:
        raise HTTPException(status_code=403, detail=f"Permission denied: {target}")
    except OSError as exc:
        log.warning("fs browse failed", path=target, error=str(exc))
        raise HTTPException(status_code=500, detail=f"Could not read folder: {exc.strerror or exc}")

    entries.sort(key=lambda e: e.name.lower())
    if len(entries) <= ITEM_COUNT_MAX_ENTRIES:
        for entry in entries:
            entry.item_count = _count_subdirs(entry.path)

    parent = os.path.dirname(target)
    if parent == target:
        parent = None

    return DirectoryListing(
        path=target,
        parent=parent,
        segments=path_segments(target, roots),
        entries=entries,
    )


@router.get("/browse", response_model=DirectoryListing)
async def browse_directory(
    path: Optional[str] = Query(default=None, description="Absolute folder path; omit for the roots"),
):
    """List the subfolders of a folder on the machine running this backend."""
    return list_directory(path)
