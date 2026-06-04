/**
 * Feature flag composable backed by posthog-js.
 *
 * On startup we hydrate from localStorage so flag reads return correct
 * values before posthog-js finishes its first /decide round-trip — no
 * 300ms-after-launch UI flicker.
 *
 * After posthog init, ``initFeatureFlags()`` (called from
 * ``usePostHog.js``) wires ``posthog.onFeatureFlags`` to keep the
 * reactive store in sync. Components using ``isEnabled`` / ``get`` get
 * Vue refs that re-render automatically when flag values change.
 */
import { computed, reactive } from 'vue'
import posthog from 'posthog-js'
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

/**
 * Snapshot of the cached flag values, suitable for posthog-js
 * ``bootstrap.featureFlags`` to seed the SDK at init time.
 */
export function getCachedFlags() {
  return { ...state.flags }
}

/**
 * Wire posthog-js's flag updates into the reactive store. Call once
 * after ``posthog.init()``.
 */
export function initFeatureFlags() {
  if (initialized) return
  initialized = true
  try {
    posthog.onFeatureFlags(() => {
      const next = {}
      try {
        const allFlags = posthog.featureFlags?.getFlagVariants?.() || {}
        Object.assign(next, allFlags)
      } catch {
        // fall through to empty
      }
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
    })
  } catch (err) {
    console.warn('[featureFlags] onFeatureFlags wiring failed', err)
  }
}

export function useFeatureFlags() {
  function isEnabled(name, defaultValue = false) {
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

  function onChange(callback) {
    subscribers.add(callback)
    return () => subscribers.delete(callback)
  }

  return { isEnabled, get, onChange }
}
