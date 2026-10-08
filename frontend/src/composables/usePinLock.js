/**
 * PIN lock composable for profile protection.
 *
 * Manages PIN cache with sessionStorage persistence, idle timeout tracking, and PIN modal state.
 * PINs are cached in sessionStorage to survive page reloads within the same browser session,
 * but are cleared when the browser tab is closed.
 */
import { ref, readonly, nextTick } from 'vue'
import { getCurrentProfileId } from './useProfile'
import { getApiBase } from '../apiConfig'
import { makeGlobalKey } from '../utils/storageKeys'

// PIN cache storage key (global, not per-profile — PIN cache spans profiles)
function getPinCacheStorageKey() {
  return makeGlobalKey('pin_cache')
}

// In-memory PIN cache:
//   profileId -> { pin: string, lastActivity: number, timeoutMinutes: number|null }
// Hydrated from sessionStorage on load. timeoutMinutes is the idle limit the
// server last reported for the profile; it lets hydration expire an entry
// without a round trip.
const pinCache = new Map()
const pinTimeouts = new Map()
const DEFAULT_TIMEOUT_MINUTES = 30

// Hydrate PIN cache from sessionStorage on module load. The persisted
// lastActivity is honored: the idle clock must survive a reload, because the
// app reloads itself on every device switch, retry, and profile switch, and
// restarting the clock on each of those meant a PIN could effectively never
// expire while working remotely.
try {
  const stored = sessionStorage.getItem(getPinCacheStorageKey())
  if (stored) {
    const data = JSON.parse(stored)
    const now = Date.now()
    for (const [profileId, entry] of Object.entries(data)) {
      if (!entry?.pin) continue
      // Old entries without a trustworthy deadline must require a fresh PIN.
      if (!Number.isFinite(entry.lastActivity) || !Number.isFinite(entry.timeoutMinutes)) continue
      const { lastActivity, timeoutMinutes } = entry
      if (now - lastActivity >= timeoutMinutes * 60 * 1000) continue
      pinCache.set(profileId, { pin: entry.pin, lastActivity, timeoutMinutes })
    }
  }
} catch (e) {
  // Ignore parse errors, start fresh
}

/**
 * Persist PIN cache to sessionStorage.
 */
function persistPinCache() {
  try {
    const data = {}
    for (const [profileId, entry] of pinCache.entries()) {
      data[profileId] = {
        pin: entry.pin,
        lastActivity: entry.lastActivity,
        timeoutMinutes: entry.timeoutMinutes ?? null,
      }
    }
    sessionStorage.setItem(getPinCacheStorageKey(), JSON.stringify(data))
  } catch (e) {
    // Ignore storage errors (e.g., quota exceeded)
  }
}

// Modal state
const showPinModal = ref(false)
const pinModalProfileId = ref(null)
const pinModalError = ref('')
const pinModalCallback = ref(null)

// Expiry is local and synchronous. Network refreshes must never hold the
// privacy boundary open, and a returning input must not revive an expired PIN.
let idleCheckInterval = null
let idleDeadlineTimer = null
let tracking = false
let nativeActive = true
let privacyEpoch = 0
const IDLE_CHECK_INTERVAL_MS = 10000
const ACTIVITY_PERSIST_INTERVAL_MS = 5000
let lastActivityPersistAt = 0

function coverPrivateContent() {
  privacyEpoch++
  document.documentElement.setAttribute('data-pin-privacy', '')
}

function contentVisible() {
  return nativeActive && document.visibilityState !== 'hidden'
}

function interfaceActive() {
  return contentVisible() && document.hasFocus()
}

async function revealPrivateContent() {
  const epoch = ++privacyEpoch
  // Auto-lock listeners change Vue state synchronously; wait for their DOM
  // patch before removing the cover, including teleported media and dialogs.
  await nextTick()
  if (epoch === privacyEpoch && contentVisible()) {
    document.documentElement.removeAttribute('data-pin-privacy')
  }
}

function expirePin(profileId, cached, now = Date.now()) {
  if (now - cached.lastActivity < cached.timeoutMinutes * 60 * 1000) return false
  pinCache.delete(profileId)
  persistPinCache()
  if (profileId === getCurrentProfileId()) {
    coverPrivateContent()
    window.dispatchEvent(new CustomEvent('pin-auto-locked', { detail: { profileId } }))
    void revealPrivateContent()
  }
  return true
}

function checkLocalTimeouts() {
  const now = Date.now()
  for (const [profileId, cached] of pinCache) expirePin(profileId, cached, now)
  scheduleIdleDeadline()
}

function scheduleIdleDeadline() {
  clearTimeout(idleDeadlineTimer)
  idleDeadlineTimer = null
  if (!tracking || !pinCache.size) return
  const deadline = Math.min(...[...pinCache.values()].map(c => c.lastActivity + c.timeoutMinutes * 60 * 1000))
  idleDeadlineTimer = setTimeout(checkLocalTimeouts, Math.max(0, deadline - Date.now()))
}

