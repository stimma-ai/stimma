import axios from 'axios'
import { processFinalPrompt, extractVerbatim, restoreVerbatim, verifyVerbatimPreserved, type NamedWildcard, type PromptSegment } from '../utils/promptProcessor'
import { getWildcards, getSegments } from './useWildcards'
import { getApiBase } from '../apiConfig'
import { promptLanguageByCode } from '../components/generation/promptLanguages'

function getAPIBase() {
  return getApiBase()
}

function getApiErrorMessage(error: any): string {
  const detail = error?.response?.data?.detail
  if (typeof detail === 'string') return detail
  if (detail?.message) return detail.message
  return error?.message || 'Request failed'
}

/**
 * Prompt transforms applied at generate time, in declared order:
 *   1. Enhance (autoImprove) — family-aware LLM rewrite (optionally pre-cached).
 *      The model family (resolved server-side) picks the style: prose / booru
 *      keywords / cinematography. For Ideogram (mode 'ideogram-json') the text
 *      step is SKIPPED here — JSON must run post-resolve (step 3).
 *   2. translate    — translate into a target language
 *   3. Ideogram JSON — when Enhance is on and the tool is Ideogram, convert the
 *      fully-resolved prompt to structured JSON (final step).
 * All are non-destructive: the editor text is untouched; only the prompt that is
 * actually sent to the tool is transformed.
 */
export interface SubmitPromptOptions {
  autoImprove?: {
    enabled: boolean
    instructions?: string | null
    // The tool's model string — classified server-side to pick the enhancement style.
    model?: string | null
    // Whether the tool outputs video — authoritative for cinematography routing
    // (we know the task, so it doesn't depend on the model string being recognized).
    isVideo?: boolean
    // Number of input images the tool will edit (image-to-image / inpaint). >0
    // routes a natural-language image model to the edit style. 0 for text-to-image.
    inputImageCount?: number
    // 'text' = pre-resolve rewrite (prose/keyword/cinematography); 'ideogram-json'
    // = post-resolve JSON conversion. Defaults to 'text' when absent.
    mode?: 'text' | 'ideogram-json'
    // image-to-video: library id of the source/first frame. On the cinematography
    // path the backend shows it to the model so the prompt animates the real image.
    mediaId?: number | null
  }
  translate?: { enabled: boolean; language?: string | null }
}

/**
 * Run auto-improve (the slow LLM call) on a prompt, preserving [verbatim] text.
 * Returns the improved prompt, or the original if all retries drop verbatim
 * placeholders. Throws (with a helpful message) on API failure.
 */
async function improveViaApi(prompt: string, instructions: string | null, model: string | null, isVideo: boolean, inputImageCount: number, mediaId: number | null): Promise<string> {
  // Extract [verbatim] segments and replace with placeholders before sending to LLM
  const { processed: promptWithPlaceholders, segments: verbatimSegments } = extractVerbatim(prompt)
  const MAX_RETRIES = 3

  // Retry loop to ensure verbatim placeholders survive the rewrite
  for (let attempt = 0; attempt < MAX_RETRIES; attempt++) {
    const improveResponse = await axios.post(`${getAPIBase()}/prompt/improve`, {
      prompt: promptWithPlaceholders,
      instructions: instructions || null,
      model: model || null,
      is_video: isVideo,
      input_image_count: inputImageCount,
      media_id: mediaId ?? null,
    })
    const candidatePrompt = improveResponse.data.improved_prompt
    if (verbatimSegments.length === 0) return candidatePrompt
    if (verifyVerbatimPreserved(candidatePrompt, verbatimSegments)) {
      return restoreVerbatim(candidatePrompt, verbatimSegments)
    }
    console.warn(`[SubmissionQueue] Improve attempt ${attempt + 1}: verbatim placeholders dropped, retrying...`)
  }
  console.warn('[SubmissionQueue] All improve retries failed to preserve verbatim text, using original prompt')
  return prompt
}

/**
 * Translate a prompt into the given language code, preserving [verbatim] text,
 * wildcards, and comments. Throws (with a helpful message) on API failure.
 */
