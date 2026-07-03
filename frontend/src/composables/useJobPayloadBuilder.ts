/**
 * Schema-driven job payload builder for ToolView.
 *
 * Extracts parameters from the tool's unified parameter_schema rather than
 * hardcoded task-type branches.
 */

import axios from 'axios'

const API_BASE = '/api'

// Types
export interface PayloadBuilderState {
  globalPrefs: {
    prompt: string
    negative_prompt: string
    folder_path: string
    inputImages: Array<{ path: string; mediaId?: number; width?: number; height?: number; _originalPath?: string; _originalHash?: string; _preprocessor?: string | null; _flip?: any }>
    inputVideos: Array<{ path: string; mediaId?: number }>
    inputAudios: Array<{ path: string; mediaId?: number }>
    promptOptions?: any
    autoMarkerIds?: number[]
  }
  modelParams: Record<string, any>
  videoImages: {
    startImage: { path: string; mediaId?: number } | null
    endImage: { path: string; mediaId?: number } | null
  }
  maskDataUrl: string | null
  enabledLoras: any[]
  inputImageWidth: number
  inputImageHeight: number
  finalResolution?: number
}

export interface PayloadBuilderConfig {
  tool: {
    generator: string
    model: string
    task_type: string
    task_types?: string[]  // All supported task types (tool may support multiple)
    full_tool_id: string
    parameter_schema?: { properties?: Record<string, any>; required?: string[] }
  }
  generatorInstanceId: string
  autoDeleteDuration: number
  projectId?: number | null  // Project scope for associating generated media
}

export interface PreUploadResult {
  [key: string]: any
}

// Parameter extractors - keyed by parameter_schema property name.
// Unified table: well-known inputs (prompt, images, mask, dimensions, seed) and
// tuning parameters (steps, cfg, sampler, etc.) all live here, keyed by field name.
const paramExtractors: Record<string, (s: PayloadBuilderState) => any> = {
  // Text inputs
  'prompt': (s) => s.globalPrefs.prompt || '',
  'negative_prompt': (s) => s.globalPrefs.negative_prompt || '',

  // Image inputs (unified array)
  'input_images': (s) => {
    // For videoFramePicker, images come from videoImages state
    // For imagePicker, images come from globalPrefs.inputImages
    if (s.videoImages.startImage) {
      const images = [s.videoImages.startImage.path]
      if (s.videoImages.endImage?.path) images.push(s.videoImages.endImage.path)
      return images
    }
    return s.globalPrefs.inputImages.map(i => i.path)
  },
  'input_media_ids': (s) => {
    if (s.videoImages.startImage) {
      const ids = []
      if (s.videoImages.startImage.mediaId) ids.push(s.videoImages.startImage.mediaId)
      if (s.videoImages.endImage?.mediaId) ids.push(s.videoImages.endImage.mediaId)
      return ids
    }
    return s.globalPrefs.inputImages.map(i => i.mediaId).filter(Boolean)
  },

  // Video inputs (unified array)
  'input_videos': (s) => s.globalPrefs.inputVideos.map(v => v.path),
  'input_video_media_ids': (s) => s.globalPrefs.inputVideos.map(v => v.mediaId).filter(Boolean),

  // Audio inputs (unified array) — audio-conditioned tools (lip-sync, avatar)
  'input_audios': (s) => s.globalPrefs.inputAudios.map(a => a.path),
  'input_audio_media_ids': (s) => s.globalPrefs.inputAudios.map(a => a.mediaId).filter(Boolean),

  // Mask is handled by pre-upload, not extracted here
  'mask': () => null,

  // Resolution/dimension params
  'width': (s) => s.modelParams.width,
  'height': (s) => s.modelParams.height,
  'megapixels': (s) => s.modelParams.megapixels,
  // Upscale resolution - always send finalResolution (computed from either mode)
  'resolution': (s) => s.finalResolution,
  // scale_factor is UI-only; always send resolution instead
  'scale_factor': () => undefined,
  'aspect_ratio': (s) => s.modelParams.aspect_ratio,
  'image_size': (s) => s.modelParams.image_size,

  // Sampling params
  'cfg': (s) => s.modelParams.cfg,
  'guidance': (s) => s.modelParams.guidance,
  'steps': (s) => s.modelParams.steps,
  'denoise': (s) => s.modelParams.denoise,
  'shift': (s) => s.modelParams.shift,
  'sampler': (s) => s.modelParams.sampler,
  'scheduler': (s) => s.modelParams.scheduler,
  'seed': (s) => s.modelParams.seed,
  'temperature': (s) => s.modelParams.temperature,

  // Model selection
  'checkpoint': (s) => s.modelParams.checkpoint,
  'loras': (s) => s.enabledLoras,
  'selected_loras': (s) => s.enabledLoras,

  // Video params
  'frame_count': (s) => s.modelParams.frameCount,
  'fps': (s) => s.modelParams.fps,
  'duration': (s) => s.modelParams.duration,

  // Upscale params
  'color_correction': (s) => s.modelParams.colorCorrection || 'lab',

  // Inpaint/outpaint params
  'strength': (s) => s.modelParams.strength,
  'context_expand_factor': (s) => s.modelParams.context_expand_factor,
  'mask_blend_pixels': (s) => s.modelParams.mask_blend_pixels,
  'mask_fill_holes': (s) => s.modelParams.mask_fill_holes,
  'feathering': (s) => s.modelParams.feathering,

  // Outpaint padding
  'top': (s) => s.modelParams.top,
  'bottom': (s) => s.modelParams.bottom,
  'left': (s) => s.modelParams.left,
  'right': (s) => s.modelParams.right,
}

