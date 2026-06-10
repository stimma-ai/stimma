/**
 * Local default values for feature flags evaluated by the frontend.
 *
 * These are the fallbacks used before the sidecar's flag bag arrives (and
 * permanently under DO_NOT_TRACK=1, which suppresses the server fetch).
 * When adding a new flag, add it here AND to
 * backend/feature_flag_defaults.py so first-launch behavior is
 * deterministic in both processes.
 *
 * Flag names should be lowercase-snake-case.
 */
export const FLAG_DEFAULTS = {
  // Example: recipe_v3_ui: false,
}
