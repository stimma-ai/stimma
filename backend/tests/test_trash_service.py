from pathlib import Path

import pytest

from trash_service import TrashService


def test_sidecar_failure_leaves_primary_for_retry(tmp_path, monkeypatch):
    primary = tmp_path / "edited.png"
    sidecar = tmp_path / "edited.png.stimmaedit.json"
    primary.write_bytes(b"image")
    sidecar.write_text('{"source_media_id": 1}', encoding="utf-8")

    real_unlink = Path.unlink

    def fail_sidecar(path, *args, **kwargs):
        if path == sidecar:
            raise PermissionError("cannot remove sidecar")
        return real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_sidecar)

    with pytest.raises(PermissionError):
        TrashService().permanently_delete(str(primary))

    assert primary.exists()
    assert sidecar.exists()


def test_permanent_delete_is_idempotent_when_files_are_missing(tmp_path):
    TrashService().permanently_delete(str(tmp_path / "already-gone.png"))
