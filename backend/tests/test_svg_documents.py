"""Tests for the SVG document type.

Covers the parts that are cheap to get wrong and expensive to notice:
sanitization (this is a security boundary), size resolution (drives grid
aspect ratios), format registration (an unregistered format silently
classifies as an image), and the export toolkit's encoders.
"""

import io
import json
import zipfile
from pathlib import Path

import pytest
from httpx import AsyncClient
from PIL import Image

from tests.helpers.media import create_media_item
from utils import svg_doc

SIMPLE = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24">'
    '<circle cx="12" cy="12" r="10" fill="currentColor"/></svg>'
)


class TestParsing:
    def test_rejects_empty(self):
        with pytest.raises(svg_doc.SvgParseError):
            svg_doc.parse_svg("")

    def test_rejects_malformed(self):
        with pytest.raises(svg_doc.SvgParseError):
            svg_doc.parse_svg("<svg><rect></svg>")

    def test_rejects_non_svg_root(self):
        with pytest.raises(svg_doc.SvgParseError) as exc:
            svg_doc.parse_svg("<html><body/></html>")
        assert "expected <svg>" in str(exc.value)

    def test_strips_doctype(self):
        """DOCTYPE is the entity-expansion surface; no legitimate SVG needs one."""
        text = (
            '<!DOCTYPE svg [<!ENTITY boom "aaaaaaaa">]>'
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 4 4"><rect width="4" height="4"/></svg>'
        )
        clean, doc = svg_doc.prepare_text(text)
        assert "DOCTYPE" not in clean
        assert "ENTITY" not in clean
        assert (doc.width, doc.height) == (4, 4)

    def test_rejects_oversized(self):
        with pytest.raises(svg_doc.SvgParseError):
            svg_doc.parse_svg("<svg>" + "x" * (svg_doc.MAX_SVG_BYTES + 1) + "</svg>")


class TestSizing:
    def test_width_height_attributes(self):
        assert svg_doc.intrinsic_size(svg_doc.parse_svg(SIMPLE)) == (24, 24)

    def test_falls_back_to_viewbox(self):
        text = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 50"><rect/></svg>'
        assert svg_doc.intrinsic_size(svg_doc.parse_svg(text)) == (100, 50)

    def test_percentage_size_falls_back_to_viewbox(self):
        """A percentage size is unresolvable without a viewport, so viewBox wins."""
        text = (
            '<svg xmlns="http://www.w3.org/2000/svg" width="100%" height="100%" '
            'viewBox="0 0 32 16"><rect/></svg>'
        )
        assert svg_doc.intrinsic_size(svg_doc.parse_svg(text)) == (32, 16)

    def test_absolute_units_convert_to_px(self):
        text = '<svg xmlns="http://www.w3.org/2000/svg" width="1in" height="72pt"><rect/></svg>'
        assert svg_doc.intrinsic_size(svg_doc.parse_svg(text)) == (96, 96)

    def test_no_size_information_uses_default(self):
        text = '<svg xmlns="http://www.w3.org/2000/svg"><rect/></svg>'
        assert svg_doc.intrinsic_size(svg_doc.parse_svg(text)) == (
            svg_doc.DEFAULT_SIZE,
            svg_doc.DEFAULT_SIZE,
        )

    def test_single_dimension_derives_the_other_from_viewbox(self):
        text = '<svg xmlns="http://www.w3.org/2000/svg" width="200" viewBox="0 0 100 50"><rect/></svg>'
        assert svg_doc.intrinsic_size(svg_doc.parse_svg(text)) == (200, 100)

    def test_viewbox_is_normalized_onto_every_document(self):
        text = '<svg xmlns="http://www.w3.org/2000/svg" width="40" height="20"><rect/></svg>'
        clean, _doc = svg_doc.prepare_text(text)
        assert 'viewBox="0 0 40 20"' in clean


