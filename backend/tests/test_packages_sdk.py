"""stimma.packages from the run_code SDK: workspace files become members with lineage."""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image, ImageDraw
from sqlalchemy import select

from database import Chat, MediaItem, MediaLineage
from packages.manifest import read_manifest


def _icon(path: Path) -> None:
    img = Image.new("RGBA", (1200, 1200), (0, 0, 0, 0))
    ImageDraw.Draw(img).rectangle((200, 200, 1000, 1000), fill=(10, 200, 120, 255))
    img.save(path, format="PNG")


@pytest.mark.asyncio
async def test_package_draft_from_sandbox_sdk(db_session, tmp_path):
    from agent.v2.code_runtime import StimmaSDK

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _icon(workspace / "mark.png")
    (workspace / "cover.html").write_text('<h1>Hi</h1><stimma-media ref="m1"></stimma-media><stimma-files ref="r1"></stimma-files>')
    (workspace / "brief.txt").write_text("brief")

    async with db_session() as session:
        chat = Chat(name="pkg")
        session.add(chat)
        await session.commit()
        sdk = StimmaSDK(
            session=session, chat_id=chat.id, workspace_dir=workspace,
            project_workspace_dir=None, interrupt_checker=lambda: False,
        )
        recipes = sdk.packages.recipes()
        assert any(r["id"] == "app-icons" for r in recipes)

        pkg = sdk.packages.new("SDK icons")
        master = await pkg.add_member("mark.png", role="master")
        assert master == "m1"
        run_id = await pkg.run("app-icons", {"master": master}, {"platforms": ["web"], "app_name": "SDK"})
        assert run_id == "r1"
        pkg.add_file("brief.txt")
        pkg.set_cover("cover.html")
        media_id = await pkg.save()

        media = await session.get(MediaItem, media_id)
        assert media.file_format == "stimmapackage"
        manifest = read_manifest(Path(media.file_path))
        assert manifest["members"][0]["name"] == "mark.png"
        assert manifest["runs"][0]["params"]["app_name"] == "SDK"
        assert manifest["extras"][0]["name"] == "brief.txt"
        assert manifest["cover"]["kind"] == "authored"
        # The workspace file was saved to the library and the package descends from it.
        member_media = await session.get(MediaItem, manifest["members"][0]["media_id"])
        assert member_media is not None and member_media.file_hash == manifest["members"][0]["hash"]
        edges = list(await session.scalars(select(MediaLineage).where(MediaLineage.media_id == media_id)))
        assert [e.source_media_id for e in edges] == [member_media.id]
        assert media_id in sdk._session_media_ids
        status = await sdk.packages.status(media_id)
        assert status["stale"] is False
