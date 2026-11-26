"""Element checkouts in a chat workspace: ``elements/<slug>/``.

The agent edits ``element.json``, ``ELEMENT.md`` and ``files/`` with its
ordinary file tools. ``media/`` holds read-only copies of the element's
current media (``<key>.<ext>``) to look at; they are copies rather than links
so nothing written in the workspace can reach library files, and so the file
tools, which stay inside the workspace, can open them. ``.stimma-element.json``
records which element and revision the checkout came from.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from elements import template
from elements.bundle import (
    ElementConflict,
    ElementError,
    SaveResult,
    bundle_manifest,
    commit_element,
    copy_bundle_to,
    element_asset,
    slot_media,
    visible_manifest,
)
from elements.manifest import (
    FILES_DIR,
    INSTRUCTIONS_NAME,
    MANIFEST_NAME,
    SLUG_RE,
    new_manifest,
    read_manifest,
    slugify,
    starter_instructions,
    write_manifest,
)

ELEMENTS_MOUNT = "elements"
CHECKOUT_META = ".stimma-element.json"
MEDIA_DIR = "media"


@dataclass
class Checkout:
    path: str  # workspace-relative, e.g. "elements/mira"
    directory: Path
    asset_id: Optional[int]
    base_revision_id: Optional[int]
    refreshed: bool = True
    conflict: Optional[str] = None
    notes: list[str] = field(default_factory=list)


CHECKOUT_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,80}$")


def elements_root(workspace_dir: str | Path) -> Path:
    """``elements/`` in the workspace; a link or anything resolving outside it is refused."""
    workspace = Path(workspace_dir).resolve()
    root = Path(workspace_dir) / ELEMENTS_MOUNT
    if root.is_symlink() or (root.exists() and (not root.is_dir() or not root.resolve().is_relative_to(workspace))):
        raise ElementError(f"{ELEMENTS_MOUNT}/ in this workspace must be a plain folder")
    return root


def _contained(workspace_dir: str | Path, directory: Path) -> Path:
    """A checkout folder that is a real folder inside ``elements/``, with real files."""
    root = elements_root(workspace_dir).resolve() if elements_root(workspace_dir).exists() else None
    if directory.is_symlink() or (root is not None and directory.exists() and directory.resolve().parent != root):
        raise ElementError(f"{ELEMENTS_MOUNT}/{directory.name}/ must be a plain folder")
    for name in (MANIFEST_NAME, INSTRUCTIONS_NAME, CHECKOUT_META, FILES_DIR, MEDIA_DIR):
        if (directory / name).is_symlink():
            raise ElementError(f"{ELEMENTS_MOUNT}/{directory.name}/{name} must not be a link")
    return directory


def readonly_error(parts: list[str]) -> Optional[str]:
    """Error text when a workspace path is inside an element's read-only parts."""
    if len(parts) >= 3 and parts[0] == ELEMENTS_MOUNT:
        if parts[2] == MEDIA_DIR:
            return (
                f"Error: {'/'.join(parts[:3])}/ holds read-only copies of the element's media for viewing. "
                "To change which media the element uses, edit media_menu in element.json "
                "(asset_id of a library asset), then save with element(action=\"save\")."
            )
        if parts[2] == CHECKOUT_META:
            return f"Error: {'/'.join(parts[:3])} is managed by the app and can't be edited."
    return None