// Called whenever profile metadata loads (including timeout edits). Cache the
// policy even before a PIN is entered so unlock starts with the actual limit.
function syncPinTimeouts(profiles) {
  for (const profile of profiles) {
    if (!profile.has_pin) {
      pinTimeouts.delete(profile.id)
      pinCache.delete(profile.id)
      continue
    }
    const timeout = profile.pin_idle_timeout_minutes || DEFAULT_TIMEOUT_MINUTES
    pinTimeouts.set(profile.id, timeout)
    const cached = pinCache.get(profile.id)
    if (cached) cached.timeoutMinutes = timeout
  }
  checkLocalTimeouts()
  persistPinCache()
}

function updateActivity(profileId = null) {
  const id = profileId || getCurrentProfileId()
  const cached = pinCache.get(id)
  if (!cached) return
  const now = Date.now()
  if (expirePin(id, cached, now)) {
    scheduleIdleDeadline()
    return
  }
  cached.lastActivity = now
  scheduleIdleDeadline()
  if (now - lastActivityPersistAt >= ACTIVITY_PERSIST_INTERVAL_MS) {
    lastActivityPersistAt = now
    persistPinCache()
  }
}

function handleActivity(event) {
  if (!interfaceActive()) return
  const cached = pinCache.get(getCurrentProfileId())
  if (cached && expirePin(getCurrentProfileId(), cached)) {
    // Consume the waking gesture rather than deliver it to private controls.
    event?.stopImmediatePropagation()
    if (event?.cancelable) event.preventDefault()
    scheduleIdleDeadline()
    return
  }
  updateActivity()
}

function handleInactive() {
  if (pinCache.has(getCurrentProfileId())) coverPrivateContent()
  checkLocalTimeouts()
}

function handleBlur() {
  // A visible desktop window can lose focus without being backgrounded.
  // Recheck expiry, but keep an unlocked workspace visible.
  checkLocalTimeouts()
}

function handleResume() {
  checkLocalTimeouts()
  // Focus and visibility are lifecycle signals, not user activity.
  void revealPrivateContent()
}

function handleVisibility() {
  if (document.visibilityState === 'hidden') handleInactive()
  else handleResume()
}

function handleNativeActivity(event) {
  nativeActive = event.detail === true
  if (nativeActive) handleResume()
  else handleInactive()
}

const activityEvents = ['mousemove', 'scroll', 'mousedown', 'keydown', 'touchstart']
function startIdleTracking() {
  if (typeof window === 'undefined' || tracking) return
  tracking = true
  for (const type of activityEvents) window.addEventListener(type, handleActivity, true)
  window.addEventListener('blur', handleBlur)
  window.addEventListener('focus', handleResume)
  window.addEventListener('pagehide', handleInactive)
  window.addEventListener('pageshow', handleResume)
  window.addEventListener('stimma:app-active', handleNativeActivity)
  document.addEventListener('visibilitychange', handleVisibility)
  checkLocalTimeouts()
  if (!contentVisible()) handleInactive()
  idleCheckInterval = setInterval(checkIdleTimeouts, IDLE_CHECK_INTERVAL_MS)
  void checkIdleTimeouts()
}

function stopIdleTracking() {
  if (typeof window === 'undefined') return
  tracking = false
  for (const type of activityEvents) window.removeEventListener(type, handleActivity, true)
  window.removeEventListener('blur', handleBlur)
  window.removeEventListener('focus', handleResume)
  window.removeEventListener('pagehide', handleInactive)
  window.removeEventListener('pageshow', handleResume)
  window.removeEventListener('stimma:app-active', handleNativeActivity)
  document.removeEventListener('visibilitychange', handleVisibility)
  clearInterval(idleCheckInterval)
  clearTimeout(idleDeadlineTimer)
  idleCheckInterval = idleDeadlineTimer = null
}

async function checkIdleTimeouts() {
  checkLocalTimeouts()
  for (const [profileId, cached] of pinCache) {
    const requestedTimeout = cached.timeoutMinutes
    const reported = await getProfilePinTimeout(profileId)
    // A late response must not mutate a replacement PIN or resurrect expiry.
    if (pinCache.get(profileId) !== cached) continue
    if (reported !== null && cached.timeoutMinutes === requestedTimeout) {
      cached.timeoutMinutes = reported
      pinTimeouts.set(profileId, reported)
      persistPinCache()
    }
    checkLocalTimeouts()
  }
}

/**
 * Get the PIN idle timeout for a profile (in minutes).
 * Returns null if profile has no PIN configured.
 */
async function getProfilePinTimeout(profileId) {
  try {
    const response = await fetch(`${getApiBase()}/profiles`, { signal: AbortSignal.timeout(5000) })
    if (!response.ok) return null

    const data = await response.json()
    const profile = data.profiles?.find(p => p.id === profileId)
    return profile?.has_pin ? (profile.pin_idle_timeout_minutes || 30) : null
  } catch {
    return null
  }
}

/**
 * Check if a profile requires PIN entry.
 */
async function profileRequiresPin(profileId) {
  try {
    const response = await fetch(`${getApiBase()}/profiles`)
    if (!response.ok) return false

    const data = await response.json()
    const profile = data.profiles?.find(p => p.id === profileId)
    return profile?.has_pin === true
  } catch {
    return false
  }
}

