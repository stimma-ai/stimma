/**
 * Feature flag composable backed by the sidecar's first-party flag bag.
 *
 * The backend fetches GET {cloud}/api/feature-flags (on launch, every 6 h,
 * and on sign-in change) and reflects the bag to the frontend via
 * GET /api/feature-flags plus the `flags_updated` WebSocket event.
 *
 * On startup we hydrate from localStorage so flag reads return correct
 * values before the first sidecar round-trip — no after-launch UI flicker.
 * `featureFlagDefaults.js` provides local fallbacks for flags the server
 * hasn't defined.
 */
import { computed, reactive } from 'vue'
import { getApiBase } from '../apiConfig'
import { FLAG_DEFAULTS } from '../featureFlagDefaults'

const STORAGE_KEY = 'stimma:flags'

const state = reactive({ flags: loadCachedFlags() })
const subscribers = new Set()
let initialized = false

function loadCachedFlags() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return {}
    const parsed = JSON.parse(raw)
    return parsed && typeof parsed === 'object' ? parsed : {}
  } catch {
    return {}
  }
}

function saveCachedFlags(flags) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(flags))
  } catch {
    // localStorage full / disabled — ignore
  }
}

function applyFlags(next) {
  if (!next || typeof next !== 'object') return
  const changed = JSON.stringify(next) !== JSON.stringify(state.flags)
  if (!changed) return
  state.flags = next
  saveCachedFlags(next)
  const snapshot = { ...next }
  subscribers.forEach((cb) => {
    try {
      cb(snapshot)
    } catch (err) {
      console.warn('[featureFlags] subscriber failed', err)
    }
  })
}

/**
 * Wire up the sidecar flag bag: one initial fetch + live updates over the
 * existing WebSocket. Call once at app startup (App.vue).
 */
export function initFeatureFlags(wsOn) {
  if (initialized) return
  initialized = true

  fetch(`${getApiBase()}/feature-flags`)
    .then((r) => (r.ok ? r.json() : null))
    .then((body) => {
      if (body && typeof body.flags === 'object') applyFlags(body.flags)
    })
    .catch(() => {})

  if (typeof wsOn === 'function') {
    wsOn('flags_updated', (data) => {
      if (data && typeof data.flags === 'object') applyFlags(data.flags)
    })
  }
}

export function useFeatureFlags() {
  function getBool(name, defaultValue = false) {
    return computed(() => {
      if (name in state.flags) {
        return state.flags[name] !== false && Boolean(state.flags[name])
      }
      if (name in FLAG_DEFAULTS) {
        return Boolean(FLAG_DEFAULTS[name])
      }
      return Boolean(defaultValue)
    })
  }

  function get(name, defaultValue = null) {
    return computed(() => {
      if (name in state.flags) return state.flags[name]
      if (name in FLAG_DEFAULTS) return FLAG_DEFAULTS[name]
      return defaultValue
    })
  }

  function has(name) {
    return computed(() => name in state.flags || name in FLAG_DEFAULTS)
  }

  function onChange(callback) {
    subscribers.add(callback)
    return () => subscribers.delete(callback)
  }

  // Back-compat alias
  const isEnabled = getBool

  return { getBool, get, has, isEnabled, onChange }
}
