import importlib.util
from pathlib import Path
import tarfile


SCRIPT = Path(__file__).parents[2] / "scripts" / "package_python_runtime.py"
SPEC = importlib.util.spec_from_file_location("package_python_runtime", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_runtime_archive_is_deterministic_and_has_normal_root_layout(tmp_path):
    source = tmp_path / "python"
    output = tmp_path / "out"
    (source / "Lib" / "example").mkdir(parents=True)
    (source / "python.exe").write_bytes(b"python executable")
    (source / "Lib" / "example" / "module.py").write_text("value = 1\n", encoding="utf-8")

    first = MODULE.package_runtime(source, output)
    second = MODULE.package_runtime(source, output)

    assert first["sha256"] == second["sha256"]
    assert first["archive_bytes"] == second["archive_bytes"]
    archive = Path(second["archive"])
    assert archive.name == f"stimma-python-runtime-{second['sha256']}.tar.xz"
    with tarfile.open(archive, "r:xz") as packaged:
        assert packaged.getnames() == ["Lib/example/module.py", "python.exe"]


def test_runtime_cache_reuses_identical_inputs_and_rejects_corruption(tmp_path, monkeypatch):
    source = tmp_path / "python"
    source.mkdir()
    (source / "python.exe").write_bytes(b"python executable")
    cache = tmp_path / "cache"
    monkeypatch.setenv("STIMMA_BUILD_CACHE", str(cache))
    first = MODULE.package_runtime(source, tmp_path / "one")
    second = MODULE.package_runtime(source, tmp_path / "two")
    assert second["cache_hit"] is True
    assert first["sha256"] == second["sha256"]
    next(cache.rglob("*.tar.xz")).write_bytes(b"corrupt")
    repaired = MODULE.package_runtime(source, tmp_path / "three")
    assert repaired["sha256"] == first["sha256"]
    assert not repaired.get("cache_hit")
    (source / "python.exe").write_bytes(b"changed executable")
    changed = MODULE.package_runtime(source, tmp_path / "four")
    assert changed["sha256"] != first["sha256"]
