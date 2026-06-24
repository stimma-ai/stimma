"""Stimma content policy for local endpoints.

Stimma Cloud injects its content policy server-side on every cloud request. Local
(BYOAI) endpoints never hit that proxy, so when the user opts in we inject the
*same* text into the system prompt ourselves, fetched from the cloud
(GET /api/content-policy) so it stays remotely controllable.

The cloud is the single source of truth — there is intentionally no bundled
fallback. We cache the last successful fetch and serve it (even when stale) if the
cloud is unreachable; if we've never fetched it, we inject nothing.
"""

import time
from typing import Optional

import httpx

from core.logging import get_logger

log = get_logger(__name__)

_CACHE_TTL_SECONDS = 4 * 60 * 60  # refresh at most this often

_cached_text: Optional[str] = None
_cached_at: float = 0.0


def _cloud_base_url() -> str:
    try:
        from config import get_settings
        return (get_settings().cloud.base_url or "https://stimma.ai").rstrip("/")
    except Exception:
        return "https://stimma.ai"


async def get_content_policy() -> Optional[str]:
    """Return the content-policy text from the cloud, cached (4h TTL).

    On fetch failure, serves the last cached copy even if stale. Returns None if it
    has never been fetched — there is no local fallback, by design.
    """
    global _cached_text, _cached_at

    if _cached_text is not None and (time.monotonic() - _cached_at) < _CACHE_TTL_SECONDS:
        return _cached_text

    try:
        from privacy_lockdown import is_privacy_lockdown_enabled
        if is_privacy_lockdown_enabled():
            log.info("content-policy fetch skipped in Privacy Lockdown")
            return _cached_text
    except Exception:
        pass

    url = f"{_cloud_base_url()}/api/content-policy"
    try:
        from cloud_runtime import with_cloud_access_headers
        async with httpx.AsyncClient(timeout=httpx.Timeout(5.0, connect=3.0)) as client:
            resp = await client.get(url, headers=with_cloud_access_headers())
        resp.raise_for_status()
        text = (resp.json() or {}).get("text")
        if text and isinstance(text, str):
            _cached_text = text.strip()
            _cached_at = time.monotonic()
            return _cached_text
        raise ValueError("content-policy response had no text")
    except Exception as e:
        if _cached_text is not None:
            log.warning(f"content-policy fetch failed ({e}); serving stale cached copy")
            return _cached_text
        log.warning(f"content-policy fetch failed ({e}); no cached copy — skipping policy injection")
        return None
