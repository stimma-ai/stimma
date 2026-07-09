/**
 * App-entry readiness gate (OOBE entitlement flow).
 *
 * Readiness comes from GET /api/settings (`settings.readiness`), computed by
 * the backend from cloud auth state + local LLM config + provider registry.
 * This composable owns:
 *  - the cached readiness value + a refresh helper
 *  - the "don't show this again" per-profile flag
 *  - post-login choice handling (skip -> panel, purchase -> quiet wait ->
 *    panel with finish-checkout affordance if it never resolves)
 *
 * See plans/OOBE_ENTITLEMENT_FLOW.md.
 */
import { ref, computed, readonly } from 'vue'
import { useSettingsApi } from './useSettingsApi'
import { fetchCloudAccount } from './useCloudAccount'
import { makeProfileKey } from '../utils/storageKeys'
import { addToast, removeToast } from './useToasts'

// Global reactive state (shared across all components)
const readiness = ref(null) // { ready, has_agent_llm, has_generation, missing } | null while unknown
const dismissedForSession = ref(false)
const dontShowAgain = ref(false)
const purchaseWaiting = ref(false)
const finishCheckoutNeeded = ref(false)

let dontShowKeyCached = null
let purchaseFocusCount = 0
let purchaseWaitStart = 0
let purchaseWaitTimer = null
let purchaseWaitToastId = null

const PURCHASE_WAIT_MS = 90_000
const PURCHASE_FOCUS_LIMIT = 2
const PURCHASE_POLL_MS = 15_000

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
 * Pull the fresh tier/balance from the cloud BEFORE reading readiness.
 *
 * /api/settings computes readiness from the backend's *cached* auth tier
 * (settings.py `_has_active_subscription`), which stays 'free' after an
 * in-session purchase until GET /api/auth/account refreshes it. Without this,
 * the purchase-wait polls readiness forever, never sees the new subscription,
 * and degrades to "Checkout didn't finish" even though checkout succeeded.
 * Refreshing the account here also connects the cloud tool provider on the
 * free->paid transition (see backend /auth/account).
 */
async function refreshAccountThenReadiness() {
  try {
    await fetchCloudAccount()
  } catch (e) {
    // Not signed in / cloud unreachable — fall back to cached readiness.
  }
  return refreshReadiness()
}

function stopPurchaseWait() {
  purchaseWaiting.value = false
  purchaseFocusCount = 0
  purchaseWaitStart = 0
  if (purchaseWaitTimer) {
    clearInterval(purchaseWaitTimer)
    purchaseWaitTimer = null
  }
  if (typeof window !== 'undefined') {
    window.removeEventListener('focus', onPurchaseWaitFocus)
  }
  if (purchaseWaitToastId != null) {
    removeToast(purchaseWaitToastId)
    purchaseWaitToastId = null
  }
}

async function onPurchaseWaitFocus() {
  if (!purchaseWaiting.value) return
  await refreshAccountThenReadiness()
  if (readiness.value?.ready) {
    stopPurchaseWait()
    return
  }
  purchaseFocusCount += 1
  const elapsed = purchaseWaitStart ? Date.now() - purchaseWaitStart : 0
  if (purchaseFocusCount >= PURCHASE_FOCUS_LIMIT || elapsed >= PURCHASE_WAIT_MS) {
    // Checkout abandoned (or just never finished): degrade to the readiness
    // panel with a finish-checkout affordance. Login itself stayed intact.
    stopPurchaseWait()
    finishCheckoutNeeded.value = true
    dismissedForSession.value = false
  }
}

/**
 * React to the `choice` a desktop login carried back from the plan chooser.
 * Call this once per completed login (see useAuth.js).
 */
async function handleLoginChoice(choice) {
  if (choice === 'purchase') {
    finishCheckoutNeeded.value = false
    dismissedForSession.value = true // quiet wait, not the panel
    purchaseWaiting.value = true
    purchaseWaitStart = Date.now()
    purchaseFocusCount = 0
    purchaseWaitToastId = addToast('Complete your purchase in the browser…', 'info', 0)
    if (typeof window !== 'undefined') {
      window.addEventListener('focus', onPurchaseWaitFocus)
    }
    purchaseWaitTimer = setInterval(async () => {
      await refreshAccountThenReadiness()
      if (readiness.value?.ready) stopPurchaseWait()
    }, PURCHASE_POLL_MS)
    await refreshAccountThenReadiness()
    if (readiness.value?.ready) stopPurchaseWait()
    return
  }

  // choice=skip, or unsubscribed with no choice param (legacy/edge) -> panel.
  finishCheckoutNeeded.value = false
  dismissedForSession.value = false
  await refreshReadiness()
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
  if (purchaseWaiting.value) return false
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
    purchaseWaiting: readonly(purchaseWaiting),
    finishCheckoutNeeded: readonly(finishCheckoutNeeded),
    dontShowAgain: readonly(dontShowAgain),
    shouldShowPanel,

    refreshReadiness,
    checkStartupReadiness,
    handleLoginChoice,
    dismissPanel,
    setDontShowAgain,
  }
}
