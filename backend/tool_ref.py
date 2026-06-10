"""
toolRef / toolSource resolver for telemetry.

Raw tool ids are NOT safe to egress for every tool: user-provider tool ids
(STP slugs) are user-chosen strings — e.g. ComfyUI-Stimma slugs come from
a user-editable workflow node — so they are content.

- ``toolSource``: ``builtin | marketplace | cloud | user``.
- ``toolRef``: the tool id verbatim for builtin/marketplace/cloud tools
  (catalog data), and the install-salted hash for user-provider tools
  (per-tool funnels stay joinable within an install; the name never leaves
  the machine).
"""
from typing import Optional, Tuple

from object_hash import salted_hash

SOURCE_BUILTIN = "builtin"
SOURCE_MARKETPLACE = "marketplace"
SOURCE_CLOUD = "cloud"
SOURCE_USER = "user"

# Provider ids whose tool catalogs are ours (toolRef passes verbatim).
_CLOUD_PROVIDER_IDS = {"stimma-cloud"}


def classify_tool_source(
    provider_id: Optional[str],
    provider_type: Optional[str] = None,
) -> str:
    """Classify a provider into the closed toolSource enum."""
    pid = (provider_id or "").lower()
    if pid.startswith("builtin") or (provider_type or "").lower() == "builtin":
        return SOURCE_BUILTIN
    if pid in _CLOUD_PROVIDER_IDS or "stimma-cloud" in pid:
        return SOURCE_CLOUD
    return SOURCE_USER


def resolve_tool_ref(
    tool_id: Optional[str],
    tool_source: str,
) -> Optional[str]:
    """Return the telemetry-safe toolRef for a tool id.

    Builtin/marketplace/cloud tool ids are our catalog data and pass
    verbatim; user-provider ids are salted-hashed.
    """
    if not tool_id:
        return None
    if tool_source in (SOURCE_BUILTIN, SOURCE_MARKETPLACE, SOURCE_CLOUD):
        return str(tool_id)
    return salted_hash(str(tool_id))


def tool_ref_for(
    tool_id: Optional[str],
    provider_id: Optional[str] = None,
    provider_type: Optional[str] = None,
) -> Tuple[Optional[str], str]:
    """Convenience: ``(toolRef, toolSource)`` from a tool id + provider info."""
    source = classify_tool_source(provider_id, provider_type)
    return resolve_tool_ref(tool_id, source), source
