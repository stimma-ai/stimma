"""A failed composite serialization must not truncate the source of truth."""
import hashlib
import json
import os
import stat

import pytest

from config_writer import atomic_write
from structured_media import write_composite_content
from tests.helpers.media import create_media_item


@pytest.mark.asyncio
async def test_composite_write_preserves_file_and_cache_on_failure(db_session, tmp_path):
    path = tmp_path / "set.stimmaset.json"
    original = b'{"items": [{"path": "original.png"}]}'
    path.write_bytes(original)
    async with db_session() as session:
        item = await create_media_item(
            session, file_path=path, file_format="stimmaset.json",
            raw_metadata=original.decode(), file_hash=hashlib.sha256(original).hexdigest(),
        )
        old_hash = item.file_hash
        with pytest.raises(TypeError):
            await write_composite_content(session, item, {"items": ["partial", object()]})
        assert path.read_bytes() == original
        assert item.raw_metadata == original.decode()
        assert item.file_hash == old_hash
        assert list(tmp_path.iterdir()) == [path]

        content = {"items": [{"path": "replacement.png"}] * 1000}
        await write_composite_content(session, item, content)
        await session.commit()
        assert json.loads(path.read_text()) == content == json.loads(item.raw_metadata)
        assert item.file_hash == hashlib.sha256(path.read_bytes()).hexdigest()
        assert item.file_size == path.stat().st_size
        assert list(tmp_path.iterdir()) == [path]

    output = tmp_path / "output.bin"
    output.write_bytes(b"complete output")
    with pytest.raises(OSError, match="interrupted write"):
        with atomic_write(output, "wb") as handle:
            handle.write(b"partial")
            raise OSError("interrupted write")
    assert output.read_bytes() == b"complete output"
    with atomic_write(output, "wb") as handle:
        handle.write(b"replacement")
    assert output.read_bytes() == b"replacement"
    assert set(tmp_path.iterdir()) == {path, output}


@pytest.mark.parametrize("existing_mode", [None, 0o644, 0o640, 0o600])
def test_atomic_write_preserves_mode_or_uses_umask(tmp_path, existing_mode):
    path = tmp_path / "set.stimmaset.json"
    if existing_mode is not None:
        path.write_text("original")
        path.chmod(existing_mode)
    previous_umask = os.umask(0o027)
    try:
        with atomic_write(path) as handle:
            handle.write("replacement")
    finally:
        os.umask(previous_umask)
    assert stat.S_IMODE(path.stat().st_mode) == (existing_mode if existing_mode is not None else 0o640)


@pytest.mark.parametrize("exists", [False, True])
def test_atomic_config_write_keeps_credentials_private(tmp_path, monkeypatch, exists):
    import config_writer
    from ruamel.yaml import YAML

    path = tmp_path / "config.yaml"
    monkeypatch.setattr(config_writer, "get_config_path", lambda: path)
    if exists:
        path.write_text("tool_providers: []")
        path.chmod(0o644)
    previous_umask = os.umask(0o022)
    try:
        config_writer._atomic_write_config({"tool_providers": [{"api_key": "test-secret"}]}, YAML())
    finally:
        os.umask(previous_umask)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
