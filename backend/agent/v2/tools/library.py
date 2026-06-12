"""Search, retrieve, save, and browse the media library."""

import hashlib
import json
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_, and_, delete, func, Integer, literal

from ..tools_registry import tool, ToolParameter

from board_service import serialize_board
from config import get_settings
from core.logging import get_logger
from core.profile_context import get_current_profile
from project_service import attach_media_to_project, infer_project_id_from_workspace_path
from providers.registry import ProviderRegistry
from database import (
    MediaItem, MediaLineage, Tag, MediaTag,
    Board, BoardItem, BoardSection, Marker, MediaMarker,
    Keyword, MediaKeyword, MediaToolLineage, Face,
)

log = get_logger(__name__)

STATIC_MEDIA_TYPES = ["images", "videos", "audio", "text", "sets", "grids", "structured"]
STATIC_RESOLUTIONS = ["small", "medium", "large", "huge"]
STATIC_SORTS = ["created_desc", "created_asc", "indexed_desc", "indexed_asc", "random"]
OPTION_FACETS = ["media_types", "resolutions", "generated", "folders", "keywords", "tags", "markers", "tools"]
FACET_TO_FILTER_KEY = {
    "media_types": "media_types",
    "resolutions": "resolutions",
    "generated": "generated",
    "folders": "folders",
    "keywords": "keywords",
    "tags": "tags",
    "markers": "markers",
    "tools": "tools",
}


def _get_default_folder(workspace_dir: Optional[Path] = None) -> str:
    """Get default generation folder for the current profile."""
    settings = get_settings()
    profile_id = get_current_profile()
    try:
        folder = settings.get_generation_folder_for_profile(profile_id)
        return folder.path
    except ValueError:
        for folder in settings.folders:
            if folder.allow_generate:
                return folder.path
        return "./output"


def _media_summary(item: MediaItem) -> Dict[str, Any]:
    """Compact summary of a media item for search/browse results."""
    return {
        "media_id": item.id,
        "filename": os.path.basename(item.file_path) if item.file_path else None,
        "prompt": _best_prompt(item),
        "caption": item.vlm_caption,
        "width": item.width,
        "height": item.height,
        "tool_id": item.tool_id,
        "created_at": item.created_date.isoformat() if item.created_date else None,
    }


def _safe_parse_json(value: Any) -> Any:
    """Accept native objects or JSON strings from the model."""
    if value is None or isinstance(value, (dict, list, bool, int, float)):
        return value
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            return value
    return value


def _normalize_list(value: Any) -> List[Any]:
    """Coerce a scalar/array into a list, preserving order and removing empties."""
    value = _safe_parse_json(value)
    if value is None:
        return []
    if isinstance(value, list):
        return [item for item in value if item not in (None, "")]
    return [value]


def _as_csv(values: List[Any]) -> Optional[str]:
    cleaned = [str(v).strip() for v in values if str(v).strip()]
    return ",".join(cleaned) if cleaned else None


def _normalize_filters(filters: Any) -> Dict[str, Any]:
    """Normalize browse filters into a predictable dict shape."""
    parsed = _safe_parse_json(filters)
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        raise ValueError("filters must be an object")

    normalized: Dict[str, Any] = {}

    for text_key in ("query", "caption_query", "prompt_query"):
        value = parsed.get(text_key)
        if isinstance(value, str) and value.strip():
            normalized[text_key] = value.strip()

    generated = parsed.get("generated")
    if isinstance(generated, bool):
        normalized["generated"] = generated

    for facet in ("media_types", "resolutions", "folders", "keywords", "tags", "markers", "tools"):
        raw = parsed.get(facet)
        if raw is None:
            continue
        if isinstance(raw, dict):
            include = _normalize_list(raw.get("include"))
            exclude = _normalize_list(raw.get("exclude"))
        else:
            include = _normalize_list(raw)
            exclude = []
        facet_value: Dict[str, List[Any]] = {}
        if include:
            facet_value["include"] = include
        if exclude:
            facet_value["exclude"] = exclude
        if facet_value:
            normalized[facet] = facet_value

    created_at = parsed.get("created_at")
    if isinstance(created_at, dict):
        after = created_at.get("after")
        before = created_at.get("before")
        created_filter = {}
        if isinstance(after, str) and after.strip():
            created_filter["after"] = after.strip()
        if isinstance(before, str) and before.strip():
            created_filter["before"] = before.strip()
        if created_filter:
            normalized["created_at"] = created_filter

    return normalized


def _sort_spec(sort_by: Optional[str], random_seed: Optional[int]) -> Dict[str, Any]:
    effective = (sort_by or "created_desc").strip().lower()
    if effective not in STATIC_SORTS:
        effective = "created_desc"
    spec: Dict[str, Any] = {"by": effective}
    if effective == "random":
        spec["random_seed"] = random_seed if random_seed is not None else 42
    return spec


def _copy_filters_without_facet(filters: Dict[str, Any], facet: str) -> Dict[str, Any]:
    copied = json.loads(json.dumps(filters))
    filter_key = FACET_TO_FILTER_KEY.get(facet)
    if filter_key:
        copied.pop(filter_key, None)
    return copied


def _apply_created_at_filters(stmt, created_at: Optional[Dict[str, str]]):
    if not created_at:
        return stmt

    after = created_at.get("after")
    if after:
        try:
            stmt = stmt.where(MediaItem.created_date >= datetime.fromisoformat(after))
        except ValueError:
            pass

    before = created_at.get("before")
    if before:
        try:
            stmt = stmt.where(MediaItem.created_date <= datetime.fromisoformat(before))
        except ValueError:
            pass

    return stmt


async def _resolve_filter_tag_ids(session: AsyncSession, raw_tags: List[Any]) -> List[int]:
    ids: List[int] = []
    names: List[str] = []
    for value in raw_tags:
        if isinstance(value, int):
            ids.append(value)
        elif isinstance(value, str) and value.strip():
            stripped = value.strip()
            if stripped.isdigit():
                ids.append(int(stripped))
            else:
                names.append(stripped)

    if names:
        ids.extend(await _resolve_tag_ids(session, names))

    return list(dict.fromkeys(ids))


async def _resolve_filter_marker_ids(session: AsyncSession, raw_markers: List[Any]) -> List[int]:
    ids: List[int] = []
    names: List[str] = []
    for value in raw_markers:
        if isinstance(value, int):
            ids.append(value)
        elif isinstance(value, str) and value.strip():
            stripped = value.strip()
            if stripped.isdigit():
                ids.append(int(stripped))
            else:
                names.append(stripped)

    if names:
        result = await session.execute(
            select(Marker.id).where(Marker.name.in_(names))
        )
        ids.extend(row[0] for row in result.fetchall())

    return list(dict.fromkeys(ids))


async def _build_browse_query(
    session: AsyncSession,
    filters: Dict[str, Any],
    sort_by: str,
    random_seed: Optional[int],
):
    from utils.query_builder import build_filtered_query

    stmt = select(MediaItem).where(
        MediaItem.deleted_at.is_(None),
        MediaItem.superseded_by.is_(None),
        MediaItem.metadata_status == "completed",
        (MediaItem.file_unavailable == False) | (MediaItem.file_unavailable.is_(None)),
    )

    query_value = filters.get("query")
    if query_value:
        stmt = stmt.where(
            or_(
                MediaItem.vlm_caption.ilike(f"%{query_value}%"),
                MediaItem.extracted_prompt.ilike(f"%{query_value}%"),
            )
        )

    tag_include = await _resolve_filter_tag_ids(session, filters.get("tags", {}).get("include", []))
    tag_exclude = await _resolve_filter_tag_ids(session, filters.get("tags", {}).get("exclude", []))
    marker_include = await _resolve_filter_marker_ids(session, filters.get("markers", {}).get("include", []))
    marker_exclude = await _resolve_filter_marker_ids(session, filters.get("markers", {}).get("exclude", []))

    stmt = build_filtered_query(
        stmt,
        caption_query=filters.get("caption_query"),
        prompt_query=filters.get("prompt_query"),
        media_types=_as_csv(filters.get("media_types", {}).get("include", [])),
        excluded_media_types=_as_csv(filters.get("media_types", {}).get("exclude", [])),
        resolutions=_as_csv(filters.get("resolutions", {}).get("include", [])),
        excluded_resolutions=_as_csv(filters.get("resolutions", {}).get("exclude", [])),
        keywords=_as_csv(filters.get("keywords", {}).get("include", [])),
        excluded_keywords=_as_csv(filters.get("keywords", {}).get("exclude", [])),
        folders=_as_csv(filters.get("folders", {}).get("include", [])),
        excluded_folders=_as_csv(filters.get("folders", {}).get("exclude", [])),
        is_generated=filters.get("generated"),
        marker_ids=_as_csv(marker_include),
        excluded_marker_ids=_as_csv(marker_exclude),
        tag_ids=_as_csv(tag_include),
        excluded_tag_ids=_as_csv(tag_exclude),
        tool_ids=_as_csv(filters.get("tools", {}).get("include", [])),
        excluded_tool_ids=_as_csv(filters.get("tools", {}).get("exclude", [])),
    )
    stmt = _apply_created_at_filters(stmt, filters.get("created_at"))

    if sort_by == "created_desc":
        stmt = stmt.order_by(MediaItem.created_date.desc().nulls_last(), MediaItem.id.desc())
    elif sort_by == "created_asc":
        stmt = stmt.order_by(MediaItem.created_date.asc().nulls_last(), MediaItem.id.asc())
    elif sort_by == "indexed_desc":
        stmt = stmt.order_by(MediaItem.indexed_date.desc(), MediaItem.id.desc())
    elif sort_by == "indexed_asc":
        stmt = stmt.order_by(MediaItem.indexed_date.asc(), MediaItem.id.asc())
    elif sort_by == "random":
        seed = random_seed if random_seed is not None else 42
        seed_multiplier = literal(seed | 1)
        product = MediaItem.random_sort_value * seed_multiplier
        transformed = product - func.cast(product, Integer)
        stmt = stmt.order_by(transformed, MediaItem.id.asc())
    else:
        stmt = stmt.order_by(MediaItem.created_date.desc().nulls_last(), MediaItem.id.desc())

    return stmt


