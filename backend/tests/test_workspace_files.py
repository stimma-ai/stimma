"""Live file sharing, confinement, archive access and round trips."""

import json
from pathlib import Path
from zipfile import ZipFile, ZipInfo

import pytest
from sqlalchemy import select
from database import Chat, ChatItem, AssetRevision, Asset
from agent.v2.tools.share_files import share_files
from agent.v2.conversation import _item_to_message
from workspace_files import resolve_file, read_zip_entry
from fastapi import HTTPException


@pytest.fixture
async def shared_workspace(db_session, tmp_path, monkeypatch):
    root = tmp_path / "chat"
    project = tmp_path / "project"
    root.mkdir()
    project.mkdir()
    monkeypatch.setattr("routes.workspace_files.get_workspace_dir", lambda *args: root)
    monkeypatch.setattr(
        "routes.workspace_files.get_project_workspace",
        lambda project_id: project if project_id else None,
    )
    async with db_session() as session:
        chat = Chat(name="File refs test")
        session.add(chat)
        await session.commit()
        await session.refresh(chat)
        yield session, chat, root, project


@pytest.mark.asyncio
async def test_share_live_files_and_missing(client, shared_workspace):
    session, chat, root, _ = shared_workspace
    (root / "nested").mkdir()
    (root / "nested/script.py").write_text("print(1)")
    result = json.loads(
        await share_files(
            [{"path": "nested/script.py", "caption": "A script"}],
            session=session,
            chat_id=chat.id,
        )
    )
    assert result["files"][0]["name"] == "script.py"
    assert "caption" not in result["files"][0]
    item = await session.scalar(select(ChatItem).where(ChatItem.chat_id == chat.id))
    assert item.item_type == "file_display"
    assert "caption" not in json.loads(item.item_metadata)["files"][0]
    assert item.media_id is None and item.asset_id is None
    url = result["files"][0]["url"]
    response = await client.get(url)
    assert response.text == "print(1)"
    assert response.headers["cache-control"] == "no-store"
    (root / "nested/script.py").write_text("print(2)")
    assert (await client.get(url)).text == "print(2)"
    assert (
        await client.get(f"/api/chats/{chat.id}/workspace/nested/script.py")
    ).text == "print(2)"
    (root / "nested/script.py").unlink()
    assert (await client.get(url)).status_code == 404


@pytest.mark.asyncio
async def test_traversal_and_invalid_roots(client, shared_workspace, tmp_path):
    session, chat, root, _ = shared_workspace
    outside = tmp_path / "secret.txt"
    outside.write_text("secret")
    (root / "link").symlink_to(outside)
    base = f"/api/chats/{chat.id}/files/chat/content"
    for path in [
        "../secret.txt",
        "/secret.txt",
        "nested/../../secret.txt",
        "bad\\path",
        "link",
        ".",
        "\x00",
    ]:
        response = await client.get(base, params={"path": path})
        assert response.status_code == 400, (path, response.text)
        assert "secret" not in response.text
    assert (
        await client.get(
            base.replace("/chat/content", "/project/content"),
            params={"path": "test.txt"},
        )
    ).status_code == 400
    result = await share_files(
        [{"path": "../secret.txt"}], session=session, chat_id=chat.id
    )
    assert result.startswith("Error:")
    assert not (
        await session.scalars(select(ChatItem).where(ChatItem.chat_id == chat.id))
    ).all()


@pytest.mark.asyncio
async def test_archive_index_entry_attach_and_conversation(client, shared_workspace):
    session, chat, root, _ = shared_workspace
    with ZipFile(root / "bundle.zip", "w") as archive:
        archive.writestr("reports/data.csv", "name,count\ncat,42\n")
        archive.writestr("reports/notes.md", "# Notes")
        archive.writestr("../unsafe.txt", "hidden")
    base = f"/api/chats/{chat.id}/files/chat"
    response = await client.get(base + "/index", params={"path": "bundle.zip"})
    assert response.status_code == 200
    assert [entry["path"] for entry in response.json()["entries"]] == [
        "reports/data.csv",
        "reports/notes.md",
    ]
    response = await client.get(
        base + "/content",
        params={"path": "bundle.zip", "entry": "reports/notes.md", "download": True},
    )
    assert response.text == "# Notes"
    assert response.headers["content-disposition"].startswith("attachment")
    assert (
        await client.get(
            base + "/content", params={"path": "bundle.zip", "entry": "../unsafe.txt"}
        )
    ).status_code == 400
    assert (
        await client.get(
            base + "/content", params={"path": "bundle.zip", "entry": "missing"}
        )
    ).status_code == 404
    response = await client.post(
        base + "/attach", json={"path": "bundle.zip", "entry": "reports/notes.md"}
    )
    assert response.status_code == 200
    ref = response.json()
    assert resolve_file(root, ref["path"]).read_text() == "# Notes"
    response = await client.post(
        f"/api/chats/{chat.id}/items",
        json={
            "item_type": "user_message",
            "message_text": "Fix this",
            "attachments": [{"workspace_ref": ref}],
        },
    )
    assert response.status_code == 200, response.text
    item = await session.get(ChatItem, response.json()["id"])
    assert ref["path"] in _item_to_message(item)["content"]


