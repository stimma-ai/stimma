"""Package SDK: retained workspace members with lineage, without library clutter."""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image, ImageDraw
from sqlalchemy import select

from database import Chat, MediaItem, MediaLineage
from packages.manifest import read_manifest, sha256_file
from tests.helpers.media import create_media_item


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
        recipes = await sdk.packages.recipes()
        assert any(r["id"] == "app-icons" for r in recipes)
        assert "references/app-icons" in await sdk.packages.guidance("app-icons")
        guidance = await sdk.packages.guidance("logo-exports")
        assert '"name": "artwork"' in guidance
        assert '"name": "png_sizes"' in guidance
        assert "LONGEST EDGE" in guidance

        pkg = sdk.packages.new("SDK icons")
        master = await pkg.add_member("mark.png", role="master")
        assert master == "m1"
        run_id = await pkg.run("app-icons", {"master": master}, {"background": "#FFFFFF", "platforms": ["web"], "app_name": "SDK"})
        assert run_id == "r1"
        with pytest.raises(ValueError, match="set_cover"):
            await pkg.save()
        assert pkg.media_id is None
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
        # The workspace payload is retained and the package descends from it.
        member_media = await session.get(MediaItem, manifest["members"][0]["media_id"])
        assert member_media is not None and member_media.file_hash == manifest["members"][0]["hash"]
        edges = list(await session.scalars(select(MediaLineage).where(MediaLineage.media_id == media_id)))
        assert [e.source_media_id for e in edges] == [member_media.id]
        assert media_id in sdk._session_media_ids
        status = await sdk.packages.status(media_id)
        assert status["stale"] is False


@pytest.mark.asyncio
async def test_recipe_accepts_an_added_file_reference(db_session, tmp_path):
    from agent.v2.code_runtime import StimmaSDK

    palette = tmp_path / "palette.json"
    palette.write_text('{"colors":[{"name":"ink","hex":"#172334"}]}')
    async with db_session() as session:
        chat = Chat(name="file reference")
        session.add(chat)
        await session.commit()
        sdk = StimmaSDK(session=session, chat_id=chat.id, workspace_dir=tmp_path,
                       project_workspace_dir=None, interrupt_checker=lambda: False)
        pkg = sdk.packages.new("Palette")
        ref = pkg.add_file("palette.json")
        assert ref == "extras/palette.json"
        run = await pkg.run("palette-exports", {"palette": ref})
        manifest = await pkg.manifest()
        assert palette.is_file()
        assert manifest["runs"][0]["id"] == run
        assert manifest["members"][0]["hash"] == sha256_file(palette)


@pytest.mark.asyncio
async def test_revision_note_requires_an_explicit_revision_target(db_session):
    from agent.v2.tools.show import show

    async with db_session() as session:
        result = await show(media_id=42, role="final", revision_note="Updated package",
                            session=session, chat_id=None)
        assert result.startswith("Error: revision_note requires revises=")


@pytest.mark.asyncio
async def test_showing_a_package_stages_it_as_an_artifact(db_session, tmp_path):
    """A package belongs on the artifact stage, not in the image viewer.

    The caller does not have to ask for that: a deliverable with revisions is
    an artifact by nature, and requiring `artifact=True` is how it ended up
    opening in the slideshow.
    """
    import json as _json

    from agent.v2.tools.show import show
    from database import ChatItem
    from packages.bundle import PackageBuilder

    workspace = tmp_path / "ws"
    workspace.mkdir()
    _icon(workspace / "mark.png")

    async with db_session() as session:
        chat = Chat(name="stage")
        session.add(chat)
        await session.commit()

        media = await create_media_item(
            session, file_path=workspace / "mark.png", file_hash=sha256_file(workspace / "mark.png"),
            file_format="png", width=1200, height=1200,
        )
        async with PackageBuilder(session, profile_id="default", title="Staged icons") as builder:
            await builder.run("app-icons", {"master": await builder.add_member(media.id)}, {"background": "#FFFFFF", "app_name": "Acme", "platforms": ["web"]})
            package, _asset = await builder.save()

        result = await show(role="final", media_id=package.id, session=session, chat_id=chat.id)
        assert not result.startswith("Error")

        item = await session.scalar(
            select(ChatItem).where(ChatItem.chat_id == chat.id, ChatItem.item_type == "media_display")
        )
        display = _json.loads(item.item_metadata)["display_data"] if isinstance(item.item_metadata, str) else item.item_metadata["display_data"]
        assert display.get("artifact"), "a package must carry the artifact blob the stage routes on"
        assert display["artifact"]["asset_id"]


