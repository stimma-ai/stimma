/**
 * Push-to-talk voice input backed by on-device ASR models (Tauri/Rust).
 *
 * The Rust side captures the mic and streams interim transcripts over a Tauri
 * Channel; this composable folds those partials into the target text field live
 * so the user watches their words appear as they speak. On stop, the Rust side
 * runs a final clean pass and returns the committed transcript.
 *
 * Parakeet TDT 0.6B v3 is downloaded on first use.
 */

import { ref, computed, onMounted, onUnmounted } from 'vue'
import { isTauri as checkIsTauri, initApiConfig } from '../apiConfig'
import { desktop } from '../desktop'
import { useTelemetry } from './useTelemetry'
import { isPrivacyLockdownActive } from './usePrivacyLockdown'
import { addToast } from './useToasts'

export const VOICE_DOWNLOAD_LOCKDOWN_MESSAGE =
  'Voice model downloads are disabled while Privacy Lockdown is enabled. Disable Privacy Lockdown to download this model.'

export type VoiceState = 'idle' | 'downloading' | 'recording' | 'finalizing' | 'error'

// Remove the preference left by builds that offered multiple voice models.
localStorage.removeItem('stimma.voiceModel')

// ---- Tauri bridge (lazy, shared) ------------------------------------------

export const supported = ref(false)
let initPromise: Promise<void> | null = null

async function initTauri(): Promise<void> {
  if (initPromise) return initPromise
  initPromise = (async () => {
    try {
      await initApiConfig()
      supported.value = checkIsTauri()
    } catch (e) {
      console.warn('[useVoiceInput] Desktop init failed:', e)
      supported.value = false
    }
  })()
  return initPromise
}

initTauri()

/** Whether Parakeet v3 is already downloaded. */
async function isModelReady(): Promise<boolean> {
  await initTauri()
  if (!supported.value) return false
  return await desktop.voiceModelStatus()
}

// ---- Composable -----------------------------------------------------------

export interface VoiceInputOptions {
  /** Current text in the target field. */
  getText: () => string
  /** Replace the target field text. */
  setText: (text: string) => void
  /** Optional: refocus the field after transcription commits. */
  focus?: () => void
  /**
   * Telemetry surface (closed enum: main_chat | flow_chat | prompt_agent |
   * feedback | global_search). No transcript is ever tracked — only surface, duration, and
   * the committed/cancelled outcome.
   */
  surface?: string
}

