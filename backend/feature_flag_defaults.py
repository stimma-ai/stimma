"""
Default values for PostHog feature flags evaluated by the sidecar.

When adding a new flag, add it here AND to
``frontend/src/featureFlagDefaults.js`` so first-launch behavior is
deterministic before either process has fetched flag definitions.

Flag names should be lowercase-snake-case.
"""
from typing import Any, Dict

FLAG_DEFAULTS: Dict[str, Any] = {
    # Example: "recipe_v3_ui": False,
}
