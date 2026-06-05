"""Shared web-search core used by the agent's ``browse_web`` tool and the
recipe DSL's ``web_search`` primitive.

Encapsulates the cloud (Serper.dev via Stimma Cloud) → DuckDuckGo fallback
ladder so both surfaces share one path. The agent tool wraps results into a
formatted string for the LLM; the recipe primitive consumes the structured
list directly. Don't add formatting concerns here — return plain dicts and
let callers shape them.
"""

from __future__ import annotations

import asyncio
from typing import Any, Optional

import httpx

from core.logging import get_logger


log = get_logger(__name__)


# Browser-like headers for outbound media fetches. Many CDNs and image hosts
# return 403 to httpx's default ``python-httpx/x.y`` User-Agent (anti-hotlink
# / anti-scrape rules). Sending a plausible browser UA + standard Accept
# headers gets us the same response the browser already got when it loaded
# the same URL into a preview tile, so the backend never breaks promises the
# frontend made by displaying the image.
#
# Note on Accept: we intentionally DO NOT advertise image/avif or image/heic.
# Servers doing content negotiation (e.g. Chewy's CDN) will deliver AVIF when
# the client claims to accept it, but our PIL pipeline can't decode AVIF
# without pillow-heif. Listing the formats we can actually process — with
# image/* as a low-q catch-all — coaxes most CDNs into sending JPEG/PNG/WebP.
_BROWSER_FETCH_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "image/jpeg,image/png,image/webp,image/gif,image/*;q=0.5,*/*;q=0.1",
    "Accept-Language": "en-US,en;q=0.9",
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def search(
    query: str,
    *,
    kind: str = "text",
    n: int = 10,
) -> list[dict[str, Any]]:
    """Run a web search and return a list of structured result dicts.

    ``kind`` is ``"text"`` or ``"images"``. Result shape:

    - ``kind="images"``: ``{title, image_url, source, width, height}``
    - ``kind="text"``:   ``{title, url, snippet}``

    Tries Stimma Cloud (Serper.dev) for paying tiers; falls back to DuckDuckGo
    for free tier or any cloud failure. Raises ``WebSearchError`` only when
    both paths fail.
    """
    if kind not in ("text", "images"):
        raise ValueError(f"kind must be 'text' or 'images', got {kind!r}")
    if not isinstance(n, int) or n < 1:
        raise ValueError(f"n must be a positive integer, got {n!r}")
    if not isinstance(query, str) or not query.strip():
        raise ValueError("query must be a non-empty string")

    cloud = await _cloud_search(query, kind, n)
    if cloud is not None:
        return cloud
    return await _local_search(query, kind, n)


async def fetch_url_bytes(
    url: str,
    *,
    max_size_mb: int = 10,
    timeout_seconds: float = 30.0,
) -> tuple[bytes, Optional[str]]:
    """Download ``url`` and return ``(bytes, http_content_type)``.

    Enforces a hard size cap (``max_size_mb``) so a misreporting server
    can't fill memory. Returns ``http_content_type`` for diagnostics only;
    callers should sniff the bytes to decide what they actually have.
    Raises ``WebFetchError`` on HTTP error, oversize, or transport failure.
    """
    if not isinstance(url, str) or not url.strip():
        raise WebFetchError("url must be a non-empty string")
    if not isinstance(max_size_mb, int) or max_size_mb < 1:
        raise WebFetchError(f"max_size_mb must be a positive int, got {max_size_mb!r}")

    cap_bytes = max_size_mb * 1024 * 1024
    try:
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=timeout_seconds,
            headers=_BROWSER_FETCH_HEADERS,
        ) as client:
            async with client.stream("GET", url) as response:
                if response.status_code >= 400:
                    raise WebFetchError(
                        f"HTTP {response.status_code} fetching {url}",
                        status_code=response.status_code,
                    )
                content_type = response.headers.get("content-type", "").split(";")[0].strip() or None
                # Reject obvious oversize from Content-Length before streaming.
                content_length = response.headers.get("content-length")
                if content_length and content_length.isdigit() and int(content_length) > cap_bytes:
                    raise WebFetchError(
                        f"Content-Length {content_length} exceeds {max_size_mb} MB cap",
                    )
                buf = bytearray()
                async for chunk in response.aiter_bytes():
                    buf.extend(chunk)
                    if len(buf) > cap_bytes:
                        raise WebFetchError(
                            f"response exceeded {max_size_mb} MB cap while streaming",
                        )
                return bytes(buf), content_type
    except WebFetchError:
        raise
    except (httpx.TimeoutException, asyncio.TimeoutError) as exc:
        raise WebFetchError(f"timeout fetching {url}: {exc}") from exc
    except httpx.HTTPError as exc:
        raise WebFetchError(f"transport error fetching {url}: {exc}") from exc