def _read_meta(directory: Path) -> Optional[dict[str, Any]]:
    try:
        data = json.loads((directory / CHECKOUT_META).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _write_meta(directory: Path, *, asset_id: Optional[int], base_revision_id: Optional[int]) -> None:
    meta = {
        "asset_id": asset_id,
        "base_revision_id": base_revision_id,
        "content_hash": content_hash(directory),
        "synced_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
    }
    (directory / CHECKOUT_META).write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")


def content_hash(directory: Path) -> str:
    """Digest of the editable parts, to tell whether the agent changed anything."""
    digest = hashlib.sha256()
    paths = [directory / MANIFEST_NAME, directory / INSTRUCTIONS_NAME]
    files = directory / FILES_DIR
    if files.is_dir():
        paths += sorted(p for p in files.rglob("*") if p.is_file())
    for path in paths:
        rel = path.relative_to(directory).as_posix().encode()
        digest.update(len(rel).to_bytes(4, "big") + rel)
        try:
            digest.update(path.read_bytes())
        except FileNotFoundError:
            digest.update(b"\0missing")
    return digest.hexdigest()


def is_modified(directory: Path) -> bool:
    meta = _read_meta(directory)
    return meta is None or meta.get("content_hash") != content_hash(directory)


def _clear_media(directory: Path) -> None:
    media_dir = directory / MEDIA_DIR
    if not media_dir.exists() and not media_dir.is_symlink():
        return
    if media_dir.is_symlink() or media_dir.is_file():
        media_dir.unlink()
        return
    for path in media_dir.rglob("*"):
        try:
            os.chmod(path, stat.S_IRUSR | stat.S_IWUSR | (stat.S_IXUSR if path.is_dir() else 0))
        except OSError:
            pass
    os.chmod(media_dir, stat.S_IRWXU)
    shutil.rmtree(media_dir)


async def refresh_media(session: AsyncSession, directory: Path, manifest: dict[str, Any]) -> list[str]:
    """Rewrite ``media/`` as read-only copies of each slot's current media."""
    notes: list[str] = []
    _clear_media(directory)
    media_dir = directory / MEDIA_DIR
    media_dir.mkdir(parents=True)
    for entry in manifest.get("media_menu") or []:
        key = entry.get("key")
        item = await slot_media(session, entry)
        source = Path(item.file_path) if item is not None else None
        if item is None or not source.is_file():
            notes.append(f"media '{key}' is not in the library any more")
            continue
        ext = (item.file_format or source.suffix.lstrip(".") or "bin").lower()
        target = media_dir / f"{key}.{ext}"
        shutil.copyfile(source, target)
        os.chmod(target, stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
    os.chmod(media_dir, stat.S_IRUSR | stat.S_IXUSR | stat.S_IRGRP | stat.S_IXGRP)
    return notes


def _checkout_dir_for(workspace_dir: str | Path, slug: str, asset_id: int) -> Path:
    """``elements/<slug>/``, or ``<slug>-<id>`` when another element already holds the slug."""
    root = elements_root(workspace_dir)
    if not CHECKOUT_NAME_RE.match(slug):
        slug = slugify(slug)
    for candidate in (root / slug, root / f"{slug}-{asset_id}"):
        if candidate.is_symlink():
            continue
        meta = _read_meta(candidate) if candidate.exists() else None
        if not candidate.exists() or (meta is not None and meta.get("asset_id") == asset_id):
            return _contained(workspace_dir, candidate)
    raise ElementError(f"{ELEMENTS_MOUNT}/{slug}/ is already in use in this workspace")


def find_checkout(workspace_dir: str | Path, asset_id: int) -> Optional[Path]:
    root = elements_root(workspace_dir)
    if not root.is_dir():
        return None
    for child in sorted(root.iterdir()):
        meta = _read_meta(child) if child.is_dir() and not child.is_symlink() else None
        if meta is not None and meta.get("asset_id") == asset_id:
            return _contained(workspace_dir, child)
    return None


def list_checkouts(workspace_dir: str | Path) -> dict[int, str]:
    root = elements_root(workspace_dir)
    out: dict[int, str] = {}
    if root.is_dir():
        for child in sorted(root.iterdir()):
            meta = _read_meta(child) if child.is_dir() and not child.is_symlink() else None
            if meta is not None and isinstance(meta.get("asset_id"), int):
                out[meta["asset_id"]] = f"{ELEMENTS_MOUNT}/{child.name}"
    return out


async def open_element(session: AsyncSession, workspace_dir: str | Path, asset_id: int) -> Checkout:
    """Materialize or refresh ``elements/<slug>/`` for an element.

    Unsaved edits are never overwritten: if the element moved on while the
    checkout has edits, the result carries a conflict notice instead.
    """
    asset, revision, media = await element_asset(session, asset_id)
    manifest = await visible_manifest(session, revision.id, bundle_manifest(media))
    directory = find_checkout(workspace_dir, asset.id) or _checkout_dir_for(
        workspace_dir, manifest.get("slug") or slugify(asset.title or ""), asset.id
    )
    rel = f"{ELEMENTS_MOUNT}/{directory.name}"
    meta = _read_meta(directory) if directory.exists() else None
    if meta is not None and is_modified(directory):
        notes = await refresh_media(session, directory, manifest)
        if meta.get("base_revision_id") != revision.id:
            return Checkout(
                rel, directory, asset.id, meta.get("base_revision_id"), refreshed=False, notes=notes,
                conflict=(
                    f"{rel}/ has unsaved edits, and '{asset.title}' was changed elsewhere since they started "
                    f"(now version {revision.revision_number}). The workspace copy was left as it is. "
                    "Saving it will be refused unless you pass force=true, which replaces the newer version; "
                    f"to start over from the newest version, delete {rel}/ and open it again."
                ),
            )
        return Checkout(rel, directory, asset.id, revision.id, refreshed=False, notes=notes)
    await copy_bundle_to(media, directory)
    edited = await visible_manifest(session, revision.id, read_manifest(directory))
    if asset.title:
        edited["name"] = asset.title
    write_manifest(directory, edited)
    notes = await refresh_media(session, directory, manifest)
    _write_meta(directory, asset_id=asset.id, base_revision_id=revision.id)
    return Checkout(rel, directory, asset.id, revision.id, notes=notes)


def init_element(
    workspace_dir: str | Path, *, slug: Optional[str], name: str, kind: str = "", description: str = ""
) -> Checkout:
    slug = (slug or slugify(name)).strip().lower()
    if not SLUG_RE.match(slug):
        raise ElementError("slug must be lowercase letters, digits and '-' (for example 'mira')")
    directory = elements_root(workspace_dir) / slug
    if directory.exists() or directory.is_symlink():
        raise ElementError(f"{ELEMENTS_MOUNT}/{slug}/ already exists; pick another slug or edit that one")
    directory.mkdir(parents=True)
    _contained(workspace_dir, directory)
    manifest = new_manifest(name, kind, description, slug=slug)
    write_manifest(directory, manifest)
    (directory / INSTRUCTIONS_NAME).write_text(
        starter_instructions(manifest["name"], kind, description), encoding="utf-8"
    )
    (directory / FILES_DIR).mkdir()
    (directory / CHECKOUT_META).write_text(
        json.dumps({"asset_id": None, "base_revision_id": None, "content_hash": None}, indent=2) + "\n",
        encoding="utf-8",
    )
    return Checkout(f"{ELEMENTS_MOUNT}/{slug}", directory, None, None)


def resolve_checkout(workspace_dir: str | Path, slug: str) -> Path:
    slug = (slug or "").strip().strip("/")
    if slug.startswith(f"{ELEMENTS_MOUNT}/"):
        slug = slug[len(ELEMENTS_MOUNT) + 1:]
    if not CHECKOUT_NAME_RE.match(slug):
        raise ElementError("slug names a folder under elements/: lowercase letters, digits and '-', for example 'mira'")
    directory = elements_root(workspace_dir) / slug
    if directory.is_symlink():
        raise ElementError(f"{ELEMENTS_MOUNT}/{slug}/ must be a plain folder")
    if not directory.is_dir():
        raise ElementError(
            f"{ELEMENTS_MOUNT}/{slug}/ doesn't exist. Use element(action=\"init\") to start one "
            "or element(action=\"open\") to check out a saved one."
        )
    return _contained(workspace_dir, directory)


async def save_checkout(
    session: AsyncSession,
    workspace_dir: str | Path,
    slug: str,
    *,
    profile_id: str,
    force: bool = False,
    project_id: Optional[int] = None,
    note: Optional[str] = None,
) -> tuple[SaveResult, Checkout]:
    directory = resolve_checkout(workspace_dir, slug)
    meta = _read_meta(directory) or {}
    asset_id = meta.get("asset_id") if isinstance(meta.get("asset_id"), int) else None
    result = await commit_element(
        session,
        profile_id=profile_id,
        source_dir=directory,
        asset_id=asset_id,
        base_revision_id=meta.get("base_revision_id"),
        force=force,
        note=note,
        origin_type="chat_element",
        project_id=project_id,
    )
    # The checkout now matches the saved revision (listed files, defaults filled in).
    write_manifest(directory, {**result.manifest, "name": result.asset.title or result.manifest["name"]})
    notes = await refresh_media(session, directory, result.manifest)
    _write_meta(directory, asset_id=result.asset.id, base_revision_id=result.revision.id)
    return result, Checkout(
        f"{ELEMENTS_MOUNT}/{directory.name}", directory, result.asset.id, result.revision.id, notes=notes
    )


def render_for_chat(directory: Path, context: Optional[dict[str, Any]] = None) -> template.RenderedTemplate:
    try:
        text = (directory / INSTRUCTIONS_NAME).read_text(encoding="utf-8")
    except (FileNotFoundError, UnicodeDecodeError):
        text = ""
    return template.render(text, {"surface": "chat", **(context or {})})


__all__ = [
    "CHECKOUT_META",
    "Checkout",
    "ELEMENTS_MOUNT",
    "ElementConflict",
    "ElementError",
    "MEDIA_DIR",
    "find_checkout",
    "init_element",
    "is_modified",
    "list_checkouts",
    "open_element",
    "readonly_error",
    "render_for_chat",
    "save_checkout",
]
