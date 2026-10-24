import asyncio
import io
from unittest.mock import AsyncMock

from PIL import Image
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from agent.v2.code_runtime import StimmaSDK
from database import Base, MediaItem


@pytest.fixture
async def layout_session(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'layouts.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            yield session
    finally:
        await engine.dispose()


def layout_media(bundle, media_id):
    return MediaItem(
        id=media_id, file_path=str(bundle), file_hash=f"layout-{media_id}",
        file_size=1, file_format="stimmalayout", width=1200, height=630,
        megapixels=0.756,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("as_media", [False, True])
async def test_layout_export_preserves_canvas_alpha_and_source(tmp_path, monkeypatch, as_media, layout_session):
    bundle = tmp_path / "launch.stimmalayout"
    bundle.mkdir()
    source = '<html data-stimma-width="1200" data-stimma-height="630">Example</html>'
    (bundle / "index.html").write_text(source)
    raw = io.BytesIO()
    Image.new("RGBA", (2400, 1260), (40, 90, 120, 160)).save(raw, "PNG")
    render = AsyncMock(return_value=(raw.getvalue(), 1200, 630))
    monkeypatch.setattr("utils.document_render.render_layout_bundle", render)
    session = layout_session
    session.add(layout_media(bundle, 42))
    await session.commit()
    sdk = StimmaSDK(session=session, chat_id=None, workspace_dir=tmp_path,
                    project_workspace_dir=None, interrupt_checker=lambda: False)
    layout = 42 if as_media else "launch.stimmalayout"
    image = await sdk.rasterize_layout(layout)
    assert image.size == (1200, 630)
    assert image.mode == "RGBA"
    assert image.getchannel("A").getextrema() == (160, 160)
    render.assert_awaited_with(bundle, queue_timeout_s=30.0, render_timeout_s=60.0)
    path = await sdk.rasterize_layout(layout, out="exports/launch.png")
    assert path == tmp_path / "exports/launch.png"
    with Image.open(path) as exported:
        assert exported.size == (1200, 630)
    assert (bundle / "index.html").read_text() == source


@pytest.mark.asyncio
async def test_parallel_layout_exports_keep_chat_session_usable(tmp_path, monkeypatch, layout_session):
    from sqlalchemy import select

    bundle = tmp_path / "parallel.stimmalayout"
    bundle.mkdir()
    (bundle / "index.html").write_text('<html>Preview</html>')
    layout_session.add_all([layout_media(bundle, media_id) for media_id in range(1, 11)])
    await layout_session.commit()
    raw = io.BytesIO()
    Image.new("RGBA", (12, 6), "red").save(raw, "PNG")
    render = AsyncMock(return_value=(raw.getvalue(), 12, 6))
    monkeypatch.setattr("utils.document_render.render_layout_bundle", render)
    sdk = StimmaSDK(session=layout_session, chat_id=None, workspace_dir=tmp_path,
                    project_workspace_dir=None, interrupt_checker=lambda: False)

    results = await asyncio.gather(*[
        sdk.rasterize_layout(media_id, out=f"preview-{media_id}.png")
        for media_id in range(1, 11)
    ], return_exceptions=True)

    assert not [result for result in results if isinstance(result, BaseException)]
    assert all(result.is_file() for result in results)
    assert render.await_count == 10
    assert await layout_session.scalar(select(MediaItem.id).where(MediaItem.id == 1)) == 1


@pytest.mark.asyncio
async def test_layout_export_rejects_nonbundle(tmp_path):
    sdk = StimmaSDK(session=None, chat_id=None, workspace_dir=tmp_path,
                    project_workspace_dir=None, interrupt_checker=lambda: False)
    with pytest.raises(ValueError, match="layout bundle"):
        await sdk.rasterize_layout("missing.stimmalayout")


@pytest.mark.asyncio
@pytest.mark.parametrize("dpi", [True, 0, 600, float("nan"), "300"])
async def test_layout_export_rejects_invalid_density(tmp_path, dpi):
    sdk = StimmaSDK(session=None, chat_id=None, workspace_dir=tmp_path,
                    project_workspace_dir=None, interrupt_checker=lambda: False)
    with pytest.raises(ValueError, match="dpi must"):
        await sdk.rasterize_layout("card.stimmalayout", dpi=dpi)


@pytest.mark.asyncio
async def test_editable_html_export_embeds_assets_and_preserves_print_css(tmp_path):
    from pathlib import Path
    bundle = tmp_path / "card.stimmalayout"
    bundle.mkdir()
    Image.new("RGB", (20, 10), "red").save(bundle / "logo.png")
    font = Path("render_fonts/LiberationSans-Regular.ttf")
    (bundle / "font.ttf").write_bytes(font.read_bytes())
    source = '''<html data-stimma-width="560" data-stimma-height="794"><style>
    @font-face{font-family:Card;src:url("font.ttf")}
    @page{size:148mm 210mm;margin:0}
    </style><body><img src="logo.png"><p style="font-family:Card">Editable copy</p></body></html>'''
    (bundle / "index.html").write_text(source)
    sdk = StimmaSDK(session=None, chat_id=None, workspace_dir=tmp_path,
                    project_workspace_dir=None, interrupt_checker=lambda: False)
    exported = await sdk.export_layout_html("card.stimmalayout", out="delivery/card.html")
    html = exported.read_text()
    assert 'data:image/png;base64,' in html
    assert 'data:font/ttf;base64,' in html
    assert 'size:148mm 210mm' in html and 'Editable copy' in html
    assert 'src="logo.png"' not in html and 'url("font.ttf")' not in html
    assert (bundle / "index.html").read_text() == source
