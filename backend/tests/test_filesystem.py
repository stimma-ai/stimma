"""
Tests for the folder-picker browse endpoint (GET /api/fs/browse).

Covers:
- The roots listing (no path) exposes a Home root
- Listing a folder returns only visible subfolders, sorted, with counts
- Breadcrumb segments anchor at a root and walk every component below it
- ~ expansion, and rejection of relative paths, files, and missing folders
"""

import os
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.fixture(scope="module")
async def fs_client(test_app):
    from routes.filesystem import router

    test_app.include_router(router)
    transport = ASGITransport(app=test_app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"X-Profile-ID": "default"},
    ) as ac:
        yield ac


@pytest.fixture(scope="module")
def tree(tmp_path_factory) -> Path:
    """A small folder tree: two visible subfolders, one hidden, one file."""
    root = tmp_path_factory.mktemp("browse")
    (root / "beta").mkdir()
    (root / "Alpha").mkdir()
    (root / "Alpha" / "nested").mkdir()
    (root / "Alpha" / ".hidden-nested").mkdir()
    (root / ".hidden").mkdir()
    (root / "notes.txt").write_text("not a folder")
    return root


async def test_roots_listing(fs_client):
    resp = await fs_client.get("/api/fs/browse")
    assert resp.status_code == 200
    data = resp.json()
    assert data["path"] == ""
    assert data["parent"] is None
    assert data["segments"] == []
    kinds = {e["kind"] for e in data["entries"]}
    assert "home" in kinds
    home = next(e for e in data["entries"] if e["kind"] == "home")
    assert home["name"] == "Home"
    assert home["path"] == str(Path.home())
    assert all(e["is_dir"] for e in data["entries"])


async def test_lists_visible_subfolders_sorted_with_counts(fs_client, tree):
    resp = await fs_client.get("/api/fs/browse", params={"path": str(tree)})
    assert resp.status_code == 200
    data = resp.json()
    assert data["path"] == str(tree)
    assert data["parent"] == str(tree.parent)

    names = [e["name"] for e in data["entries"]]
    assert names == ["Alpha", "beta"], "case-insensitive sort, no files, no dotfolders"

    alpha = data["entries"][0]
    assert alpha["path"] == str(tree / "Alpha")
    assert alpha["is_dir"] is True
    assert alpha["item_count"] == 1, "hidden nested folder is not counted"
    assert data["entries"][1]["item_count"] == 0


async def test_segments_walk_components(fs_client, tree):
    nested = tree / "Alpha" / "nested"
    resp = await fs_client.get("/api/fs/browse", params={"path": str(nested)})
    assert resp.status_code == 200
    segments = resp.json()["segments"]
    # Every crumb is navigable: each path is a prefix of the next.
    paths = [s["path"] for s in segments]
    assert paths[-1] == str(nested)
    assert paths[-2] == str(tree / "Alpha")
    assert [s["name"] for s in segments[-2:]] == ["Alpha", "nested"]
    for shorter, longer in zip(paths, paths[1:]):
        assert longer.startswith(shorter)


async def test_segments_use_root_display_name(fs_client):
    from routes.filesystem import DirectoryEntry, path_segments

    roots = [DirectoryEntry(name="Home", path="/home/someone", kind="home")]
    segments = path_segments("/home/someone/Pictures/2024", roots)
    assert [(s.name, s.path) for s in segments] == [
        ("Home", "/home/someone"),
        ("Pictures", "/home/someone/Pictures"),
        ("2024", "/home/someone/Pictures/2024"),
    ]

    outside = path_segments("/srv/media", roots)
    assert [(s.name, s.path) for s in outside] == [
        (os.sep, os.sep),
        ("srv", "/srv"),
        ("media", "/srv/media"),
    ]


async def test_tilde_expands_to_home(fs_client):
    resp = await fs_client.get("/api/fs/browse", params={"path": "~"})
    assert resp.status_code == 200
    assert resp.json()["path"] == str(Path.home())


async def test_rejects_relative_path(fs_client):
    resp = await fs_client.get("/api/fs/browse", params={"path": "relative/dir"})
    assert resp.status_code == 400


async def test_rejects_file(fs_client, tree):
    resp = await fs_client.get("/api/fs/browse", params={"path": str(tree / "notes.txt")})
    assert resp.status_code == 400
    assert "Not a folder" in resp.json()["detail"]


async def test_missing_folder_is_404(fs_client, tree):
    resp = await fs_client.get("/api/fs/browse", params={"path": str(tree / "does-not-exist")})
    assert resp.status_code == 404
