"""Browse the web — search, search for images, fetch a page, or download a file."""

import asyncio

from ..tools_registry import tool, ToolParameter
from ..web_search_core import WebFetchError, WebSearchError, fetch_url_bytes, search as core_search
from ._workspace_files import readonly_workspace_error, resolve_workspace_path

from core.logging import get_logger

log = get_logger(__name__)

MAX_CONTENT = 15_000  # ~4k tokens, fits comfortably in context
MAX_DOWNLOAD_MB = 100  # media files (video refs) can be large; still a hard cap


@tool(
    name="browse_web",
    description=(
        "Browse the web: search for text results, search for images, fetch a URL to read its "
        "content, or download a URL to a file in the workspace. Use action='download' to save "
        "files (images, reference media) — prefer it over curl/wget in bash."
    ),
    parameters=[
        ToolParameter(name="action", type="string", description="What to do", enum=["search", "search_images", "fetch", "download"]),
        ToolParameter(name="query", type="string", description="Search query (for action='search' or 'search_images')", required=False),
        ToolParameter(name="url", type="string", description="URL to fetch (for action='fetch' or 'download')", required=False),
        ToolParameter(name="path", type="string", description="Workspace-relative file path to save to (for action='download'), e.g. 'images/ref1.jpg'. Parent directories are created.", required=False),
        ToolParameter(name="num_results", type="integer", description="Number of search results (default 5)", required=False),
        ToolParameter(name="max_length", type="integer", description="Max characters to return from fetch (default 15000)", required=False),
    ],
)
async def browse_web(
    action: str,
    query: str | None = None,
    url: str | None = None,
    path: str | None = None,
    num_results: int = 5,
    max_length: int = MAX_CONTENT,
    **kwargs,
) -> str:
    action = action.lower().strip()

    if action == "search":
        if not query:
            return "Error: query is required for action='search'"
        return await _search_formatted(query, "text", num_results)
    elif action == "search_images":
        if not query:
            return "Error: query is required for action='search_images'"
        return await _search_formatted(query, "images", num_results)
    elif action == "fetch":
        if not url:
            return "Error: url is required for action='fetch'"
        return await _fetch(url, max_length)
    elif action == "download":
        if not url:
            return "Error: url is required for action='download'"
        if not path:
            return "Error: path is required for action='download'"
        return await _download(url, path, kwargs.get("workspace_dir"))
    else:
        return f"Error: unknown action '{action}'. Use 'search', 'search_images', 'fetch', or 'download'."


# ---------------------------------------------------------------------------
# Search: delegate to web_search_core, then format for the LLM
# ---------------------------------------------------------------------------


async def _search_formatted(query: str, kind: str, n: int) -> str:
    try:
        results = await core_search(query, kind=kind, n=n)
    except WebSearchError as exc:
        log.error(f"Web search error: {exc}")
        return f"Error performing search: {exc}"
    if not results:
        return "No results found." if kind == "text" else "No image results found."
    if kind == "images":
        return _format_image_results(results)
    return _format_text_results(results)


def _format_text_results(results: list[dict]) -> str:
    lines = []
    for i, r in enumerate(results, 1):
        title = r.get("title", "")
        url = r.get("url", "")
        snippet = r.get("snippet", "")
        lines.append(f"{i}. {title}\n   {url}\n   {snippet}")
    return "\n\n".join(lines)


def _format_image_results(results: list[dict]) -> str:
    lines = []
    for i, r in enumerate(results, 1):
        title = r.get("title", "")
        image_url = r.get("image_url", "")
        source = r.get("source", "")
        width = r.get("width") or ""
        height = r.get("height") or ""
        size_str = f" ({width}x{height})" if width and height else ""
        lines.append(f"{i}. {title}{size_str}\n   Image: {image_url}\n   Source: {source}")
    lines.append("(To save any of these to the workspace, use browse_web action='download'.)")
    return "\n\n".join(lines)


# ---------------------------------------------------------------------------
# Fetch
# ---------------------------------------------------------------------------


async def _fetch(url: str, max_length: int) -> str:
    try:
        import trafilatura

        def _do_fetch():
            downloaded = trafilatura.fetch_url(url)
            if not downloaded:
                return None
            return trafilatura.extract(
                downloaded,
                include_links=True,
                include_tables=True,
                favor_recall=True,
            )

        content = await asyncio.get_event_loop().run_in_executor(None, _do_fetch)

        if not content:
            return f"Could not extract content from {url}"

        max_length = min(max_length, MAX_CONTENT)
        if len(content) > max_length:
            content = content[:max_length] + "\n\n... (truncated)"

        return content

    except Exception as e:
        log.error(f"Web fetch error for {url}: {e}")
        return f"Error fetching {url}: {e}"


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------


async def _download(url: str, path: str, workspace_dir: str | None) -> str:
    """Save an http(s) URL to a workspace-relative path.

    Same risk class as fetch (public GET, output confined to the workspace),
    so no permission prompt — this exists so the agent doesn't have to reach
    for curl in bash to save what it just found.
    """
    if not workspace_dir:
        return "Error: No workspace directory available"
    if not url.lower().startswith(("http://", "https://")):
        return "Error: url must be http(s)"

    ro_err = readonly_workspace_error(path)
    if ro_err:
        return ro_err
    resolved, err = resolve_workspace_path(workspace_dir, path)
    if err:
        return err

    try:
        data, content_type = await fetch_url_bytes(url, max_size_mb=MAX_DOWNLOAD_MB)
    except WebFetchError as e:
        log.error(f"Web download error for {url}: {e}")
        return f"Error downloading {url}: {e}"

    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_bytes(data)

    size_kb = len(data) / 1024
    size_str = f"{size_kb / 1024:.1f} MB" if size_kb >= 1024 else f"{size_kb:.0f} KB"
    type_str = f", {content_type}" if content_type else ""
    return f"Downloaded {url} to {path} ({size_str}{type_str})"
