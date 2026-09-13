"""The ``stimma-package.json`` manifest: format 1.

This is a file format. It outlives the code that writes it, so changes are
additive and versioned by ``format``.

Identity is by content hash. ``media_id`` on a member is a resolution cache
for this profile; the hash is what survives export and import.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

PACKAGE_FORMAT = "stimmapackage"
PACKAGE_EXTENSION = ".stimmapackage"
MANIFEST_NAME = "stimma-package.json"
MANIFEST_FORMAT_VERSION = 1
MEMBERS_DIR = "members"
EXTRAS_DIR = "extras"
INTERNAL_DIR = "_stimma"
COVER_NAME = "index.html"
COVER_SOURCE_NAME = f"{INTERNAL_DIR}/cover.src.html"
KIT_VERSION = 1

# Portability rules every bundle path must satisfy. Windows and macOS collapse
# case, Windows chokes on long paths, and symlinks do not survive a zip.
MAX_PATH_LENGTH = 200
_SAFE_SEGMENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._ @()+-]*$")


class ManifestError(ValueError):
    """The manifest or a bundle path violates the format."""


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def slugify(text: str, fallback: str = "package") -> str:
    text = (text or "").strip().lower()
    text = re.sub(r"[\s_]+", "-", text)
    text = re.sub(r"[^a-z0-9-]", "", text)
    text = re.sub(r"-+", "-", text).strip("-")
    return text[:60] or fallback


def check_bundle_path(rel_path: str) -> str:
    """Validate one bundle-relative POSIX path. Returns it normalized."""
    if not rel_path or rel_path.startswith("/") or rel_path.startswith("\\"):
        raise ManifestError(f"bundle path must be relative: {rel_path!r}")
    if "\\" in rel_path:
        raise ManifestError(f"bundle path must use '/' separators: {rel_path!r}")
    if len(rel_path) > MAX_PATH_LENGTH:
        raise ManifestError(f"bundle path is longer than {MAX_PATH_LENGTH} characters: {rel_path!r}")
    parts = rel_path.split("/")
    for part in parts:
        if part in ("", ".", ".."):
            raise ManifestError(f"bundle path has an empty or dot segment: {rel_path!r}")
        if not _SAFE_SEGMENT_RE.match(part):
            raise ManifestError(
                f"bundle path segment {part!r} has characters that do not travel well; "
                "use letters, digits, '-', '_', '.', ' ', '@', '(', ')', '+'"
            )
    return "/".join(parts)


def check_case_collisions(paths: list[str]) -> None:
    seen: dict[str, str] = {}
    for p in paths:
        key = p.lower()
        if key in seen and seen[key] != p:
            raise ManifestError(
                f"bundle paths {seen[key]!r} and {p!r} differ only by case; "
                "Windows and macOS would collapse them"
            )
        seen[key] = p


def new_manifest(*, title: str, slug: Optional[str] = None) -> dict[str, Any]:
    return {
        "format": MANIFEST_FORMAT_VERSION,
        "kind": "stimma-package",
        "title": title or "Untitled package",
        "slug": slug or slugify(title),
        "created_at": utc_now_iso(),
        "members": [],
        "runs": [],
        "extras": [],
        "cover": {"path": COVER_NAME, "kind": "auto", "kit_version": KIT_VERSION},
        "lineage": {"scope": "none"},
    }


def parse_manifest(raw: Any) -> Optional[dict[str, Any]]:
    """Parse JSON text/bytes/dict into a manifest dict, or None when it is not one."""
    if isinstance(raw, (str, bytes)):
        try:
            payload = json.loads(raw or "{}")
        except (json.JSONDecodeError, TypeError):
            return None
    else:
        payload = raw
    if not isinstance(payload, dict) or payload.get("kind") != "stimma-package":
        return None
    return payload


def validate_manifest(manifest: Any) -> list[str]:
    """Return a list of problems; empty when the manifest is well-formed."""
    errors: list[str] = []
    if not isinstance(manifest, dict) or manifest.get("kind") != "stimma-package":
        return ["kind must be 'stimma-package'"]
    if manifest.get("format") != MANIFEST_FORMAT_VERSION:
        errors.append(f"format must be {MANIFEST_FORMAT_VERSION}, got {manifest.get('format')!r}")
    if not manifest.get("title"):
        errors.append("title is required")
    member_ids: set[str] = set()
    for i, member in enumerate(manifest.get("members") or []):
        where = f"members[{i}]"
        if not isinstance(member, dict):
            errors.append(f"{where}: must be an object")
            continue
        mid = member.get("id")
        if not mid or mid in member_ids:
            errors.append(f"{where}: id missing or duplicate")
        member_ids.add(mid)
        if not member.get("hash"):
            errors.append(f"{where}: hash is required")
        if not member.get("path"):
            errors.append(f"{where}: path is required")
    run_ids: set[str] = set()
    for i, run in enumerate(manifest.get("runs") or []):
        where = f"runs[{i}]"
        if not isinstance(run, dict):
            errors.append(f"{where}: must be an object")
            continue
        rid = run.get("id")
        if not rid or rid in run_ids:
            errors.append(f"{where}: id missing or duplicate")
        run_ids.add(rid)
        recipe = run.get("recipe") or {}
        if not recipe.get("id") or recipe.get("version") is None:
            errors.append(f"{where}: recipe id and version are required")
        for role, member_id in (run.get("inputs") or {}).items():
            if member_id not in member_ids:
                errors.append(f"{where}: input {role!r} names unknown member {member_id!r}")
        if not isinstance(run.get("files"), list):
            errors.append(f"{where}: files must be a list")
    cover = manifest.get("cover") or {}
    if cover and cover.get("kind") not in ("auto", "authored"):
        errors.append("cover.kind must be 'auto' or 'authored'")
    return errors


def iter_manifest_paths(manifest: dict[str, Any]):
    """Yield every bundle-relative file path the manifest declares."""
    for member in manifest.get("members") or []:
        if member.get("path"):
            yield member["path"]
    for run in manifest.get("runs") or []:
        for entry in run.get("files") or []:
            if entry.get("path"):
                yield entry["path"]
    for extra in manifest.get("extras") or []:
        if extra.get("path"):
            yield extra["path"]


def member_by_id(manifest: dict[str, Any], member_id: str) -> Optional[dict[str, Any]]:
    for member in manifest.get("members") or []:
        if member.get("id") == member_id:
            return member
    return None


def run_by_id(manifest: dict[str, Any], run_id: str) -> Optional[dict[str, Any]]:
    for run in manifest.get("runs") or []:
        if run.get("id") == run_id:
            return run
    return None


def resolve_ref(manifest: dict[str, Any], ref: str) -> Optional[dict[str, Any]]:
    """Resolve a cover ``ref`` to ``{"kind": member|run|file, "path": ..., ...}``.

    A ref is a member id, a run id, or a bundle-relative path the manifest
    declares. Anything else is unresolved.
    """
    if not ref:
        return None
    member = member_by_id(manifest, ref)
    if member is not None:
        return {"kind": "member", "path": member["path"], "member": member}
    run = run_by_id(manifest, ref)
    if run is not None:
        return {"kind": "run", "path": run.get("root", ""), "run": run}
    normalized = ref.lstrip("./")
    for path in iter_manifest_paths(manifest):
        if path == normalized:
            return {"kind": "file", "path": path}
    return None


def read_manifest(bundle_dir: Path) -> dict[str, Any]:
    path = Path(bundle_dir) / MANIFEST_NAME
    manifest = parse_manifest(path.read_text(encoding="utf-8"))
    if manifest is None:
        raise ManifestError(f"{path} is not a package manifest")
    return manifest


def write_manifest(bundle_dir: Path, manifest: dict[str, Any]) -> None:
    (Path(bundle_dir) / MANIFEST_NAME).write_text(
        json.dumps(manifest, indent=2, sort_keys=False) + "\n", encoding="utf-8"
    )


def is_package_directory(dir_path: Path) -> bool:
    """A package bundle is a ``.stimmapackage`` directory with a manifest."""
    dir_path = Path(dir_path)
    return (
        dir_path.name.lower().endswith(PACKAGE_EXTENSION)
        and (dir_path / MANIFEST_NAME).exists()
    )


def is_package_format(file_format: Optional[str]) -> bool:
    return (file_format or "").lower() == PACKAGE_FORMAT
