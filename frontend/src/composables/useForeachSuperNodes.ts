import type { FlowEquation } from './useFlowsApi'
import { buildIterationsForForeach } from './useFlowGrouping'

/**
 * Derives one "super-node" per outermost iteration-like primitive (foreach or
 * hitl.approve) in the equation set.
 *
 * The super-node is the graph-view analogue of `IterationGroupItem` in the
 * tree view: an iteration primitive and all its iterations/slots collapse to
 * a single graph node whose body shows the *canonical shape* of one
 * iteration, with multiplicity (per-iteration status/media/durations) carried
 * as arrays on each body position. Downstream deps that pointed at the
 * primitive's key continue to resolve correctly because the super-node uses
 * the same key.
 *
 * Nested foreach are *recursively flattened* to leaf iterations. Each leaf
 * carries its `dims` (coordinates through the nesting levels), letting the
 * navigator render as a grid at depth 2 (e.g. 8 outer × 6 inner = 48 cells
 * in an 8-row, 6-col grid) instead of collapsing the inner loop away.
 *
 * hitl.approve is always 1D (slots don't nest hitl.approve), so its dims are
 * just `[slotCount]`.
 */

export interface BodyPosition {
  id: string
  title: string
  subtitle: string | null
  equation_type: string
  task_type: string | null
  tool_id: string | null
  hitl_kind: string | null
  control_kind: string | null
  optional: boolean
  presentCount: number
  iterStatuses: (string | null)[]
  iterEquationKeys: (string | null)[]
  iterMediaIds: number[][]
  iterDurations: (number | null)[]
  iterErrors: (string | null)[]
  iterDisplayNames: (string | null)[]
}

export interface FlatIteration {
  // Innermost foreach_iteration wrapper key for this unit of work.
  wrapperKey: string
  // Per-level indices (outer → innermost). Length = nesting depth.
  dims: number[]
  // Human labels per level (e.g. iteration key or index).
  levelLabels: string[]
  // Equations making up this leaf iteration's body.
  equations: FlowEquation[]
  // Primary (media producer, else last-completed, etc.).
  primary: FlowEquation | null
}

export interface ForeachSuperNodeData {
  foreachKey: string
  foreach: FlowEquation
  flatIterations: FlatIteration[]
  iterCount: number
  // Per-level sizes. Length = nesting depth. Product = iterCount (assumes
  // uniform inner-count per outer, which holds for foreach(collection)
  // patterns; ragged nests fall back to DFS order with max-dim padding).
  iterDims: number[]
  bodyPositions: BodyPosition[]
  bodyEdges: Array<{ fromId: string; toId: string }>
  iterLabels: string[]
  absorbedKeys: Set<string>
}

function isForeachPrimitive(eq: FlowEquation): boolean {
  return eq.equation_type === 'control' && eq.control_kind === 'foreach'
}

function isApprovePrimitive(eq: FlowEquation): boolean {
  return eq.equation_type === 'control' && eq.control_kind === 'approve'
}

function isLlmBatchPrimitive(eq: FlowEquation): boolean {
  return eq.equation_type === 'llm_batch'
}

function equationIsRenderable(eq: FlowEquation): boolean {
  // Hide control-flow scaffolding (filter/switch/take/etc — backend marks
  // these via is_scaffolding) until they fail, where the error is the only
  // useful signal. Everything else, including user-written `code()`
  // callbacks, must render — otherwise a hitl.approve whose body is just a
  // user code() ends up with zero body positions and the super-node draws
  // an empty rectangle.
  if (eq.is_scaffolding && eq.status !== 'failed') return false
  return true
}

function pickPrimary(equations: FlowEquation[]): FlowEquation | null {
  if (equations.length === 0) return null
  const media = equations.filter(
    (e) => e.status === 'completed' && e.result_media_ids && e.result_media_ids.length > 0,
  )
  if (media.length) return media[media.length - 1]
  const completed = equations.filter((e) => e.status === 'completed')
  if (completed.length) return completed[completed.length - 1]
  const failed = equations.find((e) => e.status === 'failed')
  if (failed) return failed
  return equations[0]
}

// Strip the innermost wrapper prefix and drop iteration keys so equations at
// the same "position" across iterations share a stable id.
//   wrapperKey: parent/foreach$0/cb:iter
//   childKey:   parent/foreach$0/cb:iter/fn:iter2/tool$0
//   position:   fn/tool$0
function positionIdForChild(wrapperKey: string, childKey: string): string {
  const rel = childKey.slice(wrapperKey.length + 1)
  return rel
    .split('/')
    .map((seg) => {
      const colon = seg.indexOf(':')
      return colon < 0 ? seg : seg.slice(0, colon)
    })
    .join('/')
}

