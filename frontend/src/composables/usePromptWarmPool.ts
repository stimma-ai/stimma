import { watch, onUnmounted, type Ref } from 'vue'
import axios from 'axios'
import { useWildcards, useSegments } from './useWildcards'
import { getApiBase } from '../apiConfig'

function getAPIBase() {
  return getApiBase()
}

// Server-side pool TTL is 30s (see PROMPT_WARM_POOL_TTL) - heartbeat well
// under that so a steady, unchanging forever-mode run (no prompt edits, no
// job completions for a while) never lets the intent go stale.
const HEARTBEAT_MS = 12000

interface PromptWarmPoolOptions {
  generatorInstanceId: string
  toolId: Ref<string | null>
  prompt: Ref<string>
  autoImproveEnabled: Ref<boolean>
  autoImproveInstructions: Ref<string | null>
  model?: Ref<string | null>
  isVideo?: Ref<boolean>
  isAudio?: Ref<boolean>
  inputImageCount?: Ref<number>
  // True only while generate-forever is actually running. The warm pool only
  // exists for the duration of a forever-mode registration - there's no duty
  // cycle to preserve for a single manual generation, so we don't speculate
  // there (the synchronous enhance-at-submit path handles that case, same as
  // it always has).
  active: Ref<boolean>
  // Forever mode's concurrency. Client authority - it's the one driving how
  // many GPU slots are meant to stay full.
  concurrency: Ref<number>
  debounceMs?: number
}

/**
 * Tells the server how many LLM-enhanced prompt variants to keep warm for this
 * generator instance while generate-forever is running. This is a thin,
 * fire-and-forget signal — the actual LLM work happens entirely server-side
 * (see GenerationQueue's prompt warm pool), so this composable holds no cache
 * and never blocks a submit waiting on an LLM call.
 */
export function usePromptWarmPool(options: PromptWarmPoolOptions) {
  const {
    generatorInstanceId,
    toolId,
    prompt,
    autoImproveEnabled,
    autoImproveInstructions,
    model,
    isVideo,
    isAudio,
    inputImageCount,
    active,
    concurrency,
    debounceMs = 1500,
  } = options

  const { wildcards } = useWildcards()
  const { segments } = useSegments()

  const promptSourcesSignature = () => {
    const w = wildcards.value
      .map(x => ({ name: String(x.name).toLowerCase(), values: [...(x.values || [])] }))
      .sort((a, b) => a.name.localeCompare(b.name))
    const s = segments.value
      .map(x => ({ name: String(x.name).toLowerCase(), content: x.content || '' }))
      .sort((a, b) => a.name.localeCompare(b.name))
    return JSON.stringify({ wildcards: w, segments: s })
  }

  let debounceTimer: ReturnType<typeof setTimeout> | null = null
  let heartbeatTimer: ReturnType<typeof setInterval> | null = null

  function sendUpdate() {
    if (debounceTimer) {
      clearTimeout(debounceTimer)
      debounceTimer = null
    }
    if (!toolId.value) return
    if (!active.value) return
    if (!autoImproveEnabled.value || !prompt.value.trim()) {
      // Enhancement got disabled (or the prompt was cleared) without forever
      // mode itself stopping - explicitly clear rather than silently leaving
      // a pool that only self-heals after the TTL.
      clear()
      return
    }
    axios.post(`${getAPIBase()}/generate/prompt-warm-pool/update`, {
      generator_instance_id: generatorInstanceId,
      tool_id: toolId.value,
      prompt: prompt.value,
      instructions: (autoImproveInstructions.value || '').trim() || null,
      model: model?.value ?? null,
      is_video: isVideo?.value ?? false,
      is_audio: isAudio?.value ?? false,
      input_image_count: inputImageCount?.value ?? 0,
      prompt_sources_signature: promptSourcesSignature(),
      concurrency: concurrency.value,
    }).catch(err => {
      console.warn('[PromptWarmPool] update failed:', err)
    })
  }

  function scheduleUpdate() {
    if (debounceTimer) clearTimeout(debounceTimer)
    debounceTimer = setTimeout(() => {
      debounceTimer = null
      sendUpdate()
    }, debounceMs)
  }

  /** Clear the pool immediately rather than waiting on the server's TTL. */
  function clear() {
    if (debounceTimer) {
      clearTimeout(debounceTimer)
      debounceTimer = null
    }
    if (!toolId.value) return
    axios.post(`${getAPIBase()}/generate/prompt-warm-pool/update`, {
      generator_instance_id: generatorInstanceId,
      tool_id: toolId.value,
      prompt: prompt.value || '',
      concurrency: 0,
    }).catch(() => { /* best-effort - server TTL/unregister/disconnect also tear it down */ })
  }

  // Starting forever mode should warm the pool immediately, not after a
  // debounce delay - the prompt is presumably already settled by the time the
  // user clicks start. Subsequent edits while still active are debounced.
  // A periodic heartbeat also runs the whole time forever mode is active:
  // server-side consumption already refreshes the pool's TTL on every job
  // (which covers the common case, since job cadence is far under the TTL),
  // but a heartbeat is the backstop for a steady run where the prompt never
  // changes and consumes are infrequent (e.g. concurrency=1 on a long job).
  watch(active, (isActive) => {
    if (isActive) {
      sendUpdate()
      if (!heartbeatTimer) {
        heartbeatTimer = setInterval(sendUpdate, HEARTBEAT_MS)
      }
    } else {
      if (debounceTimer) {
        clearTimeout(debounceTimer)
        debounceTimer = null
      }
      if (heartbeatTimer) {
        clearInterval(heartbeatTimer)
        heartbeatTimer = null
      }
    }
  })

  onUnmounted(() => {
    if (debounceTimer) clearTimeout(debounceTimer)
    if (heartbeatTimer) clearInterval(heartbeatTimer)
  })

  watch(
    [
      prompt,
      autoImproveEnabled,
      autoImproveInstructions,
      concurrency,
      wildcards,
      segments,
      ...(model ? [model] : []),
      ...(isVideo ? [isVideo] : []),
      ...(isAudio ? [isAudio] : []),
      ...(inputImageCount ? [inputImageCount] : []),
    ],
    () => {
      if (active.value) scheduleUpdate()
    }
  )

  return { clear }
}