/**
 * Determine the effective task type based on tool capabilities and current state.
 *
 * For tools that support multiple task types (e.g., both "text-to-image" and "image-to-image"),
 * we infer the task type based on what inputs are provided:
 * - If input images are provided AND tool supports "image-to-image" → "image-to-image"
 * - If start frame is provided AND tool supports "image-to-video" → "image-to-video"
 * - Otherwise → use the primary task_type
 *
 * This ensures lineage tracking and source_inputs are properly recorded.
 */
export function resolveEffectiveTaskType(config: PayloadBuilderConfig, state: PayloadBuilderState): string {
  const taskTypes = config.tool.task_types || [config.tool.task_type]
  const primaryTaskType = config.tool.task_type

  // Check if input images are provided
  const hasInputImages = state.globalPrefs.inputImages.length > 0 &&
    state.globalPrefs.inputImages.some(img => img.path)

  // If tool supports image-to-image and we have input images, use image-to-image
  if (hasInputImages && taskTypes.includes('image-to-image')) {
    return 'image-to-image'
  }

  // If tool supports image-to-video and we have a start frame, use image-to-video
  if (taskTypes.includes('image-to-video') && primaryTaskType === 'text-to-video') {
    if (state.videoImages?.startImage?.path) {
      return 'image-to-video'
    }
  }

  return primaryTaskType
}

/**
 * Build the base payload common to all job types
 */
export function buildBasePayload(config: PayloadBuilderConfig, state: PayloadBuilderState) {
  return {
    tool_id: config.tool.full_tool_id,
    task_type: resolveEffectiveTaskType(config, state),
    folder_path: state.globalPrefs.folder_path,
    generator_instance_id: config.generatorInstanceId,
    auto_delete_duration: config.autoDeleteDuration,
    auto_marker_ids: state.globalPrefs.autoMarkerIds?.length ? [...state.globalPrefs.autoMarkerIds] : undefined,
    project_id: config.projectId || undefined,
  }
}

/**
 * Extract parameter values from state based on what's defined in parameter_schema.
 * The unified bucket: well-known inputs (prompt, images, mask, dimensions, seed)
 * and tuning parameters (steps, cfg, sampler, etc.) all live in parameter_schema.
 */
