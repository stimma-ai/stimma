/**
 * Build distribution flag — compile-time constant injected by Vite
 * (`define` in vite.config.js): 'dev' (default) or 'official' (set only
 * by release CI).
 *
 * Gates the consent UI (onboarding strip, Settings privacy toggle).
 * Source builds show the permanently-disabled telemetry treatment instead.
 */

/* global __STIMMA_DISTRIBUTION__ */
export const DISTRIBUTION =
  typeof __STIMMA_DISTRIBUTION__ !== 'undefined' ? __STIMMA_DISTRIBUTION__ : 'dev'

export function isOfficialBuild() {
  return DISTRIBUTION === 'official'
}
