/**
 * Presets API composable
 * Handles all API calls for preset management (Toolsv3)
 *
 * Presets are saved parameter configurations for tools.
 * They are identified by the full tool ID (provider_id:tool_id).
 */
import axios from 'axios'
import { getApiBase } from '../apiConfig'

function getPresetsAPIBase() {
  return `${getApiBase()}/presets`
}

/**
 * Preset state - saved parameter configuration
 */
export interface PresetState {
  // Generation parameters
  width?: number
  height?: number
  cfg?: number
  steps?: number
  sampler?: string
  scheduler?: string
  shift?: number
  denoise?: number

  // LoRAs
  loras?: Array<{ lora: string; weight: number; enabled: boolean }>

  // Prompt templates
  prompt?: string
  negative_prompt?: string
  promptOptions?: {
    autoImprove?: { enabled: boolean; instructions: string }
    varyPrompt?: { enabled: boolean; instructions: string }
  }

  // Other settings
  [key: string]: any
}

export interface Preset {
  id: number
  profile_id: string
  name: string
  tool_id: string  // Full tool ID: "builtin:ComfyUI:flux-dev:text-to-image"
  state: PresetState
  pinned: boolean
  pin_order: number | null
  created_at: string
  updated_at: string
  last_used_at: string | null
  usage_count: number
}

export interface CreatePresetRequest {
  name: string
  tool_id: string  // Full tool ID
  state?: PresetState
  pinned?: boolean
}

export interface UpdatePresetRequest {
  name?: string
  state?: PresetState
  pinned?: boolean
  pin_order?: number
}

export function usePresetsApi() {
  /**
   * List all presets for the current profile
   */
  async function listPresets(options?: {
    tool_id?: string  // Filter by full tool ID
    pinned_only?: boolean
  }): Promise<Preset[]> {
    const params: Record<string, any> = {}
    if (options?.tool_id) params.tool_id = options.tool_id
    if (options?.pinned_only) params.pinned_only = options.pinned_only

    const response = await axios.get(getPresetsAPIBase(), { params })
    return response.data
  }

  /**
   * Get presets for a specific tool
   */
  async function getPresetsForTool(toolId: string): Promise<Preset[]> {
    return listPresets({ tool_id: toolId })
  }

  /**
   * Get pinned presets only
   */
  async function getPinnedPresets(): Promise<Preset[]> {
    return listPresets({ pinned_only: true })
  }

  /**
   * Get a specific preset by ID
   */
  async function getPreset(presetId: number): Promise<Preset> {
    const response = await axios.get(`${getPresetsAPIBase()}/${presetId}`)
    return response.data
  }

  /**
   * Create a new preset
   */
  async function createPreset(request: CreatePresetRequest): Promise<Preset> {
    const response = await axios.post(getPresetsAPIBase(), request)
    return response.data
  }

  /**
   * Update a preset
   */
  async function updatePreset(presetId: number, request: UpdatePresetRequest): Promise<Preset> {
    const response = await axios.put(`${getPresetsAPIBase()}/${presetId}`, request)
    return response.data
  }

  /**
   * Delete a preset (soft delete)
   */
  async function deletePreset(presetId: number): Promise<void> {
    await axios.delete(`${getPresetsAPIBase()}/${presetId}`)
  }

  /**
   * Duplicate a preset
   */
  async function duplicatePreset(presetId: number): Promise<Preset> {
    const response = await axios.post(`${getPresetsAPIBase()}/${presetId}/duplicate`)
    return response.data
  }

  /**
   * Record preset usage (updates last_used_at and usage_count)
   */
  async function recordPresetUsage(presetId: number): Promise<{ status: string; usage_count: number }> {
    const response = await axios.post(`${getPresetsAPIBase()}/${presetId}/use`)
    return response.data
  }

  /**
   * Save current tool state as a new preset
   */
  async function saveAsPreset(
    name: string,
    toolId: string,
    state: PresetState,
    pinned: boolean = false
  ): Promise<Preset> {
    return createPreset({
      name,
      tool_id: toolId,
      state,
      pinned,
    })
  }

  return {
    listPresets,
    getPresetsForTool,
    getPinnedPresets,
    getPreset,
    createPreset,
    updatePreset,
    deletePreset,
    duplicatePreset,
    recordPresetUsage,
    saveAsPreset,
  }
}