// Recursive expansion. Given a foreach primitive, return one FlatIteration
// per leaf unit of work (DFS row-major order). Updates `dimsMax` in place so
// callers can see per-level sizes.
function expandLeafIterations(
  foreach: FlowEquation,
  equationsByKey: Map<string, FlowEquation>,
  dimsSoFar: number[],
  labelsSoFar: string[],
  dimsMax: number[],
  level: number,
): FlatIteration[] {
  const directIterations = buildIterationsForForeach(foreach, equationsByKey)
  if (level >= dimsMax.length) dimsMax.push(directIterations.length)
  else dimsMax[level] = Math.max(dimsMax[level], directIterations.length)

  const out: FlatIteration[] = []
  directIterations.forEach((iter, idx) => {
    const label = iter.iterKey || String(idx)
    // Is there a direct-child inner foreach primitive? (depth = 1 after wrapper)
    const wrapperPrefix = iter.wrapperKey + '/'
    let innerForeach: FlowEquation | null = null
    for (const eq of equationsByKey.values()) {
      if (!eq.equation_key.startsWith(wrapperPrefix)) continue
      const tail = eq.equation_key.slice(wrapperPrefix.length)
      if (tail.includes('/')) continue
      if (isForeachPrimitive(eq)) { innerForeach = eq; break }
    }
    if (innerForeach) {
      out.push(...expandLeafIterations(
        innerForeach,
        equationsByKey,
        [...dimsSoFar, idx],
        [...labelsSoFar, label],
        dimsMax,
        level + 1,
      ))
    } else {
      // Leaf iteration. Collect renderable children under this wrapper.
      const leafEqs: FlowEquation[] = []
      for (const eq of equationsByKey.values()) {
        if (!eq.equation_key.startsWith(wrapperPrefix)) continue
        if (!equationIsRenderable(eq)) continue
        leafEqs.push(eq)
      }
      out.push({
        wrapperKey: iter.wrapperKey,
        dims: [...dimsSoFar, idx],
        levelLabels: [...labelsSoFar, label],
        equations: leafEqs,
        primary: pickPrimary(leafEqs),
      })
    }
  })
  return out
}

function deriveTitle(
  sample: FlowEquation,
  displayNames: (string | null)[],
): string {
  const names = new Set(displayNames.filter(Boolean) as string[])
  if (names.size === 1) return [...names][0]
  const prefixes = new Set<string>()
  for (const dn of displayNames) {
    if (!dn) continue
    const idx = dn.indexOf(': ')
    prefixes.add(idx < 0 ? dn : dn.slice(0, idx))
  }
  if (prefixes.size === 1) return [...prefixes][0]
  if (sample.display_name) return sample.display_name
  switch (sample.equation_type) {
    case 'llm_call':    return 'LLM'
    case 'code':        return 'Code'
    case 'hitl':        return 'Approve'
    case 'info':        return 'Note'
    case 'tool_call': {
      const tid = sample.tool_id
      if (tid) {
        const parts = tid.split(':').filter(Boolean)
        if (parts.length >= 2) return parts[1]
      }
      return 'Tool'
    }
    case 'control':
      if (sample.control_kind === 'foreach') return 'Loop'
      if (sample.control_kind === 'approve') return 'Pick'
      return 'Control'
    case 'llm_batch':   return 'LLM'
    default: return sample.equation_type
  }
}

function deriveSubtitle(sample: FlowEquation): string | null {
  if (sample.equation_type === 'tool_call' && sample.task_type) return sample.task_type
  return null
}

