"""Image editor proves Revision branching and managed WorkingDocuments."""

import io
import json

import pytest
from PIL import Image
from sqlalchemy import func, select

from asset_service import create_asset_from_media
from database import Asset, AssetRevision, ManagedArtifact, MediaItem
from tests.helpers.media import create_media_item, generate_test_image


def _png_bytes(color=(10, 20, 30)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (16, 12), color).save(buffer, format="PNG")
    return buffer.getvalue()


async def _save_edit(client, source_media_id, *, project, **fields):
    data = {
        "source_media_id": str(source_media_id),
        "editor_project": json.dumps(project),
        **{key: str(value).lower() if isinstance(value, bool) else str(value) for key, value in fields.items()},
    }
    return await client.post(
        "/api/media/save-edit",
        data=data,
        files={"file": ("edited.png", _png_bytes(), "image/png")},
    )


@pytest.mark.asyncio
async def test_editor_save_commits_revision_and_old_revision_save_branches(
    generation_client, generation_db_session, generation_temp_appdata_dir, tmp_path
):
    async with generation_db_session() as session:
        source_path = tmp_path / "source.png"
        source_hash = generate_test_image(source_path)
        source_media = await create_media_item(
            session, file_path=source_path, file_hash=source_hash
        )
        asset = await create_asset_from_media(session, media_id=source_media.id)
        source_revision_id = asset.current_revision_id
        asset_id = asset.id
        await session.commit()

    first = await _save_edit(
        generation_client,
        source_media.id,
        project={"layers": [{"name": "base"}]},
        asset_id=asset_id,
        base_revision_id=source_revision_id,
    )
    assert first.status_code == 200, first.text
    first_payload = first.json()
    assert first_payload["asset_id"] == asset_id

    second = await _save_edit(
        generation_client,
        source_media.id,
        project={"layers": [{"name": "alternate"}]},
        asset_id=asset_id,
        base_revision_id=source_revision_id,
    )
    assert second.status_code == 200, second.text
    second_payload = second.json()
    assert second_payload["asset_id"] == asset_id
    assert not list((generation_temp_appdata_dir / "output").rglob("upload_*"))

    async with generation_db_session() as session:
        first_revision = await session.get(AssetRevision, first_payload["revision_id"])
        second_revision = await session.get(AssetRevision, second_payload["revision_id"])
        refreshed_asset = await session.get(Asset, asset_id)
        assert first_revision.parent_revision_id == source_revision_id
        assert second_revision.parent_revision_id == source_revision_id
        assert second_revision.revision_number == 3
        assert refreshed_asset.current_revision_id == second_revision.id
        assert await session.scalar(
            select(func.count()).select_from(Asset).where(Asset.id == asset_id)
        ) == 1
        assert await session.scalar(
            select(ManagedArtifact).where(ManagedArtifact.artifact_kind == "editor_state")
        ) is not None

    project_response = await generation_client.get(
        f"/api/media/{second_payload['media_id']}/editor-project"
    )
    assert project_response.status_code == 200
    assert project_response.json()["version"] == 2
    assert project_response.json()["project"]["layers"][0]["name"] == "alternate"


@pytest.mark.asyncio
async def test_editor_save_as_new_creates_distinct_asset_with_lineage(
    generation_client, generation_db_session, tmp_path
):
    async with generation_db_session() as session:
        source_path = tmp_path / "source-new.png"
        source_hash = generate_test_image(source_path)
        source_media = await create_media_item(
            session, file_path=source_path, file_hash=source_hash
        )
        source_asset = await create_asset_from_media(session, media_id=source_media.id)
        source_asset_id = source_asset.id
        source_revision_id = source_asset.current_revision_id
        await session.commit()

    response = await _save_edit(
        generation_client,
        source_media.id,
        project={"layers": []},
        asset_id=source_asset_id,
        base_revision_id=source_revision_id,
        save_as_new=True,
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["asset_id"] != source_asset_id

    async with generation_db_session() as session:
        output = await session.get(MediaItem, payload["media_id"])
        output_revision = await session.get(AssetRevision, payload["revision_id"])
        assert output_revision.revision_number == 1
        metadata = json.loads(output.generation_metadata)
        assert metadata["source_inputs"][0]["media_id"] == source_media.id


@pytest.mark.asyncio
async def test_editor_reedit_durable_snapshot_keeps_target_asset(
    generation_client, generation_db_session, tmp_path
):
    async with generation_db_session() as session:
        source_path = tmp_path / "external-source.png"
        source_hash = generate_test_image(source_path)
        source_media = await create_media_item(
            session, file_path=source_path, file_hash=source_hash
        )
        asset = await create_asset_from_media(session, media_id=source_media.id)
        asset_id = asset.id
        source_revision_id = asset.current_revision_id
        asset_count = await session.scalar(select(func.count()).select_from(Asset))
        await session.commit()

    first = await _save_edit(
        generation_client,
        source_media.id,
        project={"layers": [{"name": "first"}]},
        asset_id=asset_id,
        base_revision_id=source_revision_id,
    )
    assert first.status_code == 200, first.text
    first_payload = first.json()
    project = await generation_client.get(
        f"/api/media/{first_payload['media_id']}/editor-project"
    )
    assert project.status_code == 200
    durable_source_id = project.json()["source_media_id"]
    assert durable_source_id != source_media.id

    second = await _save_edit(
        generation_client,
        durable_source_id,
        project={"layers": [{"name": "second"}]},
        asset_id=asset_id,
        base_revision_id=first_payload["revision_id"],
    )
    assert second.status_code == 200, second.text
    assert second.json()["asset_id"] == asset_id

    async with generation_db_session() as session:
        assert await session.scalar(select(func.count()).select_from(Asset)) == asset_count
