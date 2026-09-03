/**
 * PIN lock composable for profile protection.
 *
 * Manages PIN cache with sessionStorage persistence, idle timeout tracking, and PIN modal state.
 * PINs are cached in sessionStorage to survive page reloads within the same browser session,
 * but are cleared when the browser tab is closed.
 */
import { ref, readonly, computed, watch, onUnmounted } from 'vue'
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
      const lastActivity = Number.isFinite(entry.lastActivity) ? entry.lastActivity : now
      const timeoutMinutes = Number.isFinite(entry.timeoutMinutes) ? entry.timeoutMinutes : null
      if (timeoutMinutes !== null && now - lastActivity >= timeoutMinutes * 60 * 1000) continue
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

// Idle tracking state
let idleCheckInterval = null
const IDLE_CHECK_INTERVAL_MS = 10000 // Check every 10 seconds
// Activity is persisted at most this often; the idle limit is minutes, so a
// clock that lags by a few seconds across a reload is fine.
const ACTIVITY_PERSIST_INTERVAL_MS = 5000
let lastActivityPersistAt = 0

/**
 * Update last activity timestamp for a profile.
 */
function updateActivity(profileId = null) {
  const id = profileId || getCurrentProfileId()
  const cached = pinCache.get(id)
  if (cached) {
    const now = Date.now()
    cached.lastActivity = now
    if (now - lastActivityPersistAt >= ACTIVITY_PERSIST_INTERVAL_MS) {
      lastActivityPersistAt = now
      persistPinCache()
    }
  }
}

/**
 * Activity event handler - updates timestamp on user interaction.
 */
function handleActivity() {
  updateActivity()
}

/**
 * Pointer motion only counts while the window is focused. An unfocused
 * window still receives mousemove when the cursor crosses it on the way to
 * another app, and that must not keep a locked-away profile open.
 */
function handleFocusedActivity() {
  if (typeof document !== 'undefined' && !document.hasFocus()) return
  updateActivity()
}

/**
 * Start idle tracking by listening to user activity events.
 */
function startIdleTracking() {
  if (typeof window === 'undefined') return

  // Listen for activity events
  window.addEventListener('mousemove', handleFocusedActivity, { passive: true })
  window.addEventListener('scroll', handleFocusedActivity, { passive: true })
  window.addEventListener('mousedown', handleActivity, { passive: true })
  window.addEventListener('keydown', handleActivity, { passive: true })
  window.addEventListener('touchstart', handleActivity, { passive: true })
  window.addEventListener('focus', handleActivity, { passive: true })

  // Start periodic idle check. Run one immediately: a reload restores the
  // clock from storage and may already be past the limit.
  if (!idleCheckInterval) {
    idleCheckInterval = setInterval(checkIdleTimeouts, IDLE_CHECK_INTERVAL_MS)
    void checkIdleTimeouts()
  }
}

/**
 * Stop idle tracking and clean up event listeners.
 */
function stopIdleTracking() {
  if (typeof window === 'undefined') return

  window.removeEventListener('mousemove', handleFocusedActivity)
  window.removeEventListener('scroll', handleFocusedActivity)
  window.removeEventListener('mousedown', handleActivity)
  window.removeEventListener('keydown', handleActivity)
  window.removeEventListener('touchstart', handleActivity)
  window.removeEventListener('focus', handleActivity)

  if (idleCheckInterval) {
    clearInterval(idleCheckInterval)
    idleCheckInterval = null
  }
}

/**
 * Check all cached PINs for idle timeout expiration.
 *
 * The limit comes from the connected server. When it cannot be reached the
 * last value it reported is used, so a flaky remote link cannot postpone
 * expiry indefinitely.
 */
async function checkIdleTimeouts() {
  for (const [profileId, cached] of pinCache.entries()) {
    const reported = await getProfilePinTimeout(profileId)
    if (reported !== null) {
      cached.timeoutMinutes = reported
    }
    const timeout = cached.timeoutMinutes
    if (timeout === null || timeout === undefined) continue // No PIN configured, or never learned

    const timeoutMs = timeout * 60 * 1000
    const elapsed = Date.now() - cached.lastActivity

    if (elapsed >= timeoutMs) {
      // PIN expired - remove from cache
      pinCache.delete(profileId)
      persistPinCache()
      console.log(`[PinLock] PIN cache expired for profile: ${profileId}`)

      // If this is the current profile, notify the app to show lock screen
      if (profileId === getCurrentProfileId()) {
        window.dispatchEvent(new CustomEvent('pin-auto-locked', { detail: { profileId } }))
      }
    }
  }
}

/**
 * Get the PIN idle timeout for a profile (in minutes).
 * Returns null if profile has no PIN configured.
 */
async function getProfilePinTimeout(profileId) {
  try {
    const response = await fetch(`${getApiBase()}/profiles`)
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
  return pinCache.has(profileId)
}

/**
 * Get the cached PIN for a profile.
 */
function getCachedPin(profileId) {
  const cached = pinCache.get(profileId)
  return cached?.pin || null
}

/**
 * Cache a PIN for a profile.
 */
function cachePin(profileId, pin) {
  const previous = pinCache.get(profileId)
  pinCache.set(profileId, {
    pin,
    lastActivity: Date.now(),
    timeoutMinutes: previous?.timeoutMinutes ?? null,
  })
  persistPinCache()
}

/**
 * Clear the cached PIN for a profile.
 */
function clearCachedPin(profileId) {
  pinCache.delete(profileId)
  persistPinCache()
}

/**
 * Clear all cached PINs.
 */
function clearAllCachedPins() {
  pinCache.clear()
  persistPinCache()
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
