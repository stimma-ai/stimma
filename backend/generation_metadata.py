"""Canonical builder for ``media_items.generation_metadata``.

This is the SINGLE source of truth for the shape of generation metadata. Every
producer of library media — the generation queue (tool view / agent / flow tool
calls), the composite-media tools (sets, grids, layouts), document creation,
code-save, the edit endpoint, and external-import normalization — MUST build its
metadata through :func:`build_generation_metadata` / :func:`dump_generation_metadata`
rather than assembling its own dict literal.

Why this exists: the metadata used to be hand-rolled in ~19 places with per-task
branches that silently disagreed field-by-field (videos dropped prompt_metadata
and seed, images dropped generator/model, upscale-video dropped the prompt, etc.).
Centralizing the shape here makes those classes of bug impossible: add a field
once and every producer gets it; consumers can rely on every key being present.

The shape is intentionally a flat superset. Fields that don't apply to a given
producer are present with empty/None values (``prompt=""``, ``parameters={}``,
``source_inputs=[]``) so the JSON is uniform regardless of media type or origin.
Consumers should still use ``.get()`` because rows written before this module
existed won't have every key.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Optional


# Bump only with a coordinated migration; consumers branch on this.
GENERATION_METADATA_VERSION = 3

# Keys that are generation INPUTS or transport/internal plumbing — they never
# belong in the flat ``parameters`` dict that describes how the output was made.
# Mirrors (and replaces) the per-branch ``internal_keys`` sets that used to drift.
INTERNAL_PARAM_KEYS = frozenset({
    "prompt",
    "negative_prompt",
    "prompt_metadata",
    "auto_marker_ids",
    "mask_image",
    "input_images",
    "input_videos",
    "input_media_ids",
    "input_video_media_ids",
    "inspired_by_media_id",
    "_ephemeral_run_id",
    "_run_id",
})

# Top-level keys every canonical metadata dict carries (excludes the optional
# ``inspired_by`` and any producer-specific ``extra``). Used by validation/tests.
CANONICAL_KEYS = frozenset({
    "version",
    "source",
    "task_type",
    "tool_id",
    "generator",
    "model",
    "prompt",
    "negative_prompt",
    "parameters",
    "prompt_metadata",
    "source_inputs",
    "lineage_trace",
    "generated_at",
})

_UNSET = object()


def utcnow_z() -> str:
    """ISO-8601 UTC timestamp with a trailing ``Z``. The canonical timestamp."""
    return datetime.utcnow().isoformat() + "Z"


def build_parameters(
    raw_params: Optional[dict] = None,
    *,
    seed: Any = _UNSET,
    generation_time: Optional[float] = None,
    extra: Optional[dict] = None,
) -> dict:
    """Build the flat ``parameters`` dict from a producer's raw params.

    Drops :data:`INTERNAL_PARAM_KEYS` and ``None`` values, then layers on the
    resolved ``seed`` (pass the already-resolved value), the rounded
    ``generation_time``, and any producer-specific ``extra`` fields. Pass the
    full raw param dict — no per-task hardcoded field lists; whatever the
    producer actually used is what gets recorded.
    """
    out = {
        k: v
        for k, v in (raw_params or {}).items()
        if k not in INTERNAL_PARAM_KEYS and v is not None
    }
    if seed is not _UNSET:
        out["seed"] = seed
    if generation_time is not None:
        out["generation_time"] = round(generation_time, 2)
    if extra:
        out.update({k: v for k, v in extra.items() if v is not None})
    return out


def build_generation_metadata(
    *,
    task_type: str,
    source: str = "stimma",
    tool_id: Optional[str] = None,
    generator: Optional[str] = None,
    model: Optional[str] = None,
    prompt: str = "",
    negative_prompt: str = "",
    parameters: Optional[dict] = None,
    prompt_metadata: Any = None,
    source_inputs: Optional[list] = None,
    lineage_trace: Optional[list] = None,
    generated_at: Optional[str] = None,
    inspired_by: Optional[dict] = None,
    extra: Optional[dict] = None,
) -> dict:
    """Build a canonical generation_metadata dict.

    Always returns the full :data:`CANONICAL_KEYS` superset so the stored shape
    is identical across images, videos, documents, sets/grids/layouts, and
    every producing surface. ``inspired_by`` and ``extra`` (e.g. flow context,
    or media-type specifics like a document ``format``) are added when provided.
    """
    if not task_type:
        raise ValueError("generation_metadata requires a task_type")

    meta = {
        "version": GENERATION_METADATA_VERSION,
        "source": source,
        "task_type": task_type,
        "tool_id": tool_id,
        "generator": generator,
        "model": model,
        "prompt": prompt or "",
        "negative_prompt": negative_prompt or "",
        "parameters": parameters if parameters is not None else {},
        "prompt_metadata": prompt_metadata,
        "source_inputs": source_inputs if source_inputs is not None else [],
        "lineage_trace": lineage_trace if lineage_trace is not None else [],
        "generated_at": generated_at or utcnow_z(),
    }
    if inspired_by is not None:
        meta["inspired_by"] = inspired_by
    if extra:
        meta.update(extra)
    return meta


def dump_generation_metadata(**kwargs: Any) -> str:
    """Convenience: :func:`build_generation_metadata` then ``json.dumps``."""
    return json.dumps(build_generation_metadata(**kwargs))


def validate_generation_metadata(meta: dict) -> None:
    """Assert ``meta`` carries the canonical superset. For tests / debug use."""
    missing = CANONICAL_KEYS - set(meta)
    if missing:
        raise ValueError(f"generation_metadata missing canonical keys: {sorted(missing)}")
    if meta.get("version") != GENERATION_METADATA_VERSION:
        raise ValueError(f"unexpected metadata version: {meta.get('version')}")
