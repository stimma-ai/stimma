"""Brand delivery preserves decisions, source artwork and portable presentation."""
import io
import json
from pathlib import Path

import pytest
import pypdfium2 as pdfium
from PIL import Image

from packages.cover import render_cover_document
from packages.export import export_single_html
from packages.manifest import new_manifest, sha256_file
from packages.print_cover import export_pdf
from packages.recipes import RecipeError, ResolvedInput, check_determinism, describe_file, get_recipe, run_recipe


def resolved(path, role):
    return {role: ResolvedInput(role=role, path=path, hash=sha256_file(path), **describe_file(path))}


@pytest.mark.asyncio
async def test_logo_raster_keeps_color_alpha_aspect_and_original(tmp_path):
    path = tmp_path / "original.png"
    Image.new("RGBA", (800, 200), (240, 110, 40, 128)).save(path)
    spec = get_recipe("logo-exports")
    inputs = resolved(path, "artwork")
    result = await run_recipe(spec, inputs, {"png_sizes": "200,800,1600"}, tmp_path / "out", slug="sample")
    paths = {f.path for f in result.files}
    assert paths == {"original/sample-primary.png", "png/sample-primary-200.png", "png/sample-primary-800.png", "README.txt"}
    assert (tmp_path / "out/original/sample-primary.png").read_bytes() == path.read_bytes()
    with Image.open(tmp_path / "out/png/sample-primary-200.png") as image:
        assert image.size == (200, 50)
        assert image.getpixel((10, 10))[3] == 128
        assert image.getpixel((10, 10))[0] > 230
    assert await check_determinism(spec, inputs, {"png_sizes": "200,800"}) == []


@pytest.mark.asyncio
async def test_svg_each_size_renders_natively_and_pdf_keeps_vector(tmp_path):
    path = tmp_path / "wide.svg"
    path.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="800" height="200" viewBox="0 0 800 200"><path fill="#de6633" d="M0 0H800V200H0Z"/></svg>')
    calls = []

    async def renderer(given, size):
        calls.append(size)
        out = io.BytesIO()
        Image.new("RGBA", (size, size // 4), "#de6633").save(out, format="PNG")
        return out.getvalue()

    inputs = resolved(path, "artwork")
    spec = get_recipe("logo-exports")
    await run_recipe(spec, inputs, {"png_sizes": "256,512"}, tmp_path / "out", renderer=renderer)
    assert calls == [256, 512]
    assert (tmp_path / "out/original/package-primary.svg").read_bytes() == path.read_bytes()
    pdf_path = tmp_path / "out/pdf/package-primary.pdf"
    with pdfium.PdfDocument(pdf_path) as pdf:
        assert len(pdf) == 1
        assert pdf[0].get_size() == pytest.approx((600, 150))
        assert any(o.type == pdfium.raw.FPDF_PAGEOBJ_PATH for o in pdf[0].get_objects())
        assert not any(o.type == pdfium.raw.FPDF_PAGEOBJ_IMAGE for o in pdf[0].get_objects())
    assert await check_determinism(spec, inputs, {"png_sizes": "256"}, renderer=renderer) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("sizes", ["", "-2", "0,256", "8193", "256px", "256,,512"])
async def test_logo_sizes_fail_clearly(tmp_path, sizes):
    path = tmp_path / "source.png"
    Image.new("RGB", (32, 32), "red").save(path)
    with pytest.raises(RecipeError):
        await run_recipe(get_recipe("logo-exports"), resolved(path, "artwork"), {"png_sizes": sizes}, tmp_path / "out")


@pytest.mark.asyncio
async def test_palette_values_roles_and_contrast_are_reusable(tmp_path):
    path = tmp_path / "palette.json"
    path.write_text(json.dumps({"colors": [{"name": "ink", "hex": "#000000", "role": "Text"}, {"name": "paper", "hex": "#ffffff"}], "pairs": [{"foreground": "ink", "background": "paper"}, {"foreground": "ink", "background": "ink"}]}))
    spec = get_recipe("palette-exports")
    inputs = resolved(path, "palette")
    result = await run_recipe(spec, inputs, {}, tmp_path / "out")
    output = json.loads((tmp_path / "out/package-palette.json").read_text())
    assert output["colors"][0]["role"] == "Text"
    assert output["pairs"][0]["ratio"] == 21
    assert output["pairs"][0]["normal_text_aa"] is True
    assert output["pairs"][1]["large_text_aa"] is False
    assert "--paper: #FFFFFF;" in (tmp_path / "out/package-palette.css").read_text()
    assert all(not f.path.endswith("html") for f in result.files)
    assert await check_determinism(spec, inputs, {}) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [[], {"colors": []}, {"colors": [{"name": "bad;}", "hex": "#000000"}]}, {"colors": [{"name": "ink", "hex": "red"}]}, {"colors": [{"name": "ink", "hex": "#000000"}], "pairs": [{"foreground": "missing", "background": "ink"}]}])
async def test_palette_rejects_invalid_spec(tmp_path, payload):
    path = tmp_path / "palette.json"
    path.write_text(json.dumps(payload))
    with pytest.raises(RecipeError):
        await run_recipe(get_recipe("palette-exports"), resolved(path, "palette"), {}, tmp_path / "out")


def test_swatch_and_bundled_typography_survive_offline_and_pdf(tmp_path):
    font = Path(__file__).parents[1] / "render_fonts/LiberationSans-Regular.ttf"
    (tmp_path / "font.ttf").write_bytes(font.read_bytes())
    manifest = new_manifest(title="Candidate identity")
    manifest["members"] = [{"id": "m1", "name": "font.ttf", "path": "font.ttf"}]
    html, problems = render_cover_document(manifest, authored_html='''
      <div class="sp-page"><stimma-section page label="Candidate — not approved">
        <stimma-swatch value="#E87733" label="Accent &amp; emphasis" usage="Decorative &lt;not text&gt;"></stimma-swatch>
        <stimma-type ref="m1" label="Body &amp; labels · Noto Sans Regular">Useful typography.</stimma-type>
      </stimma-section></div>''', bundle_dir=tmp_path)
    assert not problems
    assert "--sp-swatch:#E87733" in html
    (tmp_path / "index.html").write_text(html)
    (tmp_path / "stimma-package.json").write_text(json.dumps(manifest))
    offline = export_single_html(tmp_path)
    assert "base64," in offline and 'url("font.ttf")' not in offline
    with pdfium.PdfDocument(export_pdf(tmp_path)) as pdf:
        assert len(pdf) == 1
        text = pdf[0].get_textpage().get_text_range()
        for expected in ("Candidate", "not approved", "Accent & emphasis", "Decorative <not text>",
                         "Body & labels", "#E87733", "Useful typography", "Made with"):
            assert expected in text


def test_components_validate_values_and_refs():
    _, problems = render_cover_document(new_manifest(title="Test"), authored_html='<stimma-swatch value="red"></stimma-swatch><stimma-type ref="missing">Text</stimma-type>')
    assert any("six-digit" in p for p in problems)
    assert any("bundled font" in p for p in problems)
