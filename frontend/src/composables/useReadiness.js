/**
 * App-entry readiness gate (OOBE entitlement flow).
 *
 * Readiness comes from GET /api/settings (`settings.readiness`), computed by
 * the backend from cloud auth state + local LLM config + provider registry.
 * This composable owns:
 *  - the cached readiness value + a refresh helper
 *  - the "don't show this again" per-profile flag
 *  - post-login handling (refresh account + readiness, show the panel if
 *    still not ready)
 *
 * See plans/OOBE_ENTITLEMENT_FLOW.md.
 */
import { ref, computed, readonly } from 'vue'
import { useSettingsApi } from './useSettingsApi'
import { fetchCloudAccount } from './useCloudAccount'
import { makeProfileKey } from '../utils/storageKeys'

// Global reactive state (shared across all components)
const readiness = ref(null) // { ready, has_agent_llm, has_generation, missing } | null while unknown
const dismissedForSession = ref(false)
const dontShowAgain = ref(false)

let dontShowKeyCached = null

function dontShowKey() {
  if (!dontShowKeyCached) {
    dontShowKeyCached = makeProfileKey('readiness_panel', 'dont_show')
  }
  return dontShowKeyCached
}

function loadDontShowAgain() {
  try {
    dontShowAgain.value = localStorage.getItem(dontShowKey()) === '1'
  } catch (e) {
    dontShowAgain.value = false
  }
  return dontShowAgain.value
}

function setDontShowAgain(value) {
  dontShowAgain.value = value
  try {
    if (value) {
      localStorage.setItem(dontShowKey(), '1')
    } else {
      localStorage.removeItem(dontShowKey())
    }
  } catch (e) {
    // localStorage unavailable — in-memory value still applies for this session
  }
}

/**
 * Refetch settings and update the cached readiness value.
 */
async function refreshReadiness() {
  try {
    const { fetchSettings } = useSettingsApi()
    const settings = await fetchSettings()
    if (settings.readiness) {
      readiness.value = settings.readiness
    }
  } catch (e) {
    console.error('[useReadiness] failed to refresh readiness:', e)
  }
  return readiness.value
}

/**
 * Pull the fresh balance from the cloud BEFORE reading readiness.
 *
 * /api/settings computes readiness from the backend's *cached* auth state,
 * which stays stale after an in-session balance top-up until GET
 * /api/auth/account refreshes it. Refreshing the account here also connects
 * the cloud tool provider on the zero->positive balance transition (see
 * backend /auth/account).
 */
async function refreshAccountThenReadiness() {
  try {
    await fetchCloudAccount()
  } catch (e) {
    // Not signed in / cloud unreachable — fall back to cached readiness.
  }
  return refreshReadiness()
}

/**
 * Run once per completed login (see useAuth.js): refresh account + readiness
 * and let shouldShowPanel decide whether the panel needs to appear.
 */
async function handleLoginChoice() {
  dismissedForSession.value = false
  await refreshAccountThenReadiness()
}

/**
 * Run once at app startup, after the onboarding gate has already passed
 * (a truly fresh user with no onboarding_completed flag goes to onboarding
 * instead, never this).
 */
async function checkStartupReadiness() {
  loadDontShowAgain()
  await refreshReadiness()
  return readiness.value
}

const shouldShowPanel = computed(() => {
  if (dismissedForSession.value) return false
  if (dontShowAgain.value) return false
  return !!(readiness.value && !readiness.value.ready)
})

function dismissPanel() {
  dismissedForSession.value = true
}

export function useReadiness() {
  return {
    readiness: readonly(readiness),
    dontShowAgain: readonly(dontShowAgain),
    shouldShowPanel,

    refreshReadiness,
    refreshAccountThenReadiness,
    checkStartupReadiness,
    handleLoginChoice,
    dismissPanel,
    setDontShowAgain,
  }
}
