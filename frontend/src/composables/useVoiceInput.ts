/**
 * Push-to-talk voice input backed by on-device ASR models (Tauri/Rust).
 *
 * The Rust side captures the mic and streams interim transcripts over a Tauri
 * Channel; this composable folds those partials into the target text field live
 * so the user watches their words appear as they speak. On stop, the Rust side
 * runs a final clean pass and returns the committed transcript.
 *
 * The model is downloaded on first use. `voiceModel` selects which model to use
 * and is persisted across sessions.
 */

import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { isTauri as checkIsTauri, initApiConfig } from '../apiConfig'
import { useTelemetry } from './useTelemetry'

export const VOICE_MODELS = [
  {
    id: 'base.en',
    label: 'Whisper Base',
    size: '142 MB',
    description: 'Fastest Whisper option.',
  },
  {
    id: 'small.en',
    label: 'Whisper Small',
    size: '466 MB',
    description: 'More accurate Whisper option.',
  },
  {
    id: 'parakeet-tdt-0.6b-v2',
    label: 'Parakeet TDT 0.6B v2',
    size: '661 MB',
    description: 'English only; optimized for faster local transcription.',
  },
] as const

export type VoiceModel = typeof VOICE_MODELS[number]['id']
export type VoiceState = 'idle' | 'downloading' | 'recording' | 'finalizing' | 'error'

// ---- Selected model (persisted, shared across all inputs) -----------------

const VOICE_MODEL_KEY = 'stimma.voiceModel'

function isVoiceModel(value: string | null): value is VoiceModel {
  return VOICE_MODELS.some((model) => model.id === value)
}

function loadModel(): VoiceModel {
  const v = localStorage.getItem(VOICE_MODEL_KEY)
  return isVoiceModel(v) ? v : 'base.en'
}

export const voiceModel = ref<VoiceModel>(loadModel())
watch(voiceModel, (v) => localStorage.setItem(VOICE_MODEL_KEY, v))

// ---- Tauri bridge (lazy, shared) ------------------------------------------

export const supported = ref(false)
let invokeFn: any = null
let ChannelCtor: any = null
let initPromise: Promise<void> | null = null

async function initTauri(): Promise<void> {
  if (initPromise) return initPromise
  initPromise = (async () => {
    try {
      await initApiConfig()
      if (!checkIsTauri()) {
        supported.value = false
        return
      }
      const { invoke, Channel } = await import('@tauri-apps/api/core')
      invokeFn = invoke
      ChannelCtor = Channel
      supported.value = true
    } catch (e) {
      console.warn('[useVoiceInput] Tauri init failed:', e)
      supported.value = false
    }
  })()
  return initPromise
}

initTauri()

interface ModelStatus {
  baseEn: boolean
  smallEn: boolean
  parakeetTdt06bV2: boolean
}

function statusForModel(status: ModelStatus, model: VoiceModel): boolean {
  if (model === 'small.en') return status.smallEn
  if (model === 'parakeet-tdt-0.6b-v2') return status.parakeetTdt06bV2
  return status.baseEn
}

/** Whether the given model is already downloaded. */
export async function isModelReady(model: VoiceModel): Promise<boolean> {
  await initTauri()
  if (!supported.value) return false
  const status: ModelStatus = await invokeFn('voice_model_status')
  return statusForModel(status, model)
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

  async function downloadModel(model: VoiceModel) {
    state.value = 'downloading'
    error.value = null
    downloaded.value = 0
    downloadTotal.value = null

    const chan = new ChannelCtor()
    chan.onmessage = (ev: any) => {
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
      await invokeFn('voice_download_model', { modelId: model, onEvent: chan })
      if (state.value === 'downloading') state.value = 'idle'
      track('voice_model_downloaded', { model }, 'feature')
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
      void invokeFn?.('voice_keepalive').catch(() => { /* session gone; ignore */ })
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

    const model = voiceModel.value
    if (!(await isModelReady(model))) {
      await downloadModel(model)
      return false
    }

    // Treat an all-whitespace field (including the lone space typed just before
    // a hold) as empty so dictation doesn't start with a leading space.
    baseText = opts.getText() ?? ''
    if (baseText.trim().length === 0) baseText = ''
    interim = ''

    const chan = new ChannelCtor()
    chan.onmessage = (ev: any) => {
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
      await invokeFn('voice_start', { modelId: model, onEvent: chan })
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
      const finalText: string = await invokeFn('voice_stop')
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
      try { await invokeFn('voice_cancel') } catch { /* ignore */ }
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
    voiceModel,
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