class TestInkTone:
    """The viewer's Auto ground rides on this: get it wrong and the person is
    shown an empty rectangle where their icon should be."""

    @pytest.mark.parametrize("body,expected", [
        # The common icon shape: strokes inheriting currentColor, which renders
        # black through <img>.
        ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
         'stroke="currentColor"><rect x="4" y="4" width="16" height="16"/></svg>', "dark"),
        # No paint stated at all — SVG's initial fill is black.
        ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
         '<circle cx="12" cy="12" r="8"/></svg>', "dark"),
        ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
         '<rect width="24" height="24" fill="#ffffff"/></svg>', "light"),
        ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
         '<rect width="24" height="24" style="fill:#f5f5f5"/></svg>', "light"),
        # Two tones cannot both be legible on one ground.
        ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
         '<rect width="10" height="10" fill="#111"/>'
         '<rect x="12" width="10" height="10" fill="#eee"/></svg>', "mixed"),
        # Paint this cannot reduce to a flat color.
        ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
         '<rect width="24" height="24" fill="url(#g)"/></svg>', "mixed"),
    ])
    def test_classifies_paint(self, body, expected):
        assert svg_doc.ink_tone(svg_doc.parse_svg(body)) == expected

    def test_defs_do_not_count_as_paint(self):
        """A template inside <defs> never lands on the canvas, so its color must
        not drag the whole document to 'mixed'."""
        text = (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
            '<defs><rect id="t" width="4" height="4" fill="#ffffff"/></defs>'
            '<circle cx="12" cy="12" r="8" fill="#000000"/></svg>'
        )
        assert svg_doc.ink_tone(svg_doc.parse_svg(text)) == "dark"

    def test_thumbnail_grounding_reads_the_file(self, tmp_path):
        """Vector thumbnails bake their ground in, so every surface that shows
        one — chips, grids, boards — inherits the right answer."""
        from routes.media_files import _SVG_GROUND_FOR_INK, _svg_ink_tone

        icon = tmp_path / "icon.svg"
        icon.write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
            'stroke="currentColor"><rect x="4" y="4" width="16" height="16"/></svg>'
        )
        assert _SVG_GROUND_FOR_INK[_svg_ink_tone(str(icon))] == (255, 255, 255)

        # Unreadable or unparseable falls back to 'mixed', which grounds nothing
        # and leaves the thumbnail transparent.
        assert _svg_ink_tone(str(tmp_path / "absent.svg")) == "mixed"
        assert "mixed" not in _SVG_GROUND_FOR_INK


class TestSanitize:
    @pytest.mark.parametrize("hostile,gone", [
        ('<script>alert(1)</script>', 'script'),
        ('<foreignObject><div/></foreignObject>', 'foreignObject'),
    ])
    def test_removes_executable_elements(self, hostile, gone):
        text = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 4 4">{hostile}</svg>'
        clean, doc = svg_doc.prepare_text(text)
        assert gone not in clean
        assert doc.removed

    def test_removes_event_handlers(self):
        text = (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 4 4" onload="alert(1)">'
            '<rect onclick="alert(2)"/></svg>'
        )
        clean, _doc = svg_doc.prepare_text(text)
        assert "onload" not in clean
        assert "onclick" not in clean

    def test_removes_external_image(self):
        text = (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 4 4">'
            '<image href="https://example.invalid/x.png" width="4" height="4"/></svg>'
        )
        clean, _doc = svg_doc.prepare_text(text)
        assert "example.invalid" not in clean
        assert "<image" not in clean

    def test_keeps_data_uri_image(self):
        text = (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 4 4">'
            '<image href="data:image/png;base64,AAA" width="4" height="4"/></svg>'
        )
        clean, doc = svg_doc.prepare_text(text)
        assert "data:image/png" in clean
        assert not doc.removed

    def test_keeps_fragment_references(self):
        """Gradients, masks, and <use> all depend on url(#id) — these must survive."""
        text = (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
            '<defs><linearGradient id="g"><stop stop-color="#000"/></linearGradient></defs>'
            '<rect fill="url(#g)" width="10" height="10"/></svg>'
        )
        clean, doc = svg_doc.prepare_text(text)
        assert 'url(#g)' in clean
        assert not doc.removed

    def test_removes_external_url_reference(self):
        text = (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
            '<rect fill="url(https://example.invalid/g.svg#g)" width="10" height="10"/></svg>'
        )
        clean, _doc = svg_doc.prepare_text(text)
        assert "example.invalid" not in clean

    def test_removes_relative_url_reference(self):
        """A bare relative ref is still external — it just looks harmless."""
        text = (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
            '<rect fill="url(other.svg#g)" width="10" height="10"/></svg>'
        )
        clean, _doc = svg_doc.prepare_text(text)
        assert "other.svg" not in clean

    def test_removes_css_import_and_external_url(self):
        text = (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><style>'
            '@import url(https://example.invalid/a.css); .c{fill:url(remote.svg#p)}'
            '</style></svg>'
        )
        clean, _doc = svg_doc.prepare_text(text)
        assert "@import" not in clean
        assert "example.invalid" not in clean
        assert "remote.svg" not in clean

    def test_removes_javascript_uri(self):
        text = (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
            '<a href="javascript:alert(1)"><rect width="4" height="4"/></a></svg>'
        )
        clean, _doc = svg_doc.prepare_text(text)
        assert "javascript:" not in clean

    def test_animation_is_kept_but_flagged(self):
        text = (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
            '<circle r="2"><animate attributeName="r" to="5"/></circle></svg>'
        )
        clean, doc = svg_doc.prepare_text(text)
        assert "<animate" in clean
        assert doc.is_animated

    def test_unembedded_font_is_flagged(self):
        text = (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 20">'
            '<text font-family="Helvetica Neue" x="0" y="10">Hi</text></svg>'
        )
        _clean, doc = svg_doc.prepare_text(text)
        assert any("font" in w for w in doc.warnings)

    def test_clean_document_round_trips_without_complaint(self):
        clean, doc = svg_doc.prepare_text(SIMPLE)
        assert not doc.removed
        assert not doc.warnings
        assert "currentColor" in clean
        # Re-preparing a prepared document must be a no-op.
        again, doc2 = svg_doc.prepare_text(clean)
        assert again == clean
        assert not doc2.removed


