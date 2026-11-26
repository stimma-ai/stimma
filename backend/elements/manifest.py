"""The ``element.json`` manifest (format 1) and the ``.stimmaelement`` bundle layout.

This is a file format: changes are additive and versioned by ``format``.

Bundle::

    <object>.stimmaelement/
      element.json   thin manifest (this module)
      ELEMENT.md     instructions, with optional block conditionals (template.py)
      _tile.png      library card image, made from the cover at save time
      files/         companion files owned by the revision

The Asset title owns the element's name once it exists; ``name`` in the
manifest is what the last save wrote.
"""

from __future__ import annotations

import json
import re
from pathlib import Path, PurePosixPath
from typing import Any, Optional

from packages.manifest import slugify as _slugify

ELEMENT_FORMAT = "stimmaelement"
ELEMENT_EXTENSION = ".stimmaelement"
ELEMENT_ASSET_TYPE = "element"
MANIFEST_NAME = "element.json"
INSTRUCTIONS_NAME = "ELEMENT.md"
FILES_DIR = "files"
TILE_NAME = "_tile.png"
MANIFEST_FORMAT_VERSION = 1

STATUSES = ("canonical", "candidate", "rejected")
KEY_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,59}$")
_SAFE_SEGMENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._ @()+-]*$")
MAX_FILE_PATH = 200


class ElementManifestError(ValueError):
    pass


def slugify(text: str) -> str:
    return _slugify(text, fallback="element")


def is_element_format(file_format: Optional[str]) -> bool:
    return (file_format or "").lower() == ELEMENT_FORMAT


def new_manifest(name: str, kind: str = "", description: str = "", slug: Optional[str] = None) -> dict[str, Any]:
    name = (name or "").strip() or "Untitled element"
    return {
        "format": MANIFEST_FORMAT_VERSION,
        "name": name,
        "slug": slug or slugify(name),
        "kind": (kind or "").strip().lower(),
        "description": (description or "").strip(),
        "tags": [],
        "cover_member_key": None,
        "media_menu": [],
        "loras": [],
        "files": [],
    }


def check_file_path(path: Any) -> str:
    """A companion file path, normalized; must live under ``files/``."""
    if not isinstance(path, str) or not path:
        raise ElementManifestError("a file path is missing")
    if "\\" in path or path.startswith("/"):
        raise ElementManifestError(f"file path {path!r} must be relative and use '/'")
    parts = PurePosixPath(path).parts
    if len(parts) < 2 or parts[0] != FILES_DIR:
        raise ElementManifestError(f"file path {path!r} must be inside files/")
    if len(path) > MAX_FILE_PATH:
        raise ElementManifestError(f"file path {path!r} is longer than {MAX_FILE_PATH} characters")
    for segment in parts[1:]:
        if segment in (".", "..") or not _SAFE_SEGMENT_RE.match(segment):
            raise ElementManifestError(
                f"file path {path!r} has an unsafe name {segment!r}; use letters, digits, '.', '-', '_' or spaces"
            )
    return "/".join(parts)


