/**
 * Utilities for analyzing tool parameter schemas to determine multi-input capability.
 * Used by send-to functionality to filter tools based on selection count.
 */

import type { ProviderTool } from '../composables/useProvidersApi'

export interface MultiInputInfo {
  supportsMultiInput: boolean
  inputType: 'images' | 'videos' | null
  propertyName: string | null  // 'input_images', 'input_videos'
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
export function analyzeToolMultiInputCapability(tool: ProviderTool): MultiInputInfo {
  const schema = tool.parameter_schema
  const properties = schema?.properties || {}
  const required = schema?.required || []

  // Pattern 1: Check for array-type input properties
  const multiInputProps = ['input_images', 'input_videos']

  for (const propName of multiInputProps) {
    const prop = properties[propName]
    if (prop && prop.type === 'array') {
      const inputType = propName === 'input_images' ? 'images' : 'videos'

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
 * Check if a selection count is valid for a tool's multi-input constraints.
 *
 * @param tool - The tool to check
 * @param selectedCount - Number of items selected
 * @param mediaType - Type of media selected ('image' or 'video')
 * @returns Object with valid boolean and optional reason string
 */
export function isSelectionValidForTool(
  tool: ProviderTool,
  selectedCount: number,
  mediaType: 'image' | 'video'
): { valid: boolean; reason?: string } {
  const info = analyzeToolMultiInputCapability(tool)

  // For single-input tools, only allow exactly 1 item
  if (!info.supportsMultiInput) {
    if (selectedCount === 1) {
      return { valid: true }
    }
    return { valid: false, reason: 'Tool only accepts single input' }
  }

  // Check media type compatibility
  if (info.inputType === 'images' && mediaType === 'video') {
    return { valid: false, reason: 'Tool requires images, not videos' }
  }
  if (info.inputType === 'videos' && mediaType === 'image') {
    return { valid: false, reason: 'Tool requires videos, not images' }
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
export function getMultiInputHint(tool: ProviderTool): string | null {
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
