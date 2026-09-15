"""Vector source is readable through native workspace tools."""
import pytest

from agent.v2.tools.read_file import read_file


@pytest.mark.asyncio
async def test_read_svg_source_and_describe_raster(tmp_path):
    (tmp_path / "mark.svg").write_text('<svg viewBox="0 0 100 20">\n<path fill="#123456"/>\n</svg>')
    result = await read_file("mark.svg", workspace_dir=str(tmp_path), offset=2, limit=1)
    assert '<path fill="#123456"/>' in result
    assert "showing 2-2" in result
    (tmp_path / "image.png").write_bytes(b"image bytes")
    result = await read_file("image.png", workspace_dir=str(tmp_path))
    assert result.startswith("[Image file:")
