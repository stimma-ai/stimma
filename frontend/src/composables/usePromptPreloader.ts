import { ref, watch, type Ref } from 'vue'
import axios from 'axios'
import { resolveWildcardsForLLM, extractVerbatim, restoreVerbatim, verifyVerbatimPreserved } from '../utils/promptProcessor'
import { getWildcards, getSegments, useWildcards, useSegments } from './useWildcards'
import { getApiBase } from '../apiConfig'

function getAPIBase() {
  return getApiBase()
}

export interface PromptPreloadHint {
  originalPrompt: string
  processedPrompt: string
  improvedPrompt: string
  instructions: string | null
  model: string | null
  isVideo: boolean
  isAudio: boolean
  inputImageCount: number
  promptSourcesSignature: string
}

interface PreloadedPrompt extends PromptPreloadHint {
  cacheKey: string
  timestamp: number
}

interface PromptPreloaderOptions {
  prompt: Ref<string>
  autoImproveEnabled: Ref<boolean>
  autoImproveInstructions: Ref<string | null>
  // The tool's model string — forwarded to /improve so the cached prompt uses
  // the right family-specific style.
  model?: Ref<string | null>
  // Whether the tool outputs video — forwarded so a cached t2v prompt is built
  // with the cinematography style (not prose).
  isVideo?: Ref<boolean>
  // Whether the tool outputs audio — forwarded so a cached t2a prompt is built
  // with the sound-focused audio style (not prose).
  isAudio?: Ref<boolean>
  // Number of input images the tool will edit — forwarded so a cached prompt for
  // an edit tool is built with the edit style. Changes invalidate the cache.
  inputImageCount?: Ref<number>
  minCacheSize?: number
  debounceMs?: number
}

/**
 * Pre-computes LLM-improved prompts in the background so they're ready
 * when the user hits generate. This eliminates the delay from auto-improve
 * during job submission.
 */
