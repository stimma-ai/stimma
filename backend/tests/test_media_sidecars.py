"""Companion ownership, transport fallback and model-independent edit mapping."""
import hashlib
import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from asset_service import create_asset_from_media
from database import MediaItem, MediaSidecar, StorageObject
from media_sidecars import attach_sidecars, companions_for_media, trim_mapping
from providers.base import OutputSidecar
from providers.result_receipt import materialize_result
from storage_service import object_path, stage_managed_media, reconcile_storage
from tests.helpers.media import create_media_item
from tests.test_storage_service import _delete_asset


def mapping():
    return {"version": 1, "media_time_base": {"num": 1, "den": 24},
            "source_time_base": {"num": 1, "den": 24}, "source_extent": [0, 158],
            "spans": [{"media": [0, 158], "source": [0, 158], "preserved_streams": ["video", "audio"]}]}


def state(mapping_value=None):
    return OutputSidecar({"format": "unrelated.opaque_format", "format_version": 7,
                          "descriptor": {"not_a_tensor": [1, {"custom": True}]},
                          "media_mapping": mapping_value or mapping(),
                          "sha256": hashlib.sha256(b"opaque state").hexdigest()}, b"opaque state")


@pytest.mark.asyncio
async def test_companion_survives_source_purge_then_last_owner_deletes_it(client, db_session, tmp_path):
    async with db_session() as session:
        source_path, joined_path = tmp_path / "source.png", tmp_path / "joined.png"
        source_path.write_bytes(b"first render")
        joined_path.write_bytes(b"joined render")
        source = await create_media_item(session, file_path=source_path,
                                         file_hash=hashlib.sha256(b"first render").hexdigest())
        joined = await create_media_item(session, file_path=joined_path,
                                         file_hash=hashlib.sha256(b"joined render").hexdigest())
        await stage_managed_media(session, media=source, profile_id="default")
        await stage_managed_media(session, media=joined, profile_id="default")
        first_asset = await create_asset_from_media(session, media_id=source.id)
        joined_asset = await create_asset_from_media(session, media_id=joined.id)
        await attach_sidecars(session, media=source, sidecars=[state()], profile_id="default")
        edited = trim_mapping(mapping(), 39, 158, 24, offset_frames=600)
        await attach_sidecars(session, media=joined, sidecars=[state(edited)], profile_id="default")
        await attach_sidecars(session, media=joined, sidecars=[state(edited)], profile_id="default")
        rows = (await session.scalars(select(MediaSidecar))).all()
        assert len(rows) == 2  # Idempotent attachment; one shared content object.
        assert rows[0].storage_object_id == rows[1].storage_object_id
        storage = await session.get(StorageObject, rows[0].storage_object_id)
        blob = object_path("default", storage.object_key)
        source_id, joined_id = source.id, joined.id
        first_asset_id, joined_asset_id = first_asset.id, joined_asset.id
        await session.commit()
    await _delete_asset(client, first_asset_id)
    async with db_session() as session:
        assert await session.get(MediaItem, source_id) is None
        [record] = await companions_for_media(session, joined_id, "default")
        assert record["status"] == "available"
        assert record["media_mapping"]["spans"] == [{"media": [600, 719], "source": [39, 158], "preserved_streams": ["audio", "video"]}]
        assert blob.read_bytes() == b"opaque state"
        report = await reconcile_storage(session, profile_id="default")
        assert storage.id not in report["orphan_storage_objects"]
    await _delete_asset(client, joined_asset_id)
    assert not blob.exists()


def test_mapping_tracks_per_stream_changes_and_rejects_fractional_cuts():
    result = trim_mapping(mapping(), 39, 158, 24, offset_frames=600, preserved_streams=["video"])
    assert result["spans"][0]["preserved_streams"] == ["video"]
    assert result["spans"][0]["source"] == [39, 158]
    assert trim_mapping(mapping(), 159, 170, 24) is None


@pytest.mark.asyncio
async def test_download_receipt_retains_render_and_opaque_metadata_when_sidecar_fails(tmp_path):
    provider = type("Provider", (), {})()
    provider.download_asset = AsyncMock(side_effect=[b"render", OSError("missing companion")])
    data = {"success": True, "output": {"assets": [{"asset_id": "render.mp4", "type": "video",
             "sidecars": [{"asset_id": "state.bin", "format": "other_format", "format_version": 99,
                           "descriptor": {"freeform": True}, "media_mapping": mapping()}]}],
             "input_usage": [{"source": "native_latent"}]}}
    result = await materialize_result(provider, data, tmp_path)
    assert result.output_data == b"render"
    assert result.outputs[0].sidecars[0].info["unavailable_reason"] == "download_failed"
    assert result.metadata["input_usage"] == [{"source": "native_latent"}]
    # The saved primary is reused. Only the failed optional download is retried.
    provider.download_asset = AsyncMock(return_value=b"opaque state")
    again = await materialize_result(provider, data, tmp_path)
    provider.download_asset.assert_awaited_once_with("state.bin")
    assert again.outputs[0].sidecars[0].data == b"opaque state"
    assert json.loads(Path(tmp_path, "hashes.json").read_text())


