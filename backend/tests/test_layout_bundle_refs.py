"""Tests for layout bundle image-reference extraction."""

from pathlib import Path

from flow_runtime.layout_bundle import copy_referenced_images, extract_all_refs, lint_image_refs
import pytest


def test_svg_fragment_refs_are_not_file_refs(tmp_path):
    html = (
        '<svg><defs><linearGradient id="flameGrad"/></defs>'
        '<path fill="url(#flameGrad)" stroke="url( #flameGrad )"/></svg>'
    )
    assert extract_all_refs(html) == []
    assert lint_image_refs(html, tmp_path) == []


def test_real_file_refs_still_detected(tmp_path):
    html = '<img src="hero.png"><div style="background: url(missing.png)"></div>'
    (tmp_path / "hero.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    missing = lint_image_refs(html, tmp_path)
    assert missing == ["missing.png"]


def test_external_and_data_refs_ignored(tmp_path):
    html = (
        '<img src="https://example.com/a.png">'
        '<img src="data:image/png;base64,AAAA">'
        '<div style="background: url(/absolute/b.png)"></div>'
    )
    assert extract_all_refs(html) == []


def test_css_fonts_are_bundled_without_same_name_collisions(tmp_path):
    for folder, data in (("heading", b"heading font"), ("body", b"body font")):
        (tmp_path / folder).mkdir()
        (tmp_path / folder / "Regular.ttf").write_bytes(data)
    html = '<style>@font-face{font-family:H;src:url("heading/Regular.ttf")}@font-face{font-family:B;src:url(body/Regular.ttf)}</style>'
    assert lint_image_refs(html, tmp_path) == []
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    rewritten = copy_referenced_images(html, tmp_path, bundle)
    refs = extract_all_refs(rewritten)
    assert len(set(refs)) == 2
    assert [(bundle / ref).read_bytes() for ref in refs] == [b"heading font", b"body font"]
    assert lint_image_refs(rewritten, bundle) == []
    assert "unsupported resource" in lint_image_refs('<img src="heading/Regular.ttf">', tmp_path)[0]


@pytest.mark.asyncio
async def test_create_layout_bundles_font_from_css_parameter(tmp_path):
    from PIL import ImageFont
    from agent.v2.tools.create_layout import create_layout

    (tmp_path / "fonts").mkdir()
    font = ImageFont.load_default(size=16).path.getvalue()
    (tmp_path / "fonts/Heading.ttf").write_bytes(font)
    path = await create_layout(html='<p>A real local font</p>',
                               css="@font-face{font-family:H;src:url('fonts/Heading.ttf')}p{font-family:H}",
                               width=800, height=300, workspace_dir=str(tmp_path))
    bundle = Path(path)
    assert (bundle / "Heading.ttf").read_bytes() == font
    html = (bundle / "index.html").read_text()
    assert "url('Heading.ttf')" in html
    assert 'data-stimma-width="800" data-stimma-height="300"' in html
