"""Build and locate immutable mobile UI packages; never build in a request."""
from __future__ import annotations

import gzip
import hashlib
import json
import os
from pathlib import Path
import stat
import tarfile
import tempfile
import unicodedata

MAX_COMPRESSED_BYTES = 64 * 1024 * 1024
MAX_UNPACKED_BYTES = 128 * 1024 * 1024
MAX_FILES = 10_000


def package_directory() -> Path:
    """Explicit development override, or resources copied beside backend code."""
    override = os.environ.get("STIMMA_UI_PACKAGE_DIR")
    return Path(override) if override else Path(__file__).resolve().parent / "mobile-ui"


def _validate_package_names(names: list[str]) -> None:
    """Match native extraction limits, including case-insensitive filesystems."""
    folded = set()
    directories = set()
    for name in names:
        parts = name.split("/")
        if (len(parts) > 32 or len(name.encode("utf-8")) > 255
                or "\\" in name or any(part in ("", ".", "..") for part in parts)
                or any(ord(character) < 32 or ord(character) == 127 for character in name)):
            raise ValueError("Invalid UI package filename")
        # NFC plus casefold is at least as strict as the native NFC/lowercase
        # comparison, and catches additional case-insensitive Unicode aliases.
        canonical = unicodedata.normalize("NFC", name).casefold()
        if canonical in folded:
            raise ValueError("UI package filenames collide after normalization")
        folded.add(canonical)
        components = canonical.split("/")
        directories.update("/".join(components[:count]) for count in range(1, len(components)))
    if directories & folded:
        raise ValueError("UI package filename collides with a directory")
    if len(directories) > MAX_FILES:
        raise ValueError("UI build exceeds mobile package directory limit")


def _open_regular_file(path: Path):
    """Open binary data without following links, including on Windows.

    Windows lacks O_NOFOLLOW. Check the directory entry before and after open
    and match it to the opened descriptor so a replaced link/file is rejected.
    """
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode):
        raise ValueError("UI input changed during packaging")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    fd = os.open(path, flags)
    try:
        opened = os.fstat(fd)
        after = path.lstat()
        if (not stat.S_ISREG(opened.st_mode) or not stat.S_ISREG(after.st_mode)
                or not os.path.samestat(before, opened) or not os.path.samestat(after, opened)):
            raise ValueError("UI input changed during packaging")
        return os.fdopen(fd, "rb")
    except BaseException:
        os.close(fd)
        raise


def build_ui_package(source: Path, output: Path) -> dict:
    """Publish archive before atomically replacing its manifest; retain old hashes.

    Input must be a completed frontend build. USTAR metadata and gzip headers
    are normalized so equivalent builds produce the same compressed hash.
    """
    source, output = Path(source), Path(output)
    if source.is_symlink() or not source.is_dir():
        raise ValueError("UI source must be a real directory")
    if output.resolve().is_relative_to(source.resolve()):
        raise ValueError("Package output must be outside the frontend build")
    files = []
    unpacked = 0
    for path in sorted(source.rglob("*")):
        mode = path.lstat().st_mode
        if stat.S_ISLNK(mode):
            raise ValueError("UI packages cannot contain symbolic links")
        if stat.S_ISDIR(mode):
            continue
        if not stat.S_ISREG(mode):
            raise ValueError("UI packages can contain only regular files")
        name = path.relative_to(source).as_posix()
        if name == "mobile.html":
            continue
        unpacked += path.stat().st_size
        files.append((path, name))
    _validate_package_names([name for _, name in files])
    if not any(name == "index.html" for _, name in files):
        raise ValueError("UI build is missing index.html")
    if len(files) > MAX_FILES or unpacked > MAX_UNPACKED_BYTES:
        raise ValueError("UI build exceeds mobile package limits")
    archives = output / "packages"
    archives.mkdir(parents=True, exist_ok=True)
    temp_path = None
    manifest_temp = None
    try:
        actual_unpacked = 0
        with tempfile.NamedTemporaryFile(dir=archives, suffix=".tmp", delete=False) as raw:
            temp_path = Path(raw.name)
            with gzip.GzipFile(filename="", fileobj=raw, mode="wb", mtime=0) as compressed:
                with tarfile.open(fileobj=compressed, mode="w|", format=tarfile.USTAR_FORMAT) as archive:
                    for path, name in files:
                        # Refuse links replaced after discovery too.
                        with _open_regular_file(path) as contents:
                            info_stat = os.fstat(contents.fileno())
                            if not stat.S_ISREG(info_stat.st_mode):
                                raise ValueError("UI input changed during packaging")
                            actual_unpacked += info_stat.st_size
                            if actual_unpacked > MAX_UNPACKED_BYTES:
                                raise ValueError("UI build exceeds mobile package limits")
                            info = tarfile.TarInfo(name)
                            info.size = info_stat.st_size
                            info.mode = 0o644
                            archive.addfile(info, contents)
            raw.flush()
            os.fsync(raw.fileno())
        size = temp_path.stat().st_size
        if size > MAX_COMPRESSED_BYTES:
            raise ValueError("Compressed UI package exceeds mobile package limits")
        hasher = hashlib.sha256()
        with temp_path.open("rb") as contents:
            for chunk in iter(lambda: contents.read(1024 * 1024), b""):
                hasher.update(chunk)
        digest = hasher.hexdigest()
        manifest = {
            "formatVersion": 1, "hash": digest, "bytes": size,
            "unpackedBytes": actual_unpacked, "bridgeVersion": 1, "apiVersion": 1,
            "entrypoint": "index.html",
        }
        destination = archives / f"{digest}.tar.gz"
        # Temp files are created owner-only; the package is read by whoever
        # runs the server (a build as root, a gate as an unprivileged user,
        # the packaged app), so both files get the same modes as the build.
        os.chmod(temp_path, 0o644)
        # Content-addressed archives are never modified or removed on rebuild;
        # one left by an earlier build still gets today's modes.
        if not destination.exists():
            os.replace(temp_path, destination)
        os.chmod(destination, 0o644)
        with tempfile.NamedTemporaryFile(dir=output, mode="w", suffix=".tmp", delete=False) as handle:
            manifest_temp = Path(handle.name)
            json.dump(manifest, handle, sort_keys=True, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(manifest_temp, 0o644)
        os.replace(manifest_temp, output / "manifest.json")
        return manifest
    finally:
        if temp_path:
            temp_path.unlink(missing_ok=True)
        if manifest_temp:
            manifest_temp.unlink(missing_ok=True)