function buildSuperNodeFromIterations(
  primitive: FlowEquation,
  flatIterations: FlatIteration[],
  iterDims: number[],
  equationsByKey: Map<string, FlowEquation>,
): ForeachSuperNodeData {
  const iterCount = flatIterations.length

  // Absorb every equation under the primitive (including wrappers and body
  // children) so they redirect to the super-node key.
  const absorbed = new Set<string>()
  absorbed.add(primitive.equation_key)
  const prefix = primitive.equation_key + '/'
  for (const eq of equationsByKey.values()) {
    if (eq.equation_key.startsWith(prefix)) absorbed.add(eq.equation_key)
  }

  type PosAccum = {
    id: string
    order: number
    samples: FlowEquation[]
    iterStatuses: (string | null)[]
    iterEquationKeys: (string | null)[]
    iterMediaIds: number[][]
    iterDurations: (number | null)[]
    iterErrors: (string | null)[]
    iterDisplayNames: (string | null)[]
  }
  const positions = new Map<string, PosAccum>()

  flatIterations.forEach((flit, iterIdx) => {
    flit.equations.forEach((child, orderInIter) => {
      const posId = positionIdForChild(flit.wrapperKey, child.equation_key)
      let p = positions.get(posId)
      if (!p) {
        p = {
          id: posId,
          order: orderInIter,
          samples: [],
          iterStatuses: new Array(iterCount).fill(null),
          iterEquationKeys: new Array(iterCount).fill(null),
          iterMediaIds: Array.from({ length: iterCount }, () => [] as number[]),
          iterDurations: new Array(iterCount).fill(null),
          iterErrors: new Array(iterCount).fill(null),
          iterDisplayNames: new Array(iterCount).fill(null),
        }
        positions.set(posId, p)
      }
      p.samples.push(child)
      p.iterStatuses[iterIdx] = child.status
      p.iterEquationKeys[iterIdx] = child.equation_key
      p.iterMediaIds[iterIdx] = child.result_media_ids ?? []
      const compute = typeof child.compute_duration_ms === 'number'
        && Number.isFinite(child.compute_duration_ms)
        && child.compute_duration_ms >= 0
      p.iterDurations[iterIdx] = compute
        ? (child.compute_duration_ms as number)
        : (child.execution_duration_ms ?? null)
      p.iterErrors[iterIdx] = child.error ?? null
      p.iterDisplayNames[iterIdx] = child.display_name ?? null
    })
  })

  const bodyPositions: BodyPosition[] = [...positions.values()]
    .sort((a, b) => a.order - b.order)
    .map((p) => {
      const sample = p.samples[0]
      return {
        id: p.id,
        title: deriveTitle(sample, p.iterDisplayNames),
        subtitle: deriveSubtitle(sample),
        equation_type: sample.equation_type,
        task_type: sample.task_type ?? null,
        tool_id: sample.tool_id ?? null,
        hitl_kind: sample.hitl_kind ?? null,
        control_kind: sample.control_kind ?? null,
        optional: p.samples.length < iterCount,
        presentCount: p.samples.length,
        iterStatuses: p.iterStatuses,
        iterEquationKeys: p.iterEquationKeys,
        iterMediaIds: p.iterMediaIds,
        iterDurations: p.iterDurations,
        iterErrors: p.iterErrors,
        iterDisplayNames: p.iterDisplayNames,
      }
    })

  // Body edges: intra-leaf deps, deduped to position level.
  const posIdByEqKey = new Map<string, string>()
  flatIterations.forEach((flit) => {
    flit.equations.forEach((child) => {
      posIdByEqKey.set(
        child.equation_key,
        positionIdForChild(flit.wrapperKey, child.equation_key),
      )
    })
  })
  const bodyEdgeSet = new Set<string>()
  flatIterations.forEach((flit) => {
    flit.equations.forEach((child) => {
      const tgtPos = posIdByEqKey.get(child.equation_key)
      if (!tgtPos) return
      for (const depKey of child.dependencies ?? []) {
        const srcPos = posIdByEqKey.get(depKey)
        if (srcPos && srcPos !== tgtPos) {
          bodyEdgeSet.add(`${srcPos}→${tgtPos}`)
        }
      }
    })
  })
  const bodyEdges = [...bodyEdgeSet].map((s) => {
    const [fromId, toId] = s.split('→')
    return { fromId, toId }
  })

  const iterLabels = flatIterations.map((f) => f.levelLabels.join(' · '))

  return {
    foreachKey: primitive.equation_key,
    foreach: primitive,
    flatIterations,
    iterCount,
    iterDims,
    iterLabels,
    bodyPositions,
    bodyEdges,
    absorbedKeys: absorbed,
  }
}

function buildForeachOne(
  foreach: FlowEquation,
  equationsByKey: Map<string, FlowEquation>,
): ForeachSuperNodeData {
  const dimsMax: number[] = []
  const flatIterations = expandLeafIterations(
    foreach, equationsByKey, [], [], dimsMax, 0,
  )
  return buildSuperNodeFromIterations(foreach, flatIterations, dimsMax, equationsByKey)
}

function buildApproveOne(
  approve: FlowEquation,
  equationsByKey: Map<string, FlowEquation>,
): ForeachSuperNodeData {
  // hitl.approve iterates over per-slot wrappers (control_kind='slot') exactly
  // like foreach iterates over foreach_iteration wrappers. `buildIterations
  // ForForeach` already accepts both wrapper kinds, so we reuse it.
  const slots = buildIterationsForForeach(approve, equationsByKey)
  const flatIterations: FlatIteration[] = slots.map((slot, idx) => {
    const wrapperPrefix = slot.wrapperKey + '/'
    const leafEqs: FlowEquation[] = []
    for (const eq of equationsByKey.values()) {
      if (!eq.equation_key.startsWith(wrapperPrefix)) continue
      if (!equationIsRenderable(eq)) continue
      leafEqs.push(eq)
    }
    const label = slot.iterKey || String(idx)
    return {
      wrapperKey: slot.wrapperKey,
      dims: [idx],
      levelLabels: [label],
      equations: leafEqs,
      primary: pickPrimary(leafEqs),
    }
  })
  return buildSuperNodeFromIterations(
    approve, flatIterations, [flatIterations.length], equationsByKey,
  )
}