async def probe_url_reachable(url: str, *, timeout_seconds: float = 6.0) -> bool:
    """Best-effort probe: can we actually fetch this URL with our headers?

    Used to pre-filter web_search image results so the user only ever picks
    from candidates we can promote into the library. Some hosts 200 on HEAD
    but 4xx on GET (or vice versa); we use a small ranged GET so the response
    matches what ``fetch_url_bytes`` will see at promotion time. The body is
    streamed-and-discarded — we just need the status. False on any error so
    a flaky host fails closed (drop the candidate) rather than open (let the
    user pick something that will then fail at resolve time).
    """
    if not isinstance(url, str) or not url.strip():
        return False
    try:
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=timeout_seconds,
            headers={**_BROWSER_FETCH_HEADERS, "Range": "bytes=0-1023"},
        ) as client:
            async with client.stream("GET", url) as response:
                # 200 (full) and 206 (partial) are both fine — we don't care
                # which the server gave us, only that it didn't reject the
                # request. 416 (range-not-satisfiable) is rare for tiny ranges
                # but still indicates the server is willing to serve the URL.
                if response.status_code in (200, 206, 416):
                    # Drain a tiny prefix so the connection releases cleanly.
                    async for _ in response.aiter_bytes():
                        break
                    return True
                return False
    except Exception:  # noqa: BLE001 — any failure means "don't show this URL"
        return False


class WebSearchError(RuntimeError):
    pass


class WebFetchError(RuntimeError):
    def __init__(self, message: str, *, status_code: Optional[int] = None) -> None:
        super().__init__(message)
        self.status_code = status_code


# ---------------------------------------------------------------------------
# Cloud (Serper.dev via Stimma Cloud)
# ---------------------------------------------------------------------------


async def _cloud_search(
    query: str,
    kind: str,
    n: int,
) -> Optional[list[dict[str, Any]]]:
    """Try Serper.dev via Stimma Cloud. Returns None if unavailable."""
    try:
        from auth_storage import load_auth_state
        from config import get_settings
        from firebase_auth import get_valid_id_token

        auth_state = load_auth_state()
        if not auth_state:
            log.info("cloud search skipped: no auth state")
            return None
        tier = auth_state.get("tier", "free")
        if tier == "free":
            log.info("cloud search skipped: free tier")
            return None

        id_token = await get_valid_id_token()
        if not id_token:
            log.info("cloud search skipped: no valid id token")
            return None

        base_url = get_settings().cloud.base_url
        url = f"{base_url}/api/search/web"

        log.info("cloud search request", query=query, kind=kind, base_url=base_url)

        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                headers={"Authorization": f"Bearer {id_token}"},
                json={"query": query, "search_type": kind, "num_results": n},
                timeout=15.0,
            )
            if response.status_code != 200:
                log.warning(
                    "cloud search failed, falling back to local",
                    status=response.status_code,
                    body=response.text,
                )
                return None
            return _parse_serper(response.json(), kind)
    except Exception as exc:
        log.warning("cloud search error, falling back to local", error=str(exc))
        return None


