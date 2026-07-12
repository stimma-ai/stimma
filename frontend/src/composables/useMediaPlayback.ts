/**
 * Global media playback state, shared by every player in the app.
 *
 * Two independent channels — video and audio — each with a persisted mute
 * flag and volume level (profile-scoped). Mute is stored separately from
 * volume so unmuting restores the previous level, and so muting in one place
 * (e.g. the slideshow) sticks across close/reopen and across surfaces.
 * Surfaces whose listening context differs from the slideshow's can carve out
 * their own persisted channel via useScopedVideoPlayback(scope).
 *
 * This module also owns the playback registry that prevents ghost playback.
 * Per the HTML spec, a media element removed from the document keeps playing
 * its audio, and KeepAlive-cached views hold their detached DOM (and any
 * playing element in it) alive indefinitely. Audible players wire their
 * element in via useManagedMediaElement(), which:
 *   - pauses it when a KeepAlive ancestor deactivates the view,
 *   - tears it down when the component unmounts or a keyed re-render swaps
 *     the element out while it may still be playing,
 *   - enforces "one audible player at a time": when an audible element starts
 *     playing, other audible registered elements pause. Muted/ambient playback
 *     (e.g. a muted looping video) neither claims exclusivity nor gets paused.
 */
import { ref, watch, onBeforeUnmount, onDeactivated, type Ref } from 'vue'
import { makeProfileKey } from '../utils/storageKeys'

const videoMuted = ref(true)
const videoVolume = ref(0.5)
const audioMuted = ref(false)
const audioVolume = ref(1)

let hydrated = false

function clamp01(v: number): number {
  return Math.max(0, Math.min(1, v))
}

// Computed per call, not at module scope: profile isn't loaded yet at import
// time (same reason SlideshowMode computes its settings key per call).
function settingsKey(): string {
  return makeProfileKey('media_playback', 'settings')
}

function persist() {
  try {
    localStorage.setItem(
      settingsKey(),
      JSON.stringify({
        videoMuted: videoMuted.value,
        videoVolume: videoVolume.value,
        audioMuted: audioMuted.value,
        audioVolume: audioVolume.value,
      })
    )
  } catch (e) {
    console.error('Failed to save media playback settings:', e)
  }
}

function hydrate() {
  if (hydrated) return
  hydrated = true
  try {
    const raw = localStorage.getItem(settingsKey())
    if (raw) {
      const s = JSON.parse(raw)
      if (typeof s.videoMuted === 'boolean') videoMuted.value = s.videoMuted
      if (typeof s.videoVolume === 'number') videoVolume.value = clamp01(s.videoVolume)
      if (typeof s.audioMuted === 'boolean') audioMuted.value = s.audioMuted
      if (typeof s.audioVolume === 'number') audioVolume.value = clamp01(s.audioVolume)
    } else {
      // First run: seed from the legacy per-surface prefs (slideshow settings
      // blob for video, AudioPlayer's shared volume key for audio), where
      // mute was representable only as volume === 0.
      try {
        const slideshow = JSON.parse(localStorage.getItem(makeProfileKey('slideshow', 'settings')) || '{}')
        if (typeof slideshow.volume === 'number') {
          videoMuted.value = slideshow.volume === 0
          if (slideshow.volume > 0) videoVolume.value = clamp01(slideshow.volume)
        }
      } catch { /* ignore malformed legacy settings */ }
      const legacyAudio = parseFloat(localStorage.getItem(makeProfileKey('audio_player', 'volume')) ?? '')
      if (!isNaN(legacyAudio)) {
        audioMuted.value = legacyAudio === 0
        if (legacyAudio > 0) audioVolume.value = clamp01(legacyAudio)
      }
      localStorage.removeItem(makeProfileKey('audio_player', 'volume'))
      persist()
    }
  } catch (e) {
    console.error('Failed to load media playback settings:', e)
  }
  watch([videoMuted, videoVolume, audioMuted, audioVolume], persist)
}

function toggleVideoMute() {
  if (videoMuted.value) {
    videoMuted.value = false
    if (videoVolume.value === 0) videoVolume.value = 0.5
  } else {
    videoMuted.value = true
  }
}

function toggleAudioMute() {
  if (audioMuted.value) {
    audioMuted.value = false
    if (audioVolume.value === 0) audioVolume.value = 1
  } else {
    audioMuted.value = true
  }
}