class TestFormatRegistration:
    def test_svg_is_a_recognized_scanner_extension(self):
        from media_scanner import ALL_EXTENSIONS, get_file_extension, is_supported_extension

        assert ".svg" in ALL_EXTENSIONS
        assert is_supported_extension(Path("logo.svg"))
        assert get_file_extension(Path("logo.svg")) == ".svg"

    def test_svg_is_atomic_and_structured_not_composite(self):
        from utils.query_builder import (
            ATOMIC_FORMATS,
            COMPOSITE_FORMATS,
            STRUCTURED_FORMATS,
            is_composite_format,
        )

        assert "svg" in ATOMIC_FORMATS
        assert "svg" in STRUCTURED_FORMATS
        assert "svg" not in COMPOSITE_FORMATS
        assert not is_composite_format("svg")

    def test_scanner_extracts_svg_dimensions(self, tmp_path):
        from media_scanner import extract_metadata

        svg_file = tmp_path / "mark.svg"
        svg_file.write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 60"><rect/></svg>'
        )
        meta = extract_metadata(svg_file)
        assert meta["file_format"] == "svg"
        assert (meta["width"], meta["height"]) == (120, 60)
        assert meta["has_alpha"] is True

    def test_scanner_survives_a_broken_svg(self, tmp_path):
        """A corrupt file must still index, at the default size, not crash the scan."""
        from media_scanner import extract_metadata

        svg_file = tmp_path / "broken.svg"
        svg_file.write_text("<svg><this is not xml")
        meta = extract_metadata(svg_file)
        assert meta["file_format"] == "svg"
        assert meta["width"] == svg_doc.DEFAULT_SIZE

    def test_svg_thumbnails_never_take_the_sync_path(self):
        """SVG rasterizes through the UI client, so the sync path must refuse it."""
        from routes.media_files import BROWSER_RENDERED_FORMATS

        assert "svg" in BROWSER_RENDERED_FORMATS
        assert "stimmalayout" in BROWSER_RENDERED_FORMATS

    def test_render_box_follows_the_thumbnail_size_not_the_work_area(self):
        """A 24px icon must rasterize at thumbnail size — vector has no native px."""
        from routes.media_files import _svg_render_box

        assert _svg_render_box(24, 24, 512) == (512, 512)
        # Aspect ratio survives: the long side hits the target, the short side scales.
        assert _svg_render_box(200, 100, 512) == (512, 256)
        # Oversized documents come down to the box rather than rendering huge.
        assert _svg_render_box(2048, 1024, 256) == (256, 128)
        # Degenerate sizes must not divide by zero or produce a 0px canvas.
        assert _svg_render_box(0, 0, 512) == (1, 1)


