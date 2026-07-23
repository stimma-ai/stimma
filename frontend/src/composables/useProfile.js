/**
 * Profile management composable.
 *
 * Manages the current profile state and provides an API fetch wrapper
 * that automatically includes the profile header.
 */
import { ref, readonly, computed } from 'vue'
import axios from 'axios'
import { getApiBase, rewriteUrl, isTauri } from '../apiConfig'
import { getCachedPin } from './usePinLock'

// Global reactive state (shared across all components)
const currentProfileId = ref(localStorage.getItem('profileId') || null)

// In the desktop app each window is pinned to one profile (browser-style
// multi-window). The pinned profile comes from the Rust window registry and
// overrides the localStorage seed above, which only decides the profile for
// the bootstrap window of a fresh install (and for plain web dev).
let windowProfileInitPromise = null

/**
 * Resolve this window's pinned profile from the Rust window registry.
 * Must be awaited before profile-scoped startup work.
 */
export function initWindowProfile() {
  if (!windowProfileInitPromise) {
    windowProfileInitPromise = (async () => {
      if (!isTauri()) return null
      try {
        const { invoke } = await import('@tauri-apps/api/core')
        const profileId = await invoke('get_window_profile')
        if (profileId) {
          currentProfileId.value = profileId
        }
        return profileId || null
      } catch (error) {
        console.warn('[Profile] Failed to resolve window profile:', error)
        return null
      }
    })()
  }
  return windowProfileInitPromise
}

/**
 * Record which profile this window ended up on, so the window registry can
 * restore it on relaunch and focus it on profile switches.
 */
export async function reportWindowProfile(profileId) {
  if (!isTauri() || !profileId) return
  try {
    const { invoke } = await import('@tauri-apps/api/core')
    await invoke('report_window_profile', { profileId })
  } catch (error) {
    console.warn('[Profile] Failed to report window profile:', error)
  }
}

/**
 * Browser-style profile switch: open (or focus) the profile's own window.
 * Returns false outside the desktop app or on failure — callers fall back
 * to the legacy in-place switch.
 */
export async function openProfileWindow(profileId) {
  if (!isTauri() || !profileId) return false
  try {
    const { invoke } = await import('@tauri-apps/api/core')
    await invoke('open_profile_window', { profileId })
    return true
  } catch (error) {
    console.warn('[Profile] Failed to open profile window:', error)
    return false
  }
}
const profiles = ref([])
const isLoadingProfiles = ref(false)

// Computed db_guid for current profile (used in URLs and localStorage keys)
const currentDbGuid = computed(() => {
  const profile = profiles.value.find(p => p.id === currentProfileId.value)
  return profile?.db_guid || null
})

/**
 * Get the current profile ID.
 */
export function getCurrentProfileId() {
  return currentProfileId.value
}

/**
 * Get the current database GUID.
 * Used for constructing globally unique URLs and localStorage keys.
 */
export function getCurrentDbGuid() {
  return currentDbGuid.value
}

/**
 * Set the current profile ID.
 * Updates localStorage and triggers data refresh.
 */
export function setCurrentProfileId(profileId) {
  const oldProfileId = currentProfileId.value
  if (oldProfileId === profileId) return // No change

  // Dispatch 'profile-will-change' BEFORE changing the profile ID
  // This allows composables to flush pending saves to the OLD profile's storage
  window.dispatchEvent(new CustomEvent('profile-will-change', {
    detail: { oldProfileId, newProfileId: profileId }
  }))

  // Now update the profile ID
  currentProfileId.value = profileId
  localStorage.setItem('profileId', profileId)
  void reportWindowProfile(profileId)

  // Dispatch 'profile-changed' AFTER changing the profile ID
  // This triggers composables to reload from the NEW profile's storage
  window.dispatchEvent(new CustomEvent('profile-changed', { detail: { profileId } }))
}

/**
 * Fetch wrapper that automatically includes the X-Profile-ID header.
 * Use this instead of raw fetch() for all API calls.
 */
export async function apiFetch(url, options = {}) {
  const headers = { ...options.headers }
  if (currentProfileId.value) {
    headers['X-Profile-ID'] = currentProfileId.value
  }
  return fetch(url, { ...options, headers })
}

/**
 * This window's profile no longer exists — close the window (browser-style).
 * Returns false when it is the last window (or outside the desktop app); the
 * caller then falls back to another profile in place.
 */
