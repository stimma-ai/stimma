"""Tests for layout bundle image-reference extraction."""

from pathlib import Path

from flow_runtime.layout_bundle import extract_all_refs, lint_image_refs


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