export function useVoiceInput(opts: VoiceInputOptions) {
  const { track } = useTelemetry()
  let recordingStartedAt = 0

  function trackUse(outcome: 'committed' | 'cancelled') {
    if (!recordingStartedAt) return
    const durationMs = Date.now() - recordingStartedAt
    recordingStartedAt = 0
    track('voice_input_used', {
      surface: opts.surface || 'main_chat',
      durationMs,
      outcome,
    }, 'feature')
  }

  const state = ref<VoiceState>('idle')
  const error = ref<string | null>(null)
  const downloaded = ref(0)
  const downloadTotal = ref<number | null>(null)

  // Text present before recording started; interim transcript is layered on top.
  let baseText = ''
  let interim = ''

  const isRecording = computed(() => state.value === 'recording')
  const isBusy = computed(() => state.value === 'downloading' || state.value === 'finalizing')
  const downloadFraction = computed(() => {
    if (!downloadTotal.value) return null
    return Math.min(1, downloaded.value / downloadTotal.value)
  })

  function applyText() {
    const needsSpace = baseText.length > 0 && !/\s$/.test(baseText) && interim.length > 0
    opts.setText(baseText + (needsSpace ? ' ' : '') + interim)
  }

  async function downloadModel() {
    if (isPrivacyLockdownActive()) {
      error.value = VOICE_DOWNLOAD_LOCKDOWN_MESSAGE
      state.value = 'error'
      addToast(VOICE_DOWNLOAD_LOCKDOWN_MESSAGE, 'info', 6500)
      return
    }

    state.value = 'downloading'
    error.value = null
    downloaded.value = 0
    downloadTotal.value = null

    const onEvent = (ev: any) => {
      if (ev.type === 'progress') {
        downloaded.value = ev.downloaded
        downloadTotal.value = ev.total ?? null
      } else if (ev.type === 'done') {
        state.value = 'idle'
      } else if (ev.type === 'error') {
        error.value = ev.message
        state.value = 'error'
      }
    }

    try {
      await desktop.voiceDownloadModel(onEvent)
      if (state.value === 'downloading') state.value = 'idle'
      track('voice_model_downloaded', { model: 'parakeet-tdt-0.6b-v3' }, 'feature')
    } catch (e) {
      error.value = String(e)
      state.value = 'error'
    }
  }

  // ---- Liveness lease ------------------------------------------------------
  // While recording, ping the Rust side on a timer so it knows this webview is
  // still alive and showing the indicator. If we go away (HMR swap, page
  // refresh, crash, lost focus) the pings stop and the capture loop abandons
  // itself within a few seconds — see LEASE_TIMEOUT in voice.rs. This is the
  // real backstop; the explicit teardown hooks below just make it instant.
  const KEEPALIVE_INTERVAL_MS = 1000
  let keepaliveTimer: ReturnType<typeof setInterval> | null = null

  function startKeepalive() {
    stopKeepalive()
    keepaliveTimer = setInterval(() => {
      void desktop.voiceKeepalive().catch(() => { /* session gone; ignore */ })
    }, KEEPALIVE_INTERVAL_MS)
  }

  function stopKeepalive() {
    if (keepaliveTimer != null) {
      clearInterval(keepaliveTimer)
      keepaliveTimer = null
    }
  }

  /**
   * Begin push-to-talk. If the model isn't downloaded yet, this kicks off the
   * download instead of recording — the caller presses again once it's ready.
   * Returns true if recording actually started.
   */
  async function start(): Promise<boolean> {
    if (state.value === 'recording' || state.value === 'finalizing' || state.value === 'downloading') {
      return false
    }
    error.value = null
    await initTauri()
    if (!supported.value) {
      error.value = 'Voice input requires the desktop app'
      state.value = 'error'
      return false
    }

    if (!(await isModelReady())) {
      await downloadModel()
      return false
    }

    // Treat an all-whitespace field (including the lone space typed just before
    // a hold) as empty so dictation doesn't start with a leading space.
    baseText = opts.getText() ?? ''
    if (baseText.trim().length === 0) baseText = ''
    interim = ''

    const onEvent = (ev: any) => {
      if (ev.type === 'partial') {
        interim = ev.text
        applyText()
      } else if (ev.type === 'error') {
        error.value = ev.message
        state.value = 'error'
      }
    }

    state.value = 'recording'
    recordingStartedAt = Date.now()
    try {
      await desktop.voiceStart(onEvent)
      startKeepalive()
      return true
    } catch (e) {
      error.value = String(e)
      state.value = 'error'
      return false
    }
  }

  /** End push-to-talk and commit the final transcript. */
  async function stop(): Promise<void> {
    if (state.value !== 'recording') return
    stopKeepalive()
    trackUse('committed')
    state.value = 'finalizing'
    try {
      const finalText: string = await desktop.voiceStop()
      interim = finalText ?? ''
      applyText()
    } catch (e) {
      error.value = String(e)
    } finally {
      // Fold the committed transcript into the base so further dictation appends.
      baseText = opts.getText() ?? baseText
      interim = ''
      if (state.value !== 'error') state.value = 'idle'
      opts.focus?.()
    }
  }

  // ---- Spacebar push-to-talk ----------------------------------------------
  // A quick Space tap types a space as usual (anywhere, including mid-text). A
  // deliberate hold (> SPACE_HOLD_MS) starts dictation and appends to whatever
  // is already in the field; releasing stops and commits. We let the first
  // space type natively (so normal typing is untouched) and just suppress OS
  // key-repeat during the hold — the lone space becomes the word separator,
  // and an all-whitespace field is normalized away in start().
  const SPACE_HOLD_MS = 250
  let spacePending = false
  let spaceDictating = false
  let spaceTimer: ReturnType<typeof setTimeout> | null = null

  function clearSpaceTimer() {
    if (spaceTimer != null) {
      clearTimeout(spaceTimer)
      spaceTimer = null
    }
  }

  function handleInputKeydown(e: KeyboardEvent) {
    if (e.code !== 'Space' && e.key !== ' ') return
    if (!supported.value) return
    if (e.repeat) {
      // Suppress auto-repeat spaces while deciding tap-vs-hold or dictating.
      if (spacePending || spaceDictating) e.preventDefault()
      return
    }
    if (state.value !== 'idle') return
    spacePending = true
    spaceDictating = false
    clearSpaceTimer()
    spaceTimer = setTimeout(() => {
      spaceTimer = null
      if (spacePending && state.value === 'idle') {
        spaceDictating = true
        void start()
      }
    }, SPACE_HOLD_MS)
  }

  function handleInputKeyup(e: KeyboardEvent) {
    if (e.code !== 'Space' && e.key !== ' ') return
    if (!spacePending && !spaceDictating) return
    clearSpaceTimer()
    const wasDictating = spaceDictating
    spacePending = false
    spaceDictating = false
    if (wasDictating) void stop()
  }

  /** Abort without committing (best effort). */
  async function cancel(): Promise<void> {
    stopKeepalive()
    clearSpaceTimer()
    spacePending = false
    spaceDictating = false
    if (state.value === 'recording') {
      trackUse('cancelled')
      try { await desktop.voiceCancel() } catch { /* ignore */ }
    }
    interim = ''
    if (state.value !== 'error') state.value = 'idle'
  }

  // ---- Teardown safety nets ------------------------------------------------
  // A held-Space dictation only stops on keyup. If we never see that keyup —
  // the window loses focus, the tab/app is hidden, or the page is unloading —
  // abandon the session here so the Rust loop doesn't keep capturing. (If even
  // these don't fire, the Rust lease still catches it; this just makes it
  // immediate.)
  function onWindowBlur() {
    if (state.value === 'recording') void cancel()
  }
  function onVisibilityChange() {
    if (document.hidden && state.value === 'recording') void cancel()
  }
  function onPageHide() {
    if (state.value === 'recording') void cancel()
  }

  onMounted(() => {
    window.addEventListener('blur', onWindowBlur)
    document.addEventListener('visibilitychange', onVisibilityChange)
    window.addEventListener('pagehide', onPageHide)
  })
  onUnmounted(() => {
    window.removeEventListener('blur', onWindowBlur)
    document.removeEventListener('visibilitychange', onVisibilityChange)
    window.removeEventListener('pagehide', onPageHide)
    // The component owning this dictation is gone (route change, HMR); don't
    // leave the mic capturing.
    void cancel()
  })

  return {
    supported,
    state,
    error,
    isRecording,
    isBusy,
    downloaded,
    downloadTotal,
    downloadFraction,
    start,
    stop,
    cancel,
    handleInputKeydown,
    handleInputKeyup,
  }
}
