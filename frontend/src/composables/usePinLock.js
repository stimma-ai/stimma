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

// In-memory PIN cache: profileId -> { pin: string, lastActivity: number }
// Hydrated from sessionStorage on load
const pinCache = new Map()

// Hydrate PIN cache from sessionStorage on module load
try {
  const stored = sessionStorage.getItem(getPinCacheStorageKey())
  if (stored) {
    const data = JSON.parse(stored)
    for (const [profileId, entry] of Object.entries(data)) {
      // Restore with updated lastActivity to prevent immediate timeout
      pinCache.set(profileId, {
        pin: entry.pin,
        lastActivity: Date.now()
      })
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
      data[profileId] = { pin: entry.pin, lastActivity: entry.lastActivity }
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

/**
 * Update last activity timestamp for a profile.
 */
function updateActivity(profileId = null) {
  const id = profileId || getCurrentProfileId()
  const cached = pinCache.get(id)
  if (cached) {
    cached.lastActivity = Date.now()
    // Note: We don't persist on every activity update for performance.
    // Activity is reset to Date.now() on hydration anyway.
  }
}

/**
 * Activity event handler - updates timestamp on user interaction.
 */
function handleActivity() {
  updateActivity()
}

/**
 * Start idle tracking by listening to user activity events.
 */
function startIdleTracking() {
  if (typeof window === 'undefined') return

  // Listen for activity events
  window.addEventListener('mousemove', handleActivity, { passive: true })
  window.addEventListener('mousedown', handleActivity, { passive: true })
  window.addEventListener('keydown', handleActivity, { passive: true })
  window.addEventListener('touchstart', handleActivity, { passive: true })
  window.addEventListener('scroll', handleActivity, { passive: true })

  // Start periodic idle check
  if (!idleCheckInterval) {
    idleCheckInterval = setInterval(checkIdleTimeouts, IDLE_CHECK_INTERVAL_MS)
  }
}

/**
 * Stop idle tracking and clean up event listeners.
 */
function stopIdleTracking() {
  if (typeof window === 'undefined') return

  window.removeEventListener('mousemove', handleActivity)
  window.removeEventListener('mousedown', handleActivity)
  window.removeEventListener('keydown', handleActivity)
  window.removeEventListener('touchstart', handleActivity)
  window.removeEventListener('scroll', handleActivity)

  if (idleCheckInterval) {
    clearInterval(idleCheckInterval)
    idleCheckInterval = null
  }
}

/**
 * Check all cached PINs for idle timeout expiration.
 */
async function checkIdleTimeouts() {
  const now = Date.now()

  for (const [profileId, cached] of pinCache.entries()) {
    // Fetch timeout for this profile
    const timeout = await getProfilePinTimeout(profileId)
    if (timeout === null) continue // No PIN configured

    const timeoutMs = timeout * 60 * 1000
    const elapsed = now - cached.lastActivity

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
  pinCache.set(profileId, {
    pin,
    lastActivity: Date.now()
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