export function extractParameters(config: PayloadBuilderConfig, state: PayloadBuilderState): Record<string, any> {
  const props = config.tool.parameter_schema?.properties || {}
  const params: Record<string, any> = {}

  for (const fieldName of Object.keys(props)) {
    const extractor = paramExtractors[fieldName]
    if (extractor) {
      const value = extractor(state)
      if (value !== null && value !== undefined) {
        params[fieldName] = value
      }
    } else {
      // Fallback: try to get directly from modelParams (for generic params)
      const value = state.modelParams[fieldName]
      if (value !== undefined) {
        params[fieldName] = value
      }
    }
  }

  // Snap width/height to allowed dimensions if tool has x-allowed-dimensions
  const widthSchema = props.width
  const allowedDims = widthSchema?.['x-allowed-dimensions'] as [number, number][] | undefined
  if (allowedDims && allowedDims.length > 0 && params.width && params.height) {
    const targetRatio = params.width / params.height
    let bestPair = allowedDims[0]
    let bestDiff = Infinity
    for (const pair of allowedDims) {
      const ratio = pair[0] / pair[1]
      const diff = Math.abs(ratio - targetRatio)
      if (diff < bestDiff) {
        bestDiff = diff
        bestPair = pair
      }
    }
    params.width = bestPair[0]
    params.height = bestPair[1]
  }

  // Add media IDs for image inputs
  if ('input_images' in props) {
    if (state.videoImages.startImage) {
      // VideoFramePicker mode — media IDs from videoImages
      const ids = []
      if (state.videoImages.startImage.mediaId) ids.push(state.videoImages.startImage.mediaId)
      if (state.videoImages.endImage?.mediaId) ids.push(state.videoImages.endImage.mediaId)
      if (ids.length > 0) params.input_media_ids = ids
    } else if (state.globalPrefs.inputImages.some(i => i.mediaId)) {
      // ImagePicker mode — media IDs from inputImages
      params.input_media_ids = state.globalPrefs.inputImages.map(i => i.mediaId).filter(Boolean)
    }
  }

  // Add media IDs for audio inputs (lineage) — audio-conditioned tools
  if ('input_audios' in props && state.globalPrefs.inputAudios.some(a => a.mediaId)) {
    params.input_audio_media_ids = state.globalPrefs.inputAudios.map(a => a.mediaId).filter(Boolean)
  }

  // Reference image prep: send original paths + all preprocessing metadata for lineage
  const images = state.globalPrefs.inputImages
  const hasPrep = images.some((i: any) => i._preprocessor || i._paintLayerPath || i._extendPadding || i._scale || i._flip || i._crop)
  if (hasPrep) {
    params._original_input_paths = images.map((i: any) => i._originalPath || i.path)
    params._original_input_hashes = images.map((i: any) => i._originalHash).filter(Boolean)
    params._input_preprocessors = images.map((i: any) => i._preprocessor || null)
    params._input_preprocessor_params = images.map((i: any) => i._preprocessorParams || null)
    params._input_paint_layers = images.map((i: any) => i._paintLayerPath || null)
    params._input_extend_padding = images.map((i: any) => i._extendPadding || null)
    params._input_extend_bg_colors = images.map((i: any) => i._extendBgColor || null)
    params._input_scales = images.map((i: any) => i._scale || null)
    params._input_flips = images.map((i: any) => i._flip || null)
    params._input_crops = images.map((i: any) => i._crop || null)
  }

  return params
}

/**
 * Get pre-upload tasks (e.g., mask upload for inpaint)
 */
