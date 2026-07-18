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

    scanned, untrusted = await fast_scan_directories(
        [str(source)], excluded_paths=[app_data]
    )

    assert [item["file_path"] for item in scanned] == [str(external)]
    assert untrusted == set()


@pytest.mark.asyncio
async def test_fast_scan_rejects_source_inside_app_owned_storage(tmp_path: Path):
    app_data = tmp_path / "Stimma"
    generated = app_data / "profile" / "staging" / "generated" / "result.png"
    generated.parent.mkdir(parents=True)
    generated.write_bytes(b"png")

    scanned, untrusted = await fast_scan_directories(
        [str(generated.parent)], excluded_paths=[app_data]
    )

    assert scanned == []
    assert untrusted == {str(generated.parent)}


@pytest.mark.asyncio
async def test_fast_scan_rejects_temporary_transfer_tree(tmp_path: Path):
    transfer = tmp_path / "stimma-assets-old" / "result.png"
    transfer.parent.mkdir(parents=True)
    transfer.write_bytes(b"png")

    scanned, untrusted = await fast_scan_directories(
        [str(tmp_path)], excluded_paths=[tmp_path]
    )

    assert scanned == []
    assert untrusted == {str(tmp_path)}


@pytest.mark.asyncio
async def test_fast_scan_flags_missing_root_as_untrusted(tmp_path: Path):
    present = tmp_path / "present"
    present.mkdir()
    (present / "a.png").write_bytes(b"png")
    missing = tmp_path / "unmounted-volume"

    scanned, untrusted = await fast_scan_directories(
        [str(present), str(missing)], excluded_paths=[]
    )

    assert [item["file_path"] for item in scanned] == [str(present / "a.png")]
    assert untrusted == {str(missing)}


@pytest.mark.asyncio
async def test_fast_scan_flags_unreadable_root_as_untrusted(tmp_path: Path):
    import os

    if os.geteuid() == 0:
        pytest.skip("root bypasses directory permissions")

    locked = tmp_path / "locked"
    locked.mkdir()
    (locked / "a.png").write_bytes(b"png")
    locked.chmod(0o000)
    try:
        scanned, untrusted = await fast_scan_directories(
            [str(locked)], excluded_paths=[]
        )
    finally:
        locked.chmod(0o755)

    assert scanned == []
    assert untrusted == {str(locked)}
