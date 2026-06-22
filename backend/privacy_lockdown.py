"""Hard privacy lockdown for Stimma-owned network surfaces.

``STIMMA_PRIVACY_LOCKDOWN=1`` is stronger than the telemetry consent toggle:
the app must not contact Stimma services, send Stimma identifiers, sign in to
Stimma Cloud, or buffer volunteerable data for later submission.
"""

from __future__ import annotations

import os
from urllib.parse import urlparse

PRIMARY_ENV = "STIMMA_PRIVACY_LOCKDOWN"
LEGACY_DNT_ENV = "DO_NOT_TRACK"
LEGACY_SHORT_ENV = "PRIVACY_LOCKDOWN"

_TRUTHY = {"1", "true", "yes", "on"}


class PrivacyLockdownError(RuntimeError):
    """Raised when code attempts to use a Stimma service in lockdown."""


def _env_truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in _TRUTHY


def is_privacy_lockdown_enabled() -> bool:
    """True when the local-only privacy mode is active."""
    return (
        _env_truthy(PRIMARY_ENV)
        or _env_truthy(LEGACY_SHORT_ENV)
        or _env_truthy(LEGACY_DNT_ENV)
    )


def active_env_name() -> str | None:
    """Return the env var currently enabling lockdown, if any."""
    for name in (PRIMARY_ENV, LEGACY_SHORT_ENV, LEGACY_DNT_ENV):
        if _env_truthy(name):
            return name
    return None


def disabled_message(feature: str = "Stimma services") -> str:
    return f"{feature} unavailable while Privacy Lockdown is enabled."


def raise_if_enabled(feature: str = "Stimma services") -> None:
    if is_privacy_lockdown_enabled():
        raise PrivacyLockdownError(disabled_message(feature))


def is_stimma_service_url(url: str | None) -> bool:
    """Return True for Stimma-owned service hosts."""
    if not url:
        return False
    try:
        host = (urlparse(url).hostname or "").lower()
    except Exception:
        return False
    return host == "stimma.ai" or host.endswith(".stimma.ai")


def raise_for_stimma_url_if_enabled(url: str | None, feature: str = "Stimma services") -> None:
    if is_privacy_lockdown_enabled() and is_stimma_service_url(url):
        raise PrivacyLockdownError(disabled_message(feature))
