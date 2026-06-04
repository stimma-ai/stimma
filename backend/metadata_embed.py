"""
Embed Stimma generation metadata into exported images.

Writes two parallel records on output:

  - An A1111-style `parameters` string for ecosystem interop
    (CivitAI, Forge, Automatic1111, etc.).
  - A `stimma` sidecar JSON object mirroring the STP execute-request
    shape (a single `parameters` object; see docs/TOOLS_PROTOCOL.md).

PNG carries them as `parameters` and `stimma` tEXt chunks.
JPEG carries them as EXIF UserComment (A1111) + MakerNote (Stimma).

The Stimma sidecar is provenance, not a round-trip spec. The export
endpoint (which re-encodes anyway for format/resize/quality) uses PIL.
The drag-out path is hybrid: Python prepares the payload strings here,
and the Tauri-side Rust code does byte-level chunk insertion against
the source file (no re-encode).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Mapping, Optional

import piexif
from PIL import Image
from PIL.PngImagePlugin import PngInfo

log = logging.getLogger(__name__)

SIDECAR_VERSION = 1
STIMMA_CHUNK_KEY = "stimma"
A1111_CHUNK_KEY = "parameters"


def _format_lora(entry: object) -> Optional[tuple[str, float]]:
    if not isinstance(entry, Mapping):
        return None
    name = entry.get("name") or entry.get("lora")
    if not name:
        return None
    try:
        weight = float(entry.get("weight", 1.0))
    except (TypeError, ValueError):
        weight = 1.0
    return Path(str(name)).stem, weight


def build_a1111_string(gen_metadata: Mapping) -> str:
    params = gen_metadata.get("parameters") or {}
    prompt = (gen_metadata.get("prompt") or "").strip()
    negative = (gen_metadata.get("negative_prompt") or "").strip()

    lora_tags = []
    for entry in (params.get("loras") or []):
        norm = _format_lora(entry)
        if norm is None:
            continue
        name, weight = norm
        lora_tags.append(f"<lora:{name}:{weight:g}>")
    if lora_tags:
        prompt = (prompt + " " + " ".join(lora_tags)).strip()

    tail: list[str] = []
    if params.get("steps") is not None:
        tail.append(f"Steps: {params['steps']}")
    if params.get("sampler"):
        tail.append(f"Sampler: {params['sampler']}")
    if params.get("cfg") is not None:
        tail.append(f"CFG scale: {params['cfg']}")
    if params.get("seed") is not None:
        tail.append(f"Seed: {params['seed']}")

    width = params.get("width")
    height = params.get("height")
    if width and height:
        tail.append(f"Size: {width}x{height}")

    model_name = params.get("model")
    if not model_name:
        tool_id = gen_metadata.get("tool_id") or ""
        if ":" in tool_id:
            model_name = tool_id.rsplit(":", 1)[-1]
    if model_name:
        tail.append(f"Model: {model_name}")

    tail.append("Source: Stimma")

    lines: list[str] = []
    if prompt:
        lines.append(prompt)
    if negative:
        lines.append(f"Negative prompt: {negative}")
    lines.append(", ".join(tail))
    return "\n".join(lines)


def build_stimma_sidecar(
    gen_metadata: Mapping,
    hash_lookup: Optional[Mapping[int, str]] = None,
) -> dict:
    """Project Stimma's internal generation_metadata into the STP-mirrored sidecar.

    hash_lookup: optional {media_id: sha256 hex} for substituting internal IDs
    with portable content fingerprints in `parameters`.
    """
    # Single flat parameters object — prompt, inputs, and generation params all
    # live together (matches the STP single-parameter_schema contract).
    params = dict(gen_metadata.get("parameters") or {})
    if gen_metadata.get("prompt"):
        params["prompt"] = gen_metadata["prompt"]
    if gen_metadata.get("negative_prompt"):
        params["negative_prompt"] = gen_metadata["negative_prompt"]

    for src in (gen_metadata.get("source_inputs") or []):
        if not isinstance(src, Mapping):
            continue
        role = src.get("role")
        if not role:
            continue
        media_id = src.get("media_id")
        if media_id is None or not hash_lookup:
            continue
        file_hash = hash_lookup.get(media_id)
        if not file_hash:
            continue
        fingerprint = f"sha256:{file_hash}"
        existing = params.get(role)
        if existing is None:
            params[role] = fingerprint
        elif isinstance(existing, list):
            existing.append(fingerprint)
        else:
            params[role] = [existing, fingerprint]

    output_metadata: dict = {}
    if gen_metadata.get("generation_time") is not None:
        output_metadata["generation_time"] = gen_metadata["generation_time"]
    if params.get("seed") is not None:
        output_metadata["actual_seed"] = params["seed"]

    sidecar: dict = {
        "source": "stimma",
        "version": SIDECAR_VERSION,
        "tool_id": gen_metadata.get("tool_id"),
        "task_type": gen_metadata.get("task_type"),
        "generated_at": gen_metadata.get("generated_at"),
        "parameters": params,
    }
    if output_metadata:
        sidecar["output_metadata"] = output_metadata
    return sidecar


def _encode_user_comment(text: str) -> bytes:
    return b"ASCII\x00\x00\x00" + text.encode("utf-8")


def attach_png_metadata(
    img: Image.Image,
    a1111: Optional[str],
    sidecar: Optional[Mapping],
) -> PngInfo:
    """Build a PngInfo combining A1111 + Stimma chunks with any preserved tEXt from the source."""
    info = PngInfo()
    skip = {A1111_CHUNK_KEY, STIMMA_CHUNK_KEY, "stimmer"}
    for k, v in (img.info or {}).items():
        if k in skip or not isinstance(k, str):
            continue
        if isinstance(v, bytes):
            try:
                v = v.decode("utf-8")
            except UnicodeDecodeError:
                continue
        if not isinstance(v, str):
            continue
        try:
            info.add_text(k, v)
        except Exception:
            pass
    if a1111:
        info.add_text(A1111_CHUNK_KEY, a1111)
    if sidecar is not None:
        info.add_text(STIMMA_CHUNK_KEY, json.dumps(sidecar, separators=(",", ":")))
    return info


def build_jpeg_exif(
    a1111: Optional[str],
    sidecar: Optional[Mapping],
    src_exif_bytes: Optional[bytes] = None,
) -> bytes:
    """Build EXIF bytes carrying A1111 (UserComment) + Stimma JSON (MakerNote).

    UserComment is the ecosystem-standard slot for A1111 parameters and is read
    by CivitAI / Forge / Automatic1111. MakerNote holds the Stimma sidecar JSON
    — most viewers (Finder Get Info, Preview, web galleries) ignore it, so it
    doesn't pollute the user-visible description.
    """
    if src_exif_bytes:
        try:
            exif_dict = piexif.load(src_exif_bytes)
        except Exception:
            exif_dict = {"0th": {}, "Exif": {}, "GPS": {}, "1st": {}, "thumbnail": None}
    else:
        exif_dict = {"0th": {}, "Exif": {}, "GPS": {}, "1st": {}, "thumbnail": None}

    if a1111:
        exif_dict.setdefault("Exif", {})[piexif.ExifIFD.UserComment] = _encode_user_comment(a1111)
    if sidecar is not None:
        exif_dict.setdefault("Exif", {})[piexif.ExifIFD.MakerNote] = (
            b"stimma\x00" + json.dumps(sidecar, separators=(",", ":")).encode("utf-8")
        )
    return piexif.dump(exif_dict)


_INTERNAL_SOURCES = {
    "stimma",
    "stimmer",
    "recipe",
    "agent_v2_create_layout",
    "agent_v2_run_code",
}


def load_generation_metadata(metadata_json: Optional[str]) -> Optional[dict]:
    """Parse generation_metadata JSON and return it iff produced by Stimma.

    Accepts all internal source values (stimma / recipe / agent_v2_*). Rejects
    external (third-party) metadata so we don't overwrite an importer's
    original A1111/ComfyUI-style record with our own re-projection of it.
    """
    if not metadata_json:
        return None
    try:
        data = json.loads(metadata_json)
    except (TypeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    if data.get("source") not in _INTERNAL_SOURCES:
        return None
    # Must minimally have the shape we project from.
    if not data.get("tool_id"):
        return None
    return data
