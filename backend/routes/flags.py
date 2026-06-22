"""Sidecar API for feature flags and compliance region.

The frontend reads the backend's flag bag here (and gets live updates via
the ``flags_updated`` WebSocket event); the onboarding flow reads the
consent regime from the region endpoint (official builds — dev builds and
Privacy Lockdown installs get the local optin fallback without any network).
"""
from fastapi import APIRouter

from feature_flags import get_feature_flags

router = APIRouter(prefix="/api", tags=["flags"])


@router.get("/feature-flags")
async def get_flags():
    """Effective feature-flag bag (local defaults overlaid by server values)."""
    return {"flags": get_feature_flags().all()}


@router.get("/compliance/region")
async def get_compliance_region():
    """Consent regime for this install: {country, regime, cached}."""
    from compliance_region import get_region
    return await get_region()