@pytest.mark.asyncio
async def test_workspace_copy_reuses_original_svg_member_without_reserializing(db_session, tmp_path):
    from agent.v2.code_runtime import StimmaSDK

    source = tmp_path / 'original.svg'
    data = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><circle cx="50" cy="50" r="40"/></svg>'
    source.write_bytes(data)
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    (workspace / 'master.svg').write_bytes(data)
    async with db_session() as session:
        media = await create_media_item(session, file_path=source, file_format='svg',
                                        file_hash=sha256_file(source), width=100, height=100)
        chat = Chat(name='Shared vector')
        session.add(chat)
        await session.commit()
        sdk = StimmaSDK(session=session, chat_id=chat.id, workspace_dir=workspace,
                        project_workspace_dir=None, interrupt_checker=lambda: False)
        pkg = sdk.packages.new('Shared vector')
        member = await pkg.add_member('master.svg')
        assert await pkg.add_member(media.id) == member
        manifest = await pkg.manifest()
        assert len(manifest['members']) == 1
        assert manifest['members'][0]['media_id'] == media.id
        assert manifest['members'][0]['hash'] == sha256_file(source)
        folder = workspace / await pkg.preview()
        assert (folder / manifest['members'][0]['path']).read_bytes() == data
        # An edited copy must not resolve back to the original asset.
        (workspace / 'master.svg').write_bytes(data.replace(b'r="40"', b'r="30"'))
        edited = await pkg.add_member('master.svg')
        assert edited != member
        assert (await pkg.manifest())['members'][1]['media_id'] != media.id


@pytest.mark.asyncio
async def test_html_preview_renders_chosen_width_and_readable_slices(db_session, tmp_path, monkeypatch):
    import io
    from unittest.mock import AsyncMock
    from agent.v2.code_runtime import StimmaSDK

    raw = io.BytesIO()
    image = Image.new('RGB', (390, 2100), '#246856')
    ImageDraw.Draw(image).rectangle((0, 928, 389, 955), fill='white')
    image.save(raw, 'PNG')
    renderer = AsyncMock(return_value=raw.getvalue())
    monkeypatch.setattr('utils.local_render.render_html', renderer)
    async with db_session() as session:
        chat = Chat(name='Responsive guide')
        session.add(chat)
        await session.commit()
        sdk = StimmaSDK(session=session, chat_id=chat.id, workspace_dir=tmp_path,
                        project_workspace_dir=None, interrupt_checker=lambda: False)
        pkg = sdk.packages.new('Responsive guide')
        pkg.set_cover('<div class="sp-page"><h1>Example</h1></div>')
        preview = await pkg.preview_html(width=390)
        assert preview['width'] == 390 and preview['height'] == 2100
        assert len(preview['slices']) == 3
        assert renderer.await_args.kwargs['width'] == 390
        assert renderer.await_args.kwargs['height'] is None
        with Image.open(tmp_path / preview['slices'][1]) as strip:
            assert strip.size == (390, 960)
            assert strip.getpixel((0, 0)) == (255, 255, 255, 255)
        assert (tmp_path / preview['image']).is_file()
        assert pkg.media_id is None and (await pkg.manifest())['extras'] == []
        with pytest.raises(ValueError, match='width'):
            await pkg.preview_html(width=0)
        pkg._builder.cleanup()


@pytest.mark.asyncio
async def test_pdf_preview_shows_authored_pages_without_saving(db_session, tmp_path):
    from agent.v2.code_runtime import StimmaSDK

    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    _icon(workspace / 'mark.png')
    async with db_session() as session:
        chat = Chat(name='PDF draft')
        session.add(chat)
        await session.commit()
        sdk = StimmaSDK(session=session, chat_id=chat.id, workspace_dir=workspace,
                        project_workspace_dir=None, interrupt_checker=lambda: False)
        pkg = sdk.packages.new('PDF draft')
        await pkg.add_member('mark.png')
        pkg.set_cover('''<style>:root { --sp-bg: #123f86; --sp-fg: white; }</style>
            <div class="sp-page"><h1>Draft</h1>
            <stimma-section page layout="single" label="The work">
            <stimma-media ref="m1"></stimma-media></stimma-section></div>''')
        preview = await pkg.preview_pdf()
        assert preview['page_count'] == 2
        assert (workspace / preview['pdf']).read_bytes().startswith(b'%PDF-')
        for name in preview['pages']:
            assert not Path(name).is_absolute()
            with Image.open(workspace / name) as image:
                assert image.info.get('document-preview') == '1'
                assert image.size == (1200, 675)
                assert image.convert('RGB').getpixel((2, 2)) == (18, 63, 134)
        assert pkg.media_id is None
        assert (await pkg.manifest())['extras'] == []
        pkg._builder.cleanup()


