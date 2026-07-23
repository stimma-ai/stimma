import { watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { makeProfileKey, makeProfileKeyFor } from '../utils/storageKeys'

const STORAGE_KEY = 'last_route'

/**
 * Read the saved route for a specific profile (defaults to '/').
 * Used to land on a profile's last location when switching to it, instead of
 * reloading in place on the previous profile's URL (which references objects
 * that don't exist in the target profile).
 */
export function getSavedRouteForProfile(profileId) {
  const saved = localStorage.getItem(makeProfileKeyFor(profileId, STORAGE_KEY))
  return saved && saved !== '/' ? saved : '/'
}

export function useRouteRestore() {
  const router = useRouter()
  const route = useRoute()

  function saveCurrentRoute() {
    const key = makeProfileKey(STORAGE_KEY)
    localStorage.setItem(key, route.fullPath)
  }

  function restoreRoute() {
    const key = makeProfileKey(STORAGE_KEY)
    const savedPath = localStorage.getItem(key)
    // Only restore from the app root. Deep links and typed URLs must win over
    // whatever route happened to be saved last.
    if (route.fullPath !== '/') return
    // Don't restore over a route that opted out (e.g. dev previews accessed
    // via direct URL). Otherwise the saved path clobbers the user's typed URL.
    if (route.meta?.skipRouteRestore) return
    if (savedPath && savedPath !== '/' && savedPath !== route.fullPath) {
      router.replace(savedPath)
    }
  }

  function setupPersistence() {
    watch(() => route.fullPath, () => {
      if (!route.name) return  // Skip during redirects
      if (route.meta?.skipRouteRestore) return  // Opt-out routes don't persist
      saveCurrentRoute()
    })
  }

  return { restoreRoute, setupPersistence }
}
