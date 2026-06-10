/**
 * Global app configuration loaded from backend at startup.
 *
 * Uses the bundle ID to namespace localStorage keys so different
 * channels (debug, canary, stable, etc.) don't share state.
 */

import { ref } from 'vue'

let bundleId = localStorage.getItem('stimma_bundle_id') || ''
let settingsLoaded = false

// Reactive ref for developer mode - allows Vue components to react to changes
const devModeRef = ref(false)

// Reactive ref for captioning (visual analysis) feature - allows hiding all caption/keyword UI when disabled
const captioningEnabledRef = ref(false)

// Anonymous usage telemetry consent: true/false, or null while undetermined
// (onboarding not completed). Official builds only — dev builds have no
// telemetry regardless.
const telemetryEnabledRef = ref(null)

/**
 * Set the bundle ID from backend settings.
 * Called once at app startup after fetching settings.
 */
export function setBundleId(id) {
  bundleId = id || ''
  localStorage.setItem('stimma_bundle_id', bundleId)
  settingsLoaded = true
}

// Keep old name as alias for backward compatibility during migration
export const setAppModifier = setBundleId

/**
 * Check if settings have been loaded (and thus bundleId is valid).
 */
export function isSettingsLoaded() {
  return settingsLoaded
}

/**
 * Get the current bundle ID.
 * e.g., "ai.stimma.stimma.debug" for dev, "ai.stimma.stimma" for stable.
 */
export function getBundleId() {
  return bundleId
}

// Keep old name as alias for backward compatibility during migration
export const getAppModifier = getBundleId

/**
 * Set developer mode from backend settings.
 * Shows/hides debug tools and developer options in the UI.
 */
export function setDevMode(enabled) {
  devModeRef.value = enabled === true
}

/**
 * Set captioning enabled from backend settings.
 * Controls visibility of all caption/keyword UI elements.
 */
export function setCaptioningEnabled(enabled) {
  captioningEnabledRef.value = enabled === true
}

export function setTelemetryEnabled(enabled) {
  telemetryEnabledRef.value = typeof enabled === 'boolean' ? enabled : null
}

/**
 * Reactive ref for developer mode.
 * Use this in Vue components for reactive updates.
 */
export { devModeRef, captioningEnabledRef, telemetryEnabledRef }
