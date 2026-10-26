/**
 * Utilities for analyzing tool parameter schemas to determine multi-input capability.
 * Used by send-to functionality to filter tools based on selection count.
 */

import type { MediaType } from './mediaTypes'

/** A full tool, or a catalog summary that carries only its parameter outline. */
export interface ToolSchemaSource {
  parameter_schema?: Record<string, any>
  parameter_outline?: { properties?: Record<string, any> }
}

/**
 * A tool's parameter properties: from its full schema, else from a catalog
 * summary's outline. The outline keeps only the media slots and the keys
 * send-to checks read (type, item limits, x-control, x-accept-media), so it
 * answers these media questions the way the full schema would — and nothing
 * else (no defaults, enums or other parameters). Null when neither exists.
 */
export function toolParameterProperties(tool: ToolSchemaSource | null | undefined): Record<string, any> | null {
  const full = tool?.parameter_schema?.properties
  if (full && typeof full === 'object') return full
  if (tool?.parameter_schema) return null
  const outline = tool?.parameter_outline?.properties
  return outline && typeof outline === 'object' ? outline : null
}

export interface MultiInputInfo {
  supportsMultiInput: boolean
  inputType: 'images' | 'videos' | 'audios' | null
  propertyName: string | null  // 'input_images', 'input_videos', 'input_audios'
  minItems: number
  maxItems: number
}

/**
 * Analyzes a tool's parameter_schema to determine if it accepts multiple inputs
 * and what the constraints are.
 *
 * Handles two patterns:
 * 1. Array-type properties (input_images, input_videos) with minItems/maxItems
 * 2. Multiple separate image/video input properties (start_image, end_image, etc.)
 */
export function analyzeToolMultiInputCapability(tool: ToolSchemaSource): MultiInputInfo {
  const properties = toolParameterProperties(tool) || {}

  // Pattern 1: Check for array-type input properties. Visual inputs are matched
  // before audio so avatar/lip-sync (visual + audio) report their visual input.
  const multiInputProps = ['input_images', 'input_videos', 'input_audios']

  for (const propName of multiInputProps) {
    const prop = properties[propName]
    if (prop && prop.type === 'array') {
      const inputType = propName === 'input_images' ? 'images' : propName === 'input_videos' ? 'videos' : 'audios'

      // Get constraints from schema or ui_hints
      // ui_hints are mapped to x-* properties in JSON Schema by the backend
      const minItems = prop.minItems ?? prop['x-min-items'] ?? 1
      const maxItems = prop.maxItems ?? prop['x-max-items'] ?? Infinity

      return {
        supportsMultiInput: true,
        inputType,
        propertyName: propName,
        minItems,
        maxItems,
      }
    }
  }

  // No array-type input property found — single input tool
  return {
    supportsMultiInput: false,
    inputType: null,
    propertyName: null,
    minItems: 1,
    maxItems: 1,
  }
}

/**
 * Whether the tool requires a mask input (inpaint-style). Mask tools are
 * excluded from simple batch mode until there is a per-item mask design.
 */
export function toolRequiresMask(tool: ToolSchemaSource): boolean {
  const props = toolParameterProperties(tool) || {}
  return 'mask' in props
}

/**
 * Field names the current media-batch MVP can execute as the batched slot.
 * Keep this narrow so send-to eligibility matches ToolView and backend support.
 */
export function getBatchableMediaField(tool: ToolSchemaSource): 'input_images' | 'input_videos' | null {
  const props = toolParameterProperties(tool) || {}
  if ('input_videos' in props) return 'input_videos'
  if ('input_images' in props && props.input_images?.['x-control'] !== 'video_frame_picker') return 'input_images'
  return null
}

export function getBatchableMediaType(tool: ToolSchemaSource): 'image' | 'video' | null {
  const field = getBatchableMediaField(tool)
  if (field === 'input_videos') return 'video'
  if (field === 'input_images') return 'image'
  return null
}

/**
 * The media type a single-input tool accepts, inferred from its schema.
 * Returns null when undetermined.
 */
export function getSingleInputMediaType(tool: ToolSchemaSource): 'image' | 'video' | null {
  const props = toolParameterProperties(tool) || {}
  if ('input_videos' in props || 'input_video' in props) return 'video'
  if ('input_images' in props || 'input_image' in props || 'start_image' in props || 'source_image' in props || 'image' in props) {
    return 'image'
  }
  return null
}

/**
 * Check if a selection count is valid for a tool's multi-input constraints.
 *
 * Single-input tools are eligible for BATCH when more than one item is selected:
 * Stimma runs the tool once per item. The exception is mask-required tools, which
 * are excluded from simple batch mode.
 *
 * @param tool - The tool to check
 * @param selectedCount - Number of items selected
 * @param mediaType - Type of media selected ('image' or 'video')
 * @returns Object with valid boolean and optional reason string
 */
export function isSelectionValidForTool(
  tool: ToolSchemaSource,
  selectedCount: number,
  mediaType: MediaType
): { valid: boolean; reason?: string } {
  const info = analyzeToolMultiInputCapability(tool)

  // Single-input tools: 1 item = normal reference input; >1 = batch (run per item).
  if (!info.supportsMultiInput) {
    if (selectedCount === 1) {
      return { valid: true }
    }
    // Batch mode (selectedCount > 1)
    const accepted = getBatchableMediaType(tool)
    if (!accepted) {
      return { valid: false, reason: 'Tool does not support media batch input' }
    }
    if (accepted === 'video' && mediaType === 'image') {
      return { valid: false, reason: 'Tool requires videos, not images' }
    }
    // A video into an image slot is fine — we grab a frame on ingestion.
    if (toolRequiresMask(tool)) {
      return { valid: false, reason: 'Mask tools are not supported in batch mode' }
    }
    return { valid: true }
  }

  // Check media type compatibility. A video into an image slot is fine (we grab a
  // frame on ingestion); only image-into-video is rejected.
  if (info.inputType === 'videos' && mediaType === 'image') {
    return { valid: false, reason: 'Tool requires videos, not images' }
  }

  // An array slot that can run with a single item batches when more than one is
  // selected (run once per item) — slot maxItems does not cap the batch. Only a
  // slot that *requires* multiple inputs (minItems > 1, e.g. a 2-image blend)
  // enforces the count constraints for a single multi-reference run.
  if (selectedCount > 1 && info.minItems <= 1) {
    if (toolRequiresMask(tool)) {
      return { valid: false, reason: 'Mask tools are not supported in batch mode' }
    }
    if (!getBatchableMediaField(tool)) {
      return { valid: false, reason: 'Tool does not support media batch input' }
    }
    return { valid: true }
  }

  // Check count constraints
  if (selectedCount < info.minItems) {
    return { valid: false, reason: `Requires at least ${info.minItems} items` }
  }
  if (selectedCount > info.maxItems) {
    return { valid: false, reason: `Maximum ${info.maxItems} items allowed` }
  }

  return { valid: true }
}

/**
 * Get a human-readable hint about a tool's multi-input constraints.
 * Returns null for single-input tools.
 */
export function getMultiInputHint(tool: ToolSchemaSource): string | null {
  const info = analyzeToolMultiInputCapability(tool)
  if (!info.supportsMultiInput) return null

  if (info.minItems === info.maxItems) {
    return `${info.minItems} ${info.inputType}`
  }
  if (info.maxItems === Infinity) {
    return `${info.minItems}+ ${info.inputType}`
  }
  return `${info.minItems}-${info.maxItems} ${info.inputType}`
}
