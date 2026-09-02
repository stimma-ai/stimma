/**
 * Authentication composable for Stimma Cloud desktop auth.
 *
 * The backend is the source of truth for auth state, token storage, token
 * refresh, and cloud tool connection.
 *
 * Which backend matters. Sign-in and sign-out are about THIS install (the
 * multi-device "local island"), so every call here goes through the desktop
 * bridge to this machine's own backend — never through the API base, which
 * points at whichever server the window is driving. Through the API base a
 * satellite's "Sign out" would sign out the remote server's account while
 * this install stayed signed in, and its sign-in would bind the browser
 * callback on the wrong computer. Outside Electron the bridge resolves to
 * the one backend there is, which is what the API base pointed at anyway.
 */
import { ref, readonly } from 'vue'
import { isTauri } from '../apiConfig'
import { desktop } from '../desktop'
import { isPrivacyLockdownActive, setPrivacyLockdownActive } from './usePrivacyLockdown'
import { useReadiness } from './useReadiness'

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
    // Check this install's auth status (its backend is the source of truth)
    const response = await desktop.authLocal('GET', '/auth/status')
    if (response.ok) {
      const data = response.data || {}
      console.log('[useAuth] backend auth status:', data)
      setPrivacyLockdownActive(data.privacy_lockdown === true)

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
export async function signInWithBrowser(mode) {
  authError.value = null

  if (isPrivacyLockdownActive()) {
    const message = 'Stimma sign-in is unavailable in Privacy Lockdown.'
    authError.value = message
    throw new Error(message)
  }

  try {
    // 1. Start auth flow - THIS install's backend creates the callback
    //    server, so the browser redirect lands on the machine it opened from.
    const startResponse = await desktop.authLocal('POST', '/auth/start')

    if (!startResponse.ok) {
      throw new Error('Failed to start authentication')
    }

    const { session_id, login_url } = startResponse.data

    // Carry the chosen action (Sign in vs Create account) to the web login page
    // so it opens on the matching tab instead of a fixed default.
    let openUrl = login_url
    if (mode === 'sign-in' || mode === 'create') {
      openUrl += (openUrl.includes('?') ? '&' : '?') + 'mode=' + mode
    }

    // 2. Open system browser to login page
    if (isTauri()) {
      // The hardened native path bypasses the AppImage-bundled xdg-open on
      // Linux; its desktop-file parser can turn a Snap browser's --class
      // argument into an unwanted second URL.
      const { desktop } = await import('../desktop')
      await desktop.openAuthUrl(openUrl)
    } else {
      // Web fallback - open in new tab
      window.open(openUrl, '_blank')
    }

    // 3. Poll for result
    const result = await pollForAuthResult(session_id)

    if (result.error) {
      throw new Error(result.error)
    }

    if (result.user) {
      setUser(result.user)
    }

    // Refresh account + readiness after every completed login. The panel
    // shows itself (via shouldShowPanel) if the account still isn't ready.
    await useReadiness().handleLoginChoice()

    return result

  } catch (error) {
    console.error('Google sign-in error:', error)
    authError.value = error.message || 'Sign-in failed'
    throw error
  }
}

/**
 * Poll the backend for auth result.
 *
 * The 30-minute ceiling matches the backend callback-server lifetime
 * (routes/auth.py). An unsubscribed account can spend minutes on the
 * plan-chooser interstitial before the login completes, so this must not
 * expire mid-deliberation.
 */
async function pollForAuthResult(sessionId, timeoutMs = 1800000) {
  const start = Date.now()
  const pollInterval = 1000

  while (Date.now() - start < timeoutMs) {
    const response = await desktop.authLocal('GET', `/auth/poll/${sessionId}`)
    const data = response.data || {}

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
 *
 * Signs THIS install out: its backend clears stored auth, disconnects cloud,
 * stops serving and revokes the sessions it issued. In Electron, main then
 * drops its cached remote sessions and, if the window was driving another
 * server, takes the proxy away — the connection screen's "Use local server"
 * is the explicit way back.
 */
export async function signOut() {
  try {
    await desktop.authLocal('POST', '/auth/logout')
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