export function usePromptPreloader(options: PromptPreloaderOptions) {
  const {
    prompt,
    autoImproveEnabled,
    autoImproveInstructions,
    model,
    isVideo,
    isAudio,
    inputImageCount,
    minCacheSize = 2,
    debounceMs = 1500  // Wait a bit longer than typing debounce
  } = options

  const currentModel = () => model?.value ?? null
  const currentIsVideo = () => isVideo?.value ?? false
  const currentIsAudio = () => isAudio?.value ?? false
  const currentInputImageCount = () => inputImageCount?.value ?? 0
  const { wildcards } = useWildcards()
  const { segments } = useSegments()
  const resolvePrompt = (value: string) => resolveWildcardsForLLM(value, getWildcards(), getSegments())
  const promptSourcesSignature = () => {
    const wildcards = getWildcards()
      .map(w => ({ name: String(w.name).toLowerCase(), values: [...(w.values || [])] }))
      .sort((a, b) => a.name.localeCompare(b.name))
    const segments = getSegments()
      .map(s => ({ name: String(s.name).toLowerCase(), content: s.content || '' }))
      .sort((a, b) => a.name.localeCompare(b.name))
    return JSON.stringify({ wildcards, segments })
  }
  const buildSnapshot = (originalPrompt: string, instructions: string | null) => {
    const processedPrompt = resolvePrompt(originalPrompt)
    const normalizedInstructions = (instructions || '').trim() || null
    const cacheContext = {
      originalPrompt,
      instructions: normalizedInstructions,
      model: currentModel(),
      isVideo: currentIsVideo(),
      isAudio: currentIsAudio(),
      inputImageCount: currentInputImageCount(),
      promptSourcesSignature: promptSourcesSignature(),
    }
    return {
      ...cacheContext,
      processedPrompt,
      cacheKey: JSON.stringify(cacheContext),
    }
  }

  // Cache of pre-computed improved prompts
  const cache = ref<PreloadedPrompt[]>([])

  // Dynamic cache size based on concurrent job high-water mark
  // 2 prompts per concurrent job, minimum of minCacheSize
  let concurrentJobHighWaterMark = 1
  const getCacheCapacity = () => Math.max(minCacheSize, concurrentJobHighWaterMark * 2)

  // Currently loading prompts (to avoid duplicate requests)
  const loadingPrompts = ref<Set<string>>(new Set())

  // Debounce timer
  let debounceTimer: ReturnType<typeof setTimeout> | null = null
  let cacheGeneration = 0

  /**
   * Consume a cached improved prompt for the given input.
   * Returns the improved prompt if found and REMOVES it from cache, null otherwise.
   * Each improved prompt is unique and should only be used once.
   */
  function consumePromptPreload(
    originalPrompt: string,
    instructions: string | null
  ): PromptPreloadHint | null {
    const snapshot = buildSnapshot(originalPrompt, instructions)

    // Look for a match in cache
    const index = cache.value.findIndex(c => c.cacheKey === snapshot.cacheKey)

    if (index !== -1) {
      // Remove and return the cached prompt (consume it)
      const cached = cache.value.splice(index, 1)[0]
      console.log(`[PromptPreloader] Consumed cached prompt, ${cache.value.length} remaining`)
      const { cacheKey, timestamp, ...hint } = cached
      return hint
    }

    return null
  }

  function consumePromptPreloads(
    originalPrompt: string,
    instructions: string | null,
    count: number,
  ): PromptPreloadHint[] {
    const hints: PromptPreloadHint[] = []
    for (let i = 0; i < count; i++) {
      const hint = consumePromptPreload(originalPrompt, instructions)
      if (!hint) break
      hints.push(hint)
    }
    return hints
  }

  /**
   * Pre-load a single improved prompt into the cache.
   * Each call generates a NEW unique improved prompt (no deduplication).
   */
  async function preloadSinglePrompt(originalPrompt: string, instructions: string | null): Promise<void> {
    if (!originalPrompt.trim()) return

    const snapshot = buildSnapshot(originalPrompt, instructions)
    const generation = cacheGeneration

    // Extract [verbatim] segments and replace with placeholders before sending to LLM
    const { processed: promptWithPlaceholders, segments: verbatimSegments } = extractVerbatim(snapshot.processedPrompt)

    // Use a unique key for each loading request (allows parallel loads of same prompt)
    const loadKey = `${snapshot.cacheKey}|${Date.now()}|${Math.random()}`
    loadingPrompts.value.add(loadKey)

    try {
      let improvedPrompt: string | null = null
      const MAX_RETRIES = 3

      // Retry loop to ensure verbatim placeholders are preserved
      for (let attempt = 0; attempt < MAX_RETRIES; attempt++) {
        const response = await axios.post(`${getAPIBase()}/prompt/improve`, {
          prompt: promptWithPlaceholders,
          instructions: snapshot.instructions,
          model: snapshot.model,
          is_video: snapshot.isVideo,
          is_audio: snapshot.isAudio,
          input_image_count: snapshot.inputImageCount
        })

        const candidatePrompt = response.data.improved_prompt

        // If no verbatim segments, accept immediately
        if (verbatimSegments.length === 0) {
          improvedPrompt = candidatePrompt
          break
        }

        // Verify all placeholders are preserved
        if (verifyVerbatimPreserved(candidatePrompt, verbatimSegments)) {
          improvedPrompt = restoreVerbatim(candidatePrompt, verbatimSegments)
          break
        }

        console.warn(`[PromptPreloader] Attempt ${attempt + 1}: AI removed verbatim placeholders, retrying...`)
      }

      // If all retries failed, skip caching this prompt
      if (improvedPrompt === null) {
        console.warn('[PromptPreloader] All retries failed to preserve verbatim text, skipping cache')
        return
      }

      if (generation !== cacheGeneration) {
        console.log('[PromptPreloader] Dropping stale preloaded prompt')
        return
      }

      // Add to cache (remove oldest if at capacity)
      const capacity = getCacheCapacity()
      while (cache.value.length >= capacity) {
        cache.value.shift()
      }

      cache.value.push({
        ...snapshot,
        improvedPrompt,
        timestamp: Date.now()
      })

      console.log(`[PromptPreloader] Cached improved prompt, cache size: ${cache.value.length}/${capacity}`)
    } catch (err) {
      console.error('[PromptPreloader] Failed to pre-load prompt:', err)
    } finally {
      loadingPrompts.value.delete(loadKey)
    }
  }

  /**
   * Pre-load improved prompts to fill the cache up to capacity.
   */
  async function preloadPrompt(originalPrompt: string, instructions: string | null) {
    if (!originalPrompt.trim()) return

    const capacity = getCacheCapacity()
    const currentCount = cache.value.length + loadingPrompts.value.size
    const needed = capacity - currentCount

    if (needed <= 0) return

    console.log(`[PromptPreloader] Pre-loading ${needed} prompts (capacity: ${capacity}, have: ${cache.value.length}, loading: ${loadingPrompts.value.size})`)

    // Fire off multiple preload requests in parallel
    const promises: Promise<void>[] = []
    for (let i = 0; i < needed; i++) {
      promises.push(preloadSinglePrompt(originalPrompt, instructions))
    }

    await Promise.all(promises)
  }

  /**
   * Clear the cache (e.g., when settings change significantly)
   */
  function clearCache() {
    cacheGeneration++
    cache.value = []
    loadingPrompts.value.clear()
    if (debounceTimer) {
      clearTimeout(debounceTimer)
      debounceTimer = null
    }
  }

  /**
   * Update the concurrent job count. If this sets a new high-water mark,
   * the cache capacity will increase accordingly.
   */
  function updateConcurrentJobs(count: number) {
    if (count > concurrentJobHighWaterMark) {
      const oldCapacity = getCacheCapacity()
      concurrentJobHighWaterMark = count
      const newCapacity = getCacheCapacity()
      console.log(`[PromptPreloader] New high-water mark: ${count} concurrent jobs, capacity: ${oldCapacity} -> ${newCapacity}`)

      // Trigger preloading to fill the new capacity
      if (autoImproveEnabled.value && prompt.value.trim()) {
        preloadPrompt(prompt.value, autoImproveInstructions.value)
      }
    }
  }

  /**
   * Trigger a preload after debounce delay
   */
  function schedulePreload() {
    if (debounceTimer) {
      clearTimeout(debounceTimer)
    }

    debounceTimer = setTimeout(() => {
      debounceTimer = null
      if (autoImproveEnabled.value && prompt.value.trim()) {
        preloadPrompt(prompt.value, autoImproveInstructions.value)
      }
    }, debounceMs)
  }

  // Track the last effective prompt/enhancer config we preloaded for.
  let lastPreloadedKey = ''

  // Watch for prompt changes and pre-load when auto-improve is enabled
  watch(
    [
      prompt,
      autoImproveEnabled,
      autoImproveInstructions,
      wildcards,
      segments,
      ...(model ? [model] : []),
      ...(isVideo ? [isVideo] : []),
      ...(isAudio ? [isAudio] : []),
      ...(inputImageCount ? [inputImageCount] : []),
    ],
    ([newPrompt, enabled]) => {
      if (enabled && newPrompt.trim()) {
        // If prompt or enhancer routing changed, old cached prompts are stale.
        const key = buildSnapshot(newPrompt, autoImproveInstructions.value).cacheKey
        if (key !== lastPreloadedKey) {
          clearCache()
          lastPreloadedKey = key
        }
        schedulePreload()
      }
    },
    { immediate: true }
  )

  // When auto-improve is disabled, clear the cache
  watch(autoImproveEnabled, (enabled) => {
    if (!enabled) {
      clearCache()
    }
  })

  /**
   * Called after using a cached prompt to trigger preloading the next one.
   * This is useful for rapid generation where we want to have prompts ready.
   */
  function onCacheUsed() {
    // Immediately trigger a new preload for the current prompt
    // This ensures we have a fresh improved prompt ready for the next generation
    if (autoImproveEnabled.value && prompt.value.trim()) {
      // Small delay to avoid interfering with the current submission
      setTimeout(() => {
        if (autoImproveEnabled.value && prompt.value.trim()) {
          preloadPrompt(prompt.value, autoImproveInstructions.value)
        }
      }, 100)
    }
  }

  return {
    // Consumes (removes) a prompt from cache; each improved prompt is used only once.
    consumePromptPreload,
    consumePromptPreloads,
    preloadPrompt,
    clearCache,
    onCacheUsed,
    updateConcurrentJobs,
    // Expose for debugging
    cacheSize: () => cache.value.length,
    cacheCapacity: getCacheCapacity,
    isLoading: () => loadingPrompts.value.size > 0
  }
}
