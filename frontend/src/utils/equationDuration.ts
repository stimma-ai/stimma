// Equation kinds that do meaningful external/compute work and whose
// per-node duration is worth surfacing in the flow UI. Everything else
// (assembly, scaffolding, code, HITL human-wait, sub-second rasterize)
// hides duration to keep the UI free of meaningless numbers.
const DURATION_DISPLAY_TYPES = new Set([
  'llm_call',
  'llm_batch',
  'llm_slot',
  'tool_call',
  'fetch_media',
  'web_search',
])

export function shouldShowEquationDuration(equationType: string | null | undefined): boolean {
  return typeof equationType === 'string' && DURATION_DISPLAY_TYPES.has(equationType)
}

export interface EquationDurationLike {
  status?: string | null
  equation_type?: string | null
  execution_duration_ms?: number | null
  compute_duration_ms?: number | null
  created_at?: string | null
  completed_at?: string | null
}

export function equationDurationMs(eq: EquationDurationLike): number | null {
  if (eq.status !== 'completed') return null
  if (!shouldShowEquationDuration(eq.equation_type)) return null
  if (
    eq.equation_type === 'tool_call'
    && typeof eq.compute_duration_ms === 'number'
    && Number.isFinite(eq.compute_duration_ms)
    && eq.compute_duration_ms >= 0
  ) {
    return eq.compute_duration_ms
  }
  if (
    typeof eq.execution_duration_ms === 'number'
    && Number.isFinite(eq.execution_duration_ms)
    && eq.execution_duration_ms >= 0
  ) {
    return eq.execution_duration_ms
  }
  if (eq.created_at && eq.completed_at) {
    const t0 = Date.parse(eq.created_at)
    const t1 = Date.parse(eq.completed_at)
    if (Number.isFinite(t0) && Number.isFinite(t1) && t1 >= t0) return t1 - t0
  }
  return null
}

export function formatEquationDurationMs(ms: number | null | undefined): string | null {
  if (ms == null || !Number.isFinite(ms) || ms < 0) return null
  if (ms < 1000) return `${ms}ms`
  if (ms < 60_000) return `${(ms / 1000).toFixed(ms < 10_000 ? 1 : 0)}s`
  const mins = Math.floor(ms / 60_000)
  const secs = Math.round((ms % 60_000) / 1000)
  return secs ? `${mins}m ${secs}s` : `${mins}m`
}

export function equationDurationLabel(eq: EquationDurationLike): string | null {
  return formatEquationDurationMs(equationDurationMs(eq))
}
