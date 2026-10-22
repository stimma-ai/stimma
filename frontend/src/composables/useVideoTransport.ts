/**
 * Filmstrip transport for a looping video: play/pause, a frame-strip scrub
 * track with a live playhead, and a time ↔ frames readout. Shared by every
 * surface that shows a hero video (slideshow, chat artifact stage) so they
 * scrub and read out identically. Pair with <VideoTransportBar>.
 *
 * Playback may run through MseLoopPlayback, whose logical timeline differs
 * from the element's ever-advancing currentTime, so seeks and readouts go
 * through the controller whenever one is active.
 */
import { ref, computed, watch, onBeforeUnmount, onActivated, onDeactivated, type Ref } from 'vue'
import axios from 'axios'
import { getApiBase } from '../apiConfig'
import { getCurrentProfileId } from './useProfile'
import { getCachedPin } from './usePinLock'
import { makeProfileKey } from '../utils/storageKeys'
import { allowMobilePlayback } from './useMobilePlaybackLifecycle'
import type { MseLoopPlayback } from '../utils/mseLoopPlayback'

export interface VideoTransportSource {
  filePath: string
  // The media row's duration, shown until the element or controller reports one.
  duration?: number | null
}

export interface VideoTransportOptions {
  video: Ref<HTMLVideoElement | null>
  playback: () => MseLoopPlayback | null
  source: () => VideoTransportSource | null
  onControl?: (control: 'video_play' | 'video_pause' | 'video_scrub') => void
}

// Readout mode (time vs frames) is persisted in the same namespace as the prep
// frame picker so the click-to-toggle behavior matches everywhere.
const FRAME_MODE_KEY = 'slideshow'

