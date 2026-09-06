"""Create a deterministic XZ archive containing a portable Python directory.

The archive is transport only. Stimma extracts it once on Windows and then runs
Python from the ordinary directory tree, preserving normal import, native
extension, multiprocessing, and package-resource behavior.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import tempfile
import tarfile


def package_runtime(source: Path, output_dir: Path) -> dict[str, object]:
    source = source.resolve()
    output_dir = output_dir.resolve()
    if not (source / "python.exe").is_file():
        raise FileNotFoundError(f"portable Python executable not found: {source / 'python.exe'}")

    output_dir.mkdir(parents=True, exist_ok=True)
    files = sorted(path for path in source.rglob("*") if path.is_file())
    fd, temporary_name = tempfile.mkstemp(prefix="stimma-python-runtime-", suffix=".tar.xz", dir=output_dir)
    os.close(fd)
    temporary = Path(temporary_name)

    try:
        with tarfile.open(temporary, mode="w:xz", preset=6) as archive:
            for path in files:
                relative = path.relative_to(source).as_posix()
                info = archive.gettarinfo(str(path), arcname=relative)
                info.mtime = 0
                info.uid = 0
                info.gid = 0
                info.uname = ""
                info.gname = ""
                with path.open("rb") as source_file:
                    archive.addfile(info, source_file)

        digest = hashlib.sha256()
        with temporary.open("rb") as packaged:
            for chunk in iter(lambda: packaged.read(1024 * 1024), b""):
                digest.update(chunk)
        sha256 = digest.hexdigest()
        destination = output_dir / f"stimma-python-runtime-{sha256}.tar.xz"
        os.replace(temporary, destination)

        source_bytes = sum(path.stat().st_size for path in files)
        return {
            "archive": str(destination),
            "sha256": sha256,
            "files": len(files),
            "source_bytes": source_bytes,
            "archive_bytes": destination.stat().st_size,
        }
    finally:
        temporary.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output_dir", type=Path)
    args = parser.parse_args()
    print(json.dumps(package_runtime(args.source, args.output_dir), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
