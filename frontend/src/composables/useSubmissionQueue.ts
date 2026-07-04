import axios from 'axios'
import { getApiBase } from '../apiConfig'

function getAPIBase() {
  return getApiBase()
}

function handleReservedSubmitFailure(
  error: any,
  payload: Record<string, any> | null,
  backendSubmitStarted: boolean,
  onNoBackendSubmission?: (error: any) => void,
  onBackendRejected?: (error: any) => void,
) {
  if (payload?.forever_work_reserved !== true) {
    if (!backendSubmitStarted) {
      onNoBackendSubmission?.(error)
    }
    return
  }
  if (!backendSubmitStarted || !error?.response || error.response.status === 422) {
    onNoBackendSubmission?.(error)
    return
  }
  onBackendRejected?.(error)
}

/**
 * Prompt transforms are applied by the backend submit routes immediately before
 * queueing. The frontend sends the raw editor prompt plus this option shape so
 * single jobs, batch jobs, media-batch jobs, forever mode, and post-processing
 * chains all use one generate-time prompt pipeline.
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
    // Whether the tool outputs audio — authoritative for the sound-focused audio
    // style (text-to-audio / music / sound / speech), same as isVideo.
    isAudio?: boolean
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

/** Target output canvas, so JSON mode can compose layout for the real aspect ratio. */
export interface ImageSize {
  width?: number | null
  height?: number | null
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
 * Queue a generation job. Prompt processing now happens in the backend submit
 * route before the job is written to the queue.
 *
 * The caller is responsible for:
 * - Adding a pending job to the UI before calling this
 * - Removing the pending job when onSubmitted or onError is called
 * - Releasing any forever-mode reservation if onNoBackendSubmission is called
 */
export async function submitJobAsync(params: {
  // Prompt processing
  prompt: string
  promptOptions?: SubmitPromptOptions
  // Kept for call-site compatibility; the backend derives dimensions from parameters.
  imageSize?: ImageSize
  // Kept for call-site compatibility. Prompt preloads are attached by ToolView
  // as backend-validated hints rather than processed here.
  cachedImprovedPrompt?: string | null
  wildcards?: unknown[]
  segments?: unknown[]
  // Receives the raw editor prompt and metadata about the original prompt/options.
  buildPayload: (rawPrompt: string, promptMetadata: PromptMetadata) => Record<string, any>
  // Called after successful submission
  onSubmitted?: () => void
  // Called on error
  onError?: (error: any) => void
  // Called when cancellation/building failed before the backend submit endpoint was reached.
  onNoBackendSubmission?: (error: any) => void
  // Called when the backend received reserved forever work but rejected it before queueing.
  onBackendRejected?: (error: any) => void
  // Return false to cancel before backend submission.
  shouldSubmit?: () => boolean
  onCancelled?: () => void
}): Promise<void> {
  const { prompt, promptOptions, buildPayload, onSubmitted, onError, onNoBackendSubmission, onBackendRejected, shouldSubmit, onCancelled } = params
  let backendSubmitStarted = false
  let payload: Record<string, any> | null = null

  try {
    // Build prompt metadata for restoration on "generate more"
    const promptMetadata = buildPromptMetadata(prompt, promptOptions)

    // Build the final payload with the raw prompt and metadata. The backend
    // applies wildcards/enhance/translate/final cleanup/Ideogram JSON.
    payload = buildPayload(prompt, promptMetadata)

    if (shouldSubmit && !shouldSubmit()) {
      onCancelled?.()
      onNoBackendSubmission?.(new Error('Submission cancelled'))
      return
    }

    // Submit to backend
    backendSubmitStarted = true
    await axios.post(`${getAPIBase()}/generate/submit`, payload)

    onSubmitted?.()
  } catch (error) {
    console.error('Failed to submit job:', error)
    onError?.(error)
    handleReservedSubmitFailure(error, payload, backendSubmitStarted, onNoBackendSubmission, onBackendRejected)
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
  prompt: string
  promptOptions?: SubmitPromptOptions
  imageSize?: ImageSize
  cachedImprovedPrompt?: string | null
  wildcards?: unknown[]
  segments?: unknown[]
  buildPayload: (rawPrompt: string, promptMetadata: PromptMetadata) => Record<string, any>
  // Called after successful submission with batch info
  onSubmitted?: (batchInfo: BatchJobResponse) => void
  // Called on error
  onError?: (error: any) => void
  // Called when cancellation/building failed before the backend submit endpoint was reached.
  onNoBackendSubmission?: (error: any) => void
  // Called when the backend received reserved forever work but rejected it before queueing.
  onBackendRejected?: (error: any) => void
  // Return false to cancel before backend submission.
  shouldSubmit?: () => boolean
  onCancelled?: () => void
}): Promise<void> {
  const { prompt, promptOptions, buildPayload, onSubmitted, onError, onNoBackendSubmission, onBackendRejected, shouldSubmit, onCancelled } = params
  let backendSubmitStarted = false
  let payload: Record<string, any> | null = null

  try {
    // Build prompt metadata
    const promptMetadata = buildPromptMetadata(prompt, promptOptions)

    // Build the final payload
    payload = buildPayload(prompt, promptMetadata)

    if (shouldSubmit && !shouldSubmit()) {
      onCancelled?.()
      onNoBackendSubmission?.(new Error('Submission cancelled'))
      return
    }

    // Submit to batch endpoint
    backendSubmitStarted = true
    const response = await axios.post<BatchJobResponse>(`${getAPIBase()}/generate/submit-batch`, payload)

    onSubmitted?.(response.data)
  } catch (error) {
    console.error('Failed to submit batch job:', error)
    onError?.(error)
    handleReservedSubmitFailure(error, payload, backendSubmitStarted, onNoBackendSubmission, onBackendRejected)
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
  imageSize?: ImageSize
  cachedImprovedPrompt?: string | null
  wildcards?: unknown[]
  segments?: unknown[]
  buildPayload: (rawPrompt: string, promptMetadata: PromptMetadata) => Record<string, any>
  onSubmitted?: (batchInfo: BatchJobResponse) => void
  onError?: (error: any) => void
  // Called when cancellation/building failed before the backend submit endpoint was reached.
  onNoBackendSubmission?: (error: any) => void
  // Called when the backend received reserved forever work but rejected it before queueing.
  onBackendRejected?: (error: any) => void
  // Return false to cancel before backend submission.
  shouldSubmit?: () => boolean
  onCancelled?: () => void
}): Promise<void> {
  const { prompt, promptOptions, buildPayload, onSubmitted, onError, onNoBackendSubmission, onBackendRejected, shouldSubmit, onCancelled } = params
  let backendSubmitStarted = false
  let payload: Record<string, any> | null = null

  try {
    const promptMetadata = buildPromptMetadata(prompt, promptOptions)

    payload = buildPayload(prompt, promptMetadata)
    if (shouldSubmit && !shouldSubmit()) {
      onCancelled?.()
      onNoBackendSubmission?.(new Error('Submission cancelled'))
      return
    }

    backendSubmitStarted = true
    const response = await axios.post<BatchJobResponse>(`${getAPIBase()}/generate/submit-media-batch`, payload)

    onSubmitted?.(response.data)
  } catch (error) {
    console.error('Failed to submit media-batch job:', error)
    onError?.(error)
    handleReservedSubmitFailure(error, payload, backendSubmitStarted, onNoBackendSubmission, onBackendRejected)
  }
}
