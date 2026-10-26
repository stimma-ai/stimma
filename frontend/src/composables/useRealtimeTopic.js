/**
 * Component-facing side of the realtime scope (see realtimeScope.js).
 */
import { effectScope, watch, onActivated, onDeactivated, onBeforeUnmount, getCurrentInstance } from 'vue'
import { realtimeScope } from './realtimeScope.js'
import { useProfile } from './useProfile'
import { mobilePlatform } from '../desktop/mobileNative.ts'

// A phone on a cellular link gets at most this many preview images per second
// per job, and none larger than this. The numeric progress still arrives with
// every tick, so the job never looks stalled.
const MOBILE_PREVIEW_MAX_FPS = 2
const MOBILE_PREVIEW_MAX_BYTES = 256 * 1024

let installed = false

/**
 * Keep the server-side scope in step with this window: its profile (which can
 * change in place or be resolved after the socket opened), whether the page is
 * visible, and the platform's preview budget. Idempotent.
 */
export function installRealtimeScope() {
  if (installed) return
  installed = true
  const { currentProfileId } = useProfile()
  // Detached: the first caller is some component, and its unmounting must
  // not stop the server from following this window's profile.
  effectScope(true).run(() => {
    watch(currentProfileId, id => realtimeScope.setProfile(id), { immediate: true, flush: 'sync' })
  })
  if (mobilePlatform()) {
    realtimeScope.setPreviewPolicy({ maxFps: MOBILE_PREVIEW_MAX_FPS, maxBytes: MOBILE_PREVIEW_MAX_BYTES })
  }
  if (typeof document !== 'undefined') {
    const sync = () => realtimeScope.setPreviewsVisible(document.visibilityState !== 'hidden')
    document.addEventListener('visibilitychange', sync)
    sync()
  }
}

/** Follow a topic until the returned function is called (no component needed). */
export function acquireRealtimeTopic(topic) {
  return realtimeScope.acquire(topic)
}

/** Resolves once the server delivers `topic` (bounded wait). */
export function realtimeTopicReady(topic) {
  return realtimeScope.ready(topic)
}

/**
 * Follow the topic returned by `getter` while the calling component is
 * mounted and (under KeepAlive) active. A null/empty topic follows nothing.
 * Changes apply synchronously, so a view can switch entities and then await
 * `ready()` before reading the new entity's state.
 */
export function useRealtimeTopic(getter) {
  let active = true
  let current = null
  let release = null

  function sync() {
    const next = active ? (getter() || null) : null
    if (next === current) return
    const previous = release
    current = next
    release = next ? realtimeScope.acquire(next) : null
    previous?.()
  }

  watch(getter, sync, { flush: 'sync' })
  sync()
  if (getCurrentInstance()) {
    onActivated(() => { active = true; sync() })
    onDeactivated(() => { active = false; sync() })
    onBeforeUnmount(() => { active = false; sync() })
  }

  return {
    ready() {
      sync()
      return realtimeScope.ready(current)
    },
  }
}
