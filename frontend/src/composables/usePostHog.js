import posthog from 'posthog-js'
import { watch } from 'vue'
import {
  installIdRef,
  sessionRecordingEnabledRef,
  telemetryEnabledRef,
} from '../appConfig'
import { getCachedFlags, initFeatureFlags } from './useFeatureFlags'

let initialized = false

export function initPostHog() {
  if (initialized) return
  const key = import.meta.env.VITE_POSTHOG_KEY
  const host = import.meta.env.VITE_POSTHOG_HOST || 'https://us.i.posthog.com'
  if (!key) {
    console.log('[posthog] VITE_POSTHOG_KEY not set, skipping init')
    return
  }
  const installId = installIdRef.value
  if (!installId) {
    console.warn('[posthog] install_id missing at init; skipping')
    return
  }

  posthog.init(key, {
    api_host: host,
    person_profiles: 'identified_only',
    // URLs aren't a meaningful analytics primitive in a Tauri app — Vue
    // Router paths like /recipes/12 would otherwise pollute PostHog's Web
    // analytics dashboard alongside real stimma.ai pageviews. Track app
    // activity through explicit named events (see TELEMETRY.md) instead.
    capture_pageview: false,
    capture_pageleave: false,
    // Autocapture is OFF in the desktop app: it captures DOM element text and
    // input values, which in a creative tool would include filenames, library
    // search queries, and prompt fragments — directly contradicting the
    // privacy policy's promise that telemetry excludes prompts, file names,
    // and content. App analytics flow through explicit named events only
    // (see TELEMETRY.md). The web/marketing site keeps autocapture on.
    autocapture: false,
    disable_session_recording: true,
    session_recording: {
      maskAllInputs: false,
      maskInputOptions: { password: true },
    },
    bootstrap: { distinctID: installId, featureFlags: getCachedFlags() },
    opt_out_capturing_by_default: !telemetryEnabledRef.value,
  })
  initialized = true

  // Wire posthog-js flag updates into the reactive store. Bootstrap above
  // already seeded the cached values so reads work immediately; this hooks
  // up runtime updates so components re-render when flags change.
  initFeatureFlags()

  // Tag every event so we can split app vs web in PostHog. Pair with
  // `source: 'web'` set by stimma-cloud's PostHogTracker.
  posthog.register({ source: 'app', installId })

  posthog.identify(installId)

  // Frontend owns the app-lifecycle event; the sidecar fires `session_started`
  // (with rich library stats) once it sees this app launch's $session_id via
  // the X-Stimma-Session-Id header on the first API call.
  posthog.capture('app_launched')

  if (sessionRecordingEnabledRef.value && telemetryEnabledRef.value) {
    posthog.startSessionRecording()
  }

  watch(sessionRecordingEnabledRef, (enabled) => {
    if (!initialized) return
    if (enabled && telemetryEnabledRef.value) posthog.startSessionRecording()
    else posthog.stopSessionRecording()
  })

  watch(telemetryEnabledRef, (enabled) => {
    if (!initialized) return
    if (enabled) {
      posthog.opt_in_capturing()
      if (sessionRecordingEnabledRef.value) posthog.startSessionRecording()
    } else {
      posthog.stopSessionRecording()
      posthog.opt_out_capturing()
    }
  })
}

export function isPostHogInitialized() {
  return initialized
}

export function capturePostHog(event, properties = {}) {
  if (!initialized) return
  posthog.capture(event, properties)
}

/**
 * Identify the current install as a Stimma Cloud user.
 *
 * Called when the user signs into Cloud. Aliases install_id → firebase
 * UID so events from this install are merged into the same PostHog
 * person used by the marketing site (which identifies on signin), then
 * switches the active distinct_id to the Firebase UID for future events.
 */
export function identifyPostHogCloudUser(user) {
  if (!initialized || !user?.uid) return
  try {
    posthog.alias(user.uid, posthog.get_distinct_id())
  } catch (err) {
    console.warn('[posthog] alias failed', err)
  }
  // UID only — desktop app does not send email or other PII to PostHog.
  // The web side identifies with email separately on the marketing surface.
  posthog.identify(user.uid)
}

/**
 * Drop the Cloud-user identity and revert to install_id.
 * Called when the user signs out of Cloud.
 */
export function resetPostHogCloudUser() {
  if (!initialized) return
  posthog.reset()
  // Re-anchor to install_id so events stay correlated to this install.
  const installId = installIdRef.value
  if (installId) {
    posthog.register({ source: 'app', installId })
    posthog.identify(installId)
  }
}

export { posthog }
