"""
endpointClass classifier for BYOAI endpoint URLs.

Telemetry never carries endpoint hostnames or ports (BYOAI hostnames can
be private/LAN names). Instead, URLs classify into a closed list:

    openai | anthropic | openrouter | other_known | localhost | lan | custom
"""
import ipaddress
from typing import Optional
from urllib.parse import urlparse

# Hostname suffixes for well-known public API providers. The output stays a
# closed list regardless of what's added here.
_KNOWN_PROVIDERS = {
    "api.openai.com": "openai",
    "openai.azure.com": "other_known",
    "api.anthropic.com": "anthropic",
    "openrouter.ai": "openrouter",
    "generativelanguage.googleapis.com": "other_known",
    "api.mistral.ai": "other_known",
    "api.groq.com": "other_known",
    "api.together.xyz": "other_known",
    "api.fireworks.ai": "other_known",
    "api.deepseek.com": "other_known",
    "api.x.ai": "other_known",
    "api.cerebras.ai": "other_known",
    "api.deepinfra.com": "other_known",
    "api.hyperbolic.xyz": "other_known",
    "api.sambanova.ai": "other_known",
    "api.cohere.com": "other_known",
    "api.perplexity.ai": "other_known",
}


def _is_private_host(hostname: str) -> bool:
    try:
        ip = ipaddress.ip_address(hostname)
        return ip.is_private or ip.is_link_local
    except ValueError:
        pass
    lowered = hostname.lower()
    return (
        lowered.endswith(".local")
        or lowered.endswith(".lan")
        or lowered.endswith(".internal")
        or lowered.endswith(".home")
        or lowered.endswith(".home.arpa")
        or "." not in lowered  # bare machine names resolve via LAN search domains
    )


def endpoint_class(url: Optional[str]) -> str:
    """Classify an endpoint URL into the closed endpointClass enum."""
    if not url or not str(url).strip():
        return "custom"
    try:
        parsed = urlparse(str(url).strip())
        hostname = (parsed.hostname or "").lower()
    except Exception:
        return "custom"
    if not hostname:
        return "custom"

    if hostname in ("localhost", "127.0.0.1", "::1", "0.0.0.0"):
        return "localhost"

    for suffix, cls in _KNOWN_PROVIDERS.items():
        if hostname == suffix or hostname.endswith("." + suffix):
            return cls

    if _is_private_host(hostname):
        return "lan"

    return "custom"
