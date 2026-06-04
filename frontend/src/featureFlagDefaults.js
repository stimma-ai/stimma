/**
 * Default values for PostHog feature flags evaluated by the frontend.
 *
 * When adding a new flag, add it here AND to
 * backend/feature_flag_defaults.py so first-launch behavior is
 * deterministic before either process has fetched flag definitions.
 *
 * Flag names should be lowercase-snake-case.
 */
export const FLAG_DEFAULTS = {
  // Example: recipe_v3_ui: false,
}