@pytest.mark.asyncio
async def test_save_file_and_entry_with_chat_lineage(client, shared_workspace):
    session, chat, root, _ = shared_workspace
    (root / "report.md").write_text("# A report")
    with ZipFile(root / "bundle.zip", "w") as archive:
        archive.writestr("nested/code.py", "print(42)")
    for request in [
        {"path": "report.md"},
        {"path": "bundle.zip", "entry": "nested/code.py"},
    ]:
        response = await client.post(
            f"/api/chats/{chat.id}/files/chat/save", json=request
        )
        assert response.status_code == 200, response.text
        saved = response.json()
        asset = await session.get(Asset, saved["asset_id"])
        revision = await session.get(AssetRevision, asset.current_revision_id)
        assert revision.primary_media_id == saved["media_id"]
        assert asset.origin_type == "chat_final"
        assert asset.origin_id == str(chat.id)


def test_archive_limits_and_symlinks(tmp_path, monkeypatch):
    archive = tmp_path / "large.zip"
    with ZipFile(archive, "w") as z:
        z.writestr("large.txt", "12345")
    monkeypatch.setattr("workspace_files.MAX_ENTRY_BYTES", 4)
    with pytest.raises(HTTPException) as exc:
        read_zip_entry(archive, "large.txt")
    assert exc.value.status_code == 413
    with ZipFile(archive, "w") as z:
        info = ZipInfo("link")
        info.external_attr = 0o120777 << 16
        z.writestr(info, "/outside")
    with pytest.raises(HTTPException) as exc:
        read_zip_entry(archive, "link")
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_project_workspace_and_deleted_chat(client, shared_workspace):
    from database import Project
    from datetime import datetime

    session, chat, root, project_root = shared_workspace
    project = Project(name="File refs project")
    session.add(project)
    await session.flush()
    chat.project_id = project.id
    await session.commit()
    (root / "same.txt").write_text("chat copy")
    (project_root / "same.txt").write_text("project copy")
    files = [
        {"root": "chat", "path": "same.txt"},
        {"root": "project", "path": "same.txt"},
    ]
    result = json.loads(await share_files(files, session=session, chat_id=chat.id))
    assert (await client.get(result["files"][0]["url"])).text == "chat copy"
    assert (await client.get(result["files"][1]["url"])).text == "project copy"
    response = await client.post(
        f"/api/chats/{chat.id}/files/project/attach", json={"path": "same.txt"}
    )
    assert response.json()["root"] == "project"
    from database import ProjectAsset

    saved = (
        await client.post(
            f"/api/chats/{chat.id}/files/project/save", json={"path": "same.txt"}
        )
    ).json()
    membership = await session.scalar(
        select(ProjectAsset).where(
            ProjectAsset.asset_id == saved["asset_id"],
            ProjectAsset.project_id == project.id,
        )
    )
    assert membership is not None
    chat.deleted_at = datetime.utcnow()
    await session.commit()
    assert (await client.get(result["files"][0]["url"])).status_code == 404


@pytest.mark.asyncio
async def test_library_archive_uses_same_entry_routes(client, shared_workspace):
    session, chat, root, _ = shared_workspace
    with ZipFile(root / "archive.zip", "w") as archive:
        archive.writestr("code.py", "print(1)")
    base = f"/api/chats/{chat.id}/files/chat"
    saved = (await client.post(base + "/save", json={"path": "archive.zip"})).json()
    params = {"path": "artifact.zip", "media_id": saved["media_id"]}
    response = await client.get(base + "/index", params=params)
    assert response.status_code == 200
    assert response.json()["entries"][0]["path"] == "code.py"
    assert (
        await client.get(base + "/content", params={**params, "entry": "code.py"})
    ).text == "print(1)"
    response = await client.post(base + "/attach", json={**params, "entry": "code.py"})
    assert response.status_code == 200
    assert (root / response.json()["path"]).read_text() == "print(1)"
    response = await client.post(base + "/save", json={**params, "entry": "code.py"})
    assert response.status_code == 200
    asset = await session.get(Asset, response.json()["asset_id"])
    assert asset.asset_type == "document"


