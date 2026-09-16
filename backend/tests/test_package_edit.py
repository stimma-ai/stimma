"""Saved package edits preserve unrelated production files and identifiers."""
import json
from pathlib import Path

import pytest

from agent.v2.code_runtime import StimmaSDK
from database import Chat, MediaItem
from packages.bundle import PackageError
from packages.manifest import read_manifest


async def initial(session, workspace):
    chat = Chat(name="Package edits")
    session.add(chat)
    await session.commit()
    sdk = StimmaSDK(session=session, chat_id=chat.id, workspace_dir=workspace,
                    project_workspace_dir=None, interrupt_checker=lambda: False)
    for name, color in [("first", "#112233"), ("second", "#abcdef")]:
        (workspace / f"{name}.json").write_text(json.dumps({"colors": [{"name": name, "hex": color}]}))
    (workspace / "license.txt").write_text("Keep this file unchanged.")
    (workspace / "cover.html").write_text('<h1>Palette collection</h1><stimma-files></stimma-files>')
    pkg = sdk.packages.new("Palette collection")
    for name in ("first", "second"):
        mid = await pkg.add_member(f"{name}.json")
        await pkg.run("palette-exports", {"palette": mid})
    pkg.add_file("license.txt")
    pkg.set_cover("cover.html")
    media_id = await pkg.save()
    return sdk, media_id


def production(root):
    m = read_manifest(root)
    paths = [x["path"] for x in m["members"] + m["extras"]]
    paths += [f["path"] for r in m["runs"] for f in r["files"]]
    return {p: (root / p).read_bytes() for p in paths}


@pytest.mark.asyncio
async def test_open_add_keeps_saved_bytes_without_installed_recipes(db_session, tmp_path, monkeypatch):
    async with db_session() as session:
        sdk, mid = await initial(session, tmp_path)
        old_root = Path((await session.get(MediaItem, mid)).file_path)
        before = production(old_root)
        monkeypatch.setattr("packages.bundle.get_recipe", lambda *args: None)
        draft = await sdk.packages.open(mid)
        assert (await draft.manifest())["runs"] == read_manifest(old_root)["runs"]
        (tmp_path / "third.json").write_text('{"new":true}')
        assert await draft.add_member("third.json") == "m3"
        after_id = await draft.save()
        after = production(Path((await session.get(MediaItem, after_id)).file_path))
        assert all(after[p] == data for p, data in before.items())
        assert set(after) - set(before) == {"members/third.json"}
        assert production(old_root) == before


@pytest.mark.asyncio
async def test_replace_requires_rerun_and_keeps_other_run(db_session, tmp_path):
    async with db_session() as session:
        sdk, mid = await initial(session, tmp_path)
        old_root = Path((await session.get(MediaItem, mid)).file_path)
        before = production(old_root)
        old_manifest = read_manifest(old_root)
        draft = await sdk.packages.open(mid)
        (tmp_path / "replacement.json").write_text('{"colors":[{"name":"warm","hex":"#ee7722"}]}')
        await draft.replace_member("m1", "replacement.json")
        with pytest.raises(PackageError, match="require rerun"):
            await draft.preview()
        with pytest.raises(PackageError, match="require rerun"):
            await draft.save()
        await draft.rerun("r1")
        new_id = await draft.save()
        root = Path((await session.get(MediaItem, new_id)).file_path)
        manifest = read_manifest(root)
        after = production(root)
        assert manifest["runs"][1] == old_manifest["runs"][1]
        assert manifest["runs"][0]["root"] == old_manifest["runs"][0]["root"]
        assert manifest["members"][0]["path"] == "members/first.json"
        protected = [p for p in before if not p.startswith(old_manifest["runs"][0]["root"]) and p != "members/first.json"]
        assert all(after[p] == before[p] for p in protected)
        assert after["members/first.json"] != before["members/first.json"]
        assert production(old_root) == before


@pytest.mark.asyncio
async def test_replace_extra_preserves_path_and_unrelated_files(db_session, tmp_path):
    async with db_session() as session:
        sdk, mid = await initial(session, tmp_path)
        old_root = Path((await session.get(MediaItem, mid)).file_path)
        before = production(old_root)
        draft = await sdk.packages.open(mid)
        (tmp_path / "revised-notes.txt").write_text("Revised terms.")
        with pytest.raises(PackageError, match="unknown extra"):
            draft.replace_file("license.txt", "revised-notes.txt")
        with pytest.raises(PackageError, match="not found"):
            draft.replace_file("extras/license.txt", "missing.txt")
        assert production(tmp_path / await draft.preview()) == before
        assert draft.replace_file("extras/license.txt", "revised-notes.txt") == "extras/license.txt"
        after_id = await draft.save()
        root = Path((await session.get(MediaItem, after_id)).file_path)
        after = production(root)
        assert after.keys() == before.keys()
        assert after["extras/license.txt"] == b"Revised terms."
        assert all(after[p] == data for p, data in before.items() if p != "extras/license.txt")
        assert read_manifest(root)["extras"][0]["name"] == "license.txt"
        assert production(old_root) == before


