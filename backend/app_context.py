"""
Global application context for runtime state.

Stores the bundle ID and sandbox name set at startup, used by app_dirs
and config loading to determine directory paths.

Bundle ID identifies the release channel (e.g., "ai.stimma.stimma.debug").
Sandbox identifies an isolated instance within that channel (e.g., "default").
"""

BUNDLE_ID_STABLE = "ai.stimma.stimma"
BUNDLE_ID_BETA = "ai.stimma.stimma.beta"
BUNDLE_ID_CANARY = "ai.stimma.stimma.canary"
BUNDLE_ID_DEBUG = "ai.stimma.stimma.debug"

_bundle_id: str = BUNDLE_ID_DEBUG
_sandbox: str = "default"


def set_app_context(bundle_id: str, sandbox: str = "default") -> None:
    """Set the app context at startup."""
    global _bundle_id, _sandbox
    _bundle_id = bundle_id
    _sandbox = sandbox


def get_bundle_id() -> str:
    """Get the current bundle ID (release channel identifier)."""
    return _bundle_id


def get_sandbox() -> str:
    """Get the current sandbox name."""
    return _sandbox