def _browse_schema() -> Dict[str, Any]:
    return {
        "action": "browse",
        "filters": {
            "query": {"type": "string", "description": "Caption OR prompt substring search"},
            "caption_query": {"type": "string"},
            "prompt_query": {"type": "string"},
            "generated": {"type": "boolean"},
            "media_types": {
                "type": "facet",
                "include_exclude": True,
                "values": STATIC_MEDIA_TYPES,
            },
            "resolutions": {
                "type": "facet",
                "include_exclude": True,
                "values": STATIC_RESOLUTIONS,
            },
            "folders": {
                "type": "facet",
                "include_exclude": True,
                "discovery": "library(action='browse_options', facet='folders', ...)",
            },
            "keywords": {
                "type": "facet",
                "include_exclude": True,
                "discovery": "library(action='browse_options', facet='keywords', ...)",
            },
            "tags": {
                "type": "facet",
                "include_exclude": True,
                "discovery": "library(action='browse_options', facet='tags', ...)",
            },
            "markers": {
                "type": "facet",
                "include_exclude": True,
                "discovery": "library(action='browse_options', facet='markers', ...)",
            },
            "tools": {
                "type": "facet",
                "include_exclude": True,
                "discovery": "library(action='browse_options', facet='tools', ...)",
            },
            "created_at": {
                "type": "object",
                "fields": {"after": "ISO datetime", "before": "ISO datetime"},
            },
        },
        "sort_options": STATIC_SORTS,
        "option_facets": OPTION_FACETS,
        "notes": [
            "Use browse_options for high-cardinality facets like tags, folders, keywords, markers, and tools.",
            "For tags and markers, browse consumes IDs or exact names; browse_options returns IDs for dynamic facets.",
        ],
    }


def _cursor_to_offset(cursor: Optional[str]) -> int:
    if not cursor:
        return 0
    try:
        return max(0, int(cursor))
    except ValueError:
        return 0


async def _browse_options_static(
    session: AsyncSession,
    facet: str,
    filters: Dict[str, Any],
) -> List[Dict[str, Any]]:
    stmt = await _build_browse_query(session, _copy_filters_without_facet(filters, facet), "created_desc", None)
    base_subquery = stmt.with_only_columns(MediaItem.id, MediaItem.file_format, MediaItem.megapixels, MediaItem.generation_metadata).subquery()
    result_rows: List[Dict[str, Any]] = []

    if facet == "media_types":
        conditions = {
            "images": MediaItem.file_format.in_(["jpg", "jpeg", "png", "gif", "webp", "bmp"]),
            "videos": MediaItem.file_format.in_(["mp4", "webm", "mov", "avi", "mkv"]),
            "audio": MediaItem.file_format.in_(["mp3", "wav", "flac", "aac", "m4a", "ogg"]),
            "text": MediaItem.file_format.in_(["md"]),
            "sets": MediaItem.file_format.in_(["stimmaset.json"]),
            "grids": MediaItem.file_format.in_(["stimmagrid.json"]),
            "structured": MediaItem.file_format.in_(["md", "stimmaset.json", "stimmagrid.json"]),
        }
        for label in STATIC_MEDIA_TYPES:
            count_stmt = select(func.count()).select_from(MediaItem).where(
                MediaItem.id.in_(select(base_subquery.c.id)),
                conditions[label],
            )
            count = (await session.execute(count_stmt)).scalar() or 0
            result_rows.append({"value": label, "label": label, "count": count})
        return result_rows

    if facet == "resolutions":
        bins = {
            "small": MediaItem.megapixels < 0.8,
            "medium": and_(MediaItem.megapixels >= 0.8, MediaItem.megapixels < 1.5),
            "large": and_(MediaItem.megapixels >= 1.5, MediaItem.megapixels < 3.0),
            "huge": MediaItem.megapixels >= 3.0,
        }
        for label in STATIC_RESOLUTIONS:
            count_stmt = select(func.count()).select_from(MediaItem).where(
                MediaItem.id.in_(select(base_subquery.c.id)),
                bins[label],
            )
            count = (await session.execute(count_stmt)).scalar() or 0
            result_rows.append({"value": label, "label": label, "count": count})
        return result_rows

    generated_count = (
        await session.execute(
            select(func.count()).select_from(MediaItem).where(
                MediaItem.id.in_(select(base_subquery.c.id)),
                MediaItem.generation_metadata.isnot(None),
            )
        )
    ).scalar() or 0
    imported_count = (
        await session.execute(
            select(func.count()).select_from(MediaItem).where(
                MediaItem.id.in_(select(base_subquery.c.id)),
                MediaItem.generation_metadata.is_(None),
            )
        )
    ).scalar() or 0
    return [
        {"value": True, "label": "generated", "count": generated_count},
        {"value": False, "label": "imported", "count": imported_count},
    ]


async def _browse_options_dynamic(
    session: AsyncSession,
    facet: str,
    filters: Dict[str, Any],
    query: str,
    limit: int,
    offset: int,
) -> Tuple[List[Dict[str, Any]], Optional[str], Optional[int]]:
    base_stmt = await _build_browse_query(session, _copy_filters_without_facet(filters, facet), "created_desc", None)
    media_ids = base_stmt.with_only_columns(MediaItem.id).subquery()
    search = f"%{query.lower()}%" if query else None

    if facet == "tags":
        stmt = (
            select(
                Tag.id.label("id"),
                Tag.tag_text.label("label"),
                func.count(func.distinct(MediaTag.media_id)).label("count"),
            )
            .join(MediaTag, MediaTag.tag_id == Tag.id)
            .join(media_ids, media_ids.c.id == MediaTag.media_id)
            .group_by(Tag.id, Tag.tag_text)
        )
        if search:
            stmt = stmt.where(func.lower(Tag.tag_text).ilike(search))
        stmt = stmt.order_by(func.count(func.distinct(MediaTag.media_id)).desc(), Tag.tag_text.asc())
    elif facet == "markers":
        stmt = (
            select(
                Marker.id.label("id"),
                Marker.name.label("label"),
                func.count(func.distinct(MediaMarker.media_id)).label("count"),
            )
            .join(MediaMarker, and_(MediaMarker.marker_id == Marker.id, MediaMarker.source != "suppressed"))
            .join(media_ids, media_ids.c.id == MediaMarker.media_id)
            .group_by(Marker.id, Marker.name)
        )
        if search:
            stmt = stmt.where(func.lower(Marker.name).ilike(search))
        stmt = stmt.order_by(func.count(func.distinct(MediaMarker.media_id)).desc(), Marker.name.asc())
    elif facet == "keywords":
        stmt = (
            select(
                Keyword.id.label("id"),
                Keyword.keyword_text.label("label"),
                func.count(func.distinct(MediaKeyword.media_id)).label("count"),
            )
            .join(MediaKeyword, MediaKeyword.keyword_id == Keyword.id)
            .join(media_ids, media_ids.c.id == MediaKeyword.media_id)
            .group_by(Keyword.id, Keyword.keyword_text)
        )
        if search:
            stmt = stmt.where(func.lower(Keyword.keyword_text).ilike(search))
        stmt = stmt.order_by(func.count(func.distinct(MediaKeyword.media_id)).desc(), Keyword.keyword_text.asc())
    elif facet == "tools":
        stmt = (
            select(
                MediaToolLineage.full_tool_id.label("id"),
                MediaToolLineage.full_tool_id.label("label"),
                func.count(func.distinct(MediaToolLineage.media_id)).label("count"),
            )
            .join(media_ids, media_ids.c.id == MediaToolLineage.media_id)
            .group_by(MediaToolLineage.full_tool_id)
        )
        if search:
            stmt = stmt.where(func.lower(MediaToolLineage.full_tool_id).ilike(search))
        stmt = stmt.order_by(func.count(func.distinct(MediaToolLineage.media_id)).desc(), MediaToolLineage.full_tool_id.asc())
    elif facet == "folders":
        file_paths = (await session.execute(
            select(MediaItem.file_path).where(MediaItem.id.in_(select(media_ids.c.id)))
        )).scalars().all()
        counts: Dict[str, int] = {}
        for file_path in file_paths:
            if not file_path:
                continue
            folder = str(Path(file_path).parent)
            if query and query.lower() not in folder.lower():
                continue
            counts[folder] = counts.get(folder, 0) + 1
        ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
        page = ordered[offset: offset + limit + 1]
        items = [{"id": folder, "label": folder, "count": count} for folder, count in page[:limit]]
        next_cursor = str(offset + limit) if len(page) > limit else None
        return items, next_cursor, len(ordered)
    else:
        return [], None, 0

    all_rows = (await session.execute(stmt.offset(offset).limit(limit + 1))).all()
    items = [{"id": row.id, "label": row.label, "count": row.count} for row in all_rows[:limit]]
    next_cursor = str(offset + limit) if len(all_rows) > limit else None
    total_estimate = offset + len(all_rows) if next_cursor is None else None
    return items, next_cursor, total_estimate