/**
 * Build super-nodes for every outermost foreach in the equation map.
 */
export function buildForeachSuperNodes(
  equationsByKey: Map<string, FlowEquation>,
): ForeachSuperNodeData[] {
  const foreaches: FlowEquation[] = []
  for (const eq of equationsByKey.values()) {
    if (isForeachPrimitive(eq)) foreaches.push(eq)
  }
  foreaches.sort((a, b) => a.equation_key.length - b.equation_key.length)
  const outermost: FlowEquation[] = []
  const outerKeys: string[] = []
  for (const f of foreaches) {
    let nested = false
    for (const o of outerKeys) {
      if (f.equation_key.startsWith(o + '/')) { nested = true; break }
    }
    if (!nested) {
      outermost.push(f)
      outerKeys.push(f.equation_key)
    }
  }
  return outermost.map((f) => buildForeachOne(f, equationsByKey))
}

/**
 * Build super-nodes for every hitl.approve primitive in the equation map.
 * hitl.approve primitives don't nest, so we just emit one super-node per
 * primitive without an outermost-only filter.
 */
export function buildApproveSuperNodes(
  equationsByKey: Map<string, FlowEquation>,
): ForeachSuperNodeData[] {
  const out: ForeachSuperNodeData[] = []
  for (const eq of equationsByKey.values()) {
    if (isApprovePrimitive(eq)) out.push(buildApproveOne(eq, equationsByKey))
  }
  return out
}

// `llm(n>1)` builds an LLM_BATCH primitive plus N LLM_SLOT children at keys
// `{batch}/slot:0`..`{batch}/slot:N-1` (see backend/flow_dsl/primitives.py
// llm() and flow_runtime/keys.py make_nested_foreach_iteration_key). Unlike
// foreach/hitl.approve, slots are leaf equations — there's no per-iteration
// wrapper layer with body children. Each slot is its own iteration.
//
// Body collapses to a single position (all slots map to the position id
// "slot" via positionIdForChild's colon-strip), so the super-node renders
// as one row of N navigator blocks behind a single LLM body tile.
function buildLlmBatchOne(
  llmBatch: FlowEquation,
  equationsByKey: Map<string, FlowEquation>,
): ForeachSuperNodeData {
  const prefix = llmBatch.equation_key + '/'
  const slots: FlowEquation[] = []
  for (const eq of equationsByKey.values()) {
    if (eq.equation_type !== 'llm_slot') continue
    if (!eq.equation_key.startsWith(prefix)) continue
    const tail = eq.equation_key.slice(prefix.length)
    if (tail.includes('/')) continue
    slots.push(eq)
  }
  // Slot keys carry the slot index after the colon (`slot:0`, `slot:1`, ...);
  // sort numerically so 10 lands after 9 instead of between 1 and 2.
  slots.sort((a, b) => {
    const at = a.equation_key.slice(prefix.length)
    const bt = b.equation_key.slice(prefix.length)
    const ai = Number(at.split(':')[1] ?? '')
    const bi = Number(bt.split(':')[1] ?? '')
    if (Number.isFinite(ai) && Number.isFinite(bi)) return ai - bi
    return at.localeCompare(bt)
  })

  // Each slot is its own leaf iteration. Use the batch key as the wrapper
  // so positionIdForChild collapses all slots to a single body position
  // (without a wrapper, all positions would derive from `''`).
  const flatIterations: FlatIteration[] = slots.map((slot, idx) => ({
    wrapperKey: llmBatch.equation_key,
    dims: [idx],
    levelLabels: [String(idx)],
    equations: [slot],
    primary: slot,
  }))

  return buildSuperNodeFromIterations(
    llmBatch, flatIterations, [flatIterations.length], equationsByKey,
  )
}

/**
 * Build super-nodes for every llm(n>1) (LLM_BATCH) in the equation map.
 * LLM batches don't nest, so emit one super-node per primitive.
 */
export function buildLlmBatchSuperNodes(
  equationsByKey: Map<string, FlowEquation>,
): ForeachSuperNodeData[] {
  const out: ForeachSuperNodeData[] = []
  for (const eq of equationsByKey.values()) {
    if (isLlmBatchPrimitive(eq)) out.push(buildLlmBatchOne(eq, equationsByKey))
  }
  return out
}
