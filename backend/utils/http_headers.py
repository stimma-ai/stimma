"""HTTP header helpers."""
from urllib.parse import quote


def content_disposition(disposition: str, filename: str) -> str:
    """Build a Content-Disposition header value safe for any filename.

    Header values must be latin-1 encodable; filenames with characters outside
    that range (e.g. the U+202F narrow no-break space in macOS screenshot
    names) use the RFC 5987 filename* form, matching starlette's FileResponse.
    """
    quoted = quote(filename)
    if quoted != filename:
        return f"{disposition}; filename*=utf-8''{quoted}"
    return f'{disposition}; filename="{filename}"'