export function getPreUploadTasks(
  config: PayloadBuilderConfig,
  state: PayloadBuilderState
): Array<() => Promise<PreUploadResult>> {
  const tasks: Array<() => Promise<PreUploadResult>> = []
  const props = config.tool.parameter_schema?.properties || {}

  // Mask upload for inpaint
  const hasMaskInSchema = 'mask' in props
  const hasMaskDataUrl = !!state.maskDataUrl

  if (!hasMaskInSchema && hasMaskDataUrl) {
    console.warn('[PayloadBuilder] maskDataUrl exists but "mask" not in parameter_schema.properties!', {
      parameterSchemaProps: Object.keys(props),
      maskDataUrlLength: state.maskDataUrl?.length
    })
  }

  if (hasMaskInSchema && hasMaskDataUrl) {
    console.log('[PayloadBuilder] Pre-uploading mask...')
    tasks.push(async () => {
      const maskBlob = await fetch(state.maskDataUrl!).then(r => r.blob())
      const formData = new FormData()
      formData.append('file', maskBlob, 'mask.png')
      const response = await axios.post(`${API_BASE}/generate/upload-mask`, formData, {
        headers: { 'Content-Type': 'multipart/form-data' }
      })
      console.log('[PayloadBuilder] Mask uploaded, path:', response.data.path)
      return { mask: response.data.path }
    })
  }

  // Upload paint layers for reference images that have been painted
  const images = state.globalPrefs.inputImages
  for (let i = 0; i < images.length; i++) {
    const img = images[i] as any
    if (img._paintLayerDataUrl && !img._paintLayerPath) {
      const index = i
      tasks.push(async () => {
        const paintBlob = await fetch(img._paintLayerDataUrl).then(r => r.blob())
        const formData = new FormData()
        formData.append('file', paintBlob, 'paint_layer.png')
        const response = await axios.post(`${API_BASE}/generate/upload-paint-layer`, formData, {
          headers: { 'Content-Type': 'multipart/form-data' }
        })
        // Store the uploaded path back on the image item for lineage
        images[index]._paintLayerPath = response.data.path
        return {}  // No payload merge needed — path is on the image item
      })
    }
  }

  return tasks
}

/**
 * Compute derived fields that require calculation.
 * Note: tool-specific transformations (e.g., outpaint padding → dimensions) should
 * be handled server-side by the provider, not here.
 */
export function computeDerivedFields(config: PayloadBuilderConfig, state: PayloadBuilderState): Record<string, any> {
  return {}
}

/**
 * Check if the tool has prompt enhancement capability
 */
export function hasPromptFeature(config: PayloadBuilderConfig): boolean {
  const props = config.tool.parameter_schema?.properties || {}
  return 'prompt' in props
}

/**
 * Warn about data URLs in payload - they should ideally be uploaded first.
 * The backend will handle them gracefully, but it's not optimal.
 */
function warnAboutDataUrls(payload: Record<string, any>): void {
  for (const [key, value] of Object.entries(payload)) {
    if (typeof value === 'string' && value.startsWith('data:')) {
      console.error(`[PayloadBuilder] DATA URL DETECTED in field '${key}'!`, {
        field: key,
        dataUrlLength: value.length,
        preview: value.substring(0, 50) + '...',
        // Log stack trace to find where this came from
        stack: new Error().stack
      })
    }
  }
}

/**
 * Build the complete captured state for async job submission.
 * Returns { parameters: {...}, promptOptions: {...} }
 */
export function buildCapturedState(
  config: PayloadBuilderConfig,
  state: PayloadBuilderState,
  uploadResults: PreUploadResult = {}
): { parameters: Record<string, any>; promptOptions?: any } {
  const params = extractParameters(config, state)
  const derived = computeDerivedFields(config, state)

  const result = {
    // Unified tool parameters from parameter_schema: prompt, images, mask,
    // dimensions, seed, plus tuning params (steps, cfg, sampler, etc.) and
    // mask/media upload results.
    parameters: {
      ...params,
      ...derived,
      ...uploadResults,
    },
    // Prompt enhancement options
    promptOptions: state.globalPrefs.promptOptions ? { ...state.globalPrefs.promptOptions } : undefined,
  }

  // Warn if data URLs are present (backend will handle, but not optimal)
  warnAboutDataUrls(result.parameters)

  return result
}
