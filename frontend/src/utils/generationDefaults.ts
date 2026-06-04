/**
 * Tool defaults - extracts default values from tool schemas.
 *
 * Tools are the single source of truth for defaults. Each tool declares its
 * parameter_schema with default values - we just extract them.
 */

// Mapping between snake_case (backend/schema) and camelCase (frontend)
const snakeToCamelMap: Record<string, string> = {
  frame_count: 'frameCount',
  negative_prompt: 'negativePrompt',
  input_images: 'inputImages',
  cfg_norm_strength: 'cfgNormStrength'
}

const camelToSnakeMap: Record<string, string> = {
  frameCount: 'frame_count',
  negativePrompt: 'negative_prompt',
  inputImages: 'input_images',
  cfgNormStrength: 'cfg_norm_strength'
}

/**
 * Extract defaults from a tool's parameter_schema (the unified bucket: tunable
 * params like cfg/steps plus inputs like width/height/prompt).
 * This is the ONLY source of defaults - no hardcoded fallbacks.
 *
 * @param parameterSchema - The tool's parameter_schema
 * @returns Object with default values from the schema
 */
export function getToolDefaults(parameterSchema?: any): Record<string, any> {
  const defaults: Record<string, any> = {}

  if (parameterSchema?.properties) {
    for (const [prop, schema] of Object.entries(parameterSchema.properties)) {
      const s = schema as any
      if (s.default !== undefined) {
        const camelKey = snakeToCamelMap[prop] || prop
        defaults[camelKey] = s.default
      }
    }
  }

  return defaults
}

/**
 * Convert frontend camelCase params to backend snake_case for API calls.
 */
export function toBackendParams(params: Record<string, any>): Record<string, any> {
  const result: Record<string, any> = {}
  for (const [key, value] of Object.entries(params)) {
    const backendKey = camelToSnakeMap[key] || key
    result[backendKey] = value
  }
  return result
}

/**
 * Convert backend snake_case params to frontend camelCase.
 */
export function toFrontendParams(params: Record<string, any>): Record<string, any> {
  const result: Record<string, any> = {}
  for (const [key, value] of Object.entries(params)) {
    const frontendKey = snakeToCamelMap[key] || key
    result[frontendKey] = value
  }
  return result
}

/**
 * Get tool defaults using snake_case keys.
 */
export function getToolDefaultsSnakeCase(parameterSchema?: any): Record<string, any> {
  const camelDefaults = getToolDefaults(parameterSchema)
  return toBackendParams(camelDefaults)
}

// =============================================================================
// DEPRECATED - Legacy exports for backwards compatibility during migration
// These will be removed once all consumers are updated
// =============================================================================

/** @deprecated Use getToolDefaults instead */
export const DEFAULT_PARAMS = {
  seed: null,
  randomizeSeed: true,
  selected_loras: []
}

/** @deprecated Use getToolDefaults instead */
export const TASK_DEFAULTS: Record<string, any> = {}

/** @deprecated Use getToolDefaults instead */
export function getModelDefaults(schemaOrTool: any, _model: any = null): Record<string, any> {
  // Handle both: direct schema OR full tool object with parameter_schema
  if (schemaOrTool?.parameter_schema) {
    // It's a tool object
    return getToolDefaults(schemaOrTool.parameter_schema)
  }
  // It's a direct schema (legacy usage)
  return getToolDefaults(schemaOrTool)
}

/** @deprecated Use getToolDefaults instead */
export function getDefaultsForTask(_taskType: string, schema?: any, _model?: any): Record<string, any> {
  return { ...DEFAULT_PARAMS, ...getToolDefaults(schema) }
}

/** @deprecated Use getToolDefaultsSnakeCase instead */
export function getDefaultsForTaskSnakeCase(_taskType: string, schema?: any, _model?: any): Record<string, any> {
  return toBackendParams(getDefaultsForTask(_taskType, schema))
}

/** @deprecated Use getToolDefaultsSnakeCase instead */
export function getModelDefaultsSnakeCase(schema: any, model: any = null): Record<string, any> {
  return toBackendParams(getModelDefaults(schema, model))
}
