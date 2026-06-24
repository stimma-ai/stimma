"""Runtime-only Stimma Cloud overrides.

These helpers keep internal staging coordinates out of tracked config. Source
builds can point at a private cloud by passing environment variables from an
ignored local env file, while normal installs keep the persisted config default.
"""

from __future__ import annotations

import os
from typing import Mapping

DEFAULT_CLOUD_BASE_URL = "https://stimma.ai"


def _clean_env(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
        value = value[1:-1].strip()
    return value or None


def _first_env(*names: str) -> str | None:
    for name in names:
        value = _clean_env(os.environ.get(name))
        if value:
            return value
    return None


def env_cloud_base_url() -> str | None:
    """Cloud base URL supplied by runtime env, if any."""

    value = _first_env("STIMMA_CLOUD_BASE_URL", "STIMMA_CLOUD_URL")
    return value.rstrip("/") if value else None


def effective_cloud_base_url(configured: str | None = None) -> str:
    """Return env override, configured value, or the production default."""

    configured_value = _clean_env(configured) or DEFAULT_CLOUD_BASE_URL
    return (env_cloud_base_url() or configured_value).rstrip("/")


def cloud_access_headers() -> dict[str, str]:
    """Return Cloudflare Access service-token headers from runtime env."""

    client_id = _first_env(
        "STIMMA_CLOUD_ACCESS_CLIENT_ID",
        "CF_ACCESS_CLIENT_ID",
        "CLOUDFLARE_ACCESS_CLIENT_ID",
    )
    client_secret = _first_env(
        "STIMMA_CLOUD_ACCESS_CLIENT_SECRET",
        "CF_ACCESS_CLIENT_SECRET",
        "CLOUDFLARE_ACCESS_CLIENT_SECRET",
    )
    if not client_id or not client_secret:
        return {}
    return {
        "CF-Access-Client-Id": client_id,
        "CF-Access-Client-Secret": client_secret,
    }


def with_cloud_access_headers(headers: Mapping[str, str] | None = None) -> dict[str, str]:
    """Return headers plus runtime Cloudflare Access headers."""

    merged = dict(headers or {})
    merged.update(cloud_access_headers())
    return merged


def redact_sensitive_headers(headers: Mapping[str, str]) -> dict[str, str]:
    """Redact auth and Access credentials for local request dumps/logs."""

    secret_names = {
        "authorization",
        "cf-access-client-id",
        "cf-access-client-secret",
    }
    return {
        key: ("<redacted>" if key.lower() in secret_names else value)
        for key, value in headers.items()
    }
