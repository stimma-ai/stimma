"""Live, confined workspace references and bounded ZIP entry access."""

from utils.file_mime import guess_file_mime
from pathlib import Path, PurePosixPath
from urllib.parse import quote
from zipfile import ZipFile, BadZipFile

from fastapi import HTTPException

MAX_ENTRY_BYTES = 128 * 1024 * 1024
MAX_ZIP_ENTRIES = 10000


def validate_path(path: str) -> str:
    if (
        not path
        or "\\" in path
        or "\x00" in path
        or PurePosixPath(path).is_absolute()
        or any(p in {"..", "."} for p in path.split("/"))
    ):
        raise HTTPException(400, "Invalid workspace path")
    return path


def resolve_file(root: Path, path: str) -> Path:
    validate_path(path)
    resolved = (root / path).resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise HTTPException(400, "Path escapes workspace")
    if not resolved.is_file():
        raise HTTPException(404, "File no longer in workspace")
    return resolved


def describe_file(chat_id: int, root: str, path: str, file: Path) -> dict:
    mime = guess_file_mime(path)
    labels = {
        "py": "Python",
        "md": "Markdown",
        "js": "JavaScript",
        "ts": "TypeScript",
        "json": "JSON",
        "txt": "Text",
        "svg": "SVG",
    }
    ext = file.suffix.lstrip(".").lower()
    subtitle = labels.get(ext, ext.upper() or mime)
    if ext in {"csv", "tsv"} and file.stat().st_size <= 1024 * 1024:
        import csv

        try:
            with file.open(encoding="utf-8-sig", newline="") as stream:
                count = sum(
                    1
                    for _ in csv.reader(stream, delimiter="\t" if ext == "tsv" else ",")
                )
            subtitle = f"{max(0, count - 1)} rows"
        except (UnicodeError, csv.Error, OSError):
            pass
    elif ext == "zip":
        try:
            subtitle = (
                f"{sum(not entry['directory'] for entry in zip_entries(file))} files"
            )
        except HTTPException:
            pass
    return {
        "subtitle": subtitle,
        "modified_ns": file.stat().st_mtime_ns,
        "root": root,
        "path": path,
        "name": PurePosixPath(path).name,
        "size": file.stat().st_size,
        "mime": mime,
        "kind": PurePosixPath(path).suffix.lstrip(".").lower() or "file",
        "url": f"/api/chats/{chat_id}/files/{root}/content?path={quote(path, safe='')}",
    }


def zip_entries(file: Path) -> list:
    try:
        with ZipFile(file) as archive:
            entries = archive.infolist()
            if len(entries) > MAX_ZIP_ENTRIES:
                raise HTTPException(413, "Archive has too many entries")
            result = []
            names = set()
            for entry in entries:
                name = entry.filename.rstrip("/")
                try:
                    validate_path(name)
                except HTTPException:
                    continue
                # Symlinks and ambiguous duplicate names are not previewable.
                if entry.external_attr >> 16 & 0o170000 == 0o120000 or name in names:
                    raise HTTPException(
                        400, "Archive contains ambiguous or symbolic entries"
                    )
                names.add(name)
                result.append(
                    {
                        "path": name,
                        "name": PurePosixPath(name).name,
                        "directory": entry.is_dir(),
                        "size": entry.file_size,
                        "mime": guess_file_mime(name),
                    }
                )
            return result
    except (BadZipFile, OSError):
        raise HTTPException(400, "Cannot read archive")


def read_zip_entry(file: Path, entry: str) -> bytes:
    validate_path(entry)
    info = next(
        (
            row
            for row in zip_entries(file)
            if row["path"] == entry and not row["directory"]
        ),
        None,
    )
    if info is None:
        raise HTTPException(404, "Archive entry not found")
    if info["size"] > MAX_ENTRY_BYTES:
        raise HTTPException(413, "Archive entry is too large")
    try:
        with ZipFile(file) as archive, archive.open(entry) as stream:
            data = stream.read(MAX_ENTRY_BYTES + 1)
            if len(data) > MAX_ENTRY_BYTES:
                raise HTTPException(413, "Archive entry is too large")
            return data
    except (BadZipFile, RuntimeError, NotImplementedError, OSError):
        raise HTTPException(400, "Cannot read archive entry")
