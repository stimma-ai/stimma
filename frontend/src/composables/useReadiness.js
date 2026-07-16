/**
 * App-entry readiness gate (OOBE entitlement flow).
 *
 * Readiness comes from GET /api/settings (`settings.readiness`), computed by
 * the backend from cloud auth state + local LLM config + provider registry.
 * This composable owns:
 *  - the cached readiness value + a refresh helper
 *  - the setup-wizard show/seen logic. The wizard is VERSIONED on the
 *    backend (SETUP_WIZARD_VERSION in routes/settings.py, persisted as
 *    config `setup_wizard_seen_version`): it auto-shows whenever the
 *    persisted seen version is behind the current version, and any
 *    dismissal marks the current version seen via
 *    POST /api/settings/setup-wizard-seen. Bumping the backend constant
 *    re-runs the wizard for every install that hasn't seen the new one.
 *  - post-login handling (refresh account + readiness, show the panel if
 *    still due)
 *
 * See plans/OOBE_ENTITLEMENT_FLOW.md.
 */
import { ref, computed, readonly } from 'vue'
import axios from 'axios'
import { useSettingsApi } from './useSettingsApi'
import { fetchCloudAccount } from './useCloudAccount'
import { getApiBase } from '../apiConfig'

// Global reactive state (shared across all components)
const readiness = ref(null) // { ready, has_agent_llm, has_generation, missing, wizard_version, wizard_seen_version } | null while unknown
const dismissedForSession = ref(false)

// Dev-only override: forces the wizard to show regardless of the seen
// version (Settings → Developer → Run Setup Wizard).
const forceShowForDev = ref(false)

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
  await refreshReadiness()
  return readiness.value
}

const shouldShowPanel = computed(() => {
  if (forceShowForDev.value) return true
  if (dismissedForSession.value) return false
  const r = readiness.value
  if (!r) return false
  return (r.wizard_seen_version ?? 0) < (r.wizard_version ?? 0)
})

function dismissPanel() {
  dismissedForSession.value = true
  forceShowForDev.value = false
}

/**
 * Persist that this install has seen the current wizard version. Called on
 * every wizard dismissal path; the wizard then stays away until the backend
 * bumps SETUP_WIZARD_VERSION.
 */
async function markWizardSeen() {
  try {
    const { data } = await axios.post(`${getApiBase()}/settings/setup-wizard-seen`)
    if (readiness.value) {
      readiness.value = { ...readiness.value, wizard_seen_version: data.wizard_seen_version }
    }
  } catch (e) {
    console.error('[useReadiness] failed to persist wizard seen version:', e)
  }
}

/**
 * Dev helper: force the wizard open now, regardless of the seen version.
 */
function relaunchWizard() {
  dismissedForSession.value = false
  forceShowForDev.value = true
}

export function useReadiness() {
  return {
    readiness: readonly(readiness),
    shouldShowPanel,

    refreshReadiness,
    refreshAccountThenReadiness,
    checkStartupReadiness,
    handleLoginChoice,
    dismissPanel,
    markWizardSeen,
    relaunchWizard,
  }
}