@pytest.mark.asyncio
@pytest.mark.parametrize("materialize_asset", [False, True])
async def test_real_join_exports_and_reimports_opaque_tail_mapping(db_session, tmp_path, materialize_asset):
    import asyncio
    from types import SimpleNamespace
    from video_join import join_video

    class SDK:
        workspace_dir = tmp_path
        def _resolve_path(self, value):
            return tmp_path / value
        def _contain_av_token(self, tool, value):
            assert Path(value).resolve().is_relative_to(tmp_path.resolve())
            return value
        async def run(self, tool, *args):
            proc = await asyncio.create_subprocess_exec(tool, *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            stdout, stderr = await proc.communicate()
            assert proc.returncode == 0, stderr.decode()
            return SimpleNamespace(stdout=stdout.decode())
        async def ffmpeg(self, *args):
            return await self.run("ffmpeg", *args)
        async def ffprobe(self, *args):
            return await self.run("ffprobe", *args)

    sdk = SDK()
    source = tmp_path / "source.mp4"
    await sdk.ffmpeg("-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=64x48:rate=24", "-frames:v", "158", "-c:v", "libx264", str(source))
    async with db_session() as session:
        sdk.session = session
        media = await create_media_item(session, file_path=source, file_hash=hashlib.sha256(source.read_bytes()).hexdigest(), file_format="mp4")
        await stage_managed_media(session, media=media, profile_id="default", remove_source=False)
        await attach_sidecars(session, media=media, sidecars=[state()], profile_id="default")
        report = await join_video(sdk, [{"media_id": media.id}, {"media_id": media.id, "trim_head": 39}])
        assert report["frames"] == 277
        joined_path = Path(report["out"])
        from agent.v2.tools.library import save_workspace_file
        saved = json.loads(await save_workspace_file(session, str(joined_path), tmp_path, None,
                                                     materialize_asset=materialize_asset))
        joined = await session.get(MediaItem, saved["media_id"])
        records = await companions_for_media(session, joined.id, "default")
        assert len(records) == 2
        records.sort(key=lambda r: r["media_mapping"]["spans"][0]["media"][0])
        assert records[1]["media_mapping"]["spans"] == [{"media": [158, 277], "source": [39, 158], "preserved_streams": ["video"]}]
        assert Path(records[1]["file"]).read_bytes() == b"opaque state"
        assert records[1]["descriptor"]["not_a_tensor"] == [1, {"custom": True}]


@pytest.mark.asyncio
async def test_ephemeral_cleanup_releases_state_and_receipt(db_session, tmp_path):
    from flow_runtime.ephemeral import purge_ephemeral_run
    from database import ManagedArtifact
    from core.profile_context import ProfileScope
    async with db_session() as session:
        source = tmp_path / "ephemeral.png"
        source.write_bytes(b"ephemeral render")
        media = await create_media_item(session, file_path=source)
        media.ephemeral_run_id = "test-sidecars"
        ephemeral = state()
        ephemeral.data = b"unique ephemeral state"
        ephemeral.info["sha256"] = hashlib.sha256(ephemeral.data).hexdigest()
        await attach_sidecars(session, media=media, sidecars=[ephemeral], profile_id="default")
        [record] = await companions_for_media(session, media.id, "default")
        receipt = tmp_path / "receipt"
        receipt.mkdir()
        (receipt / "raw.bin").write_bytes(b"opaque state")
        session.add(ManagedArtifact(owner_kind="media", owner_id=str(media.id), media_id=media.id,
                                   artifact_kind="generation_receipt", locator=str(receipt)))
        await session.commit()
        with ProfileScope("default"):
            assert await purge_ephemeral_run(session, "test-sidecars") == 1
        assert not Path(record["file"]).exists()
        assert not receipt.exists()


@pytest.mark.asyncio
async def test_asset_info_and_browse_include_generic_companion_facts(client, db_session, tmp_path):
    async with db_session() as session:
        path = tmp_path / "facts.png"
        path.write_bytes(b"facts render")
        media = await create_media_item(session, file_path=path)
        asset = await create_asset_from_media(session, media_id=media.id)
        await attach_sidecars(session, media=media, sidecars=[state()], profile_id="default")
        asset_id, media_id = asset.id, media.id
        await session.commit()
    detail = await client.get(f"/api/assets/{asset_id}")
    assert detail.status_code == 200
    assert detail.json()["media"]["sidecars"][0]["descriptor"]["not_a_tensor"] == [1, {"custom": True}]
    listing = (await client.get("/api/assets")).json()["items"]
    [listed] = [r for r in listing if r["asset"]["id"] == asset_id]
    assert listed["media"]["sidecars"][0]["format"] == "unrelated.opaque_format"
    browsing = (await client.get("/api/assets/browse")).json()["items"]
    [browsed] = [r for r in browsing if r["media_id"] == media_id]
    assert browsed["sidecars"][0]["status"] == "available"
