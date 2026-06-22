/**
 * Authentication composable for Stimma Cloud desktop auth.
 *
 * The backend is the source of truth for auth state, token storage, token
 * refresh, and cloud tool connection.
 */
import { ref, readonly } from 'vue'
import { isTauri, getApiBase } from '../apiConfig'

// Global reactive state (shared across all components)
const user = ref(null)
const isAuthenticated = ref(false)
const isAuthLoading = ref(true)
const authError = ref(null)

let initialized = false

/**
 * Helper to set user state.
 */
function setUser(newUser) {
  user.value = newUser
  isAuthenticated.value = !!newUser
}

if (typeof window !== 'undefined') {
  window.addEventListener('stimma-auth-required', (event) => {
    const detail = event.detail || {}
    authError.value = detail.message || 'Please sign in again.'
    setUser(null)
  })
}

/**
 * Initialize auth state from backend.
 * Call this once at app startup.
 */
export async function initAuth() {
  if (initialized) return
  initialized = true

  try {
    // Check backend auth status (backend is source of truth)
    const response = await fetch(`${getApiBase()}/auth/status`)
    if (response.ok) {
      const data = await response.json()
      console.log('[useAuth] backend auth status:', data)

      if (data.authenticated && data.user) {
        setUser(data.user)
        authError.value = null
      } else {
        setUser(null)
      }
    } else {
      console.error('[useAuth] Failed to get auth status:', response.status)
      setUser(null)
    }
  } catch (error) {
    console.error('[useAuth] Error checking auth status:', error)
    setUser(null)
  } finally {
    isAuthLoading.value = false
  }
}

/**
 * Sign in via system browser.
 * Opens browser to stimma.cloud login page, polls for result.
 */
export async function signInWithBrowser() {
  authError.value = null

  try {
    // 1. Start auth flow - backend creates callback server
    const startResponse = await fetch(`${getApiBase()}/auth/start`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
    })

    if (!startResponse.ok) {
      throw new Error('Failed to start authentication')
    }

    const { session_id, login_url } = await startResponse.json()

    // 2. Open system browser to login page
    if (isTauri()) {
      const { open } = await import('@tauri-apps/plugin-shell')
      await open(login_url)
    } else {
      // Web fallback - open in new tab
      window.open(login_url, '_blank')
    }

    // 3. Poll for result
    const result = await pollForAuthResult(session_id)

    if (result.error) {
      throw new Error(result.error)
    }

    if (result.user) {
      setUser(result.user)
    }

  } catch (error) {
    console.error('Google sign-in error:', error)
    authError.value = error.message || 'Sign-in failed'
    throw error
  }
}

/**
 * Poll the backend for auth result.
 */
async function pollForAuthResult(sessionId, timeoutMs = 300000) {
  const start = Date.now()
  const pollInterval = 1000

  while (Date.now() - start < timeoutMs) {
    const response = await fetch(`${getApiBase()}/auth/poll/${sessionId}`)
    const data = await response.json()

    if (data.completed) {
      return data
    }

    // Wait before polling again
    await new Promise(r => setTimeout(r, pollInterval))
  }

  throw new Error('Authentication timed out - please try again')
}

/**
 * Sign out the current user.
 * Calls backend logout endpoint to clear stored auth and disconnect cloud.
 */
export async function signOut() {
  try {
    // Call backend logout to clear stored auth and disconnect cloud
    await fetch(`${getApiBase()}/auth/logout`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
    })
  } catch (error) {
    console.error('Error calling backend logout:', error)
  }

  // Update local state
  authError.value = null
  setUser(null)
}

/**
 * Composable hook for authentication state and methods.
 */
export function useAuth() {
  return {
    // State (readonly to prevent accidental mutation)
    user: readonly(user),
    isAuthenticated: readonly(isAuthenticated),
    isAuthLoading: readonly(isAuthLoading),
    authError,

    // Actions
    initAuth,
    signInWithBrowser,
    signOut,
  }
}