export function useVideoTransport(opts: VideoTransportOptions) {
  const currentTime = ref(0)
  const duration = ref(0)
  const paused = ref(true)
  const fps = ref(0)
  const stripReady = ref(false)
  const stripFailed = ref(false)
  const scrubbing = ref(false)
  const displayMode = ref<'time' | 'frames'>('time')
  try {
    displayMode.value = localStorage.getItem(makeProfileKey('frame-mode', FRAME_MODE_KEY)) === 'frames' ? 'frames' : 'time'
  } catch { /* default to time */ }

  const filePath = computed(() => opts.source()?.filePath || '')

  // The track is the same server-rendered frame-strip montage the prep frame
  // picker uses; profile/pin ride along as query params because it loads via <img>.
  const stripUrl = computed(() => {
    if (!filePath.value) return ''
    const profileId = getCurrentProfileId()
    const pin = getCachedPin(profileId)
    let u = `${getApiBase()}/generate/frame-strip?source_path=${encodeURIComponent(filePath.value)}&count=12&w=96&profile=${encodeURIComponent(profileId)}`
    if (pin) u += `&pin=${encodeURIComponent(pin)}`
    return u
  })

  watch(stripUrl, () => {
    stripReady.value = false
    stripFailed.value = false
  })

  const percent = computed(() => {
    if (duration.value <= 0) return 0
    return Math.min(100, Math.max(0, (currentTime.value / duration.value) * 100))
  })

  const label = computed(() => {
    if (displayMode.value === 'frames' && fps.value > 0) {
      const total = Math.max(1, Math.round(duration.value * fps.value))
      const idx = Math.min(total, Math.round(currentTime.value * fps.value) + 1)
      return `f ${idx}/${total}`
    }
    return `${formatTime(currentTime.value)} / ${formatTime(duration.value)}`
  })

  function formatTime(seconds: number) {
    const s = Math.max(0, seconds || 0)
    const m = Math.floor(s / 60)
    const rem = s - m * 60
    return `${m}:${rem.toFixed(1).padStart(4, '0')}`
  }

  function toggleDisplayMode() {
    displayMode.value = displayMode.value === 'frames' ? 'time' : 'frames'
    try {
      localStorage.setItem(makeProfileKey('frame-mode', FRAME_MODE_KEY), displayMode.value)
    } catch { /* ignore */ }
  }

  function togglePlayback() {
    allowMobilePlayback()
    const v = opts.video.value
    if (!v) return
    if (v.paused) {
      v.play().catch(() => { /* interrupted by teardown */ })
      opts.onControl?.('video_play')
    } else {
      v.pause()
      opts.onControl?.('video_pause')
    }
  }

  function seek(target: number) {
    const v = opts.video.value
    if (!v) return
    const playback = opts.playback()
    if (playback) playback.seekLogical(target)
    else v.currentTime = target
    currentTime.value = target
  }

  // Step one frame back/forward. Pauses playback, like every video editor.
  function stepFrame(dir: number) {
    const v = opts.video.value
    if (!v || duration.value <= 0) return
    if (!v.paused) v.pause()
    const step = fps.value > 0 ? 1 / fps.value : 0.04
    // Land one frame short of the end — seeking exactly to duration can show black.
    const maxT = Math.max(0, duration.value - step)
    const now = opts.playback()?.logicalCurrentTime ?? v.currentTime
    seek(Math.min(maxT, Math.max(0, now + dir * step)))
  }

  function seekFromPointer(e: PointerEvent) {
    const r = (e.currentTarget as HTMLElement).getBoundingClientRect()
    const frac = r.width > 0 ? Math.min(1, Math.max(0, (e.clientX - r.left) / r.width)) : 0
    if (duration.value <= 0) return
    seek(frac * duration.value)
  }

  function onPointerDown(e: PointerEvent) {
    e.preventDefault()
    e.stopPropagation()
    document.body.style.userSelect = 'none'
    ;(e.currentTarget as HTMLElement).setPointerCapture?.(e.pointerId)
    scrubbing.value = true
    seekFromPointer(e)
  }

  function onPointerMove(e: PointerEvent) {
    if (!scrubbing.value) return
    e.preventDefault()
    seekFromPointer(e)
  }

  function onPointerUp(e: PointerEvent) {
    if (!scrubbing.value) return
    scrubbing.value = false
    document.body.style.userSelect = ''
    seekFromPointer(e)
    opts.onControl?.('video_scrub')
  }

  function onPointerCancel() {
    scrubbing.value = false
    document.body.style.userSelect = ''
  }

  // Keep playhead/timecode live off the element itself (a rAF poll survives
  // keyed <video> remounts without re-wiring event listeners each swap).
  let raf: number | null = null
  function tick() {
    const v = opts.video.value
    if (v) {
      const playback = opts.playback()
      if (!scrubbing.value) currentTime.value = playback?.logicalCurrentTime ?? v.currentTime ?? 0
      if ((playback?.duration ?? 0) > 0) duration.value = playback!.duration
      else if (Number.isFinite(v.duration) && v.duration > 0) duration.value = v.duration
      paused.value = v.paused
    }
    raf = requestAnimationFrame(tick)
  }
  function startPolling() {
    if (opts.video.value && raf == null) raf = requestAnimationFrame(tick)
  }
  function stopPolling() {
    if (raf != null) {
      cancelAnimationFrame(raf)
      raf = null
    }
  }

  watch(opts.video, (v) => {
    if (v) startPolling()
    else stopPolling()
  }, { immediate: true })
  onActivated(startPolling)
  onDeactivated(stopPolling)
  onBeforeUnmount(() => {
    stopPolling()
    // Undo a mid-scrub userSelect lock.
    if (scrubbing.value) document.body.style.userSelect = ''
  })

  // fps comes from a one-shot server probe (media rows only carry duration);
  // frames mode falls back to time until it arrives.
  watch(filePath, async (fp) => {
    fps.value = 0
    currentTime.value = 0
    duration.value = opts.source()?.duration || 0
    if (!fp) return
    try {
      const { data } = await axios.get('/api/generate/video-info', { params: { source_path: fp } })
      if (filePath.value !== fp) return // navigated away mid-probe
      if (data.fps > 0) fps.value = data.fps
      if (data.duration > 0 && !(duration.value > 0)) duration.value = data.duration
    } catch { /* readout degrades to element-reported time */ }
  }, { immediate: true })

  return {
    currentTime,
    duration,
    paused,
    fps,
    scrubbing,
    stripUrl,
    stripReady,
    stripFailed,
    displayMode,
    percent,
    label,
    togglePlayback,
    stepFrame,
    toggleDisplayMode,
    onPointerDown,
    onPointerMove,
    onPointerUp,
    onPointerCancel,
  }
}

export type VideoTransport = ReturnType<typeof useVideoTransport>