def _parse_serper(data: dict, kind: str) -> list[dict[str, Any]]:
    if kind == "images":
        out = []
        for img in data.get("images", []) or []:
            out.append({
                "title": img.get("title") or "",
                "image_url": img.get("imageUrl") or "",
                "source": img.get("link") or "",
                "width": img.get("imageWidth"),
                "height": img.get("imageHeight"),
            })
        return out
    out = []
    for r in data.get("organic", []) or []:
        out.append({
            "title": r.get("title") or "",
            "url": r.get("link") or "",
            "snippet": r.get("snippet") or "",
        })
    return out


# ---------------------------------------------------------------------------
# Local (DuckDuckGo)
# ---------------------------------------------------------------------------


async def _local_search(
    query: str,
    kind: str,
    n: int,
) -> list[dict[str, Any]]:
    try:
        from ddgs import DDGS

        def _do():
            ddgs = DDGS()
            if kind == "images":
                return list(ddgs.images(query, max_results=n))
            return list(ddgs.text(query, max_results=n))

        results = await asyncio.get_event_loop().run_in_executor(None, _do)
    except Exception as exc:
        log.error(f"web search local fallback failed: {exc}")
        raise WebSearchError(f"web search failed: {exc}") from exc

    if not results:
        return []
    return _parse_ddgs(results, kind)


def _parse_ddgs(results: list, kind: str) -> list[dict[str, Any]]:
    if kind == "images":
        out = []
        for r in results:
            out.append({
                "title": r.get("title") or "",
                "image_url": r.get("image") or "",
                "source": r.get("url") or "",
                "width": r.get("width"),
                "height": r.get("height"),
            })
        return out
    out = []
    for r in results:
        out.append({
            "title": r.get("title") or "",
            "url": r.get("href") or "",
            "snippet": r.get("body") or "",
        })
    return out


# ---------------------------------------------------------------------------
# Image content-type sniffing
# ---------------------------------------------------------------------------


# Magic-byte signatures for image formats. Mirrors PIL's recognition list.
_IMAGE_SIGNATURES: tuple[tuple[bytes, str], ...] = (
    (b"\xff\xd8\xff", "jpeg"),
    (b"\x89PNG\r\n\x1a\n", "png"),
    (b"GIF87a", "gif"),
    (b"GIF89a", "gif"),
    (b"RIFF", "webp"),  # plus check for "WEBP" at offset 8
    (b"BM", "bmp"),
    (b"II*\x00", "tiff"),
    (b"MM\x00*", "tiff"),
)

# AVIF / HEIC live inside an ISOBMFF container — bytes 4-7 are "ftyp" and
# bytes 8-11 carry the major brand. Check the brand to distinguish AVIF
# from HEIC and from generic MP4 video.
_AVIF_BRANDS = frozenset({b"avif", b"avis"})
_HEIC_BRANDS = frozenset({b"heic", b"heix", b"hevc", b"hevx", b"heim", b"heis", b"hevm", b"hevs", b"mif1", b"msf1"})


def sniff_image_format(data: bytes) -> Optional[str]:
    """Return a normalized image format ('jpeg', 'png', ...) or None.

    Sniffs from magic bytes. Don't trust HTTP Content-Type — many image
    hosts mis-label or return ``application/octet-stream``.
    """
    if not data:
        return None
    for sig, fmt in _IMAGE_SIGNATURES:
        if data.startswith(sig):
            if fmt == "webp":
                # RIFF container — confirm WEBP at offset 8.
                if len(data) >= 12 and data[8:12] == b"WEBP":
                    return "webp"
                continue
            return fmt
    # ISOBMFF (AVIF / HEIC). The Accept header asks servers to skip these
    # in favor of JPEG/PNG/WebP, but some CDNs ignore content negotiation and
    # send AVIF anyway. Recognizing the format here lets us fail at decode
    # time (with a clear "format not supported" message) rather than at the
    # sniff step (which currently surfaces as a misleading "non-image bytes"
    # error to the user even though the bytes are very much an image).
    if len(data) >= 12 and data[4:8] == b"ftyp":
        brand = data[8:12]
        if brand in _AVIF_BRANDS:
            return "avif"
        if brand in _HEIC_BRANDS:
            return "heic"
    return None