@pytest.mark.asyncio
async def test_share_is_atomic_and_metadata_tracks_changes(client, shared_workspace):
    session, chat, root, _ = shared_workspace
    (root / "data.csv").write_text('name,count\n"a\nb",4\n')
    result = await share_files(
        [{"path": "data.csv"}, {"path": "missing.txt"}],
        session=session,
        chat_id=chat.id,
    )
    assert result.startswith("Error:")
    assert not (
        await session.scalars(select(ChatItem).where(ChatItem.chat_id == chat.id))
    ).all()
    base = f"/api/chats/{chat.id}/files/chat/info"
    info = (await client.get(base, params={"path": "data.csv"})).json()
    assert info["subtitle"] == "1 rows"
    (root / "data.csv").write_text("name,count\na,4\nb,5\n")
    updated = (await client.get(base, params={"path": "data.csv"})).json()
    assert updated["modified_ns"] != info["modified_ns"]
    assert updated["subtitle"] == "2 rows"


def test_archive_rejects_duplicates_and_invalid_zip(tmp_path):
    archive = tmp_path / "bad.zip"
    archive.write_text("not a zip")
    with pytest.raises(HTTPException) as exc:
        read_zip_entry(archive, "file")
    assert exc.value.status_code == 400
    with ZipFile(archive, "w") as z:
        z.writestr("file", "first")
        with pytest.warns(UserWarning):
            z.writestr("file", "second")
    with pytest.raises(HTTPException) as exc:
        read_zip_entry(archive, "file")
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_revision_metadata_for_file_viewers(client, shared_workspace):
    session, chat, root, _ = shared_workspace
    (root / "report.md").write_text("# Report")
    response = await client.post(
        f"/api/chats/{chat.id}/files/chat/save", json={"path": "report.md"}
    )
    saved = response.json()
    response = await client.get(f"/api/assets/{saved['asset_id']}/revisions")
    assert response.status_code == 200
    revision = response.json()["revisions"][0]
    assert revision["filename"] == "report.md"
    assert revision["file_size"] == 8
    assert revision["mime"] == "text/markdown"


@pytest.mark.asyncio
async def test_share_mixed_files_in_one_item(client, shared_workspace):
    session, chat, root, _ = shared_workspace
    (root / "script.py").write_text("print(1)")
    (root / "report.md").write_text("# Report")
    (root / "data.csv").write_text("name,count\nitem,1\n")
    from PIL import Image

    Image.new("RGB", (2, 2)).save(root / "image.png")
    with ZipFile(root / "bundle.zip", "w") as archive:
        archive.writestr("nested/readme.md", "# Readme")
    names = ["script.py", "report.md", "data.csv", "bundle.zip", "image.png"]
    result = json.loads(
        await share_files(
            [{"path": name} for name in names], session=session, chat_id=chat.id
        )
    )
    assert [file["name"] for file in result["files"]] == names
    items = list(
        await session.scalars(select(ChatItem).where(ChatItem.chat_id == chat.id))
    )
    assert len(items) == 1
    assert len(json.loads(items[0].item_metadata)["files"]) == 5
    for file in result["files"]:
        response = await client.get(file["url"])
        assert response.status_code == 200
        assert response.content == (root / file["path"]).read_bytes()


def test_portable_mime_types():
    from utils.file_mime import guess_file_mime

    assert guess_file_mime("script.ts") == "text/typescript"
    assert guess_file_mime("report.md") == "text/markdown"
    assert guess_file_mime("data.tsv") == "text/tab-separated-values"


def test_file_chip_stats_are_live_and_type_specific(tmp_path):
    from workspace_files import describe_file
    from PIL import Image

    script = tmp_path / "report.py"
    script.write_text("print(1)\nprint(2)")
    assert describe_file(1, "chat", script.name, script)["lines"] == 2
    script.write_text("print(1)\n")
    assert describe_file(1, "chat", script.name, script)["lines"] == 1
    table = tmp_path / "data.csv"
    table.write_text('name,value\n"two\nlines",1\n')
    assert describe_file(1, "chat", table.name, table)["rows"] == 1
    photo = tmp_path / "photo.jpg"
    Image.new("RGB", (640, 480)).save(photo)
    info = describe_file(1, "chat", photo.name, photo)
    assert (info["width"], info["height"]) == (640, 480)
