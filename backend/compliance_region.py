"""
Compliance-region check (official builds only).

``GET {cloud.base_url}/api/compliance/region`` maps the caller's country
to a consent regime (``optin`` | ``optout``), which drives the onboarding
consent-toggle default (optin -> off, optout -> on).

- Official builds call it before onboarding renders and cache
  ``{country, regime, checked_at}`` in config; once cached it is never
  re-fetched.
- Unreachable/offline -> ``optin`` (default-off, safe), re-checked on the
  next launch until a cache lands.
- Dev builds never call it (they have no consent screen).
- Privacy Lockdown suppresses the call (regime falls back to optin).
"""
import asyncio
from datetime import datetime, timezone
from typing import Optional, TypedDict

import httpx

from core.logging import get_logger
from distribution import is_dnt, is_official

log = get_logger(__name__)

REGION_TIMEOUT_SECONDS = 10

REGIME_OPTIN = "optin"
REGIME_OPTOUT = "optout"


class RegionInfo(TypedDict, total=False):
    country: Optional[str]
    regime: str
    cached: bool


def _cached_region() -> Optional[RegionInfo]:
    try:
        from config import get_settings
        compliance = get_settings().compliance
        if compliance.regime in (REGIME_OPTIN, REGIME_OPTOUT):
            return {
                "country": compliance.country,
                "regime": compliance.regime,
                "cached": True,
            }
    except Exception:
        pass
    return None


def _persist_region(country: Optional[str], regime: str) -> None:
    try:
        import config_writer
        config_writer.patch_global_section("compliance", {
            "country": country,
            "regime": regime,
            "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        })
    except Exception as e:
        log.info(f"compliance: failed to persist region cache: {e}")


async def get_region() -> RegionInfo:
    """Return the consent regime for this install.

    Cached value when available; otherwise fetched (official builds, no
    Privacy Lockdown) and cached on success. Falls back to ``optin`` uncached.
    """
    cached = _cached_region()
    if cached:
        return cached

    fallback: RegionInfo = {"country": None, "regime": REGIME_OPTIN, "cached": False}

    if not is_official() or is_dnt():
        return fallback

    try:
        from config import get_settings
        from user_agent import ua_headers
        base_url = get_settings().cloud.base_url.rstrip("/")
        url = f"{base_url}/api/compliance/region"
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(REGION_TIMEOUT_SECONDS)
        ) as client:
            response = await client.get(url, headers=ua_headers())
        if response.status_code != 200:
            return fallback
        data = response.json()
        regime = data.get("regime")
        if regime not in (REGIME_OPTIN, REGIME_OPTOUT):
            return fallback
        country = data.get("country")
        _persist_region(country, regime)
        return {"country": country, "regime": regime, "cached": True}
    except asyncio.CancelledError:
        raise
    except Exception as e:
        log.info(f"compliance: region check failed (treating as optin): {e}")
        return fallback
