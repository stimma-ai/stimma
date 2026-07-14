"""
Shared telemetry property builders.

Cross-cutting classifiers used by multiple emission points so every event
derives its categorical fields the same way (single source of truth, like
model_family / endpoint_class / tool_ref):

- ``error_hash``  — sha1 of the *normalized* error message. Groupable
  without content: the raw message never egresses, only the fingerprint.
- ``classify_tool_error`` — closed errorType list for tool/chain failures
  (``provider_disconnected`` is a required member per the catalog).
- ``classify_agent_error`` — the shared closed agent errorType list used by
  agent_turn_completed / agent_error / prompt_agent_step. Unknown
  exceptions map to ``other`` — never raw exception class names.
- ``llm_config_fields`` — {llmSource, modelFamily, endpointClass?} from a
  resolved LLM endpoint config. Hostnames and raw model strings never
  egress; they classify through endpoint_class / model_family.
- ``marker_name_for_telemetry`` — catalog fix #4: names matching the
  shipped default marker set pass through literally; everything else
  (including renamed defaults) is user content and egresses as the
  literal ``custom``. Used by ``media_marked`` and the
  ``session_started.markerCounts`` snapshot.
"""
import hashlib
import re
from typing import Any, Dict, Optional

# Closed errorType list for tool/generation/chain failures.
TOOL_ERROR_TYPES = (
    "timeout",
    "cancelled",
    "out_of_memory",
    "connection_error",
    "provider_disconnected",
    "provider_error",
)

# Shared closed agent errorType list (agent_turn_completed / agent_error /
# prompt_agent_step). ``refusal`` (textual decline detected by the shared
# classifier) and ``content_filtered`` (provider-side filter signal) are
# distinct members — different causes, different fixes.
AGENT_ERROR_TYPES = (
    "quota_exceeded",
    "content_filtered",
    "insufficient_balance",
    "subscription_required",
    "llm_not_configured",
    "refusal",
    "timeout",
    "other",
)

# Shipped default marker names (catalog fix #4). Only these pass through
# telemetry literally — anything else, including renamed defaults, is user
# content and is replaced by the literal ``custom``.
DEFAULT_MARKER_NAMES = frozenset({"favorite", "library"})

_WS_RE = re.compile(r"\s+")
_NUM_RE = re.compile(r"\d+")


def marker_name_for_telemetry(name: Optional[str]) -> str:
    """Marker name as it may appear in telemetry.

    Shipped default names pass through literally; every other name
    (user-created markers, renamed defaults) becomes ``custom``.
    """
    return name if name in DEFAULT_MARKER_NAMES else "custom"


def error_hash(message: Optional[str]) -> str:
    """Categorical fingerprint of an error message (first 16 hex of sha1).

    Normalization (lowercase, digits collapsed, whitespace collapsed) makes
    instances of the same error group together while the message content
    itself never leaves the machine.
    """
    normalized = _WS_RE.sub(" ", _NUM_RE.sub("#", (message or "").lower())).strip()
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:16]


def classify_tool_error(message: Optional[str]) -> str:
    """Map a raw tool/provider error message into the closed errorType list."""
    lowered = (message or "").lower()
    if "timeout" in lowered or "timed out" in lowered:
        return "timeout"
    if "cancel" in lowered:
        return "cancelled"
    if "out of memory" in lowered or "oom" in lowered:
        return "out_of_memory"
    if "not connected" in lowered or "disconnect" in lowered:
        return "provider_disconnected"
    if "connection" in lowered or "refused" in lowered:
        return "connection_error"
    return "provider_error"


def classify_agent_error(exc: BaseException) -> str:
    """Map an agent-surface exception into the shared closed errorType list.

    Known classes map to their categorical member; everything else is
    ``other`` (never a raw exception class name — fix for the open-domain
    fallback the old agent_error used).
    """
    import asyncio

    try:
        from llm import QuotaExceededError, ContentFilteredError
        if isinstance(exc, QuotaExceededError):
            return "quota_exceeded"
        if isinstance(exc, ContentFilteredError):
            return "content_filtered"
    except Exception:
        pass
    try:
        from llm_resolver import LLMInsufficientBalanceError, LLMNotConfiguredError
        if isinstance(exc, LLMInsufficientBalanceError):
            return "insufficient_balance"
        if isinstance(exc, LLMNotConfiguredError):
            return "llm_not_configured"
    except Exception:
        pass
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
        return "timeout"
    return "other"


def llm_config_fields(llm_config: Any) -> Dict[str, Any]:
    """Telemetry fields for a *resolved* LLM endpoint config.

    Returns ``{llmSource: stimma_cloud|endpoint|unknown, modelFamily,
    endpointClass?}`` — ``endpointClass`` present only when
    ``llmSource == endpoint`` (the fix-#2 closed enum).
    """
    from endpoint_class import endpoint_class
    from model_family import model_family

    if llm_config is None:
        return {"llmSource": "unknown", "modelFamily": "unknown"}

    url = str(getattr(llm_config, "url", "") or "")
    source = "unknown"
    if url:
        try:
            from config import get_settings
            cloud_base = (get_settings().cloud.base_url or "").rstrip("/")
        except Exception:
            cloud_base = ""
        if cloud_base and url.startswith(cloud_base):
            source = "stimma_cloud"
        else:
            source = "endpoint"

    fields: Dict[str, Any] = {
        "llmSource": source,
        "modelFamily": model_family(getattr(llm_config, "model", None)),
    }
    if source == "endpoint":
        fields["endpointClass"] = endpoint_class(url)
    return fields
