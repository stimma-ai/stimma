/**
 * Evaluator for the STP `x-constraints` / `hidden_when` parameter-constraint
 * extension. See stimma-tools-protocol TOOLS_PROTOCOL.md, "Parameter
 * Constraints (x-constraints)".
 *
 * Pure and dependency-free so it can be shared by schema parsing
 * (useToolSchemaFeatures.ts) and rendering/convergence logic
 * (SchemaParamGroup.vue, ToolView.vue).
 */

export type ConstraintCondition =
  | { param: string; op: 'equals' | 'not_equals'; value: unknown }
  | { param: string; op: 'truthy' | 'falsy' | 'empty' | 'not_empty' }
  | { param: string; op: 'in' | 'not_in'; value: unknown[] }

export type ConstraintExpr =
  | ConstraintCondition
  | { all: ConstraintExpr[] }
  | { any: ConstraintExpr[] }
  | { not: ConstraintExpr }

/** Parsed directly from the wire `x-constraints` JSON Schema extension, so
 * field names (force_value) match the wire shape rather than being renamed
 * to camelCase — there's no separate DSL-authoring form on the frontend. */
export interface ParamConstraint {
  when: ConstraintExpr
  effect: 'disable' | 'hide'
  force_value?: unknown
  reason?: string
}

function isEmptyValue(v: unknown): boolean {
  if (v === null || v === undefined) return true
  if (Array.isArray(v) || typeof v === 'string') return v.length === 0
  return false
}

function isCondition(expr: ConstraintExpr): expr is ConstraintCondition {
  return 'param' in expr
}

export function evaluateConstraintExpr(expr: ConstraintExpr, values: Record<string, unknown>): boolean {
  if ('all' in expr) return expr.all.every(e => evaluateConstraintExpr(e, values))
  if ('any' in expr) return expr.any.some(e => evaluateConstraintExpr(e, values))
  if ('not' in expr) return !evaluateConstraintExpr(expr.not, values)
  if (!isCondition(expr)) return false

  const v = values[expr.param]
  switch (expr.op) {
    case 'equals': return v === expr.value
    case 'not_equals': return v !== expr.value
    case 'truthy': return !!v
    case 'falsy': return !v
    case 'empty': return isEmptyValue(v)
    case 'not_empty': return !isEmptyValue(v)
    case 'in': return expr.value.includes(v)
    case 'not_in': return !expr.value.includes(v)
    default: return false
  }
}

export interface ParamConstraintState {
  hidden: boolean
  disabled: boolean
  forceValue?: unknown
  reason?: string
}

const NOT_DISABLED: ParamConstraintState = { hidden: false, disabled: false }

/**
 * Resolves a param's effective UI state from its constraints. `hide` wins
 * over `disable` when multiple constraints are simultaneously active.
 */
export function resolveParamConstraints(
  constraints: ParamConstraint[] | undefined,
  values: Record<string, unknown>
): ParamConstraintState {
  if (!constraints?.length) return NOT_DISABLED

  const active = constraints.filter(c => evaluateConstraintExpr(c.when, values))
  if (active.length === 0) return NOT_DISABLED

  const hide = active.find(c => c.effect === 'hide')
  if (hide) return { hidden: true, disabled: true, forceValue: hide.force_value, reason: hide.reason }

  const disable = active.find(c => c.effect === 'disable')
  if (disable) return { hidden: false, disabled: true, forceValue: disable.force_value, reason: disable.reason }

  return NOT_DISABLED
}

/** Convenience wrapper for group-level `hidden_when` (a single expression, no
 * per-constraint list — a whole section either is or isn't hidden). */
export function isSectionHidden(hiddenWhen: ConstraintExpr | undefined, values: Record<string, unknown>): boolean {
  if (!hiddenWhen) return false
  return evaluateConstraintExpr(hiddenWhen, values)
}
