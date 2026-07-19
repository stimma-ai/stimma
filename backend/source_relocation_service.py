"""Transactional rebinding of an external Source to a new filesystem root."""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from sqlalchemy import bindparam, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from database import (
    Asset,
    DeleteOperation,
    DeleteOperationItem,
    MediaItem,
    MediaLineage,
    StorageObject,
)


class SourceRelocationError(ValueError):
    """The requested root change cannot safely preserve Source identity."""


@dataclass(frozen=True)
class SourceRelocationResult:
    old_path: str
    new_path: str
    media_items_updated: int
    storage_objects_updated: int
    assets_updated: int
    lineage_paths_updated: int

    def to_dict(self) -> dict:
        return asdict(self)


def canonical_source_root(path: str, *, must_exist: bool = False) -> Path:
    """Return the canonical absolute root used by scanner-owned locators."""
    expanded = Path(path).expanduser()
    if not expanded.is_absolute():
        expanded = Path(os.path.abspath(expanded))
    try:
        return expanded.resolve(strict=must_exist)
    except (FileNotFoundError, OSError) as exc:
        raise SourceRelocationError(f"Source folder is unavailable: {path}") from exc


def _lexical_source_root(path: str) -> Path:
    expanded = Path(path).expanduser()
    if not expanded.is_absolute():
        expanded = Path(os.path.abspath(expanded))
    return expanded


def _unique_paths(paths: list[Path]) -> list[Path]:
    result: list[Path] = []
    for path in paths:
        if path not in result:
            result.append(path)
    return result


def _under_roots(column, roots: list[Path]):
    conditions = []
    for root in roots:
        root_string = str(root)
        conditions.extend(
            [
                column == root_string,
                column.startswith(root_string + os.sep, autoescape=True),
            ]
        )
    return or_(*conditions)


def _matching_root(path: Path, roots: list[Path]) -> Path | None:
    matches = [root for root in roots if path == root or root in path.parents]
    return max(matches, key=lambda root: len(root.parts)) if matches else None


def _rebase_path(path_string: str, old_roots: list[Path], new_root: Path) -> str:
    path = _lexical_source_root(path_string)
    matching_root = _matching_root(path, old_roots)
    if matching_root is None:
        resolved = path.resolve(strict=False)
        matching_root = _matching_root(resolved, old_roots)
        path = resolved
    if matching_root is None:
        raise SourceRelocationError(f"Path is outside the old Source root: {path_string}")
    return str(new_root / path.relative_to(matching_root))


def _payload_stat(path: Path, file_format: str):
    if file_format == "stimmalayout":
        path = path / "index.html"
    if not path.exists():
        raise SourceRelocationError(f"Relocated file is missing: {path}")
    if not path.is_file():
        raise SourceRelocationError(f"Relocated payload is not a file: {path}")
    return path.stat()


