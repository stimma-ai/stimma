"""Read-only batch inspection and cycle-safe traversal of recorded provenance."""

from sqlalchemy import select, func

from database import MediaItem, MediaLineage


def live_media():
    return (
        MediaItem.deleted_at.is_(None),
        MediaItem.deletion_pending_at.is_(None),
        MediaItem.ephemeral_run_id.is_(None),
    )


async def inspect_media(session, media_ids, *, detailed=True):
    from .tools.library import (
        _validate_media_ids,
        _asset_ids_for_media,
        _media_summary,
        _parse_generation_metadata,
        _build_generation_history,
    )

    ids = _validate_media_ids(media_ids)
    rows = (await session.scalars(select(MediaItem).where(MediaItem.id.in_(ids)))).all()
    by_id = {item.id: item for item in rows}
    assets = await _asset_ids_for_media(session, ids)
    items = []
    for mid in ids:
        item = by_id.get(mid)
        status = "available"
        if item is None:
            status = "missing"
        elif item.deleted_at or item.deletion_pending_at:
            status = "deleted"
        elif item.ephemeral_run_id is not None:
            status = "ephemeral"
        if status != "available":
            items.append({"media_id": mid, "status": status})
            continue
        result = {**_media_summary(item, assets.get(mid)), "status": status}
        if detailed:
            meta = _parse_generation_metadata(item)
            result.update(
                generation_metadata=meta,
                history=_build_generation_history(item, meta),
                raw_metadata=item.raw_metadata,
                provenance_status="recorded" if meta else "unrecorded",
            )
        items.append(result)
    return {"items": items}


async def traverse_lineage(
    session,
    media_ids,
    *,
    direction="parents",
    relationship="derived",
    filters=None,
    limit=20,
    offset=0,
):
    from .tools.library import (
        _validate_media_ids,
        _validate_page,
        _normalize_filters,
        _build_browse_query,
    )

    roots = _validate_media_ids(media_ids)
    _validate_page(limit, offset)
    if direction not in {"parents", "children", "ancestors", "descendants"}:
        raise ValueError(
            "direction must be parents, children, ancestors, or descendants"
        )
    if relationship not in {"derived", "inspired", "all"}:
        raise ValueError("relationship must be derived, inspired, or all")
    normalized = _normalize_filters(filters)
    upstream = direction in {"parents", "ancestors"}
    recursive = direction in {"ancestors", "descendants"}
    start = MediaLineage.media_id if upstream else MediaLineage.source_media_id
    target = MediaLineage.source_media_id if upstream else MediaLineage.media_id
    edge_conditions = (
        []
        if relationship == "all"
        else [MediaLineage.relationship_type == relationship]
    )

    reachable = (
        select(MediaItem.id.label("root_id"), MediaItem.id.label("node_id"))
        .where(MediaItem.id.in_(roots), *live_media())
        .cte("library_reachable", recursive=recursive)
    )
    if recursive:
        # UNION (not UNION ALL), with only root/node columns, terminates cycles
        # and deduplicates diamonds without losing edge or root identities.
        step = (
            select(reachable.c.root_id, target.label("node_id"))
            .select_from(reachable)
            .join(MediaLineage, start == reachable.c.node_id)
            .join(MediaItem, MediaItem.id == target)
            .where(*edge_conditions, *live_media())
        )
        reachable = reachable.union(step)

    edges = (
        select(reachable.c.root_id, MediaLineage)
        .select_from(reachable)
        .join(MediaLineage, start == reachable.c.node_id)
        .where(*edge_conditions)
    )
    if normalized:
        matches = await _build_browse_query(
            session, normalized, "created_desc", None, scope="media"
        )
        edges = edges.where(
            target.in_(matches.with_only_columns(MediaItem.id).order_by(None))
        )
    total = await session.scalar(select(func.count()).select_from(edges.subquery()))
    rows = (
        await session.execute(
            edges.order_by(reachable.c.root_id, MediaLineage.id)
            .offset(offset)
            .limit(limit)
        )
    ).all()

    ids = list(
        dict.fromkeys(
            [
                *roots,
                *[
                    mid
                    for _, edge in rows
                    for mid in (edge.source_media_id, edge.media_id)
                    if mid is not None
                ],
            ]
        )
    )
    # At most 500 roots + 1000 endpoints; inspect in bounded batches.
    items = []
    for index in range(0, len(ids), 500):
        items.extend(
            (await inspect_media(session, ids[index : index + 500], detailed=False))[
                "items"
            ]
        )
    by_id = {item["media_id"]: item for item in items}
    output_ids = list({edge.media_id for _, edge in rows})
    output_rows = (
        await session.scalars(
            select(MediaItem).where(MediaItem.id.in_(output_ids), *live_media())
        )
    ).all()
    from .tools.library import _parse_generation_metadata

    metadata = {item.id: _parse_generation_metadata(item) or {} for item in output_rows}
    result_edges = []
    for root, edge in rows:
        inputs = metadata.get(edge.media_id, {}).get("source_inputs") or []

        def matches_input(entry):
            return isinstance(entry, dict) and (
                (
                    edge.source_media_id is not None
                    and entry.get("media_id") == edge.source_media_id
                )
                or (
                    edge.source_media_id is None
                    and edge.source_file_path is not None
                    and entry.get("file_path") == edge.source_file_path
                )
            )

        recorded_input = {}
        if edge.relationship_type == "derived" and isinstance(inputs, list):
            # One source can fill multiple roles: prefer the recorded input
            # position, and only fall back to identity when unambiguous.
            candidate = (
                inputs[edge.source_order]
                if 0 <= edge.source_order < len(inputs)
                else None
            )
            matches = [entry for entry in inputs if matches_input(entry)]
            if matches_input(candidate):
                recorded_input = candidate
            elif len(matches) == 1:
                recorded_input = matches[0]
        result_edges.append(
            {
                "root_media_id": root,
                "edge_id": edge.id,
                "source_media_id": edge.source_media_id,
                "output_media_id": edge.media_id,
                "source_order": edge.source_order,
                "input_role": recorded_input.get("role"),
                "task_type": edge.task_type,
                "relationship_type": edge.relationship_type,
                "source_status": by_id[edge.source_media_id]["status"]
                if edge.source_media_id
                else ("external" if edge.source_file_path else "missing"),
                "source_file_path": edge.source_file_path
                if edge.source_media_id is None
                else None,
                "output_status": by_id[edge.media_id]["status"],
            }
        )
    return {
        "roots": roots,
        "direction": direction,
        "relationship": relationship,
        "edges": result_edges,
        "items": items,
        "total": total,
        "limit": limit,
        "offset": offset,
        "has_more": offset + len(rows) < total,
        "applied_filters": normalized,
        "provenance": "Recorded edges only. Missing/deleted/external sources may prevent traversal; inspect history for retained snapshots. No edges does not prove no ancestry.",
    }
