"""Portable MIME detection for user-visible files, independent of the OS database."""

import mimetypes
from pathlib import PurePosixPath

_TYPES = {
    "md": "text/markdown",
    "markdown": "text/markdown",
    "py": "text/x-python",
    "js": "text/javascript",
    "jsx": "text/javascript",
    "ts": "text/typescript",
    "tsx": "text/typescript",
    "json": "application/json",
    "csv": "text/csv",
    "tsv": "text/tab-separated-values",
    "zip": "application/zip",
    "yaml": "text/yaml",
    "yml": "text/yaml",
    "toml": "text/plain",
    "txt": "text/plain",
    "log": "text/plain",
    "svg": "image/svg+xml",
    "html": "text/html",
    "css": "text/css",
    "sql": "text/plain",
    "sh": "text/plain",
}


def guess_file_mime(name: str) -> str:
    extension = PurePosixPath(name).suffix.lstrip(".").lower()
    return (
        _TYPES.get(extension)
        or mimetypes.guess_type(name)[0]
        or "application/octet-stream"
    )