def _int_or_none(value: Any) -> Optional[int]:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def validate_manifest(manifest: Any) -> tuple[list[str], list[str]]:
    """(errors, warnings) in plain words. Errors block a save."""
    errors: list[str] = []
    warnings: list[str] = []
    if not isinstance(manifest, dict):
        return ["element.json must be a JSON object"], []
    if manifest.get("format", MANIFEST_FORMAT_VERSION) != MANIFEST_FORMAT_VERSION:
        errors.append(f"element.json format must be {MANIFEST_FORMAT_VERSION}")
    if not isinstance(manifest.get("name"), str) or not manifest["name"].strip():
        errors.append("name is required")
    slug = manifest.get("slug")
    if slug is not None and (not isinstance(slug, str) or not SLUG_RE.match(slug)):
        errors.append("slug must be lowercase letters, digits and '-'")
    for field in ("kind", "description"):
        if manifest.get(field) is not None and not isinstance(manifest.get(field), str):
            errors.append(f"{field} must be text")
    tags = manifest.get("tags", [])
    if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
        errors.append("tags must be a list of text")

    menu = manifest.get("media_menu", [])
    keys: set[str] = set()
    if not isinstance(menu, list):
        errors.append("media_menu must be a list")
        menu = []
    for index, entry in enumerate(menu):
        where = f"media_menu[{index}]"
        if not isinstance(entry, dict):
            errors.append(f"{where} must be an object")
            continue
        key = entry.get("key")
        if not isinstance(key, str) or not KEY_RE.match(key):
            errors.append(f"{where}.key must be a short lowercase name like 'face-front'")
        elif key in keys:
            errors.append(f"media key '{key}' is used twice")
        else:
            keys.add(key)
            where = f"media '{key}'"
        linked = _int_or_none(entry.get("asset_id"))
        embedded = _int_or_none(entry.get("embedded_media_id"))
        if (linked is None) == (embedded is None):
            errors.append(f"{where} needs an asset_id (a library asset)")
        status = entry.get("status", "canonical")
        if status not in STATUSES:
            errors.append(f"{where}.status must be one of {', '.join(STATUSES)}")
        labels = entry.get("labels", [])
        if not isinstance(labels, list) or not all(isinstance(t, str) for t in labels):
            errors.append(f"{where}.labels must be a list of text")
        if "conditional" in entry and not isinstance(entry["conditional"], bool):
            errors.append(f"{where}.conditional must be true or false")
        for text_field in ("title", "usage_hint", "provenance"):
            if entry.get(text_field) is not None and not isinstance(entry[text_field], str):
                errors.append(f"{where}.{text_field} must be text")

    cover = manifest.get("cover_member_key")
    if cover is not None and cover not in keys:
        errors.append(f"cover_member_key '{cover}' does not match any media key")

    loras = manifest.get("loras", [])
    lora_keys: set[str] = set()
    if not isinstance(loras, list):
        errors.append("loras must be a list")
        loras = []
    for index, entry in enumerate(loras):
        where = f"loras[{index}]"
        if not isinstance(entry, dict):
            errors.append(f"{where} must be an object")
            continue
        key = entry.get("key")
        if not isinstance(key, str) or not KEY_RE.match(key):
            errors.append(f"{where}.key must be a short lowercase name like 'mira-klein-v2'")
        elif key in lora_keys:
            errors.append(f"LoRA key '{key}' is used twice")
        else:
            lora_keys.add(key)
            where = f"LoRA '{key}'"
        if not entry.get("fingerprint") and not entry.get("display_name"):
            errors.append(f"{where} needs a fingerprint or a display_name")
        weight = entry.get("default_weight")
        if weight is not None and (isinstance(weight, bool) or not isinstance(weight, (int, float))):
            errors.append(f"{where}.default_weight must be a number")

    files = manifest.get("files", [])
    paths: set[str] = set()
    if not isinstance(files, list):
        errors.append("files must be a list")
        files = []
    for index, entry in enumerate(files):
        if not isinstance(entry, dict):
            errors.append(f"files[{index}] must be an object")
            continue
        try:
            path = check_file_path(entry.get("path"))
        except ElementManifestError as exc:
            errors.append(str(exc))
            continue
        if path.lower() in paths:
            errors.append(f"file '{path}' is listed twice")
        paths.add(path.lower())
    return errors, warnings


def read_manifest(directory: Path) -> dict[str, Any]:
    path = Path(directory) / MANIFEST_NAME
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ElementManifestError(f"{MANIFEST_NAME} is missing") from exc
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ElementManifestError(f"{MANIFEST_NAME} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ElementManifestError(f"{MANIFEST_NAME} must be a JSON object")
    return data


def write_manifest(directory: Path, manifest: dict[str, Any]) -> None:
    (Path(directory) / MANIFEST_NAME).write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def parse_manifest(raw: Any) -> Optional[dict[str, Any]]:
    if isinstance(raw, dict):
        return raw
    try:
        data = json.loads(raw or "")
    except (json.JSONDecodeError, TypeError):
        return None
    return data if isinstance(data, dict) else None


def starter_instructions(name: str, kind: str = "", description: str = "") -> str:
    lines = [f"# {name}", ""]
    if description:
        lines += [description, ""]
    lines += [
        "## Always the same",
        "- ",
        "",
        "## Free to change",
        "- ",
        "",
    ]
    return "\n".join(lines)