async function translateViaApi(prompt: string, languageCode: string): Promise<string> {
  const lang = promptLanguageByCode(languageCode)
  if (!lang) return prompt  // unknown code — nothing to do

  const { processed: promptWithPlaceholders, segments: verbatimSegments } = extractVerbatim(prompt)
  const MAX_RETRIES = 3

  for (let attempt = 0; attempt < MAX_RETRIES; attempt++) {
    const response = await axios.post(`${getAPIBase()}/prompt/translate`, {
      prompt: promptWithPlaceholders,
      target_language: lang.english,
    })
    const candidate = response.data.translated_prompt
    if (verbatimSegments.length === 0) return candidate
    if (verifyVerbatimPreserved(candidate, verbatimSegments)) {
      return restoreVerbatim(candidate, verbatimSegments)
    }
    console.warn(`[SubmissionQueue] Translate attempt ${attempt + 1}: verbatim placeholders dropped, retrying...`)
  }
  console.warn('[SubmissionQueue] All translate retries failed to preserve verbatim text, using untranslated prompt')
  return prompt
}

/** Target output canvas, so JSON mode can compose layout for the real aspect ratio. */
export interface ImageSize {
  width?: number | null
  height?: number | null
}

/** Convert a (fully resolved) prompt to Ideogram 4 structured JSON. */
async function ideogramJsonViaApi(prompt: string, size?: ImageSize): Promise<string> {
  const response = await axios.post(`${getAPIBase()}/prompt/to-ideogram-json`, {
    prompt,
    width: size?.width ?? null,
    height: size?.height ?? null,
  })
  return response.data.json_prompt
}

/**
 * Apply auto-improve then translate to a prompt that still contains wildcards
 * and [verbatim] markers (run BEFORE processFinalPrompt). Returns the
 * transformed prompt. `cachedImprovedPrompt`, if present, skips the improve call.
 */
async function applyImproveAndTranslate(
  prompt: string,
  promptOptions: SubmitPromptOptions | undefined,
  cachedImprovedPrompt: string | null | undefined,
): Promise<string> {
  let processedPrompt = prompt

  // 1) Enhance (text styles only). Ideogram ('ideogram-json') is handled
  // post-resolve in applyJsonMode, so skip the text rewrite here.
  const ai = promptOptions?.autoImprove
  if (ai?.enabled && ai.mode !== 'ideogram-json') {
    if (cachedImprovedPrompt) {
      processedPrompt = cachedImprovedPrompt
    } else {
      try {
        processedPrompt = await improveViaApi(processedPrompt, ai.instructions || null, ai.model || null, !!ai.isVideo, ai.inputImageCount ?? 0, ai.mediaId ?? null)
      } catch (err) {
        console.error('[SubmissionQueue] Failed to enhance prompt:', err)
        throw new Error(`Enhance Prompt is enabled, but prompt enhancement failed: ${getApiErrorMessage(err)}`)
      }
    }
  }

  // 2) Translate
  if (promptOptions?.translate?.enabled && promptOptions.translate.language) {
    try {
      processedPrompt = await translateViaApi(processedPrompt, promptOptions.translate.language)
    } catch (err) {
      console.error('[SubmissionQueue] Failed to translate prompt:', err)
      throw new Error(`Translate is enabled, but translation failed: ${getApiErrorMessage(err)}`)
    }
  }

  return processedPrompt
}

/**
 * Apply Ideogram JSON conversion to a fully resolved prompt (run AFTER
 * processFinalPrompt, so wildcards are expanded and verbatim is unwrapped).
 * Runs only when Enhance is on and the tool is Ideogram (mode 'ideogram-json').
 * Returns serialized JSON, or the input unchanged otherwise.
 */
async function applyJsonMode(
  resolvedPrompt: string,
  promptOptions: SubmitPromptOptions | undefined,
  imageSize?: ImageSize,
): Promise<string> {
  const ai = promptOptions?.autoImprove
  if (!(ai?.enabled && ai.mode === 'ideogram-json')) return resolvedPrompt
  try {
    return await ideogramJsonViaApi(resolvedPrompt, imageSize)
  } catch (err) {
    console.error('[SubmissionQueue] Failed to convert prompt to JSON:', err)
    throw new Error(`Enhance Prompt is enabled, but Ideogram JSON conversion failed: ${getApiErrorMessage(err)}`)
  }
}

