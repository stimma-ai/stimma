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