class TestUploadSanitization:
    def test_upload_sanitizes_before_hashing(self):
        """The stored bytes, the hash, and the size must all describe one document."""
        from upload_service import UploadService

        service = UploadService(profile_id="test")
        hostile = (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 8 8">'
            '<script>alert(1)</script><rect width="8" height="8"/></svg>'
        ).encode()
        clean_bytes, (w, h) = service._sanitize_svg_bytes(hostile)
        assert b"script" not in clean_bytes
        assert (w, h) == (8, 8)

    def test_upload_accepts_svg(self):
        from upload_service import UploadService

        assert ".svg" in UploadService.ALLOWED_EXTENSIONS
        assert UploadService(profile_id="test").validate_file("logo.svg") == ".svg"

    def test_unparseable_upload_passes_through_unchanged(self):
        from upload_service import UploadService

        service = UploadService(profile_id="test")
        junk = b"not an svg at all"
        out, size = service._sanitize_svg_bytes(junk)
        assert out == junk
        assert size == (svg_doc.DEFAULT_SIZE, svg_doc.DEFAULT_SIZE)


class TestFiltering:
    async def test_vectors_media_type_filter(self, client: AsyncClient, db_session, tmp_path):
        async with db_session() as session:

            await create_media_item(session, materialize_asset=True, file_path=tmp_path / "a.svg", file_format="svg")

            await create_media_item(session, materialize_asset=True, file_path=tmp_path / "b.png", file_format="png")

            await session.commit()

        response = await client.get("/api/media", params={"media_types": "vectors"})
        assert response.status_code == 200
        formats = {item["file_format"] for item in response.json()["items"]}
        assert formats == {"svg"}

    async def test_excluding_vectors_leaves_images(self, client: AsyncClient, db_session, tmp_path):
        async with db_session() as session:

            await create_media_item(session, materialize_asset=True, file_path=tmp_path / "a.svg", file_format="svg")

            await create_media_item(session, materialize_asset=True, file_path=tmp_path / "b.png", file_format="png")

            await session.commit()

        response = await client.get("/api/media", params={"excluded_media_types": "vectors"})
        assert response.status_code == 200
        formats = {item["file_format"] for item in response.json()["items"]}
        assert "svg" not in formats

    async def test_vectors_are_not_swept_up_by_the_images_filter(
        self, client: AsyncClient, db_session, tmp_path
    ):
        """The whole reason 'vector' is its own type: it must not read as an image."""
        async with db_session() as session:

            await create_media_item(session, materialize_asset=True, file_path=tmp_path / "a.svg", file_format="svg")

            await session.commit()

        response = await client.get("/api/media", params={"media_types": "images"})
        assert response.status_code == 200
        formats = {item["file_format"] for item in response.json()["items"]}
        assert "svg" not in formats


