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
