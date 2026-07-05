"""Recorded generation settings + full ancestor chain for a media item.

Available in BOTH chat and flow scopes: flow chats deliberately exclude the
library/call_tool/run_code tools (to keep those namespaces out of program.py),
but turning an asset into a repeatable flow needs its provenance — which
tool made it, with which parameters, fed by which parents in which input
roles, all the way to the roots. Chat needs the same walk: reading only the
final asset's generation_params and replaying the last step silently drops
upstream hops.
"""

import json
import os
from typing import Any, Dict, List

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..tools_registry import tool, ToolParameter

from core.logging import get_logger
from database import MediaItem, MediaLineage

log = get_logger(__name__)

# Ancestor-chain cap: deep enough for any real creative chain, small enough
# that a pathological lineage graph can't flood the context.
_MAX_ANCESTORS = 20


async def _sources_for(
    session: AsyncSession, item: MediaItem, gen: Dict[str, Any]
) -> List[Dict[str, Any]]:
    """Parents of one item with input roles where recorded.

    generation_metadata.source_inputs carries roles (first_frame, source_image,
    …); MediaLineage rows fill in parents recorded without one, plus external
    file sources and upscale-superseded originals.
    """
    sources: List[Dict[str, Any]] = []
    seen: set = set()
    for entry in gen.get("source_inputs") or []:
        if isinstance(entry, dict) and entry.get("media_id"):
            sources.append({"media_id": entry["media_id"], "role": entry.get("role")})
            seen.add(entry["media_id"])

    rows = await session.execute(
        select(MediaLineage)
        .where(MediaLineage.media_id == item.id)
        .order_by(MediaLineage.source_order)
    )
    for link in rows.scalars().all():
        if link.source_media_id and link.source_media_id not in seen:
            sources.append({
                "media_id": link.source_media_id,
                "role": None,
                "task_type": link.task_type,
            })
            seen.add(link.source_media_id)
        elif not link.source_media_id and link.source_file_path:
            sources.append({"external_file": link.source_file_path, "role": None})

    superseded = await session.execute(
        select(MediaItem.id).where(MediaItem.superseded_by == item.id)
    )
    for (sid,) in superseded.fetchall():
        if sid not in seen:
            sources.append({"media_id": sid, "role": "superseded_source"})
            seen.add(sid)
    return sources


async def _describe(session: AsyncSession, item: MediaItem) -> Dict[str, Any]:
    """One hop of the chain: identity, recorded tool + full parameter surface, parents."""
    from .library import _parse_generation_metadata

    gen = _parse_generation_metadata(item) or {}
    stored = dict(gen.get("parameters") or {})
    entry: Dict[str, Any] = {
        "media_id": item.id,
        "filename": os.path.basename(item.file_path or "") or None,
        "file_format": item.file_format,
        "width": item.width,
        "height": item.height,
        "tool_id": item.tool_id or gen.get("tool_id"),
        "task_type": gen.get("task_type"),
        "prompt": gen.get("prompt") or item.extracted_prompt,
        "parameters": stored,
        "sources": await _sources_for(session, item, gen),
    }
    negative = gen.get("negative_prompt") or stored.get("negative_prompt")
    if negative:
        entry["negative_prompt"] = negative
    return entry


async def build_media_info(session: AsyncSession, media_id: int) -> Dict[str, Any]:
    """The item's recorded generation info plus its full ancestor chain.

    Ancestors are breadth-first from the item's parents (nearest hops first),
    deduplicated, cycle-safe, capped at _MAX_ANCESTORS.
    """
    result = await session.execute(select(MediaItem).where(MediaItem.id == media_id))
    item = result.scalar_one_or_none()
    if not item:
        raise ValueError(f"Media {media_id} not found")
    if item.deleted_at:
        raise ValueError(f"Media {media_id} has been deleted")

    info = await _describe(session, item)
    ancestors: List[Dict[str, Any]] = []
    seen = {media_id}
    queue = [s["media_id"] for s in info["sources"] if s.get("media_id")]
    truncated = False
    while queue:
        if len(ancestors) >= _MAX_ANCESTORS:
            truncated = True
            break
        mid = queue.pop(0)
        if mid in seen:
            continue
        seen.add(mid)
        result = await session.execute(select(MediaItem).where(MediaItem.id == mid))
        ancestor = result.scalar_one_or_none()
        if not ancestor:
            ancestors.append({"media_id": mid, "missing": True})
            continue
        entry = await _describe(session, ancestor)
        if ancestor.deleted_at:
            entry["deleted"] = True
        ancestors.append(entry)
        queue.extend(s["media_id"] for s in entry["sources"] if s.get("media_id"))
    info["ancestors"] = ancestors
    if truncated:
        info["ancestors_truncated"] = True

    if not info["tool_id"] and not ancestors:
        info["note"] = (
            "No generating tool was recorded for this item (imported or "
            "externally-created) and it has no recorded ancestors — there are "
            "no settings to reuse."
        )
    return info


@tool(
    name="media_info",
    description=(
        "Get a media item's recorded generation settings AND its full ancestor chain: "
        "per hop, the tool_id that made it, task_type, prompt, every recorded parameter, "
        "and which parent fed which input role. Use this before reproducing, varying, or "
        "turning an asset into a reusable flow — the visible item is often the END of a "
        "chain (e.g. generate → restyle → outpaint), and replaying only its last step "
        "silently drops the upstream hops. In flows, pair with params_from=<media_id> to "
        "inherit a hop's recorded knobs at runtime."
    ),
    parameters=[
        ToolParameter(
            name="media_id",
            type="integer",
            description="Library media id to inspect",
            required=True,
        ),
    ],
    scope="both",
)
async def media_info(media_id: int | None = None, **kwargs) -> str:
    session: AsyncSession = kwargs.get("session")
    if session is None:
        return "Error: no database session available"
    if media_id is None:
        return "Error: media_id is required"
    try:
        info = await build_media_info(session, int(media_id))
    except ValueError as e:
        return f"Error: {e}"
    except Exception as e:
        log.error(f"media_info failed for media {media_id}: {e}")
        return f"Error: failed to load media info: {e}"
    return json.dumps(info, default=str)
