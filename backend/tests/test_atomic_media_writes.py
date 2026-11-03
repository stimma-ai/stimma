"""A failed composite serialization must not truncate the source of truth."""
import hashlib
import json

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