def _resolve_tool_display_name(tool_id: Optional[str]) -> Optional[str]:
    """Resolve a tool_id to its human-readable display name via the provider registry."""
    if not tool_id:
        return None
    try:
        registry = ProviderRegistry.get_instance()
        provider_tool = registry.get_tool(tool_id)
        if provider_tool:
            _, descriptor = provider_tool
            return descriptor.name
    except Exception:
        pass
    return None


def _parse_generation_metadata(item: MediaItem) -> Optional[Dict[str, Any]]:
    """Parse generation metadata JSON if present."""
    if not item.generation_metadata:
        return None
    try:
        parsed = json.loads(item.generation_metadata)
    except (TypeError, json.JSONDecodeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _best_prompt(item: MediaItem, generation_metadata: Optional[Dict[str, Any]] = None) -> Optional[str]:
    """Prefer the user-authored generation prompt over extracted prompt and AI caption."""
    gen = generation_metadata if generation_metadata is not None else _parse_generation_metadata(item)
    prompt_metadata = gen.get("prompt_metadata") if isinstance(gen, dict) else None
    original_prompt = prompt_metadata.get("original_prompt") if isinstance(prompt_metadata, dict) else None
    rendered_prompt = gen.get("prompt") if isinstance(gen, dict) else None
    return original_prompt or rendered_prompt or item.extracted_prompt


def _build_generation_history(
    item: MediaItem,
    generation_metadata: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Mirror the slideshow history panel structure for agent consumption."""
    def history_params(entry: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        params = dict((entry or {}).get("parameters") or {})
        if params.get("seed") is None and (entry or {}).get("seed") is not None:
            params["seed"] = entry["seed"]
        return params

    gen = generation_metadata if generation_metadata is not None else _parse_generation_metadata(item)
    if not gen:
        return [{
            "media_id": item.id,
            "task_type": None,
            "is_imported": True,
            "model": None,
            "generator": None,
            "prompt": item.extracted_prompt or None,
            "negative_prompt": None,
            "parameters": {
                "width": item.width,
                "height": item.height,
            },
            "generated_at": item.indexed_date.isoformat() if item.indexed_date else None,
            "source_inputs": [],
            "tool_id": None,
            "raw_metadata": item.raw_metadata or None,
        }]

    params = history_params(gen)
    history = []
    step = {
        "media_id": item.id,
        "task_type": gen.get("task_type"),
        "model": gen.get("model"),
        "generator": gen.get("generator"),
        "prompt": gen.get("prompt"),
        "negative_prompt": gen.get("negative_prompt") or params.get("negative_prompt"),
        "parameters": dict(params),
        "generated_at": gen.get("generated_at"),
        "source_inputs": gen.get("source_inputs") if isinstance(gen.get("source_inputs"), list) else [],
        "tool_id": gen.get("tool_id") or None,
        "tool_name": _resolve_tool_display_name(gen.get("tool_id")),
    }

    if gen.get("source") == "external":
        step["is_imported"] = True
        step["raw_metadata"] = item.raw_metadata or None
        loras = gen.get("loras")
        if isinstance(loras, list) and loras:
            step["parameters"]["loras"] = [
                {
                    "lora": lora.get("name"),
                    "weight": lora.get("weight"),
                }
                for lora in loras
                if isinstance(lora, dict)
            ]

    history.append(step)

    lineage_trace = gen.get("lineage_trace")
    if isinstance(lineage_trace, list) and lineage_trace:
        for ancestor in reversed(lineage_trace):
            if not isinstance(ancestor, dict):
                continue
            ancestor_params = history_params(ancestor)
            history.append({
                "media_id": ancestor.get("media_id"),
                "task_type": ancestor.get("task_type"),
                "model": ancestor.get("model"),
                "generator": ancestor.get("generator"),
                "prompt": ancestor.get("prompt") or ancestor.get("prompt_preview"),
                "negative_prompt": ancestor.get("negative_prompt") or ancestor_params.get("negative_prompt"),
                "parameters": ancestor_params,
                "generated_at": ancestor.get("generated_at"),
                "source_inputs": ancestor.get("source_inputs") if isinstance(ancestor.get("source_inputs"), list) else [],
                "tool_id": ancestor.get("tool_id") or None,
                "tool_name": _resolve_tool_display_name(ancestor.get("tool_id")),
            })

    return history


def _normalize_loras_for_input(loras: Any) -> List[Dict[str, Any]]:
    """Coerce stored LoRA dicts into the shape call_tool expects.

    Storage records LoRAs as {"lora": <path>, "weight": w} (the generation
    queue's shape), but call_tool inputs require {"path": <name>, "weight": w}.
    Accepts any of path/lora/name so reproduction round-trips losslessly.
    """
    out: List[Dict[str, Any]] = []
    for lora in loras or []:
        if not isinstance(lora, dict):
            continue
        path = lora.get("path") or lora.get("lora") or lora.get("name")
        if not path:
            continue
        out.append({"path": path, "weight": lora.get("weight", 1.0)})
    return out


def build_generation_params(
    item: MediaItem,
    generation_metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build a call_tool-ready input dict that reproduces a media item.

    The output is a flat dict spreadable straight into call_tool /
    stimma.call_tool: tool_id at top level, seed at top level (not nested in
    parameters), LoRAs normalized to [{path, weight}], and input_images
    populated from recorded source images for image-to-image reproduction.
    Storage and execution use different schemas; this is the adapter.
    """
    gen = generation_metadata if generation_metadata is not None else _parse_generation_metadata(item)
    gen = gen or {}
    stored = dict(gen.get("parameters") or {})
    params: Dict[str, Any] = {}

    tool_id = item.tool_id or gen.get("tool_id")
    if tool_id:
        params["tool_id"] = tool_id

    # Reproduction must use the prompt actually sent to the generator — wildcards
    # already resolved and auto-improve already applied — not the pre-processing
    # user input. _best_prompt prefers prompt_metadata.original_prompt (the raw
    # input) so the agent can read human intent, but for a faithful re-run / grid
    # we need the rendered prompt. Fall back to original/extracted only when no
    # rendered prompt was recorded (older or externally imported items).
    prompt_metadata = gen.get("prompt_metadata") if isinstance(gen, dict) else None
    original_prompt = prompt_metadata.get("original_prompt") if isinstance(prompt_metadata, dict) else None
    prompt = gen.get("prompt") or original_prompt or item.extracted_prompt
    if prompt:
        params["prompt"] = prompt

    # Carry over every stored generation parameter for faithful reproduction
    # (steps, cfg, guidance, sampler, scheduler, and any provider-specific keys),
    # except the few whose reproduction shape differs from storage — handled below.
    _RESHAPED_KEYS = {"seed", "loras", "width", "height", "prompt", "negative_prompt"}
    for key, value in stored.items():
        if value is None or key in _RESHAPED_KEYS:
            continue
        params[key] = value

    # seed → top-level input key (call_tool reads seed from inputs, not parameters)
    seed = stored.get("seed")
    if seed is None:
        seed = gen.get("seed")
    if seed is not None:
        params["seed"] = seed

    negative_prompt = gen.get("negative_prompt") or stored.get("negative_prompt")
    if negative_prompt:
        params["negative_prompt"] = negative_prompt

    loras = _normalize_loras_for_input(stored.get("loras"))
    if loras:
        params["loras"] = loras

    if item.width:
        params["width"] = item.width
    if item.height:
        params["height"] = item.height

    source_ids: List[int] = []
    for entry in gen.get("source_inputs") or []:
        if not isinstance(entry, dict):
            continue
        mid = entry.get("media_id")
        if mid and entry.get("role") in (None, "source_image", "input_image"):
            source_ids.append(mid)
    if source_ids:
        params["input_images"] = source_ids

    return params


async def fetch_generation_params(
    session: AsyncSession,
    media_id: Optional[int],
) -> Dict[str, Any]:
    """Load a media item and return its call_tool-ready reproduction params.

    Raises ValueError if the item is missing/deleted. The returned dict is the
    flat, spreadable params (see build_generation_params)."""
    if not media_id:
        raise ValueError("media_id is required")
    result = await session.execute(select(MediaItem).where(MediaItem.id == media_id))
    item = result.scalar_one_or_none()
    if not item:
        raise ValueError(f"Media {media_id} not found")
    if item.deleted_at:
        raise ValueError(f"Media {media_id} has been deleted")
    return build_generation_params(item, _parse_generation_metadata(item))


# Generation inputs every image/media tool understands. These stay portable when
# reusing a prior result's parameters via `params_from`, even when a particular
# tool's schema doesn't enumerate them explicitly.
_UNIVERSAL_GEN_KEYS = frozenset(
    {"prompt", "negative_prompt", "seed", "loras", "width", "height"}
)


async def resolve_params_from(
    session: AsyncSession,
    tool_id: str,
    media_id: int,
    explicit: Dict[str, Any],
) -> Dict[str, Any]:
    """Seed a tool call from a prior library item's recorded generation params.

    Starts from ``media_id``'s recorded parameters, then lets explicitly-passed
    values win. Carries knobs only (prompt, seed, loras, dimensions, sampler, …)
    — never the source image's pixels — so reusing settings can't quietly turn a
    generation into an edit; an input-image parameter is for that. A knob the
    caller omits inherits from the source item instead of snapping back to the
    tool's schema default. Precedence: schema default < params_from item <
    explicit. Shared by the agent (run_code) and recipe execution paths so both
    behave identically.
    """
    base = await fetch_generation_params(session, media_id)
    if not base.get("tool_id"):
        raise RuntimeError(
            f"Media {media_id} has no recorded generation parameters "
            f"(imported or externally-created image) — nothing for params_from to reuse."
        )
    base.pop("tool_id", None)       # provenance, not a tool input
    base.pop("input_images", None)  # content, not a setting — never inherit pixels

    # Cross-tool safety: reusing settings into a *different* tool keeps only the
    # knobs it accepts (plus the universal generation inputs), so params it
    # doesn't understand are dropped rather than forwarded and rejected.
    try:
        from providers.registry import ProviderRegistry
        provider_tool = ProviderRegistry.get_instance().get_tool(tool_id)
    except Exception:
        provider_tool = None
    if provider_tool:
        props = set((provider_tool[1].parameter_schema or {}).get("properties") or {})
        base = {k: v for k, v in base.items() if k in props or k in _UNIVERSAL_GEN_KEYS}

    return {**base, **explicit}


async def _load_lineage_data(session: AsyncSession, media_id: int) -> Dict[str, Any]:
    """Load immediate parents/children with the same semantics as the media API."""
    sources_result = await session.execute(
        select(MediaLineage)
        .where(MediaLineage.media_id == media_id)
        .order_by(MediaLineage.source_order)
    )
    sources = sources_result.scalars().all()

    derivatives_result = await session.execute(
        select(MediaLineage)
        .where(MediaLineage.source_media_id == media_id)
        .order_by(MediaLineage.created_at.desc())
    )
    derivatives = derivatives_result.scalars().all()

    source_data = []
    source_ids = set()
    for source in sources:
        entry = {
            "order": source.source_order,
            "task_type": source.task_type,
        }
        if source.source_media_id:
            media_result = await session.execute(
                select(MediaItem).where(MediaItem.id == source.source_media_id)
            )
            media = media_result.scalar_one_or_none()
            if media and not media.deleted_at:
                entry["type"] = "internal"
                entry["media"] = media.to_dict()
                source_ids.add(media.id)
            else:
                entry["type"] = "deleted"
                entry["media_id"] = source.source_media_id
        else:
            entry["type"] = "external"
            entry["file_path"] = source.source_file_path
        source_data.append(entry)

    supersede_source_result = await session.execute(
        select(MediaItem).where(MediaItem.superseded_by == media_id)
    )
    for source_media in supersede_source_result.scalars().all():
        if source_media and not source_media.deleted_at and source_media.id not in source_ids:
            source_data.append({
                "order": 0,
                "task_type": "upscale",
                "type": "internal",
                "media": source_media.to_dict(),
            })
            source_ids.add(source_media.id)

    derivative_data = []
    derivative_ids = set()
    for derivative in derivatives:
        media_result = await session.execute(
            select(MediaItem).where(MediaItem.id == derivative.media_id)
        )
        media = media_result.scalar_one_or_none()
        if media and not media.deleted_at:
            derivative_data.append({
                "media": media.to_dict(),
                "task_type": derivative.task_type,
                "relationship_type": getattr(derivative, "relationship_type", "derived"),
                "created_at": derivative.created_at.isoformat() if derivative.created_at else None,
            })
            derivative_ids.add(media.id)

    current_media_result = await session.execute(
        select(MediaItem).where(MediaItem.id == media_id)
    )
    current_media = current_media_result.scalar_one_or_none()
    if current_media and current_media.superseded_by:
        superseded_result = await session.execute(
            select(MediaItem).where(MediaItem.id == current_media.superseded_by)
        )
        superseded_media = superseded_result.scalar_one_or_none()
        if superseded_media and not superseded_media.deleted_at and superseded_media.id not in derivative_ids:
            derivative_data.append({
                "media": superseded_media.to_dict(),
                "task_type": "upscale",
                "created_at": superseded_media.created_date.isoformat() if superseded_media.created_date else None,
            })

    return {
        "sources": source_data,
        "derivatives": derivative_data,
    }


@tool(
    name="library",
    description=(
        "Search, retrieve, save, and browse the media library. "
        "Manage tags, markers, and boards on media items. "
        "Use browse_schema and browse_options for progressive disclosure of browse facets. Inspect lineage. "
        "Use generation_params to get a call_tool-ready recipe for reproducing an existing image (tweak one field, then call_tool)."
    ),
    parameters=[
        ToolParameter("action", "string", "search | get | generation_params | browse | browse_schema | browse_options | save | lineage | tag | marker | board"),
        ToolParameter("query", "string", "Text query. Search matches against generation prompts by default (best signal). Use search_fields to broaden.", required=False),
        ToolParameter("search_fields", "string", "prompt (default) | caption | keywords | all — which fields to search. Only broaden when prompt search returns nothing useful.", required=False),
        ToolParameter("media_id", "integer", "Media ID (get/lineage/tag/marker)", required=False),
        ToolParameter("media_ids", "array", "List of media IDs (tag/marker/board bulk ops)", required=False, items={"type": "integer"}),
        ToolParameter("tags", "array", "Filter by tag names (browse) or tag names to add/remove (tag action)", required=False, items={"type": "string"}),
        ToolParameter("limit", "integer", "Max results, default 20", required=False),
        ToolParameter("offset", "integer", "Browse result offset, default 0", required=False),
        ToolParameter("filters", "object", "Structured browse filters object", required=False),
        ToolParameter("sort_by", "string", "Browse sort: created_desc | created_asc | indexed_desc | indexed_asc | random", required=False),
        ToolParameter("random_seed", "integer", "Seed for random browse ordering", required=False),
        ToolParameter("facet", "string", "Facet name for browse_options", required=False),
        ToolParameter("cursor", "string", "Opaque cursor for browse_options pagination", required=False),
        ToolParameter("path", "string", "Workspace filename to save (save action)", required=False),
        ToolParameter("save_tags", "array", "Tags to apply on save — only when the user explicitly requests tagging", required=False, items={"type": "string"}),
        ToolParameter("marker_name", "string", "Marker name (marker action)", required=False),
        ToolParameter("board_name", "string", "Board name (board action)", required=False),
        ToolParameter("board_id", "integer", "Board ID (board action)", required=False),
        ToolParameter("section_name", "string", "Section name (board action)", required=False),
        ToolParameter("section_id", "integer", "Section ID (board action)", required=False),
        ToolParameter("operation", "string", "add | remove | move | list | contents | create | delete | rename | create_section | rename_section | delete_section | set_collapsed (for tag/marker/board actions, default: add). Board add auto-creates the board if board_name doesn't exist yet — no separate create needed. Move relocates items to a target section.", required=False),
    ],
)
async def library(
    action: str,
    query: Optional[str] = None,
    search_fields: Optional[str] = None,
    media_id: Optional[int] = None,
    media_ids: Optional[List[int]] = None,
    tags: Optional[List[str]] = None,
    limit: Optional[int] = None,
    offset: Optional[int] = None,
    filters: Optional[Dict[str, Any]] = None,
    sort_by: Optional[str] = None,
    random_seed: Optional[int] = None,
    facet: Optional[str] = None,
    cursor: Optional[str] = None,
    path: Optional[str] = None,
    save_tags: Optional[List[str]] = None,
    marker_name: Optional[str] = None,
    board_name: Optional[str] = None,
    board_id: Optional[int] = None,
    section_name: Optional[str] = None,
    section_id: Optional[int] = None,
    operation: Optional[str] = None,
    **kwargs,
) -> str:
    session: AsyncSession = kwargs.get("session")
    workspace_dir: Optional[Path] = kwargs.get("workspace_dir")

    if not session:
        return "Error: No database session available"

    action = action.lower().strip()
    op = (operation or "add").lower().strip()

    project_id = kwargs.get("project_id")

    if action == "search":
        return await _search(session, query, search_fields, limit or 20, project_id=project_id)
    elif action == "browse":
        return await _browse(session, query, tags, filters, sort_by, random_seed, limit or 20, offset or 0, project_id=project_id)
    elif action == "browse_schema":
        return json.dumps(_browse_schema(), default=str)
    elif action == "browse_options":
        return await _browse_options(session, facet, filters, query, limit or 25, cursor)
    elif action == "get":
        return await _get(session, media_id, workspace_dir)
    elif action == "generation_params":
        return await _generation_params(session, media_id)
    elif action == "save":
        return await _save(session, path, workspace_dir, save_tags, project_id=project_id)
    elif action == "lineage":
        return await _lineage(session, media_id)
    elif action == "tag":
        return await _tag(session, media_id, media_ids, tags, op)
    elif action == "marker":
        return await _marker(session, media_id, media_ids, marker_name, op)
    elif action == "board":
        project_id = kwargs.get("project_id")
        return await _board(session, media_id, media_ids, board_name, board_id, section_name, section_id, op, project_id=project_id)
    else:
        return (
            "Error: Unknown action "
            f"'{action}'. Use: search, get, generation_params, browse, browse_schema, browse_options, "
            "save, lineage, tag, marker, board"
        )


async def _search(
    session: AsyncSession,
    query: Optional[str],
    search_fields: Optional[str],
    limit: int,
    project_id: Optional[int] = None,
) -> str:
    if not query:
        return "Error: query is required for search"

    fields = (search_fields or "prompt").lower().strip()
    valid_fields = {"prompt", "caption", "keywords", "all"}
    if fields not in valid_fields:
        return f"Error: search_fields must be one of: {', '.join(sorted(valid_fields))}"

    from utils.query_builder import not_due_for_autodelete

    conditions = []
    if fields in ("prompt", "all"):
        conditions.append(MediaItem.extracted_prompt.ilike(f"%{query}%"))
    if fields in ("caption", "all"):
        conditions.append(MediaItem.vlm_caption.ilike(f"%{query}%"))
    if fields in ("keywords", "all"):
        conditions.append(MediaItem.keywords.ilike(f"%{query}%"))

    stmt = select(MediaItem).where(
        MediaItem.deleted_at.is_(None),
        MediaItem.superseded_by.is_(None),
        not_due_for_autodelete(),
        or_(*conditions),
    )
    # Scope to project when in project context
    if project_id is not None:
        from database import ProjectMedia
        stmt = stmt.join(ProjectMedia, ProjectMedia.media_id == MediaItem.id).where(
            ProjectMedia.project_id == project_id
        )
    stmt = stmt.order_by(MediaItem.created_date.desc()).limit(limit)

    result = await session.execute(stmt)
    items = result.scalars().all()

    if not items:
        return "No results found."

    summaries = [_media_summary(item) for item in items]
    return json.dumps(summaries, default=str)


async def _browse(
    session: AsyncSession,
    query: Optional[str],
    tags: Optional[List[str]],
    filters: Optional[Dict[str, Any]],
    sort_by: Optional[str],
    random_seed: Optional[int],
    limit: int,
    offset: int,
    project_id: Optional[int] = None,
) -> str:
    normalized_filters = _normalize_filters(filters)
    if tags:
        normalized_filters.setdefault("tags", {})
        existing = normalized_filters["tags"].get("include", [])
        normalized_filters["tags"]["include"] = list(dict.fromkeys(existing + tags))
    if query and "query" not in normalized_filters:
        normalized_filters["query"] = query

    sort_spec = _sort_spec(sort_by, random_seed)
    stmt = await _build_browse_query(
        session,
        normalized_filters,
        sort_spec["by"],
        sort_spec.get("random_seed"),
    )
    # Scope to project when in project context
    if project_id is not None:
        from database import ProjectMedia
        stmt = stmt.join(ProjectMedia, ProjectMedia.media_id == MediaItem.id).where(
            ProjectMedia.project_id == project_id
        )
    total_stmt = select(func.count()).select_from(stmt.order_by(None).subquery())
    total = (await session.execute(total_stmt)).scalar() or 0
    result = await session.execute(stmt.limit(limit).offset(offset))
    items = result.scalars().all()

    if not items:
        return json.dumps({
            "items": [],
            "total": total,
            "limit": limit,
            "offset": offset,
            "has_more": False,
            "applied_filters": normalized_filters,
            "sort": sort_spec,
        }, default=str)

    summaries = [_media_summary(item) for item in items]
    return json.dumps({
        "items": summaries,
        "total": total,
        "limit": limit,
        "offset": offset,
        "has_more": offset + len(summaries) < total,
        "applied_filters": normalized_filters,
        "sort": sort_spec,
    }, default=str)


async def _browse_options(
    session: AsyncSession,
    facet: Optional[str],
    filters: Optional[Dict[str, Any]],
    query: Optional[str],
    limit: int,
    cursor: Optional[str],
) -> str:
    if not facet:
        return "Error: facet is required for browse_options"

    normalized_facet = facet.strip().lower()
    if normalized_facet not in OPTION_FACETS:
        return f"Error: Unsupported facet '{facet}'. Use one of: {', '.join(OPTION_FACETS)}"

    normalized_filters = _normalize_filters(filters)
    offset = _cursor_to_offset(cursor)

    if normalized_facet in {"media_types", "resolutions", "generated"}:
        items = await _browse_options_static(session, normalized_facet, normalized_filters)
        if query:
            lowered = query.lower()
            items = [item for item in items if lowered in str(item["label"]).lower()]
        sliced = items[offset: offset + limit + 1]
        page = sliced[:limit]
        next_cursor = str(offset + limit) if len(sliced) > limit else None
        return json.dumps({
            "facet": normalized_facet,
            "items": page,
            "next_cursor": next_cursor,
            "total_estimate": len(items),
            "applied_filters": _copy_filters_without_facet(normalized_filters, normalized_facet),
        }, default=str)

    items, next_cursor, total_estimate = await _browse_options_dynamic(
        session,
        normalized_facet,
        normalized_filters,
        query or "",
        limit,
        offset,
    )
    return json.dumps({
        "facet": normalized_facet,
        "items": items,
        "next_cursor": next_cursor,
        "total_estimate": total_estimate,
        "applied_filters": _copy_filters_without_facet(normalized_filters, normalized_facet),
    }, default=str)


async def get_media_for_workspace(
    session: AsyncSession,
    media_id: Optional[int],
    workspace_dir: Optional[Path],
) -> str:
    if not media_id:
        return "Error: media_id is required for get action"

    result = await session.execute(
        select(MediaItem).where(MediaItem.id == media_id)
    )
    item = result.scalar_one_or_none()

    if not item:
        return f"Error: Media {media_id} not found"
    if item.deleted_at:
        return f"Error: Media {media_id} has been deleted"

    if workspace_dir and item.file_path:
        filename = os.path.basename(item.file_path)
        dest = os.path.join(str(workspace_dir), filename)
        try:
            source_path = Path(item.file_path)
            if source_path.is_dir():
                # Directory-based media (e.g., .stimmalayout bundles)
                if os.path.exists(dest):
                    shutil.rmtree(dest)
                shutil.copytree(item.file_path, dest)
            else:
                shutil.copy2(item.file_path, dest)
        except FileNotFoundError:
            return f"Error: Source file not found at {item.file_path}"
        except Exception as e:
            return f"Error copying file: {e}"
    else:
        filename = os.path.basename(item.file_path) if item.file_path else None

    generation_metadata = _parse_generation_metadata(item)
    history = _build_generation_history(item, generation_metadata)
    top_history_step = history[0] if history else {}

    raw_tool_id = item.tool_id or top_history_step.get("tool_id")
    tool_name = _resolve_tool_display_name(raw_tool_id)

    dest_path = os.path.join(str(workspace_dir), filename) if workspace_dir and filename else None

    result_data = {
        "media_id": item.id,
        "filename": filename,
        "path": dest_path,
        "prompt": _best_prompt(item, generation_metadata),
        "negative_prompt": top_history_step.get("negative_prompt"),
        "history": history,
        "width": item.width,
        "height": item.height,
        "tool_id": raw_tool_id,
        "tool_name": tool_name,
        "created_at": item.created_date.isoformat() if item.created_date else None,
        "caption": item.vlm_caption,
        "keywords": item.keywords.split(",") if item.keywords else [],
        "generation_metadata": generation_metadata,
    }

    # Include face detection data if available (bbox coordinates are normalized 0-1)
    if item.face_detection_status == "completed":
        face_rows = (await session.execute(
            select(Face).where(Face.media_id == media_id).order_by(Face.confidence.desc())
        )).scalars().all()
        if face_rows:
            result_data["faces"] = [
                {
                    "x": f.bbox_x, "y": f.bbox_y,
                    "width": f.bbox_width, "height": f.bbox_height,
                    "confidence": round(f.confidence, 3),
                }
                for f in face_rows
            ]

    return json.dumps(result_data, default=str)


def _compute_file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _normalize_source_path(path: str, workspace_dir: Optional[Path]) -> Path:
    source = Path(path)
    if not source.is_absolute():
        if not workspace_dir:
            raise ValueError("No workspace directory available")
        source = workspace_dir / source
    return source


async def save_workspace_file(
    session: AsyncSession,
    path: Optional[str],
    workspace_dir: Optional[Path],
    save_tags: Optional[List[str]],
    provenance: Optional[Dict[str, Any]] = None,
    inspired_by: Optional[int | List[int]] = None,
    project_id: Optional[int] = None,
) -> str:
    if not path:
        return "Error: path is required for save action"
    try:
        source = _normalize_source_path(path, workspace_dir)
    except ValueError as e:
        return f"Error: {e}"
    if not source.exists():
        return f"Error: File not found: {source}"

    is_layout_bundle = source.is_dir() and source.name.lower().endswith('.stimmalayout')

    # Copy to output folder
    output_folder = _get_default_folder(workspace_dir)
    os.makedirs(output_folder, exist_ok=True)
    dest = os.path.join(output_folder, source.name)

    # Avoid overwriting existing files/dirs
    if os.path.exists(dest):
        if is_layout_bundle:
            base = source.name
            counter = 1
            while os.path.exists(dest):
                stem = source.name.rsplit('.stimmalayout', 1)[0]
                dest = os.path.join(output_folder, f"{stem}_{counter}.stimmalayout")
                counter += 1
        else:
            base, ext = os.path.splitext(source.name)
            counter = 1
            while os.path.exists(dest):
                dest = os.path.join(output_folder, f"{base}_{counter}{ext}")
                counter += 1

    if is_layout_bundle:
        shutil.copytree(str(source), dest)
    else:
        shutil.copy2(str(source), dest)

    # Determine file format
    if is_layout_bundle:
        ext = "stimmalayout"
    else:
        ext = os.path.splitext(dest)[1].lstrip(".").lower()
        if ext == "jpg":
            ext = "jpeg"

    # Get dimensions if it's an image (skip for layout bundles)
    width, height = 0, 0
    if not is_layout_bundle:
        try:
            from utils.image_ops import open_oriented
            with open_oriented(dest) as img:
                width, height = img.size
        except Exception:
            pass

    # Create MediaItem
    if is_layout_bundle:
        index_path = Path(dest) / "index.html"
        file_size = index_path.stat().st_size if index_path.exists() else 0
        file_hash = _compute_file_hash(index_path) if index_path.exists() else ""
    else:
        file_size = os.path.getsize(dest)
        file_hash = _compute_file_hash(Path(dest))
    megapixels = (width * height) / 1_000_000 if width and height else 0.0

    # Determine if this is non-visual media (audio, text, structured types)
    # Non-visual media should skip AI processing phases (CLIP, face detection, VLM)
    _NON_VISUAL_FORMATS = {'md', 'mp3', 'wav', 'flac', 'aac', 'm4a', 'ogg',
                           'stimmaset.json', 'stimmagrid.json', 'stimmalayout'}
    is_non_visual = ext in _NON_VISUAL_FORMATS or is_layout_bundle

    generation_metadata = None
    if provenance:
        provenance_params = dict(provenance.get("parameters") or {})
        if provenance_params.get("seed") is None and provenance.get("seed") is not None:
            provenance_params["seed"] = provenance["seed"]
        gen_meta = {
            "version": 3,
            "source": "agent_v2_run_code",
            "tool_id": provenance.get("tool_id"),
            "task_type": provenance.get("task_type"),
            "parameters": provenance_params,
            "seed": provenance.get("seed"),
            "source_inputs": provenance.get("source_inputs") or [
                {"media_id": mid, "role": "source_image"} for mid in (provenance.get("source_media_ids") or [])
            ],
            "generated_at": datetime.utcnow().isoformat(),
        }
        if provenance.get("lineage_trace"):
            gen_meta["lineage_trace"] = provenance["lineage_trace"]
        generation_metadata = json.dumps(gen_meta)
    from config_version import get_config_version_manager
    media_item = MediaItem(
        file_path=dest,
        file_hash=file_hash,
        file_size=file_size,
        file_format=ext,
        width=width,
        height=height,
        megapixels=megapixels,
        metadata_status="completed",
        metadata_processed_at=datetime.utcnow(),
        metadata_config_version=get_config_version_manager().get_version('metadata'),
        clip_status="skipped" if is_non_visual else None,
        face_detection_status="skipped" if is_non_visual else None,
        vlm_caption_status="skipped" if is_non_visual else None,
        created_date=datetime.utcnow(),
        modified_date=datetime.utcnow(),
        indexed_date=datetime.utcnow(),
        tool_id=provenance.get("tool_id") if provenance else None,
        generation_metadata=generation_metadata,
    )
    session.add(media_item)
    await session.flush()  # Get the ID
    effective_project_id = project_id or infer_project_id_from_workspace_path(workspace_dir)
    if effective_project_id is not None:
        await attach_media_to_project(session, effective_project_id, media_item.id)

    # Apply tags if provided
    if save_tags:
        tag_ids = await _resolve_or_create_tags(session, save_tags)
        for tag_id in tag_ids:
            session.add(MediaTag(media_id=media_item.id, tag_id=tag_id))

    derived_source_ids = list(provenance.get("source_media_ids") or []) if provenance else []
    for idx, source_media_id in enumerate(derived_source_ids):
        session.add(MediaLineage(
            media_id=media_item.id,
            source_media_id=source_media_id,
            source_order=idx,
            task_type=provenance.get("task_type") or "code",
            relationship_type="derived",
        ))

    inspired_ids: List[int] = []
    if isinstance(inspired_by, int):
        inspired_ids = [inspired_by]
    elif isinstance(inspired_by, list):
        inspired_ids = [value for value in inspired_by if isinstance(value, int)]

    start_idx = len(derived_source_ids)
    for offset, source_media_id in enumerate(inspired_ids):
        session.add(MediaLineage(
            media_id=media_item.id,
            source_media_id=source_media_id,
            source_order=start_idx + offset,
            task_type=provenance.get("task_type") if provenance else "inspired",
            relationship_type="inspired",
        ))

    # Propagate tool lineage chain (mirrors generation_queue.py behavior)
    from utils.lineage import propagate_tool_lineage
    source_ids_for_tool = []
    if generation_metadata and provenance:
        si = (json.loads(generation_metadata) if isinstance(generation_metadata, str) else {}).get("source_inputs", [])
        source_ids_for_tool = [
            s.get("media_id") for s in si
            if isinstance(s, dict) and s.get("media_id")
        ]
    if not source_ids_for_tool:
        source_ids_for_tool = derived_source_ids
    await propagate_tool_lineage(
        session, media_item.id, source_ids_for_tool,
        own_tool_id=provenance.get("tool_id") if provenance else None,
    )

    await session.commit()

    # Broadcast update
    try:
        from utils.websocket import broadcast_media_updated
        await broadcast_media_updated(media_item, ["created"], session)
    except Exception as e:
        log.warning(f"[library] Failed to broadcast media update: {e}")

    # Signal ingestion worker for background processing (CLIP, face detection, etc.)
    if not is_non_visual:
        try:
            from core.app import get_process_pending_event
            import threading
            process_pending_event = get_process_pending_event()
            if process_pending_event:
                def signal_ingestion():
                    try:
                        process_pending_event.set()
                    except Exception as e:
                        log.warning(f"[library] Failed to signal ingestion worker: {e}")
                thread = threading.Thread(target=signal_ingestion, daemon=True)
                thread.start()
        except Exception as e:
            log.warning(f"[library] Failed to signal ingestion worker: {e}")

    return json.dumps({"media_id": media_item.id, "filename": os.path.basename(dest)})


async def _get(
    session: AsyncSession,
    media_id: Optional[int],
    workspace_dir: Optional[Path],
) -> str:
    return await get_media_for_workspace(session, media_id, workspace_dir)


async def _save(
    session: AsyncSession,
    path: Optional[str],
    workspace_dir: Optional[Path],
    save_tags: Optional[List[str]],
    project_id: Optional[int] = None,
) -> str:
    return await save_workspace_file(session, path, workspace_dir, save_tags, project_id=project_id)


async def _generation_params(session: AsyncSession, media_id: Optional[int]) -> str:
    try:
        params = await fetch_generation_params(session, media_id)
    except ValueError as e:
        return f"Error: {e}"
    payload: Dict[str, Any] = {"params": params}
    if "tool_id" not in params:
        payload["note"] = (
            "No generating tool was recorded for this item (imported/external image), "
            "so it cannot be reproduced directly — choose a tool_id before calling call_tool."
        )
    return json.dumps(payload, default=str)


async def _lineage(session: AsyncSession, media_id: Optional[int]) -> str:
    if not media_id:
        return "Error: media_id is required for lineage action"

    # Verify item exists
    result = await session.execute(
        select(MediaItem).where(MediaItem.id == media_id)
    )
    item = result.scalar_one_or_none()
    if not item:
        return f"Error: Media {media_id} not found"

    generation_metadata = _parse_generation_metadata(item)
    history = _build_generation_history(item, generation_metadata)
    lineage_data = await _load_lineage_data(session, media_id)

    result_data = {
        "media_id": media_id,
        "prompt": _best_prompt(item, generation_metadata),
        "history": history,
        "sources": lineage_data["sources"],
        "derivatives": lineage_data["derivatives"],
    }

    output = json.dumps(result_data, default=str)
    # Truncate if very large
    if len(output) > 8000:
        output = output[:8000] + '...(truncated)"}'
    return output


async def _tag(
    session: AsyncSession,
    media_id: Optional[int],
    media_ids: Optional[List[int]],
    tags: Optional[List[str]],
    operation: str,
) -> str:
    from utils.websocket import broadcast_media_updated

    if operation == "list":
        # List all available tags
        result = await session.execute(select(Tag).order_by(Tag.tag_text))
        all_tags = result.scalars().all()
        return json.dumps([{"id": t.id, "name": t.tag_text} for t in all_tags])

    if not tags:
        return "Error: tags list is required for tag action"

    # Resolve target media IDs
    ids = _collect_media_ids(media_id, media_ids)
    if not ids:
        return "Error: media_id or media_ids is required for tag action"

    tag_ids = await _resolve_or_create_tags(session, tags)

    if operation == "add":
        added = 0
        for mid in ids:
            for tid in tag_ids:
                existing = await session.execute(
                    select(MediaTag).where(
                        and_(MediaTag.media_id == mid, MediaTag.tag_id == tid)
                    )
                )
                if not existing.scalar_one_or_none():
                    session.add(MediaTag(media_id=mid, tag_id=tid))
                    added += 1
        await session.commit()

        # Broadcast updates
        media_result = await session.execute(
            select(MediaItem).where(MediaItem.id.in_(ids))
        )
        await broadcast_media_updated(media_result.scalars().all(), ["tags"], session)
        return json.dumps({"status": "ok", "added": added, "tags": tags})

    elif operation == "remove":
        removed = 0
        for mid in ids:
            for tid in tag_ids:
                result = await session.execute(
                    delete(MediaTag).where(
                        and_(MediaTag.media_id == mid, MediaTag.tag_id == tid)
                    )
                )
                removed += result.rowcount
        await session.commit()

        media_result = await session.execute(
            select(MediaItem).where(MediaItem.id.in_(ids))
        )
        await broadcast_media_updated(media_result.scalars().all(), ["tags"], session)
        return json.dumps({"status": "ok", "removed": removed, "tags": tags})

    return f"Error: Unknown operation '{operation}'. Use: add, remove, list"


async def _marker(
    session: AsyncSession,
    media_id: Optional[int],
    media_ids: Optional[List[int]],
    marker_name: Optional[str],
    operation: str,
) -> str:
    from utils.websocket import broadcast_media_updated

    if operation == "list":
        # List all available markers
        result = await session.execute(select(Marker).order_by(Marker.name))
        all_markers = result.scalars().all()
        return json.dumps([m.to_dict() for m in all_markers])

    if not marker_name:
        return "Error: marker_name is required for marker action"

    # Resolve marker by name
    result = await session.execute(
        select(Marker).where(Marker.name == marker_name)
    )
    marker = result.scalar_one_or_none()
    if not marker:
        # Try case-insensitive
        result = await session.execute(
            select(Marker).where(Marker.name.ilike(marker_name))
        )
        marker = result.scalar_one_or_none()
    if not marker:
        return f"Error: Marker '{marker_name}' not found. Use operation='list' to see available markers."

    ids = _collect_media_ids(media_id, media_ids)
    if not ids:
        return "Error: media_id or media_ids is required for marker action"

    if operation == "add":
        added = 0
        for mid in ids:
            existing = await session.execute(
                select(MediaMarker).where(
                    and_(MediaMarker.media_id == mid, MediaMarker.marker_id == marker.id)
                )
            )
            row = existing.scalar_one_or_none()
            if row:
                if row.source != "manual":
                    row.source = "manual"
            else:
                session.add(MediaMarker(media_id=mid, marker_id=marker.id, source="manual"))
                added += 1
        await session.commit()

        media_result = await session.execute(
            select(MediaItem).where(MediaItem.id.in_(ids))
        )
        await broadcast_media_updated(media_result.scalars().all(), ["markers"], session)
        return json.dumps({"status": "ok", "added": added, "marker": marker_name})

    elif operation == "remove":
        removed = 0
        for mid in ids:
            result = await session.execute(
                delete(MediaMarker).where(
                    and_(MediaMarker.media_id == mid, MediaMarker.marker_id == marker.id)
                )
            )
            removed += result.rowcount
        await session.commit()

        media_result = await session.execute(
            select(MediaItem).where(MediaItem.id.in_(ids))
        )
        await broadcast_media_updated(media_result.scalars().all(), ["markers"], session)
        return json.dumps({"status": "ok", "removed": removed, "marker": marker_name})

    return f"Error: Unknown operation '{operation}'. Use: add, remove, list"


async def _board(
    session: AsyncSession,
    media_id: Optional[int],
    media_ids: Optional[List[int]],
    board_name: Optional[str],
    board_id: Optional[int],
    section_name: Optional[str],
    section_id: Optional[int],
    operation: str,
    project_id: Optional[int] = None,
) -> str:
    from utils.websocket import ws_manager

    if operation == "list":
        q = select(Board).where(Board.deleted_at.is_(None))
        if project_id is not None:
            q = q.where(Board.project_id == project_id)
        result = await session.execute(q.order_by(Board.updated_at.desc()))
        boards = result.scalars().all()
        return json.dumps([b.to_dict() for b in boards])

    if operation == "create":
        if not board_name:
            return "Error: board_name is required to create a board"
        board = Board(name=board_name, project_id=project_id)
        session.add(board)
        await session.flush()
        session.add(BoardSection(board_id=board.id, name=None, is_default=True, display_order=0))
        await session.commit()
        await session.refresh(board)
        board_payload = (await serialize_board(board, session)).model_dump()
        await ws_manager.broadcast("board_created", {"board": board_payload})
        return json.dumps({"status": "ok", "board": board_payload})

    board = None
    if board_id:
        result = await session.execute(
            select(Board).where(
                Board.id == board_id,
                Board.deleted_at.is_(None),
            )
        )
        board = result.scalar_one_or_none()
    elif board_name:
        result = await session.execute(
            select(Board).where(
                Board.name == board_name,
                Board.deleted_at.is_(None),
            )
        )
        board = result.scalar_one_or_none()

    if not board and board_name and operation == "add":
        # Auto-create board on add when board_name is given but doesn't exist
        board = Board(name=board_name, project_id=project_id)
        session.add(board)
        await session.flush()
        session.add(BoardSection(board_id=board.id, name=None, is_default=True, display_order=0))
        await session.commit()
        await session.refresh(board)
        board_payload = (await serialize_board(board, session)).model_dump()
        await ws_manager.broadcast("board_created", {"board": board_payload})

    if not board:
        return "Error: Board not found. Use operation='list' to see available boards, or operation='create' to make one."

    default_section_result = await session.execute(
        select(BoardSection).where(
            BoardSection.board_id == board.id,
            BoardSection.is_default.is_(True),
            BoardSection.deleted_at.is_(None),
        )
    )
    default_section = default_section_result.scalar_one_or_none()
    if not default_section:
        default_section = BoardSection(board_id=board.id, name=None, is_default=True, display_order=0)
        session.add(default_section)
        await session.flush()

    if operation == "delete":
        board.deleted_at = datetime.utcnow()
        await session.commit()
        await ws_manager.broadcast("board_deleted", {"board_id": board.id})
        return json.dumps({"status": "ok", "deleted": board.name})

    if operation == "rename":
        if not board_name:
            return "Error: board_name is required for rename (the new name)"
        old_name = board.name
        board.name = board_name
        await session.commit()
        await session.refresh(board)
        board_payload = (await serialize_board(board, session)).model_dump()
        await ws_manager.broadcast("board_updated", {"board": board_payload})
        return json.dumps({"status": "ok", "old_name": old_name, "new_name": board.name, "board": board_payload})

    if operation == "create_section":
        max_order = await session.scalar(
            select(func.coalesce(func.max(BoardSection.display_order), -1)).where(
                BoardSection.board_id == board.id,
                BoardSection.deleted_at.is_(None),
            )
        )
        section = BoardSection(
            board_id=board.id,
            name=section_name,
            is_default=False,
            display_order=(max_order or -1) + 1,
        )
        session.add(section)
        await session.commit()
        return json.dumps({"status": "ok", "section": section.to_dict()})

    section = None
    if section_id:
        result = await session.execute(
            select(BoardSection).where(
                BoardSection.id == section_id,
                BoardSection.board_id == board.id,
                BoardSection.deleted_at.is_(None),
            )
        )
        section = result.scalar_one_or_none()
    elif section_name:
        result = await session.execute(
            select(BoardSection).where(
                BoardSection.board_id == board.id,
                BoardSection.name == section_name,
                BoardSection.deleted_at.is_(None),
            )
        )
        section = result.scalar_one_or_none()

    if operation == "contents":
        result = await session.execute(
            select(MediaItem, BoardSection.name)
            .join(BoardItem, BoardItem.media_id == MediaItem.id)
            .join(BoardSection, BoardSection.id == BoardItem.board_section_id)
            .where(
                BoardSection.board_id == board.id,
                BoardSection.deleted_at.is_(None),
                MediaItem.deleted_at.is_(None),
            )
            .order_by(BoardSection.display_order.asc(), BoardItem.display_order.asc())
        )
        rows = result.all()
        items = [row[0] for row in rows]
        if not items:
            return json.dumps({"board": board.name, "items": [], "count": 0})
        summaries = []
        for item, resolved_section_name in rows:
            summary = _media_summary(item)
            summary["section_name"] = resolved_section_name
            summaries.append(summary)
        return json.dumps({"board": board.name, "items": summaries, "count": len(summaries)})

    if operation == "rename_section":
        if not section:
            return "Error: Section not found"
        section.name = section_name
        section.updated_at = datetime.utcnow()
        await session.commit()
        return json.dumps({"status": "ok", "section": section.to_dict()})

    if operation == "delete_section":
        if not section or section.is_default:
            return "Error: Section not found or cannot delete default section"
        section.deleted_at = datetime.utcnow()
        await session.execute(delete(BoardItem).where(BoardItem.board_section_id == section.id))
        await session.commit()
        board_payload = (await serialize_board(board, session)).model_dump()
        await ws_manager.broadcast("board_items_changed", {"board_id": board.id, "board": board_payload})
        await ws_manager.broadcast("board_updated", {"board": board_payload})
        return json.dumps({"status": "ok", "section_id": section.id})

    if operation == "set_collapsed":
        if not section:
            return "Error: Section not found"
        section.is_collapsed = True
        section.updated_at = datetime.utcnow()
        await session.commit()
        return json.dumps({"status": "ok", "section": section.to_dict()})

    ids = _collect_media_ids(media_id, media_ids)
    if not ids:
        return "Error: media_id or media_ids is required for board add/remove/move"

    if operation == "move":
        if not section:
            return "Error: section_name or section_id is required for move (the destination section)"
        target_section = section
        # Remove from any section in this board, then add to target
        all_section_ids_result = await session.execute(
            select(BoardSection.id).where(
                BoardSection.board_id == board.id,
                BoardSection.deleted_at.is_(None),
            )
        )
        all_section_ids = [row[0] for row in all_section_ids_result.all()]
        for mid in ids:
            await session.execute(
                delete(BoardItem).where(
                    and_(BoardItem.media_id == mid, BoardItem.board_section_id.in_(all_section_ids))
                )
            )
        max_order = await session.scalar(
            select(func.coalesce(func.max(BoardItem.display_order), -1)).where(BoardItem.board_section_id == target_section.id)
        )
        next_order = (max_order or -1) + 1
        for mid in ids:
            session.add(BoardItem(board_section_id=target_section.id, media_id=mid, display_order=next_order))
            next_order += 1
        board.updated_at = datetime.utcnow()
        await session.commit()
        board_payload = (await serialize_board(board, session)).model_dump()
        await ws_manager.broadcast("board_items_changed", {"board_id": board.id, "board": board_payload})
        await ws_manager.broadcast("board_updated", {"board": board_payload})
        return json.dumps({"status": "ok", "moved": len(ids), "to_section": target_section.name or "(default)", "board": board.name})

    if operation == "add":
        added = 0
        target_section = section or default_section
        max_order = await session.scalar(
            select(func.coalesce(func.max(BoardItem.display_order), -1)).where(BoardItem.board_section_id == target_section.id)
        )
        next_order = (max_order or -1) + 1
        for mid in ids:
            existing = await session.execute(
                select(BoardItem).where(
                    and_(BoardItem.media_id == mid, BoardItem.board_section_id == target_section.id)
                )
            )
            if not existing.scalar_one_or_none():
                session.add(BoardItem(board_section_id=target_section.id, media_id=mid, display_order=next_order))
                added += 1
                next_order += 1

        board.updated_at = datetime.utcnow()
        await session.commit()
        board_payload = (await serialize_board(board, session)).model_dump()
        await ws_manager.broadcast("board_items_changed", {"board_id": board.id, "board": board_payload})
        await ws_manager.broadcast("board_updated", {"board": board_payload})
        return json.dumps({"status": "ok", "added": added, "board": board.name})

    elif operation == "remove":
        removed = 0
        target_section = section
        for mid in ids:
            if target_section:
                result = await session.execute(
                    delete(BoardItem).where(
                        and_(BoardItem.media_id == mid, BoardItem.board_section_id == target_section.id)
                    )
                )
                removed += result.rowcount
            else:
                result = await session.execute(delete(BoardItem).where(BoardItem.media_id == mid))
                removed += result.rowcount

        board.updated_at = datetime.utcnow()
        await session.commit()
        board_payload = (await serialize_board(board, session)).model_dump()
        await ws_manager.broadcast("board_items_changed", {"board_id": board.id, "board": board_payload})
        await ws_manager.broadcast("board_updated", {"board": board_payload})
        return json.dumps({"status": "ok", "removed": removed, "board": board.name})

    return f"Error: Unknown operation '{operation}'. Use: add, remove, move, list, create, delete, rename, contents, create_section, rename_section, delete_section, set_collapsed"



def _collect_media_ids(
    media_id: Optional[int], media_ids: Optional[List[int]]
) -> List[int]:
    """Merge single media_id and media_ids list into a deduplicated list."""
    ids = []
    if media_id:
        ids.append(media_id)
    if media_ids:
        ids.extend(media_ids)
    return list(dict.fromkeys(ids))  # dedupe preserving order


async def _resolve_tag_ids(session: AsyncSession, tag_names: List[str]) -> List[int]:
    """Resolve tag names to IDs."""
    result = await session.execute(
        select(Tag.id).where(Tag.tag_text.in_(tag_names))
    )
    return [row[0] for row in result.fetchall()]


async def _resolve_or_create_tags(session: AsyncSession, tag_names: List[str]) -> List[int]:
    """Resolve tag names to IDs, creating any that don't exist."""
    tag_ids = []
    for name in tag_names:
        result = await session.execute(
            select(Tag).where(Tag.tag_text == name)
        )
        tag = result.scalar_one_or_none()
        if tag:
            tag_ids.append(tag.id)
        else:
            new_tag = Tag(tag_text=name)
            session.add(new_tag)
            await session.flush()
            tag_ids.append(new_tag.id)
    return tag_ids