@pytest.mark.asyncio
async def test_sdk_show_revises_package_and_preserves_prior_version(db_session, tmp_path):
    from agent.v2.code_runtime import StimmaSDK
    from database import Asset, AssetRevision

    async with db_session() as session:
        chat = Chat(name='Package revision')
        session.add(chat)
        await session.commit()
        sdk = StimmaSDK(session=session, chat_id=chat.id, workspace_dir=tmp_path,
                        project_workspace_dir=None, interrupt_checker=lambda: False)
        versions = []
        for n, color in enumerate(['red', 'blue']):
            Image.new('RGBA', (16, 16), color).save(tmp_path / f'mark-{n}.png')
            pkg = sdk.packages.new('Sprite kit')
            await pkg.add_member(f'mark-{n}.png')
            pkg.set_cover('<h1>Sprite kit</h1><stimma-media ref="m1"></stimma-media>')
            versions.append(await pkg.save())
            if n == 0:
                sdk.show(versions[-1], role='final')
                await sdk.flush()
                asset = await session.scalar(select(Asset).join(AssetRevision, AssetRevision.asset_id == Asset.id).where(AssetRevision.primary_media_id == versions[-1]))
                original_revision = asset.current_revision_id
                assert f'asset_id={asset.id}' in sdk._display_receipts[-1]
            else:
                sdk.show(versions[-1], role='final', revises=asset.id,
                         revision_note='Refined palette', parent_revision=original_revision)
                await sdk.flush()
        assets = (await session.scalars(select(Asset).where(Asset.title == "Sprite kit"))).all()
        revisions = (await session.scalars(select(AssetRevision).where(AssetRevision.asset_id == asset.id).order_by(AssetRevision.revision_number))).all()
        assert len(assets) == 1
        assert [r.primary_media_id for r in revisions] == versions
        assert [r.revision_number for r in revisions] == [1, 2]
        assert revisions[1].parent_revision_id == original_revision
        assert revisions[1].note == 'Refined palette'
        assert assets[0].current_revision_id == revisions[1].id
        assert f'asset_id={asset.id}' in sdk._display_receipts[-1]


@pytest.mark.asyncio
async def test_sdk_show_reports_rejected_revision_without_success_receipt(db_session, tmp_path):
    from agent.v2.code_runtime import StimmaSDK

    async with db_session() as session:
        sdk = StimmaSDK(session=session, chat_id=None, workspace_dir=tmp_path,
                        project_workspace_dir=None, interrupt_checker=lambda: False)
        sdk.show(42, role='final', revision_note='Updated package')
        with pytest.raises(ValueError, match='revision_note requires revises='):
            await sdk.flush()
        assert sdk._shown_media_ids == []
        assert sdk._display_receipts == []


@pytest.mark.asyncio
async def test_package_source_files_are_retained_without_library_assets(db_session, tmp_path):
    import json
    import zipfile
    from agent.v2.code_runtime import StimmaSDK
    from database import AssetRevision, MediaOwner

    with zipfile.ZipFile(tmp_path / "source.zip", "w") as archive:
        archive.writestr("source.json", json.dumps({"editable": True}))
    async with db_session() as session:
        chat = Chat(name="Portable inputs")
        session.add(chat)
        await session.commit()
        sdk = StimmaSDK(session=session, chat_id=chat.id, workspace_dir=tmp_path,
                        project_workspace_dir=None, interrupt_checker=lambda: False)
        with pytest.raises(RuntimeError, match="Unsupported library asset format"):
            await sdk.library.save("source.zip")
        assert await session.scalar(select(MediaItem).where(MediaItem.file_format == "zip")) is None
        pkg = sdk.packages.new("Portable inputs")
        member = await pkg.add_member("source.zip")
        media = pkg._builder.member(member).media
        assert await session.scalar(select(AssetRevision).where(
            AssetRevision.primary_media_id == media.id)) is None
        (tmp_path / "cover.html").write_text('<h1>Sources</h1><stimma-files></stimma-files>')
        pkg.set_cover("cover.html")
        package_id = await pkg.save()
        from packages.bundle import create_package_asset
        await create_package_asset(session, media=await session.get(MediaItem, package_id))
        assert await session.scalar(select(MediaOwner).where(
            MediaOwner.media_id == media.id, MediaOwner.deleted_at.is_(None))) is not None
        assert await session.scalar(select(AssetRevision).where(
            AssetRevision.primary_media_id == media.id)) is None
