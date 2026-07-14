from pathlib import Path

import pytest

from media_scanner import fast_scan_directories


@pytest.mark.asyncio
async def test_fast_scan_prunes_app_owned_storage_from_broad_source(tmp_path: Path):
    source = tmp_path / "source"
    external = source / "pictures" / "external.png"
    app_data = source / "Library" / "Stimma"
    staged = app_data / "profile" / "staging" / "generated" / "generated.png"
    managed = app_data / "profile" / "objects" / "media" / "1" / "generated.png"
    provider_asset = app_data / "cache" / "provider-assets" / "run" / "output.png"

    for path in (external, staged, managed, provider_asset):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"png")

    scanned = await fast_scan_directories(
        [str(source)], excluded_paths=[app_data]
    )

    assert [item["file_path"] for item in scanned] == [str(external)]


@pytest.mark.asyncio
async def test_fast_scan_rejects_source_inside_app_owned_storage(tmp_path: Path):
    app_data = tmp_path / "Stimma"
    generated = app_data / "profile" / "staging" / "generated" / "result.png"
    generated.parent.mkdir(parents=True)
    generated.write_bytes(b"png")

    scanned = await fast_scan_directories(
        [str(generated.parent)], excluded_paths=[app_data]
    )

    assert scanned == []


@pytest.mark.asyncio
async def test_fast_scan_rejects_temporary_transfer_tree(tmp_path: Path):
    transfer = tmp_path / "stimma-assets-old" / "result.png"
    transfer.parent.mkdir(parents=True)
    transfer.write_bytes(b"png")

    scanned = await fast_scan_directories(
        [str(tmp_path)], excluded_paths=[tmp_path]
    )

    assert scanned == []