// ---------------------------------------------------------------------------
// Scoped video channels
// ---------------------------------------------------------------------------

export interface VideoPlaybackChannel {
  muted: Ref<boolean>
  volume: Ref<number>
  toggleMute: () => void
}

const scopedVideoChannels = new Map<string, VideoPlaybackChannel>()

/**
 * A persisted mute/volume channel independent of the default video channel.
 * Surfaces with different listening contexts (e.g. ToolView's ambient stage
 * hero vs. the slideshow's deliberate viewing) keep separate settings; each
 * scope persists to its own profile-scoped key.
 */
export function useScopedVideoPlayback(scope: string): VideoPlaybackChannel {
  const existing = scopedVideoChannels.get(scope)
  if (existing) return existing

  const muted = ref(true)
  const volume = ref(0.5)
  // Computed per call, not captured: profile isn't loaded yet at import time.
  const key = () => makeProfileKey('media_playback', scope)
  try {
    const raw = localStorage.getItem(key())
    if (raw) {
      const s = JSON.parse(raw)
      if (typeof s.muted === 'boolean') muted.value = s.muted
      if (typeof s.volume === 'number') volume.value = clamp01(s.volume)
    }
  } catch (e) {
    console.error(`Failed to load ${scope} playback settings:`, e)
  }
  watch([muted, volume], () => {
    try {
      localStorage.setItem(key(), JSON.stringify({ muted: muted.value, volume: volume.value }))
    } catch (e) {
      console.error(`Failed to save ${scope} playback settings:`, e)
    }
  })

  const channel: VideoPlaybackChannel = {
    muted,
    volume,
    toggleMute() {
      if (muted.value) {
        muted.value = false
        if (volume.value === 0) volume.value = 0.5
      } else {
        muted.value = true
      }
    },
  }
  scopedVideoChannels.set(scope, channel)
  return channel
}

// ---------------------------------------------------------------------------
// Playback registry (ghost prevention + audible exclusivity)
// ---------------------------------------------------------------------------

const registeredElements = new Set<HTMLMediaElement>()

function isAudible(el: HTMLMediaElement): boolean {
  return !el.muted && el.volume > 0
}

/**
 * Stop an element for good. pause() alone isn't enough on WebKit: a detached
 * element still holding a src can keep its media pipeline alive, so clear the
 * source and force a load to release it.
 */
export function teardownMediaElement(el: HTMLMediaElement) {
  try {
    el.pause()
    el.removeAttribute('src')
    el.load()
  } catch { /* element may already be defunct */ }
}

function onRegisteredPlay(e: Event) {
  const el = e.target as HTMLMediaElement
  for (const other of [...registeredElements]) {
    if (other === el) continue
    // Anything registered but no longer in the document is a ghost — stop it
    // entirely rather than letting it play until GC.
    if (!other.isConnected) {
      registeredElements.delete(other)
      teardownMediaElement(other)
      continue
    }
    if (isAudible(el) && !other.paused && isAudible(other)) other.pause()
  }
}

function registerMediaElement(el: HTMLMediaElement): () => void {
  registeredElements.add(el)
  el.addEventListener('play', onRegisteredPlay)
  return () => {
    el.removeEventListener('play', onRegisteredPlay)
    registeredElements.delete(el)
  }
}

/**
 * Wire a component's <video>/<audio> template ref into the playback registry
 * and make its playback die with the component. Call once during setup.
 */
export function useManagedMediaElement(elRef: Ref<HTMLMediaElement | null>) {
  let unregister: (() => void) | null = null
  watch(elRef, (el, oldEl) => {
    if (unregister) {
      unregister()
      unregister = null
    }
    // A keyed re-render discards the old element while it may still be
    // playing — kill it, don't wait for GC.
    if (oldEl && oldEl !== el) teardownMediaElement(oldEl)
    if (el) unregister = registerMediaElement(el)
  }, { immediate: true })
  onDeactivated(() => {
    elRef.value?.pause()
  })
  onBeforeUnmount(() => {
    if (unregister) {
      unregister()
      unregister = null
    }
    if (elRef.value) teardownMediaElement(elRef.value)
  })
}

export function useMediaPlayback() {
  hydrate()
  return {
    videoMuted,
    videoVolume,
    toggleVideoMute,
    audioMuted,
    audioVolume,
    toggleAudioMute,
  }
}