class TestServing:
    async def test_serves_sanitized_document(self, client: AsyncClient, db_session, tmp_path):
        """A file from a watched Source was never rewritten, so serving sanitizes."""
        svg_file = tmp_path / "hostile.svg"
        svg_file.write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 8 8">'
            '<script>alert(1)</script><rect width="8" height="8" fill="red"/></svg>'
        )
        async with db_session() as session:

            item = await create_media_item(session, materialize_asset=True, file_path=svg_file, file_format="svg")

            await session.commit()

        response = await client.get(f"/api/media/{item.id}/svg")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("image/svg+xml")
        assert "default-src 'none'" in response.headers["content-security-policy"]
        assert "script" not in response.text
        assert "<rect" in response.text

    async def test_info_reports_size_and_warnings(self, client: AsyncClient, db_session, tmp_path):
        svg_file = tmp_path / "worded.svg"
        svg_file.write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 40">'
            '<text font-family="Futura" x="0" y="20">Acme</text></svg>'
        )
        async with db_session() as session:

            item = await create_media_item(session, materialize_asset=True, file_path=svg_file, file_format="svg")

            await session.commit()

        data = (await client.get(f"/api/media/{item.id}/svg-info")).json()
        assert (data["width"], data["height"]) == (200, 40)
        assert data["node_count"] == 2
        assert data["ink"] == "dark"
        assert any("font" in w for w in data["warnings"])

    async def test_serves_by_db_guid_without_a_profile_header(
        self, client: AsyncClient, db_session, tmp_path
    ):
        """The viewer's <img> cannot send X-Profile-ID, so the db_guid form must work.

        Hitting the plain /media/{id}/svg route from an <img> was the original bug:
        the profile middleware 400s it, and the browser shows a broken image.
        """
        from database_registry import get_database_registry

        svg_file = tmp_path / "byguid.svg"
        svg_file.write_text(SIMPLE)
        async with db_session() as session:
            item = await create_media_item(
                session, materialize_asset=True, file_path=svg_file, file_format="svg"
            )
            await session.commit()

        db_guid = get_database_registry().get_database("default").db_guid
        response = await client.get(
            f"/api/db/{db_guid}/media/{item.id}/svg",
            headers={"X-Profile-ID": ""},
        )
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("image/svg+xml")
        assert "<circle" in response.text

    async def test_plain_route_needs_a_profile(self, client: AsyncClient):
        """Documents why the db_guid twin exists at all."""
        from httpx import ASGITransport, AsyncClient as RawClient

        raw = RawClient(transport=client._transport, base_url="http://test")
        response = await raw.get("/api/media/1/svg")
        assert response.status_code == 400

    async def test_rejects_non_svg_media(self, client: AsyncClient, db_session, tmp_path):
        async with db_session() as session:

            item = await create_media_item(session, materialize_asset=True, file_path=tmp_path / "a.png", file_format="png")

            await session.commit()

        response = await client.get(f"/api/media/{item.id}/svg")
        assert response.status_code == 400


class TestExport:
    async def test_exports_the_source(self, client: AsyncClient, db_session, tmp_path):
        svg_file = tmp_path / "mark.svg"
        svg_file.write_text(SIMPLE)
        async with db_session() as session:

            item = await create_media_item(session, materialize_asset=True, file_path=svg_file, file_format="svg")

            await session.commit()

        response = await client.post(
            f"/api/media/{item.id}/svg-export", json={"format": "svg"}
        )
        assert response.status_code == 200
        assert "<circle" in response.text

    @pytest.mark.parametrize("variant,expected", [
        ("inline", "<svg"),
        ("data-uri", "data:image/svg+xml;base64,"),
        ("symbol", "<use href=\"#mark\"/>"),
    ])
    async def test_code_variants(self, client: AsyncClient, db_session, tmp_path, variant, expected):
        svg_file = tmp_path / "mark.svg"
        svg_file.write_text(SIMPLE)
        async with db_session() as session:

            item = await create_media_item(session, materialize_asset=True, file_path=svg_file, file_format="svg")

            await session.commit()

        response = await client.post(
            f"/api/media/{item.id}/svg-export",
            json={"format": "html", "variant": variant},
        )
        assert response.status_code == 200
        assert expected in response.text

    @pytest.mark.parametrize("options", [
        {"format": "svg"},
        {"format": "html", "variant": "inline"},
    ])
    async def test_svg_exports_are_always_optimized(
        self, client: AsyncClient, db_session, tmp_path, options
    ):
        svg_file = tmp_path / "editable.svg"
        svg_file.write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" '
            'xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape" '
            'width="24" height="24">\n'
            '  <g inkscape:label="Editor layer">\n'
            '    <circle cx="12" cy="12" r="10"/>\n'
            "  </g>\n"
            "</svg>"
        )
        async with db_session() as session:
            item = await create_media_item(
                session,
                materialize_asset=True,
                file_path=svg_file,
                file_format="svg",
            )
            await session.commit()

        response = await client.post(
            f"/api/media/{item.id}/svg-export",
            json=options,
        )

        assert response.status_code == 200
        assert "Editor layer" not in response.text
        assert ">\n<" not in response.text
        assert "<circle" in response.text

    async def test_pdf_export(self, client: AsyncClient, db_session, tmp_path):
        svg_file = tmp_path / "mark.svg"
        svg_file.write_text(SIMPLE)
        async with db_session() as session:

            item = await create_media_item(session, materialize_asset=True, file_path=svg_file, file_format="svg")

            await session.commit()

        response = await client.post(
            f"/api/media/{item.id}/svg-export", json={"format": "pdf"}
        )
        assert response.status_code == 200
        assert response.content.startswith(b"%PDF")

    async def test_rejects_unknown_format(self, client: AsyncClient, db_session, tmp_path):
        svg_file = tmp_path / "mark.svg"
        svg_file.write_text(SIMPLE)
        async with db_session() as session:

            item = await create_media_item(session, materialize_asset=True, file_path=svg_file, file_format="svg")

            await session.commit()

        response = await client.post(
            f"/api/media/{item.id}/svg-export", json={"format": "tiff"}
        )
        assert response.status_code == 400

    async def test_rejects_oversized_raster(self, client: AsyncClient, db_session, tmp_path):
        svg_file = tmp_path / "mark.svg"
        svg_file.write_text(SIMPLE)
        async with db_session() as session:

            item = await create_media_item(session, materialize_asset=True, file_path=svg_file, file_format="svg")

            await session.commit()

        response = await client.post(
            f"/api/media/{item.id}/svg-export", json={"format": "png", "width": 99999}
        )
        assert response.status_code == 400


