import io
from types import SimpleNamespace
from unittest.mock import AsyncMock

from PIL import Image
import pytest

from agent.v2.code_runtime import StimmaSDK


@pytest.mark.asyncio
@pytest.mark.parametrize("as_media", [False, True])
async def test_layout_export_preserves_canvas_alpha_and_source(tmp_path, monkeypatch, as_media):
    bundle = tmp_path / "launch.stimmalayout"
    bundle.mkdir()
    source = '<html data-stimma-width="1200" data-stimma-height="630">Example</html>'
    (bundle / "index.html").write_text(source)
    raw = io.BytesIO()
    Image.new("RGBA", (2400, 1260), (40, 90, 120, 160)).save(raw, "PNG")
    render = AsyncMock(return_value=(raw.getvalue(), 1200, 630))
    monkeypatch.setattr("utils.document_render.render_layout_bundle", render)
    session = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(
        scalar_one_or_none=lambda: SimpleNamespace(file_path=str(bundle)),
    )))
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