async def relocate_source_folder(
    session: AsyncSession,
    *,
    old_path: str,
    new_path: str,
) -> SourceRelocationResult:
    """Rebase Source-backed locators without creating or reprocessing Media.

    The caller owns the transaction and must update config only after this
    function has flushed successfully.
    """
    old_resolved = canonical_source_root(old_path)
    old_roots = _unique_paths([old_resolved, _lexical_source_root(old_path)])
    new_root = canonical_source_root(new_path, must_exist=True)
    if not new_root.is_dir():
        raise SourceRelocationError(f"Source path is not a folder: {new_path}")
    if (
        new_root == old_resolved
        or new_root in old_resolved.parents
        or old_resolved in new_root.parents
    ):
        raise SourceRelocationError("Old and new Source roots must not overlap")

    active_delete = await session.scalar(
        select(DeleteOperationItem.operation_id)
        .join(DeleteOperation, DeleteOperation.id == DeleteOperationItem.operation_id)
        .where(
            DeleteOperation.status.in_(("queued", "running")),
            _under_roots(DeleteOperationItem.file_path, old_roots),
        )
        .limit(1)
    )
    if active_delete is not None:
        raise SourceRelocationError(
            "Wait for permanent deletion to finish before relocating this Source"
        )

    media_rows = (
        await session.execute(
            select(
                MediaItem.id,
                MediaItem.file_path,
                MediaItem.file_size,
                MediaItem.file_format,
                MediaItem.modified_date,
                MediaItem.deleted_at,
                MediaItem.file_unavailable,
                MediaItem.metadata_status,
                MediaItem.clip_status,
                MediaItem.face_detection_status,
                MediaItem.vlm_caption_status,
            ).where(_under_roots(MediaItem.file_path, old_roots))
        )
    ).all()

    processing_phases = (
        "metadata_status",
        "clip_status",
        "face_detection_status",
        "vlm_caption_status",
    )
    if any(
        row._mapping[phase] == "processing"
        for row in media_rows
        for phase in processing_phases
    ):
        raise SourceRelocationError(
            "Wait for background processing to finish before relocating this Source"
        )

    rows_by_path: dict[str, list] = {}
    target_by_path: dict[str, str] = {}
    for row in media_rows:
        old_file_path = row.file_path
        rows_by_path.setdefault(old_file_path, []).append(row)
        target_by_path[old_file_path] = _rebase_path(
            old_file_path, old_roots, new_root
        )

    target_paths = set(target_by_path.values())
    existing_targets = set(
        await session.scalars(
            select(MediaItem.file_path).where(_under_roots(MediaItem.file_path, [new_root]))
        )
    )
    collisions = sorted(target_paths & existing_targets)
    if collisions:
        raise SourceRelocationError(
            f"Relocation would collide with {len(collisions)} indexed path(s) under the new root"
        )

    target_mtimes: dict[str, datetime] = {}
    for old_file_path, rows in rows_by_path.items():
        live_rows = [
            row
            for row in rows
            if row.deleted_at is None and row.file_unavailable is not True
        ]
        if not live_rows:
            continue
        current = max(live_rows, key=lambda row: row.id)
        target = Path(target_by_path[old_file_path])
        stat = _payload_stat(target, current.file_format)
        if current.file_size is not None and stat.st_size != current.file_size:
            raise SourceRelocationError(
                f"Relocated file size changed for {target}; refusing to rebind identity"
            )
        target_mtimes[old_file_path] = datetime.utcfromtimestamp(stat.st_mtime)

    media_updates = [
        {
            "relocate_id": row.id,
            "relocate_path": target_by_path[row.file_path],
            "relocate_mtime": (
                target_mtimes[row.file_path]
                if row.deleted_at is None
                and row.file_unavailable is not True
                and row.file_path in target_mtimes
                else row.modified_date
            ),
        }
        for row in media_rows
    ]
    if media_updates:
        await session.execute(
            update(MediaItem.__table__)
            .where(MediaItem.__table__.c.id == bindparam("relocate_id"))
            .values(
                file_path=bindparam("relocate_path"),
                modified_date=bindparam("relocate_mtime"),
            ),
            media_updates,
        )

    storage_rows = (
        await session.execute(
            select(StorageObject.id, StorageObject.external_path).where(
                StorageObject.kind == "external",
                _under_roots(StorageObject.external_path, old_roots),
            )
        )
    ).all()
    storage_updates = [
        {
            "relocate_id": row.id,
            "relocate_path": _rebase_path(row.external_path, old_roots, new_root),
        }
        for row in storage_rows
    ]
    if storage_updates:
        await session.execute(
            update(StorageObject.__table__)
            .where(StorageObject.__table__.c.id == bindparam("relocate_id"))
            .values(external_path=bindparam("relocate_path")),
            storage_updates,
        )

    asset_rows = (
        await session.execute(
            select(Asset.id, Asset.origin_id, Asset.updated_at).where(
                Asset.origin_type == "watched_file",
                _under_roots(Asset.origin_id, old_roots),
            )
        )
    ).all()
    asset_updates = [
        {
            "relocate_id": row.id,
            "relocate_path": _rebase_path(row.origin_id, old_roots, new_root),
            "relocate_updated_at": row.updated_at,
        }
        for row in asset_rows
    ]
    if asset_updates:
        await session.execute(
            update(Asset.__table__)
            .where(Asset.__table__.c.id == bindparam("relocate_id"))
            .values(
                origin_id=bindparam("relocate_path"),
                updated_at=bindparam("relocate_updated_at"),
            ),
            asset_updates,
        )

    lineage_rows = (
        await session.execute(
            select(MediaLineage.id, MediaLineage.source_file_path).where(
                MediaLineage.source_file_path.is_not(None),
                _under_roots(MediaLineage.source_file_path, old_roots),
            )
        )
    ).all()
    lineage_updates = [
        {
            "relocate_id": row.id,
            "relocate_path": _rebase_path(
                row.source_file_path, old_roots, new_root
            ),
        }
        for row in lineage_rows
    ]
    if lineage_updates:
        await session.execute(
            update(MediaLineage.__table__)
            .where(MediaLineage.__table__.c.id == bindparam("relocate_id"))
            .values(source_file_path=bindparam("relocate_path")),
            lineage_updates,
        )

    await session.flush()
    return SourceRelocationResult(
        old_path=str(old_resolved),
        new_path=str(new_root),
        media_items_updated=len(media_rows),
        storage_objects_updated=len(storage_rows),
        assets_updated=len(asset_rows),
        lineage_paths_updated=len(lineage_rows),
    )
