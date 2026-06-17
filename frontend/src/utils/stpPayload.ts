/**
 * Build the `{ parameters }` payload the backend ships to an STP tool via
 * `tools.execute`. There is a single `parameters` namespace — prompt, images,
 * mask, resolution, seed, and all tuning params live together.
 */
const INTERNAL_KEYS = new Set([
  'generation_time',
  'supersede_source',
  'inspired_by_media_id',
  '_original_input_paths',
  '_input_preprocessors',
  '_input_preprocessor_params',
  '_original_input_hashes',
])

export interface StpCallPayload {
  tool_id: string | null
  parameters: Record<string, any>
  n?: number
}

/**
 * Build the STP call payload from a stored params dict (jobs and flow
 * tool-call definitions). Drops internal bookkeeping keys that the backend
 * would strip before dispatch.
 */
export function buildStpCallPayload(
  toolId: string | null | undefined,
  params: Record<string, any> | null | undefined,
  options: { n?: number } = {},
): StpCallPayload {
  const parameters: Record<string, any> = {}
  if (params && typeof params === 'object') {
    for (const [key, value] of Object.entries(params)) {
      if (INTERNAL_KEYS.has(key)) continue
      if (value === undefined) continue
      parameters[key] = value
    }
  }
  const payload: StpCallPayload = {
    tool_id: toolId ?? null,
    parameters,
  }
  if (options.n !== undefined && options.n !== 1) payload.n = options.n
  return payload
}

export function stringifyStpPayload(payload: StpCallPayload | null): string | null {
  if (!payload) return null
  try {
    return JSON.stringify(payload, null, 2)
  } catch {
    return null
  }
}
