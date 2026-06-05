/**
 * Pure function to parse a saved generation config into structured updates.
 * Used by "generate more like this" and "go to tool" features.
 */

export interface SourceInput {
  path: string
  mediaId?: number
  filename?: string
  role?: string
  _preprocessor?: string | null
  _flip?: { horizontal?: boolean; vertical?: boolean; rotation?: number } | null
}

export interface LoraConfig {
  lora: string
  weight: number
}

export interface GenerationConfigUpdate {
  // Prompt-related
  prompt?: string
  negative_prompt?: string
  promptOptions?: {
    autoImprove?: {
      enabled: boolean
      instructions: string
    }
  }

  // Model parameters (keyed by param name)
  modelParams: Record<string, any>

  // LoRAs to apply
  loras?: LoraConfig[]

  // Signal to disable all existing loras (e.g., when using caption-only source)
  disableAllLoras?: boolean

  // Source inputs
  inputImages?: SourceInput[]
  videoImages?: {
    startImage?: SourceInput
    endImage?: SourceInput
  }

}

export interface ParseOptions {
  /** Whether the tool supports prompts (prompt in parameter_schema) */
  hasPrompt: boolean
  /** Whether the tool has frame_count param (video generation) */
  hasFrameCount: boolean
  /** Whether the tool has resolution param (upscale) */
  hasResolution: boolean
  /** Whether the tool uses video frames (start_image in parameter_schema) */
  hasVideoFrames: boolean
}

/**
 * Parse a generation config object into structured updates.
 *
 * @param data - The saved generation data (from sessionStorage)
 *               This is the flat API response from /api/generate/config-from-media
 * @param options - Context about the target tool
 * @returns Structured updates to apply to UI state, or null if invalid
 */
export function parseGenerationConfig(
  data: any,
  options: ParseOptions
): GenerationConfigUpdate | null {
  // The API returns a flat structure with all params at the top level
  if (!data) return null

  const result: GenerationConfigUpdate = {
    modelParams: {},
  }

  // --- Prompt handling ---
  // Priority: original prompt with wildcards > generated prompt
  const promptMetadata = data.prompt_metadata
  if (promptMetadata?.original_prompt) {
    result.prompt = promptMetadata.original_prompt

    // Restore auto-improve settings if available
    if (promptMetadata.auto_improve_enabled !== undefined) {
      result.promptOptions = {
        autoImprove: {
          enabled: promptMetadata.auto_improve_enabled || false,
          instructions: promptMetadata.auto_improve_instructions || ''
        }
      }
    }
  } else if (data.prompt && options.hasPrompt) {
    result.prompt = data.prompt
  }

  // Negative prompt
  if (data.negative_prompt !== undefined) {
    result.negative_prompt = data.negative_prompt
  }

  // --- LoRAs ---
  // Handle disable_all_loras flag (e.g., caption-only source images)
  if (data.disable_all_loras) {
    result.disableAllLoras = true
    result.loras = []
  } else {
    // Handle both new 'loras' and legacy 'selected_loras' field names
    const lorasList = data.loras || data.selected_loras
    if (lorasList && lorasList.length > 0) {
      result.loras = lorasList.map((l: any) => ({
        lora: l.lora || l.path,  // API may return 'path' instead of 'lora'
        weight: l.weight ?? 1.0
      }))
    }
  }

  // --- Model parameters ---
  // Universal params (always transferred)
  if (data.width !== undefined) result.modelParams.width = data.width
  if (data.height !== undefined) result.modelParams.height = data.height

  // Sampling params (only transferred if models are compatible)
  if (data.cfg !== undefined) result.modelParams.cfg = data.cfg
  if (data.steps !== undefined) result.modelParams.steps = data.steps
  if (data.sampler !== undefined) result.modelParams.sampler = data.sampler
  if (data.scheduler !== undefined) result.modelParams.scheduler = data.scheduler
  if (data.denoise !== undefined) result.modelParams.denoise = data.denoise
  if (data.shift !== undefined) result.modelParams.shift = data.shift

  // Video generation specific (tools with frame_count param)
  if (options.hasFrameCount) {
    if (data.frame_count !== undefined) result.modelParams.frameCount = data.frame_count
    if (data.fps !== undefined) result.modelParams.fps = data.fps
    if (data.lightning !== undefined) result.modelParams.lightning = data.lightning
  }

  // Upscale specific (tools with resolution param)
  if (options.hasResolution) {
    if (data.resolution !== undefined) result.modelParams.resolution = data.resolution
  }

  // --- Source inputs ---
  // Note: remix_source_input is handled by loadRemix() in ToolView,
  // which copies the image to the reference directory before setting inputImages.
  // parseGenerationConfig doesn't handle it because the copy is async.

  // --- Seed handling ---
  // Seed is tracked in remixSource for the "Use Seed" button.
  // Don't touch randomizeSeed here — only the explicit "Use Seed" action should change it.

  return result
}