async function closeWindowForDeletedProfile() {
  if (!isTauri()) return false
  try {
    const { invoke } = await import('@tauri-apps/api/core')
    return await invoke('close_deleted_profile_window')
  } catch (error) {
    console.warn('[Profile] Failed to close window for deleted profile:', error)
    return false
  }
}

/**
 * Load available profiles from the API.
 */
export async function loadProfiles() {
  isLoadingProfiles.value = true
  try {
    const response = await apiFetch(`${getApiBase()}/profiles`)
    if (response.ok) {
      const data = await response.json()
      profiles.value = data.profiles || []

      // If current profile ID is null or doesn't match any loaded profile,
      // set it to the first profile's ID
      const currentId = currentProfileId.value
      const exists = profiles.value.some(p => p.id === currentId)
      // A pinned profile that vanished means it was deleted: this window
      // closes rather than silently becoming another profile's window. The
      // last window can't close, so it falls through to the fallback below.
      if (currentId && !exists && profiles.value.length > 0) {
        if (await closeWindowForDeletedProfile()) return
      }
      if ((!currentId || !exists) && profiles.value.length > 0) {
        currentProfileId.value = profiles.value[0].id
        localStorage.setItem('profileId', profiles.value[0].id)
        void reportWindowProfile(profiles.value[0].id)
      }
    }
  } catch (error) {
    console.error('Failed to load profiles:', error)
  } finally {
    isLoadingProfiles.value = false
  }
}

/**
 * Ensure a valid current profile is selected before profile-scoped UI mounts.
 */
export async function initializeCurrentProfile() {
  await loadProfiles()
  return currentProfileId.value
}

// Listen for profiles-changed browser event (dispatched by useWebSocket)
window.addEventListener('profiles-changed', async () => {
  console.log('[Profile] Received profiles-changed, reloading profiles')
  await loadProfiles()

  // Check if current profile still exists after reload
  const currentId = currentProfileId.value
  const exists = profiles.value.some(p => p.id === currentId)
  if (!exists && profiles.value.length > 0) {
    console.log('[Profile] Current profile removed, switching to', profiles.value[0].id)
    setCurrentProfileId(profiles.value[0].id)
  }
})

/**
 * Composable hook for profile management.
 */
export function useProfile() {
  return {
    // State (readonly to prevent accidental mutation)
    currentProfileId: readonly(currentProfileId),
    currentDbGuid: readonly(currentDbGuid),
    profiles: readonly(profiles),
    isLoadingProfiles: readonly(isLoadingProfiles),

    // Actions
    setCurrentProfileId,
    loadProfiles,
    initializeCurrentProfile,

    // API helper
    apiFetch,

    // Computed helpers
    getCurrentProfile: () => profiles.value.find(p => p.id === currentProfileId.value),
    getCurrentDbGuid,
  }
}

// Install a global fetch interceptor.
// This automatically adds profile/PIN headers and rewrites URLs for Tauri mode.
const originalFetch = window.fetch
window.fetch = async function(url, options = {}) {
  // Only intercept API calls - check both relative and absolute URLs
  if (typeof url === 'string' && (url.startsWith('/api') || url.includes('/api/'))) {
    // Rewrite URL for Tauri mode (adds backend origin to relative URLs)
    const rewrittenUrl = rewriteUrl(url)
    const headers = { ...options.headers }
    if (currentProfileId.value) {
      headers['X-Profile-ID'] = currentProfileId.value
    }
    // Add PIN header if we have a cached PIN for this profile
    const cachedPin = getCachedPin(currentProfileId.value)
    if (cachedPin) {
      headers['X-Profile-PIN'] = cachedPin
    }
    return originalFetch(rewrittenUrl, { ...options, headers })
  }
  return originalFetch(url, options)
}

// Install axios interceptor for profile/PIN headers.
axios.interceptors.request.use(async (config) => {
  // Add profile header to all API requests
  // In Tauri mode, URLs are absolute like http://127.0.0.1:PORT/api/...
  config.headers = config.headers || {}
  if (currentProfileId.value) {
    config.headers['X-Profile-ID'] = currentProfileId.value
  } else {
    delete config.headers['X-Profile-ID']
  }
  // Add PIN header if we have a cached PIN for this profile
  const cachedPin = getCachedPin(currentProfileId.value)
  if (cachedPin) {
    config.headers['X-Profile-PIN'] = cachedPin
  }
  return config
})