/**
 * Metadata about prompt enhancement settings.
 * This is passed to the backend and embedded in the generated image
 * so it can be restored when using "generate more".
 */
export interface PromptMetadata {
  original_prompt: string
  auto_improve_enabled?: boolean
  auto_improve_instructions?: string
  translate_enabled?: boolean
  translate_language?: string
  json_mode_enabled?: boolean
}

/** Build the restore-on-"generate more" metadata from prompt options. */
function buildPromptMetadata(prompt: string, promptOptions: SubmitPromptOptions | undefined): PromptMetadata {
  const ai = promptOptions?.autoImprove
  return {
    original_prompt: prompt,
    auto_improve_enabled: ai?.enabled || false,
    auto_improve_instructions: ai?.instructions || undefined,
    translate_enabled: promptOptions?.translate?.enabled || false,
    translate_language: promptOptions?.translate?.language || undefined,
    // Derived: JSON ran iff Enhance was on for an Ideogram tool.
    json_mode_enabled: !!(ai?.enabled && ai.mode === 'ideogram-json'),
  }
}

/**
 * Queue a generation job with async prompt enhancement.
 *
 * This function processes the job in the background:
 * 1. If autoImprove enabled, enhances via LLM
 * 2. Processes prompt (strips comments, expands wildcards, unwraps verbatim)
 * 3. Submits to backend
 *
 * The caller is responsible for:
 * - Adding a pending job to the UI before calling this
 * - Removing the pending job when onSubmitted or onError is called
 */
export async function submitJobAsync(params: {
  // Prompt processing
  prompt: string
  promptOptions?: SubmitPromptOptions
  // Target output canvas — used by JSON mode to compose layout for the real aspect ratio.
  imageSize?: ImageSize
  // Optional: pre-cached improved prompt from usePromptPreloader
  // If provided and auto-improve is enabled, this will be used instead of calling the API
  cachedImprovedPrompt?: string | null
  // Named wildcards from settings for {{name}} expansion
  wildcards?: NamedWildcard[]
  // Prompt segments from settings for {{name}} expansion
  segments?: PromptSegment[]
  // The payload builder function - called after prompt processing
  // Receives both the processed prompt and metadata about the original prompt/options
  buildPayload: (processedPrompt: string, promptMetadata: PromptMetadata) => Record<string, any>
  // Called after successful submission
  onSubmitted?: () => void
  // Called on error
  onError?: (error: any) => void
}): Promise<void> {
  const { prompt, promptOptions, cachedImprovedPrompt, imageSize, wildcards, segments, buildPayload, onSubmitted, onError } = params

  try {
    // 1) Auto-improve + 2) translate (on the un-resolved prompt, preserving
    // wildcards + [verbatim]). The slow part.
    let processedPrompt = await applyImproveAndTranslate(prompt, promptOptions, cachedImprovedPrompt)

    // Final processing: expand {{name}}, strip comments, unwrap verbatim, expand inline wildcards
    processedPrompt = processFinalPrompt(processedPrompt, wildcards ?? getWildcards(), segments ?? getSegments())

    // 3) JSON mode — convert the fully resolved prompt to Ideogram 4 JSON (last step)
    processedPrompt = await applyJsonMode(processedPrompt, promptOptions, imageSize)

    // Build prompt metadata for restoration on "generate more"
    const promptMetadata = buildPromptMetadata(prompt, promptOptions)

    // Build the final payload with processed prompt and metadata
    const payload = buildPayload(processedPrompt, promptMetadata)

    // Submit to backend
    await axios.post(`${getAPIBase()}/generate/submit`, payload)

    onSubmitted?.()
  } catch (error) {
    console.error('Failed to submit job:', error)
    onError?.(error)
  }
}


/**
 * Response from batch job submission.
 */
