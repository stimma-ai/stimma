"""
Local default values for feature flags evaluated by the sidecar.

These are the fallbacks used before the first ``/api/feature-flags``
fetch completes (and permanently under ``DO_NOT_TRACK=1``, which
suppresses the fetch). When adding a new flag, add it here AND to
``frontend/src/featureFlagDefaults.js`` so first-launch behavior is
deterministic in both processes.

Flag names should be lowercase-snake-case.
"""
from typing import Any, Dict

FLAG_DEFAULTS: Dict[str, Any] = {
    # Example: "flow_v3_ui": False,
}
