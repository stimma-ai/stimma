import axios from 'axios'
import { processFinalPrompt, extractVerbatim, restoreVerbatim, verifyVerbatimPreserved, type NamedWildcard, type PromptSegment } from '../utils/promptProcessor'
import { getWildcards, getSegments } from './useWildcards'
import { getApiBase } from '../apiConfig'

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
 * Metadata about prompt enhancement settings.
 * This is passed to the backend and embedded in the generated image
 * so it can be restored when using "generate more".
 */
export interface PromptMetadata {
  original_prompt: string
  auto_improve_enabled?: boolean
  auto_improve_instructions?: string
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
  promptOptions?: {
    autoImprove?: { enabled: boolean; instructions?: string | null }
  }
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
  const { prompt, promptOptions, cachedImprovedPrompt, wildcards, segments, buildPayload, onSubmitted, onError } = params

  try {
    let processedPrompt = prompt

    // If auto-improve is enabled, enhance via LLM (this is the slow part)
    console.log('[SubmissionQueue] Auto-improve enabled:', promptOptions?.autoImprove?.enabled, 'cachedPrompt:', !!cachedImprovedPrompt)
    if (promptOptions?.autoImprove?.enabled) {
      // Check if we have a pre-cached improved prompt
      if (cachedImprovedPrompt) {
        console.log('[SubmissionQueue] Using cached improved prompt')
        processedPrompt = cachedImprovedPrompt
      } else {
        // Fall back to API call - send prompt with comments intact to guide the AI
        // (comments provide context, they'll be stripped after improvement in processFinalPrompt)
        console.log('[SubmissionQueue] No cache, calling /api/prompt/improve')
        try {
          // Extract [verbatim] segments and replace with placeholders before sending to LLM
          const { processed: promptWithPlaceholders, segments: verbatimSegments } = extractVerbatim(prompt)

          let improvedPrompt: string | null = null
          const MAX_RETRIES = 3

          // Retry loop to ensure verbatim placeholders are preserved
          for (let attempt = 0; attempt < MAX_RETRIES; attempt++) {
            const improveResponse = await axios.post(`${getAPIBase()}/prompt/improve`, {
              prompt: promptWithPlaceholders,
              instructions: promptOptions.autoImprove.instructions || null
            })

            const candidatePrompt = improveResponse.data.improved_prompt
            console.log('[SubmissionQueue] Improve response attempt', attempt + 1, ':', candidatePrompt.substring(0, 100))

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

            console.warn(`[SubmissionQueue] Attempt ${attempt + 1}: AI removed verbatim placeholders, retrying...`)
          }

          // If all retries failed, continue with unimproved prompt
          if (improvedPrompt === null) {
            console.warn('[SubmissionQueue] All retries failed to preserve verbatim text, using original prompt')
          } else {
            processedPrompt = improvedPrompt
          }
        } catch (err) {
          console.error('[SubmissionQueue] Failed to auto-improve prompt:', err)
          throw new Error(`Auto-improve is enabled, but prompt improvement failed: ${getApiErrorMessage(err)}`)
        }
      }
    }

    // Final processing: expand {{name}}, strip comments, unwrap verbatim, expand inline wildcards
    processedPrompt = processFinalPrompt(processedPrompt, wildcards ?? getWildcards(), segments ?? getSegments())

    // Build prompt metadata for restoration on "generate more"
    const promptMetadata: PromptMetadata = {
      original_prompt: prompt,
      auto_improve_enabled: promptOptions?.autoImprove?.enabled || false,
      auto_improve_instructions: promptOptions?.autoImprove?.instructions || undefined,
    }

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
  promptOptions?: {
    autoImprove?: { enabled: boolean; instructions?: string | null }
  }
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
  const { prompt, promptOptions, cachedImprovedPrompt, wildcards, segments, buildPayload, onSubmitted, onError } = params

  try {
    let processedPrompt = prompt

    // If auto-improve is enabled, enhance via LLM
    if (promptOptions?.autoImprove?.enabled) {
      if (cachedImprovedPrompt) {
        processedPrompt = cachedImprovedPrompt
      } else {
        try {
          const { processed: promptWithPlaceholders, segments: verbatimSegments } = extractVerbatim(prompt)
          let improvedPrompt: string | null = null
          const MAX_RETRIES = 3

          for (let attempt = 0; attempt < MAX_RETRIES; attempt++) {
            const improveResponse = await axios.post(`${getAPIBase()}/prompt/improve`, {
              prompt: promptWithPlaceholders,
              instructions: promptOptions.autoImprove.instructions || null
            })

            const candidatePrompt = improveResponse.data.improved_prompt

            if (verbatimSegments.length === 0) {
              improvedPrompt = candidatePrompt
              break
            }

            if (verifyVerbatimPreserved(candidatePrompt, verbatimSegments)) {
              improvedPrompt = restoreVerbatim(candidatePrompt, verbatimSegments)
              break
            }
          }

          if (improvedPrompt !== null) {
            processedPrompt = improvedPrompt
          }
        } catch (err) {
          console.error('[SubmissionQueue] Failed to auto-improve prompt:', err)
          throw new Error(`Auto-improve is enabled, but prompt improvement failed: ${getApiErrorMessage(err)}`)
        }
      }
    }

    // Final processing
    processedPrompt = processFinalPrompt(processedPrompt, wildcards ?? getWildcards(), segments ?? getSegments())

    // Build prompt metadata
    const promptMetadata: PromptMetadata = {
      original_prompt: prompt,
      auto_improve_enabled: promptOptions?.autoImprove?.enabled || false,
      auto_improve_instructions: promptOptions?.autoImprove?.instructions || undefined,
    }

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
  promptOptions?: {
    autoImprove?: { enabled: boolean; instructions?: string | null }
  }
  cachedImprovedPrompt?: string | null
  wildcards?: NamedWildcard[]
  segments?: PromptSegment[]
  buildPayload: (processedPrompt: string, promptMetadata: PromptMetadata) => Record<string, any>
  onSubmitted?: (batchInfo: BatchJobResponse) => void
  onError?: (error: any) => void
}): Promise<void> {
  const { prompt, promptOptions, cachedImprovedPrompt, wildcards, segments, buildPayload, onSubmitted, onError } = params

  try {
    let processedPrompt = prompt

    if (promptOptions?.autoImprove?.enabled) {
      if (cachedImprovedPrompt) {
        processedPrompt = cachedImprovedPrompt
      } else {
        try {
          const { processed: promptWithPlaceholders, segments: verbatimSegments } = extractVerbatim(prompt)
          let improvedPrompt: string | null = null
          const MAX_RETRIES = 3

          for (let attempt = 0; attempt < MAX_RETRIES; attempt++) {
            const improveResponse = await axios.post(`${getAPIBase()}/prompt/improve`, {
              prompt: promptWithPlaceholders,
              instructions: promptOptions.autoImprove.instructions || null
            })
            const candidatePrompt = improveResponse.data.improved_prompt
            if (verbatimSegments.length === 0) {
              improvedPrompt = candidatePrompt
              break
            }
            if (verifyVerbatimPreserved(candidatePrompt, verbatimSegments)) {
              improvedPrompt = restoreVerbatim(candidatePrompt, verbatimSegments)
              break
            }
          }
          if (improvedPrompt !== null) {
            processedPrompt = improvedPrompt
          }
        } catch (err) {
          console.error('[SubmissionQueue] Failed to auto-improve prompt:', err)
          throw new Error(`Auto-improve is enabled, but prompt improvement failed: ${getApiErrorMessage(err)}`)
        }
      }
    }

    processedPrompt = processFinalPrompt(processedPrompt, wildcards ?? getWildcards(), segments ?? getSegments())

    const promptMetadata: PromptMetadata = {
      original_prompt: prompt,
      auto_improve_enabled: promptOptions?.autoImprove?.enabled || false,
      auto_improve_instructions: promptOptions?.autoImprove?.instructions || undefined,
    }

    const payload = buildPayload(processedPrompt, promptMetadata)
    const response = await axios.post<BatchJobResponse>(`${getAPIBase()}/generate/submit-media-batch`, payload)

    onSubmitted?.(response.data)
  } catch (error) {
    console.error('Failed to submit media-batch job:', error)
    onError?.(error)
  }
}