class TestIconEncoders:
    """The icon containers must build on any platform — no iconutil, no macOS.

    The tables and writers live in ``icon_spec``, shared with the app-icons
    recipe. Output-level rules are asserted against both producers in
    ``tests/test_packages_icon_spec.py``; these cover the encoders themselves.
    """

    @staticmethod
    def _renders(sizes):
        out = {}
        for size in sizes:
            img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
            img.paste(Image.new("RGBA", (size // 2 or 1, size // 2 or 1), (10, 120, 120, 255)))
            out[size] = img
        return out

    def test_icns_round_trips(self):
        import icon_spec

        payload = icon_spec.build_icns(self._renders(icon_spec.MACOS_SIZES))
        assert payload[:4] == b"icns"
        Image.open(io.BytesIO(payload)).load()

    def test_ico_contains_every_requested_size(self):
        import icon_spec

        sizes = icon_spec.WINDOWS_SIZES
        payload = icon_spec.build_ico(self._renders(sizes))
        stored = Image.open(io.BytesIO(payload)).ico.sizes()
        assert {(s, s) for s in sizes} == set(stored)

    def test_ios_catalog_names_every_entry(self):
        """A Contents.json entry with no filename is a broken asset catalog."""
        import icon_spec

        catalog = json.loads(icon_spec.ios_contents_json())
        assert catalog["images"]
        assert all("filename" in entry for entry in catalog["images"])

    def test_every_target_renders_the_sizes_its_bundle_uses(self):
        """Bundle builders index renders by size — a missing one is a KeyError."""
        import icon_spec

        for platform in icon_spec.PLATFORMS:
            rendered = set(icon_spec.sizes_for(platform))
            needed = {img.px for img in icon_spec.images_for(platform)}
            assert needed <= rendered, f"{platform} is missing renders for {needed - rendered}"

        ios = set(icon_spec.sizes_for("ios"))
        assert {icon_spec.ios_px(size, scale) for _i, size, scale in icon_spec.IOS_ENTRIES} <= ios

        android = set(icon_spec.sizes_for("android"))
        for density, _ in icon_spec.ANDROID_DENSITIES:
            assert icon_spec.android_px(density, icon_spec.LAUNCHER_DP) in android
            assert icon_spec.android_px(density, icon_spec.ADAPTIVE_DP) in android
        assert icon_spec.PLAY_STORE_PX in android

        assert {16, 32, 48, 180, 192, 512} <= set(icon_spec.sizes_for("web"))

    def test_icns_only_asks_for_sizes_the_container_stores(self):
        import icon_spec

        assert set(icon_spec.MACOS_SIZES) <= {16, 32, 64, 128, 256, 512, 1024}

    def test_ico_stays_within_the_format_ceiling(self):
        import icon_spec

        assert max(icon_spec.WINDOWS_SIZES) <= 256
        assert max(icon_spec.WEB_ICO_SIZES) <= 256


class TestRasterizeSvgSandbox:
    """`stimma.rasterize_svg` is how the agent inspects its own work in run_code."""

    @staticmethod
    def _sdk(tmp_path):
        from agent.v2.code_runtime import StimmaSDK

        sdk = StimmaSDK.__new__(StimmaSDK)
        sdk.workspace_dir = tmp_path
        sdk.project_workspace_dir = None
        return sdk

    @staticmethod
    def _fake_renderer(filled: bool):
        """Stand in for the UI client, including its 2x supersampling."""
        async def _render(text, w, h, **kwargs):
            img = Image.new("RGBA", (w * 2, h * 2), (255, 0, 0, 255) if filled else (0, 0, 0, 0))
            buf = io.BytesIO()
            img.save(buf, "PNG")
            return buf.getvalue()
        return _render

    SVG = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 50" width="100" height="50">'
        '<rect width="100" height="50" fill="red"/></svg>'
    )

    async def test_returns_the_requested_size_not_the_supersampled_one(self, tmp_path):
        """`width=16` must mean 16 pixels — checking a mark at icon size is the point."""
        from unittest.mock import patch

        sdk = self._sdk(tmp_path)
        with patch("utils.document_render.render_svg_document", self._fake_renderer(True)):
            assert (await sdk.rasterize_svg(self.SVG, width=16)).size == (16, 8)

    async def test_defaults_to_the_documents_own_size(self, tmp_path):
        from unittest.mock import patch

        sdk = self._sdk(tmp_path)
        with patch("utils.document_render.render_svg_document", self._fake_renderer(True)):
            assert (await sdk.rasterize_svg(self.SVG)).size == (100, 50)

    async def test_one_dimension_derives_the_other(self, tmp_path):
        from unittest.mock import patch

        sdk = self._sdk(tmp_path)
        with patch("utils.document_render.render_svg_document", self._fake_renderer(True)):
            assert (await sdk.rasterize_svg(self.SVG, height=100)).size == (200, 100)

    async def test_written_file_is_also_the_requested_size(self, tmp_path):
        from unittest.mock import patch

        sdk = self._sdk(tmp_path)
        with patch("utils.document_render.render_svg_document", self._fake_renderer(True)):
            out = await sdk.rasterize_svg(self.SVG, width=32, out="icon.png")
        with Image.open(out) as written:
            assert written.size == (32, 16)

    async def test_warns_when_the_render_is_empty(self, tmp_path, capsys):
        """A blank render is silent otherwise, and it is the characteristic failure."""
        from unittest.mock import patch

        sdk = self._sdk(tmp_path)
        with patch("utils.document_render.render_svg_document", self._fake_renderer(False)):
            await sdk.rasterize_svg(self.SVG, width=64)
        assert "rendered completely empty" in capsys.readouterr().out

    async def test_missing_workspace_file_is_named(self, tmp_path):
        sdk = self._sdk(tmp_path)
        with pytest.raises(FileNotFoundError):
            await sdk.rasterize_svg("nope.svg")


class TestViewBoxOverflowCheck:
    """`create_svg` measures whether geometry spills outside the viewBox.

    Small overflow is invisible at fit-to-window and clipping alone is ambiguous
    — artwork flush with the edge looks the same as artwork running past it — so
    the check renders on a widened canvas where the spill has somewhere to land.
    """

    @staticmethod
    def _renderer():
        """Rasterize <circle> honouring the viewBox, so geometry maps honestly."""
        import xml.etree.ElementTree as ET

        from PIL import ImageDraw

        async def _render(text, w, h, **kwargs):
            root = ET.fromstring(text)
            vb = [float(v) for v in root.get("viewBox").split()]
            img = Image.new("RGBA", (w * 2, h * 2), (0, 0, 0, 0))
            draw = ImageDraw.Draw(img)
            sx, sy = (w * 2) / vb[2], (h * 2) / vb[3]
            for el in root.iter():
                if el.tag.endswith("circle"):
                    cx, cy, r = (float(el.get(k)) for k in ("cx", "cy", "r"))
                    draw.ellipse(
                        [(cx - r - vb[0]) * sx, (cy - r - vb[1]) * sy,
                         (cx + r - vb[0]) * sx, (cy + r - vb[1]) * sy],
                        fill=(255, 0, 0, 255),
                    )
            buf = io.BytesIO()
            img.save(buf, "PNG")
            return buf.getvalue()
        return _render

    async def _check(self, body):
        from unittest.mock import patch

        from agent.v2.tools.create_svg import _render_check

        text = (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 1000" '
            f'width="1000" height="1000">{body}</svg>'
        )
        _clean, doc = svg_doc.prepare_text(text)
        with patch("utils.document_render.render_svg_document", self._renderer()):
            return await _render_check(doc.root, doc.width, doc.height)

    async def test_artwork_well_inside_is_quiet(self):
        _blank, warnings = await self._check('<circle cx="500" cy="500" r="400"/>')
        assert warnings == []

    async def test_full_bleed_is_not_flagged(self):
        """Artwork exactly on the boundary is a design choice, not a mistake."""
        _blank, warnings = await self._check('<circle cx="500" cy="500" r="500"/>')
        assert warnings == []

    async def test_overflow_is_reported(self):
        _blank, warnings = await self._check('<circle cx="500" cy="500" r="510"/>')
        assert warnings and "extends past the viewBox" in warnings[0]

    @pytest.mark.parametrize("body,side", [
        ('<circle cx="520" cy="500" r="500"/>', "right"),
        ('<circle cx="480" cy="500" r="500"/>', "left"),
        ('<circle cx="500" cy="520" r="500"/>', "bottom"),
        ('<circle cx="500" cy="480" r="500"/>', "top"),
    ])
    async def test_names_the_side_that_spills(self, body, side):
        """Naming the side is the difference between a hint and a fix."""
        _blank, warnings = await self._check(body)
        assert warnings
        named = warnings[0].split(" on the ")[1].split(" —")[0]
        assert side in named

    async def test_blank_document_still_reported(self):
        _blank, _warnings = await self._check('<circle cx="500" cy="500" r="0"/>')
        assert _blank == "nothing was drawn"

    async def test_renderer_unavailable_does_not_block_the_save(self):
        from unittest.mock import patch

        from agent.v2.tools.create_svg import _render_check
        from utils.document_render import LayoutRenderUnavailable

        async def _unavailable(*a, **k):
            raise LayoutRenderUnavailable("no client")

        _clean, doc = svg_doc.prepare_text(SIMPLE)
        with patch("utils.document_render.render_svg_document", _unavailable):
            blank, warnings = await _render_check(doc.root, doc.width, doc.height)
        assert blank is None and warnings == []


class TestSandboxImportDenial:
    def test_denial_names_what_is_importable(self):
        """A dead end costs a round trip; a correction does not."""
        from agent.v2.code_runtime import _import_denied_message

        message = _import_denied_message("scipy")
        assert "scipy" in message
        assert "not allowed" in message
        # The allow-list itself, so the model can pick an alternative in place.
        assert "numpy" in message
        assert "PIL" in message


class TestOptimize:
    def test_drops_comments_and_collapses_whitespace(self):
        from routes.svg_media import _optimize

        text = (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">\n'
            '  <!-- editor note -->\n'
            '  <rect width="10" height="10"/>\n'
            '</svg>'
        )
        out = _optimize(text)
        assert "editor note" not in out
        assert "\n" not in out
        assert '<rect width="10" height="10"' in out

    def test_leaves_path_data_alone(self):
        """Rounding coordinates is a fidelity judgement, not a mechanical win."""
        from routes.svg_media import _optimize

        d = "M1.23456 2.34567L9.87654 8.76543"
        text = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><path d="{d}"/></svg>'
        assert d in _optimize(text)
