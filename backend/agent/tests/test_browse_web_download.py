"""Tests for browse_web action='download' and the workspace readonly guard."""

import pytest

from agent.v2.tools._workspace_files import readonly_workspace_error
from agent.v2.tools.browse_web import _download


@pytest.mark.parametrize(
    "path",
    [".stimma", ".stimma/tools/x.py", "./.stimma/tools/x.py", ".stimma/t.jpg"],
)
def test_readonly_guard_blocks_stimma_tree(path):
    assert readonly_workspace_error(path) is not None


@pytest.mark.parametrize(
    "path",
    ["notes.txt", "stimma/t.jpg", ".stimmarc", "images/ref.jpg"],
)
def test_readonly_guard_allows_ordinary_paths(path):
    assert readonly_workspace_error(path) is None


@pytest.mark.asyncio
async def test_download_saves_into_workspace(tmp_path, monkeypatch):
    async def fake_fetch(url, *, max_size_mb):
        return b"\xff\xd8fakejpeg", "image/jpeg"

    monkeypatch.setattr("agent.v2.tools.browse_web.fetch_url_bytes", fake_fetch)

    result = await _download("https://example.com/a.jpg", "images/ref.jpg", str(tmp_path))
    assert "Downloaded" in result
    assert (tmp_path / "images" / "ref.jpg").read_bytes() == b"\xff\xd8fakejpeg"


@pytest.mark.asyncio
async def test_download_rejects_non_http_url(tmp_path):
    result = await _download("file:///etc/passwd", "x.txt", str(tmp_path))
    assert result.startswith("Error")


@pytest.mark.asyncio
async def test_download_rejects_workspace_escape(tmp_path):
    result = await _download("https://example.com/a.jpg", "../escape.jpg", str(tmp_path))
    assert result.startswith("Error")


@pytest.mark.asyncio
async def test_download_rejects_readonly_tree(tmp_path):
    result = await _download("https://example.com/a.jpg", ".stimma/t.jpg", str(tmp_path))
    assert result.startswith("Error")