/**
 * Check if we have a valid cached PIN for a profile.
 */
function hasCachedPin(profileId) {
  return getCachedPin(profileId) !== null
}

/**
 * Get the cached PIN for a profile.
 */
function getCachedPin(profileId) {
  const cached = pinCache.get(profileId)
  if (!cached) return null
  if (expirePin(profileId, cached)) {
    scheduleIdleDeadline()
    return null
  }
  return cached.pin
}

/**
 * Cache a PIN for a profile.
 */
function cachePin(profileId, pin) {
  const previous = pinCache.get(profileId)
  pinCache.set(profileId, {
    pin,
    lastActivity: Date.now(),
    timeoutMinutes: pinTimeouts.get(profileId) ?? previous?.timeoutMinutes ?? DEFAULT_TIMEOUT_MINUTES,
  })
  persistPinCache()
  scheduleIdleDeadline()
  if (profileId === getCurrentProfileId() && !contentVisible()) coverPrivateContent()
}

/**
 * Clear the cached PIN for a profile.
 */
function clearCachedPin(profileId) {
  pinCache.delete(profileId)
  persistPinCache()
  scheduleIdleDeadline()
}

/**
 * Clear all cached PINs.
 */
function clearAllCachedPins() {
  pinCache.clear()
  persistPinCache()
  scheduleIdleDeadline()
}

/**
 * Request PIN entry from the user.
 * Shows the PIN modal and returns a promise that resolves when PIN is entered.
 *
 * @param {string} profileId - The profile ID requiring PIN
 * @returns {Promise<string>} - Resolves with the entered PIN, rejects if cancelled
 */
function requestPin(profileId) {
  return new Promise((resolve, reject) => {
    pinModalProfileId.value = profileId
    pinModalError.value = ''
    pinModalCallback.value = { resolve, reject }
    showPinModal.value = true
  })
}

/**
 * Submit PIN from the modal.
 * Verifies with backend and caches if valid.
 *
 * @param {string} pin - The PIN entered by user
 */
async function submitPin(pin) {
  const profileId = pinModalProfileId.value
  if (!profileId) return

  try {
    // Verify PIN with backend
    const response = await fetch(`${getApiBase()}/profiles/${profileId}/verify-pin`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Profile-ID': profileId
      },
      body: JSON.stringify({ pin })
    })

    if (response.ok) {
      // Cache the PIN
      cachePin(profileId, pin)
      showPinModal.value = false
      pinModalError.value = ''

      // Resolve the promise
      if (pinModalCallback.value) {
        pinModalCallback.value.resolve(pin)
        pinModalCallback.value = null
      }
    } else {
      const data = await response.json().catch(() => ({}))
      pinModalError.value = data.detail || 'Invalid PIN'
    }
  } catch (error) {
    pinModalError.value = 'Failed to verify PIN'
    console.error('[PinLock] PIN verification error:', error)
  }
}

/**
 * Cancel PIN entry.
 */
function cancelPinEntry() {
  showPinModal.value = false
  pinModalError.value = ''

  // Reject the promise
  if (pinModalCallback.value) {
    pinModalCallback.value.reject(new Error('PIN entry cancelled'))
    pinModalCallback.value = null
  }
}

/**
 * Ensure PIN is available for a profile before proceeding.
 * If profile requires PIN and none is cached, prompts user.
 *
 * @param {string} profileId - The profile ID to check
 * @returns {Promise<string|null>} - The PIN if required, null if no PIN needed
 */
async function ensurePinForProfile(profileId) {
  const requiresPin = await profileRequiresPin(profileId)
  if (!requiresPin) {
    return null
  }

  // Check cache
  if (hasCachedPin(profileId)) {
    updateActivity(profileId)
    return getCachedPin(profileId)
  }

  // Request PIN from user
  return requestPin(profileId)
}

/**
 * Composable hook for PIN lock functionality.
 */
export function usePinLock() {
  // Start idle tracking when composable is used
  startIdleTracking()

  return {
    // Modal state (readonly)
    showPinModal: readonly(showPinModal),
    pinModalProfileId: readonly(pinModalProfileId),
    pinModalError: readonly(pinModalError),

    // Cache operations
    hasCachedPin,
    getCachedPin,
    cachePin,
    clearCachedPin,
    clearAllCachedPins,

    // Modal operations
    requestPin,
    submitPin,
    cancelPinEntry,

    // Profile checks
    profileRequiresPin,
    ensurePinForProfile,

    // Activity tracking
    updateActivity,
    startIdleTracking,
    stopIdleTracking,
  }
}

// Export individual functions for use outside composable
export {
  syncPinTimeouts,
  hasCachedPin,
  getCachedPin,
  cachePin,
  clearCachedPin,
  clearAllCachedPins,
  profileRequiresPin,
  ensurePinForProfile,
  requestPin,
  submitPin,
  cancelPinEntry,
  updateActivity,
  startIdleTracking,
  stopIdleTracking,
  showPinModal,
  pinModalProfileId,
  pinModalError,
}
