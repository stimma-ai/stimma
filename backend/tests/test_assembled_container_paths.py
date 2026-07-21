"""Agent-assembled containers must reference members that still resolve after staging.

assemble_set/assemble_grid write their JSON into private staging and then hand it
to stage_managed_media(), which MOVES it into objects/media/<id>/. Member paths
therefore have to survive that move — a path relative to the staging dir does not.
"""

import hashlib
import json
from pathlib import Path

import pytest
from sqlalchemy import select

from database import MediaItem
from storage_service import stage_managed_media
from structured_media import resolve_path
from tests.helpers.media import create_media_item


async def _staged_member(session, tmp_path, name: str) -> MediaItem:
    content = f"member {name}".encode()
    source = tmp_path / f"{name}.png"
    source.write_bytes(content)
    media = await create_media_item(
        session,
        file_path=source,
        file_hash=hashlib.sha256(content).hexdigest(),
        file_size=len(content),
    )
    await stage_managed_media(session, media=media, profile_id="default")
    await session.commit()
    await session.refresh(media)
    return media


async def _load(session, media_id: int) -> MediaItem:
    result = await session.execute(select(MediaItem).where(MediaItem.id == media_id))
    return result.scalar_one()


@pytest.mark.asyncio
async def test_assembled_set_member_paths_resolve_after_staging(db_session, tmp_path):
    from agent.v2.tools.assemble_set import assemble_set

    async with db_session() as session:
        members = [await _staged_member(session, tmp_path, f"set{i}") for i in range(2)]
        result = await assemble_set(
            media_ids=[m.id for m in members],
            title="Regression Set",
            session=session,
        )

    set_id = int(result.split("media_id=")[1].split(" ")[0])
    async with db_session() as session:
        set_media = await _load(session, set_id)
        expected = [(await _load(session, m.id)).file_path for m in members]

    base = Path(set_media.file_path)
    payload = json.loads(set_media.raw_metadata)
    resolved = [str(resolve_path(base, item["path"])) for item in payload["items"]]

    assert resolved == expected
    assert all(Path(p).exists() for p in resolved)


@pytest.mark.asyncio
async def test_assembled_grid_cell_paths_resolve_after_staging(db_session, tmp_path):
    from agent.v2.tools.assemble_grid import create_parameter_sweep

    async with db_session() as session:
        members = [await _staged_member(session, tmp_path, f"grid{i}") for i in range(2)]
        result = await create_parameter_sweep(
            media_ids=[m.id for m in members],
            rows=1,
            cols=2,
            row_headers=["only"],
            col_headers=["a", "b"],
            title="Regression Grid",
            session=session,
        )

    grid_id = int(result.split("media_id=")[1].split(" ")[0])
    async with db_session() as session:
        grid_media = await _load(session, grid_id)
        expected = [(await _load(session, m.id)).file_path for m in members]

    base = Path(grid_media.file_path)
    payload = json.loads(grid_media.raw_metadata)
    resolved = [str(resolve_path(base, cell["path"])) for cell in payload["cells"]]

    assert resolved == expected
    assert all(Path(p).exists() for p in resolved)