@pytest.mark.asyncio
async def test_trashed_source_is_embedded_when_package_is_revised(db_session, tmp_path):
    from PIL import Image
    from sqlalchemy import select
    from database import Asset, AssetRevision, ContainerMember
    from asset_service import trash_asset
    async with db_session() as session:
        sdk, _unused = await initial(session, tmp_path)
        Image.new("RGBA", (16, 16), "red").save(tmp_path / "master.png")
        saved = await sdk.library.save("master.png")
        source_id = saved["media_id"]
        source_asset_id = saved["asset_id"]
        draft = sdk.packages.new("Retained sources")
        await draft.add_member(source_id)
        draft.set_cover('<h1>Retained sources</h1>')
        first = await draft.save()
        sdk.show(first, role="final")
        await sdk.flush()
        asset_id = await session.scalar(select(AssetRevision.asset_id).where(
            AssetRevision.primary_media_id == first))
        await trash_asset(session, asset_id=source_asset_id)
        await session.commit()
        draft = await sdk.packages.open(first)
        second = await draft.save()
        sdk.show(second, role="final", revises=asset_id, revision_note="Retain exact source")
        await sdk.flush()
        asset = await session.get(Asset, asset_id)
        member = await session.scalar(select(ContainerMember).where(
            ContainerMember.container_revision_id == asset.current_revision_id))
        assert member.embedded_media_id == source_id
        assert member.linked_asset_id is None
        assert (await session.get(Asset, source_asset_id)).state == "trashed"


@pytest.mark.asyncio
async def test_failed_show_revision_rolls_back_head_members_and_owners(db_session, tmp_path, monkeypatch):
    from sqlalchemy import select
    from database import Asset, AssetRevision, ContainerMember, MediaOwner
    from agent.v2.tools.show import _commit_show_artifact
    from packages.bundle import create_package_asset
    async with db_session() as session:
        sdk, first = await initial(session, tmp_path)
        asset = await create_package_asset(session, media=await session.get(MediaItem, first))
        asset_id, head = asset.id, asset.current_revision_id
        draft = await sdk.packages.open(first)
        source_id = (await draft.manifest())["members"][0]["media_id"]
        second = await draft.save()
        async def invalid_members(*args, **kwargs):
            return [{"embedded_media_id": source_id}, {"linked_asset_id": 99999999}]
        monkeypatch.setattr("container_service.infer_structured_member_specs", invalid_members)
        result = await _commit_show_artifact(session=session, chat_id=sdk.chat_id,
            media_id=second, revises=asset_id, revision_note="Rejected change", parent_revision=None)
        assert isinstance(result, str) and result.startswith("Error:")
        await session.commit()  # The caller may commit other work after an error.
        await session.refresh(asset)
        assert asset.current_revision_id == head
        assert await session.scalar(select(AssetRevision).where(
            AssetRevision.primary_media_id == second)) is None
        revisions = set(await session.scalars(select(AssetRevision.id)))
        assert all(m.container_revision_id in revisions for m in await session.scalars(select(ContainerMember)))
        owners = list(await session.scalars(select(MediaOwner).where(MediaOwner.root_kind == "container_revision")))
        assert all(int(o.root_id) in revisions for o in owners)


@pytest.mark.asyncio
async def test_preview_resumes_edits_across_sdk_calls_without_saving(db_session, tmp_path):
    """Inspection between calls must not lose source/run/cover/extra edits."""
    from sqlalchemy import func, select
    async with db_session() as session:
        sdk, mid = await initial(session, tmp_path)
        old = await sdk.packages.open(mid)
        original = await old.manifest()
        old._builder.cleanup()
        draft = await sdk.packages.open(mid)
        (tmp_path / 'replacement.json').write_text('{"colors":[{"name":"warm","hex":"#ee7722"}]}')
        await draft.replace_member('m1', 'replacement.json')
        await draft.rerun('r1')
        (tmp_path / 'notes.txt').write_text('Revised notes')
        draft.replace_file('extras/license.txt', 'notes.txt')
        draft.set_cover('<h1>Updated collection</h1><stimma-files></stimma-files>')
        before = await session.scalar(select(func.count()).select_from(MediaItem))
        snapshot = await draft.preview()
        expected = production(tmp_path / snapshot)
        draft._builder.cleanup()
        assert await session.scalar(select(func.count()).select_from(MediaItem)) == before
        # A fresh runtime has no surviving Python draft object.
        sdk2 = StimmaSDK(session=session, chat_id=sdk.chat_id, workspace_dir=tmp_path,
                         project_workspace_dir=None, interrupt_checker=lambda: False)
        resumed = await sdk2.packages.open(snapshot)
        assert resumed._builder.cover_source.startswith('<h1>Updated collection')
        assert (await resumed.manifest())['runs'][1] == original['runs'][1]
        assert production(tmp_path / await resumed.preview()) == expected
        # Loading snapshots copies extras too; later external edits cannot alter the draft.
        (tmp_path / snapshot / 'extras/license.txt').write_text('Changed after open')
        updated = await resumed.save()
        assert production(Path((await session.get(MediaItem, updated)).file_path)) == expected
        saved = await sdk2.packages.open(mid)
        reopened = await saved.manifest()
        assert {k: v for k, v in reopened.items() if k != 'created_at'} == {
            k: v for k, v in original.items() if k != 'created_at'}
        saved._builder.cleanup()
        with pytest.raises(PackageError, match='Package file changed'):
            await sdk2.packages.open(snapshot)
        with pytest.raises(PermissionError):
            await sdk2.packages.open(tmp_path.parent / 'outside-snapshot')


@pytest.mark.asyncio
@pytest.mark.parametrize('entry', ['stimma-package.json', '_stimma/cover.src.html'])
async def test_resume_rejects_snapshot_symlinks_outside_bundle(db_session, tmp_path, entry):
    async with db_session() as session:
        sdk, mid = await initial(session, tmp_path)
        pkg = await sdk.packages.open(mid)
        snapshot = tmp_path / await pkg.preview()
        target = snapshot / entry
        outside = tmp_path / 'outside-content'
        outside.write_bytes(target.read_bytes())
        target.unlink()
        target.symlink_to(outside)
        with pytest.raises(PackageError, match='Package file unavailable'):
            await sdk.packages.open(snapshot)
        pkg._builder.cleanup()
