"""Canonical identities for first-party tool providers."""

STIMMA_TOOL_PROVIDER_ID = "stimma-cloud"
STIMMA_TOOL_PROVIDER_DISPLAY_NAME = "Stimma"


def tool_provider_display_name(provider_id: str, provider_name: str | None = None) -> str:
    """Return the user-facing provider name, including legacy-name cleanup."""
    if provider_id == STIMMA_TOOL_PROVIDER_ID:
        return STIMMA_TOOL_PROVIDER_DISPLAY_NAME
    return provider_name or provider_id