export interface BatchJobResponse {
  batch_id: string
  total_jobs: number
  job_ids: number[]
}

/**
 * Submit a batch of generation jobs from set inputs.
 *
 * This is used when a set is dropped onto a tool input. The backend
 * expands the set and creates individual jobs for each item.
 */
export async function submitBatchJobAsync(params: {
  // Prompt processing
  prompt: string
  promptOptions?: SubmitPromptOptions
  // Target output canvas — used by JSON mode to compose layout for the real aspect ratio.
  imageSize?: ImageSize
  cachedImprovedPrompt?: string | null
  // Named wildcards from settings for {{name}} expansion
  wildcards?: NamedWildcard[]
  // Prompt segments from settings for {{name}} expansion
  segments?: PromptSegment[]
  // The payload builder function - called after prompt processing
  buildPayload: (processedPrompt: string, promptMetadata: PromptMetadata) => Record<string, any>
  // Called after successful submission with batch info
  onSubmitted?: (batchInfo: BatchJobResponse) => void
  // Called on error
  onError?: (error: any) => void
}): Promise<void> {
  const { prompt, promptOptions, cachedImprovedPrompt, imageSize, wildcards, segments, buildPayload, onSubmitted, onError } = params

  try {
    // 1) Auto-improve + 2) translate
    let processedPrompt = await applyImproveAndTranslate(prompt, promptOptions, cachedImprovedPrompt)

    // Final processing
    processedPrompt = processFinalPrompt(processedPrompt, wildcards ?? getWildcards(), segments ?? getSegments())

    // 3) JSON mode (last step)
    processedPrompt = await applyJsonMode(processedPrompt, promptOptions, imageSize)

    // Build prompt metadata
    const promptMetadata = buildPromptMetadata(prompt, promptOptions)

    // Build the final payload
    const payload = buildPayload(processedPrompt, promptMetadata)

    // Submit to batch endpoint
    const response = await axios.post<BatchJobResponse>(`${getAPIBase()}/generate/submit-batch`, payload)

    onSubmitted?.(response.data)
  } catch (error) {
    console.error('Failed to submit batch job:', error)
    onError?.(error)
  }
}


/**
 * Submit a media-batch: run a tool once per item in one media slot.
 *
 * Used when a media slot is marked as a batch (multi-select Send to Tool). The
 * backend sources the batch from media IDs, applies uniform batch-safe prep per
 * item, and creates one job per item under a shared batch_id. Outputs stay as
 * individual library assets (presentation-only grouping).
 */
export async function submitMediaBatchJobAsync(params: {
  prompt: string
  promptOptions?: SubmitPromptOptions
  // Target output canvas — used by JSON mode to compose layout for the real aspect ratio.
  imageSize?: ImageSize
  cachedImprovedPrompt?: string | null
  wildcards?: NamedWildcard[]
  segments?: PromptSegment[]
  buildPayload: (processedPrompt: string, promptMetadata: PromptMetadata) => Record<string, any>
  onSubmitted?: (batchInfo: BatchJobResponse) => void
  onError?: (error: any) => void
}): Promise<void> {
  const { prompt, promptOptions, cachedImprovedPrompt, imageSize, wildcards, segments, buildPayload, onSubmitted, onError } = params

  try {
    // 1) Auto-improve + 2) translate
    let processedPrompt = await applyImproveAndTranslate(prompt, promptOptions, cachedImprovedPrompt)

    processedPrompt = processFinalPrompt(processedPrompt, wildcards ?? getWildcards(), segments ?? getSegments())

    // 3) JSON mode (last step)
    processedPrompt = await applyJsonMode(processedPrompt, promptOptions, imageSize)

    const promptMetadata = buildPromptMetadata(prompt, promptOptions)

    const payload = buildPayload(processedPrompt, promptMetadata)
    const response = await axios.post<BatchJobResponse>(`${getAPIBase()}/generate/submit-media-batch`, payload)

    onSubmitted?.(response.data)
  } catch (error) {
    console.error('Failed to submit media-batch job:', error)
    onError?.(error)
  }
}
