import type { FlowEquation } from './useFlowsApi'

/**
 * Turns a phase's flat equation list into a StepItem tree where each `foreach`
 * and its per-iteration children collapse into a single IterationGroup item.
 * The group derivation is pure: inputs are `FlowEquation`s, output is a
 * render-order array. The rules come straight from the equation-key format
 * (see backend/flow_runtime/keys.py):
 *
 *   foreach primitive        {parent}/foreach$N     control_kind=foreach
 *   iteration wrapper        {parent}/foreach$N/{fn}:{iter}  control_kind=foreach_iteration
 *   equations inside a body  {wrapper_key}/...
 *
 * So an iteration wrapper's foreach group key is its key with the last
 * `/{fn}:{iter}` segment stripped. That's the one identifier we need to
 * cluster siblings together.
 */

// What's holding a pending iteration back. Set on iterations whose status
// reads as "pending" so the tile can choose an icon that reflects *why*
// it's not running — sitting on the cap reads very differently from
// blocked behind a HITL waiting on a human.
//   human   — some upstream is awaiting user input
//   error   — some upstream has failed
//   tool    — self or upstream is waiting for a tool provider to come online
//   compute — at least one upstream is still running / earlier in the queue
//   cap     — deps satisfied, waiting on the concurrency cap (could start now)
export type BlockReason = 'human' | 'error' | 'tool' | 'compute' | 'cap'

export interface GroupedIteration {
  wrapperKey: string
  iterKey: string
  wrapper: FlowEquation
  equations: FlowEquation[]
  primary: FlowEquation | null
  status: string
  hasMedia: boolean
  hasHitl: boolean
  hasError: boolean
  isActionable: boolean
  // Pending iteration whose upstream deps are satisfied — i.e., the runtime
  // could schedule it immediately if the global concurrency cap weren't full.
  // Equivalent to blockReason === 'cap'; kept for callers that read it.
  isQueued: boolean
  // Why this iteration is pending. Null on terminal/active states.
  blockReason: BlockReason | null
}

export interface IterationGroupItem {
  kind: 'group'
  groupKey: string
  foreach: FlowEquation | null
  iterations: GroupedIteration[]
  aggregate: {
    total: number
    completed: number
    failed: number
    computing: number
    pending: number
    actionable: number
    queued: number
  }
  totalDurationMs: number | null
  displayName: string
  // Cell-rendering mode. Default 'tile' — IterationCard renders the
  // primary's media. 'hitl-approve' — IterationCard renders a larger
  // fixed-size cell with persistent Approve/Replace controls reading
  // from `tasksByEquationKey`. Set on synthesized groups (e.g. the
  // auto-injected approve step inside a hitl.approve body) so the row
  // reads as a HITL action surface.
  cellMode?: 'tile' | 'hitl-approve'
  // Optional instructions strip rendered above the cell grid. Only
  // meaningful for hitl-approve mode; sourced from the parent
  // primitive (hitl.approve.instructions). The strip lives on the row
  // body so its expand/collapse follows the row's lock-open state.
  instructions?: string
  // Per-iteration source slot, when this group is a flattened sub-step
  // of a hitl.approve body. HITL approve cells use this to find the
  // candidate's media via siblings (the auto-injected approve mirrors
  // its asset, but its own result_media_ids may be empty before
  // completion — siblings always have it).
  parentSlots?: GroupedIteration[]
  // Whether the group's iterations carry media or text-shaped values.
  // Drives the body layout: 'media' renders the standard tile grid;
  // 'text' renders a vertical stack of full-width rows so multi-line
  // strings / structured values aren't squashed into thumbnail-sized
  // placeholders. Decided per-group from the upstream producer (or
  // candidate producer in approve sub-steps), not per-iteration —
  // mixed groups are vanishingly rare in practice and switching layout
  // per cell would read as visual chaos.
  contentKind: 'media' | 'text'
}

export interface SlotGroupItem {
  kind: 'slot_group'
  groupKey: string
  // The hitl.approve primitive equation. Carries `count` and `instructions`
  // in its definition, surfaced via the dedicated fields below.
  approve: FlowEquation
  count: number
  instructions: string
  // Per-slot rows. Reuses GroupedIteration so the cell rendering can share
  // status/media derivations with the foreach grouping; the slot's primary
  // is the candidate-producing tool/llm/code, which is what the user sees
  // in the cell media frame.
  slots: GroupedIteration[]
  // Sub-steps: the slot body, transposed. Each sub-step is one
  // equation-position within a slot, materialized as N parallel
  // equations (one per slot). Mirrors how phases render their step
  // sequence at the top level — hitl.approve is a "virtual phase" whose
  // steps run in parallel across slots. Order follows the first slot's
  // child order so the user sees "Generate → Approve" rather than
  // "Approve → Generate."
  subSteps: SlotSubStep[]
  aggregate: {
    total: number
    completed: number  // approved
    failed: number
    computing: number
    pending: number
    actionable: number  // awaiting approval
    queued: number
  }
  totalDurationMs: number | null
  displayName: string
}

export interface SlotSubStep {
  // Path relative to the slot wrapper, e.g. "tool$0", "hitl.approve$0".
  // Used as a stable key and as the bridge across slots.
  relativePath: string
  // Drives the cell renderer:
  //   producer    — tool / llm / code / create_image / create_layout / etc.
  //                 Renders as a tile (IterationCard).
  //   hitl-approve — auto-injected approval gate. Renders as an approve
  //                  cell with approve/reject controls.
  //   other        — info / control / unknown. Falls back to a minimal
  //                  status indicator.
  kind: 'producer' | 'hitl-approve' | 'other'
  equationType: string
  hitlKind: string | null
  toolId: string | null
  taskType: string | null
  displayName: string
  // Per-slot equations for this sub-step, in slot order. Length always
  // matches SlotGroupItem.count; entries may be null for slots where
  // the equation doesn't exist yet (rare — happens when expansion is
  // mid-flight or a callback errored before reaching this sub-step).
  equations: (FlowEquation | null)[]
  // Per-slot iteration handles, synthesized so the existing rendering
  // primitives (IterationCard) can render each slot's cell uniformly.
  // Each iteration's `wrapperKey` is the slot wrapper key; the
  // iteration's `equations` is filtered to just this sub-step's row.
  // For hitl sub-steps, iterations expose the parent slot context too
  // (so the cell can find the candidate's media via siblings).
  iterations: GroupedIteration[]
  aggregate: {
    total: number
    completed: number
    failed: number
    computing: number
    pending: number
    actionable: number
  }
}

export interface EquationStepItem {
  kind: 'equation'
  eq: FlowEquation
}

// hitl.approve primitives no longer emit a wrapper item — they expand
// inline into one IterationGroupItem per sub-step. SlotGroupItem and
// SlotSubStep types remain exported for any consumer still type-checking
// against them, but are unused by the grouping pipeline.
export type StepItem = EquationStepItem | IterationGroupItem

interface Options {
  isEquationActionable?: (eq: FlowEquation) => boolean
  // The phase we're grouping for. Used to scope wrapper discovery against
  // allEquationsByKey — callers may pass a phase-filtered `phaseEquations`
  // with scaffolding already removed (PhaseNode does), which would otherwise
  // hide iteration wrappers from the grouping code.
  phasePath?: string[]
}

function phasePathMatches(a: string[], b: string[]): boolean {
  if (a.length !== b.length) return false
  for (let i = 0; i < a.length; i++) if (a[i] !== b[i]) return false
  return true
}

function groupKeyOfWrapper(wrapperKey: string): string {
  const slash = wrapperKey.lastIndexOf('/')
  return slash < 0 ? wrapperKey : wrapperKey.slice(0, slash)
}

function iterKeyFromWrapper(wrapperKey: string): string {
  const slash = wrapperKey.lastIndexOf('/')
  const tail = slash < 0 ? wrapperKey : wrapperKey.slice(slash + 1)
  const colon = tail.indexOf(':')
  return colon < 0 ? tail : tail.slice(colon + 1)
}

function isIterationWrapper(eq: FlowEquation): boolean {
  // Both foreach iterations and hitl.approve' per-slot wrappers behave the
  // same in the grouping algorithm — they're per-iteration containers
  // whose children are the actual user-visible equations. The downstream
  // step-item kind is chosen by the parent primitive's control_kind.
  return eq.equation_type === 'control'
    && (eq.control_kind === 'foreach_iteration' || eq.control_kind === 'slot')
}

function isForeachPrimitive(eq: FlowEquation): boolean {
  return eq.equation_type === 'control' && eq.control_kind === 'foreach'
}

function isApprovePrimitive(eq: FlowEquation): boolean {
  return eq.equation_type === 'control' && eq.control_kind === 'approve'
}

// An equation is "ready to schedule" when it's pending and every upstream
// dep has reached a terminal-OK state (completed or skipped). The runtime's
// scheduler uses the same check (see backend `Graph.ready_equations`) —
// rows that hit this condition but haven't flipped to `computing` yet are
// sitting behind the concurrency cap.
export function equationIsReadyToSchedule(
  eq: FlowEquation,
  all: Map<string, FlowEquation>,
): boolean {
  if (eq.status !== 'pending') return false
  for (const depKey of eq.dependencies || []) {
    const dep = all.get(depKey)
    if (!dep) continue
    if (dep.status !== 'completed' && dep.status !== 'skipped') return false
  }
  return true
}

// Walk an equation's upstream chain to figure out *why* it's pending. The
// scheduler exposes only `pending` for everything that hasn't yet fired,
// regardless of cause — this recovers the cause for the UI. Priority of
// causes (most user-relevant first): error > human > tool > compute > cap.
//
// Caller passes a memo so the same dep traversed N times across siblings
// in a foreach only walks once.
export function classifyEquationBlock(
  eq: FlowEquation,
  all: Map<string, FlowEquation>,
  memo: Map<string, BlockReason>,
  visited: Set<string> = new Set(),
): BlockReason {
  const cached = memo.get(eq.equation_key)
  if (cached) return cached
  if (visited.has(eq.equation_key)) return 'compute'
  visited.add(eq.equation_key)

  // Self-status reasons take precedence — a node waiting for its own tool
  // provider is the cause, even if its deps are also incomplete.
  if (eq.status === 'waiting_for_tool') {
    memo.set(eq.equation_key, 'tool')
    return 'tool'
  }
  if (eq.status === 'awaiting_input') {
    memo.set(eq.equation_key, 'human')
    return 'human'
  }

  let foundError = false
  let foundHuman = false
  let foundTool = false
  let foundCompute = false

  for (const depKey of eq.dependencies || []) {
    const dep = all.get(depKey)
    if (!dep) continue
    if (dep.status === 'completed' || dep.status === 'skipped') continue
    switch (dep.status) {
      case 'failed': foundError = true; break
      case 'awaiting_input': foundHuman = true; break
      case 'waiting_for_tool': foundTool = true; break
      case 'computing': foundCompute = true; break
      case 'pending': {
        const r = classifyEquationBlock(dep, all, memo, visited)
        if (r === 'error') foundError = true
        else if (r === 'human') foundHuman = true
        else if (r === 'tool') foundTool = true
        else foundCompute = true // 'compute' or 'cap' both mean "earlier in queue"
        break
      }
      default: foundCompute = true
    }
  }

  let result: BlockReason
  if (foundError) result = 'error'
  else if (foundHuman) result = 'human'
  else if (foundTool) result = 'tool'
  else if (foundCompute) result = 'compute'
  else result = 'cap'
  memo.set(eq.equation_key, result)
  return result
}

/**
 * True when an equation is parked on an unavailable tool, or when a pending
 * equation is blocked behind one. Keeping this traversal shared ensures a
 * sequential flow retains the real cause instead of degrading to "Waiting"
 * after the first phase.
 */
export function equationHasUnavailableTool(
  eq: FlowEquation,
  all: Map<string, FlowEquation>,
  memo: Map<string, BlockReason> = new Map(),
): boolean {
  if (eq.status === 'waiting_for_tool') return true
  if (eq.status !== 'pending') return false
  return classifyEquationBlock(eq, all, memo) === 'tool'
}

// Iteration-level wrapper around classifyEquationBlock. For iterations whose
// wrapper hasn't fired, classify the wrapper's upstream chain. For iterations
// whose wrapper has fired but inner work is still pending, classify the first
// pending child. Returns null for non-pending iterations.
function classifyIterationBlock(
  status: string,
  wrapper: FlowEquation,
  children: FlowEquation[],
  all: Map<string, FlowEquation>,
  memo: Map<string, BlockReason>,
): BlockReason | null {
  if (status !== 'pending') return null
  if (wrapper.status === 'pending') return classifyEquationBlock(wrapper, all, memo)
  for (const child of children) {
    if (child.status === 'pending') return classifyEquationBlock(child, all, memo)
  }
  return classifyEquationBlock(wrapper, all, memo)
}

function equationIsRenderable(eq: FlowEquation): boolean {
  if (eq.is_scaffolding && eq.status !== 'failed') return false
  if (eq.equation_type === 'code' && eq.status !== 'failed') return false
  return true
}

function pickPrimary(equations: FlowEquation[]): FlowEquation | null {
  if (equations.length === 0) return null
  // Heuristic: the iteration's "primary" equation is the one that produces
  // the visible artefact. Prefer the last completed media producer; fall
  // back to the last completed equation; then the first failed; then the
  // first renderable.
  const mediaProducers = equations.filter(
    (e) => e.status === 'completed' && e.result_media_ids && e.result_media_ids.length > 0,
  )
  if (mediaProducers.length) return mediaProducers[mediaProducers.length - 1]
  const completed = equations.filter((e) => e.status === 'completed')
  if (completed.length) return completed[completed.length - 1]
  const failed = equations.find((e) => e.status === 'failed')
  if (failed) return failed
  return equations[0]
}

function aggregateDuration(equations: FlowEquation[]): number | null {
  // Wall-clock across the group: iterations often run in parallel, so
  // summing per-equation execution_duration_ms double-counts overlap.
  // Derive each equation's start as (completed_at - execution_duration_ms)
  // and take max(end) - min(start) so parallel work collapses correctly.
  let minStart = Number.POSITIVE_INFINITY
  let maxEnd = Number.NEGATIVE_INFINITY
  let wallAny = false
  let sumTotal = 0
  let sumAny = false
  for (const eq of equations) {
    const d = eq.execution_duration_ms
    if (typeof d !== 'number' || !Number.isFinite(d) || d < 0) continue
    sumTotal += d
    sumAny = true
    const completedStr = eq.completed_at
    if (!completedStr) continue
    const endMs = Date.parse(completedStr)
    if (!Number.isFinite(endMs)) continue
    const startMs = endMs - d
    if (startMs < minStart) minStart = startMs
    if (endMs > maxEnd) maxEnd = endMs
    wallAny = true
  }
  if (wallAny) return Math.max(0, maxEnd - minStart)
  return sumAny ? sumTotal : null
}

function groupDisplayName(
  foreach: FlowEquation | null,
  iterations: GroupedIteration[],
): string {
  // Prefer a consistent primary-equation display name across iterations —
  // "Flux.2 Klein 9B" reads better than "foreach" when every iteration calls
  // the same tool. Fall back to the foreach's own label if the primary
  // varies or is missing.
  const primaryNames = new Set<string>()
  for (const it of iterations) {
    if (it.primary?.display_name) primaryNames.add(it.primary.display_name)
    else if (it.primary?.tool_id) primaryNames.add(it.primary.tool_id)
  }
  if (primaryNames.size === 1) return [...primaryNames][0]
  // Per-iteration display_names often differ because their titles contain
  // per-item content ("Layout: card for Alice", "Layout: card for Bob").
  // Backend labels follow a "Type: title" convention — collapse on the
  // prefix before ": " so a uniform type still surfaces as the group label.
  const prefixes = new Set<string>()
  for (const it of iterations) {
    const dn = it.primary?.display_name
    if (!dn) continue
    const idx = dn.indexOf(': ')
    prefixes.add(idx < 0 ? dn : dn.slice(0, idx))
  }
  if (prefixes.size === 1) return [...prefixes][0]
  return foreach?.display_name || 'Iterations'
}

// Build `GroupedIteration`s for a single foreach primitive. Used by surfaces
// outside the phase-based step list (e.g. the Outputs panel) that still want
// to render per-iteration cards with the same shape IterationCard expects.
export function buildIterationsForForeach(
  foreach: FlowEquation,
  allEquationsByKey: Map<string, FlowEquation>,
  opts: { isEquationActionable?: (eq: FlowEquation) => boolean } = {},
): GroupedIteration[] {
  const isActionable = opts.isEquationActionable || (() => false)
  const prefix = foreach.equation_key + '/'
  const wrappers: FlowEquation[] = []
  for (const eq of allEquationsByKey.values()) {
    if (!isIterationWrapper(eq)) continue
    if (!eq.equation_key.startsWith(prefix)) continue
    // Only direct children (foreach$N/fn:iter) — no nested foreach wrappers.
    const tail = eq.equation_key.slice(prefix.length)
    if (tail.includes('/')) continue
    wrappers.push(eq)
  }
  // Positional iterations encode a numeric index after the `:` — sort by that
  // so `iter:10` lands after `iter:9` rather than between `iter:1` and
  // `iter:2` (string sort would do the latter). Non-numeric keys (KEYED mode)
  // fall back to lexical order, which is what users see for named iterations.
  wrappers.sort((a, b) => {
    const ai = iterKeyFromWrapper(a.equation_key)
    const bi = iterKeyFromWrapper(b.equation_key)
    const an = Number(ai)
    const bn = Number(bi)
    const aNum = Number.isFinite(an)
    const bNum = Number.isFinite(bn)
    if (aNum && bNum) return an - bn
    if (aNum) return -1
    if (bNum) return 1
    return ai.localeCompare(bi)
  })

  const blockMemo = new Map<string, BlockReason>()
  const iterations: GroupedIteration[] = []
  for (const w of wrappers) {
    const children: FlowEquation[] = []
    const childPrefix = w.equation_key + '/'
    for (const eq of allEquationsByKey.values()) {
      if (!eq.equation_key.startsWith(childPrefix)) continue
      if (!equationIsRenderable(eq)) continue
      children.push(eq)
    }
    const primary = pickPrimary(children)
    let status = w.status
    if (children.some((c) => c.status === 'failed')) status = 'failed'
    else if (children.some((c) => c.status === 'computing')) status = 'computing'
    else if (children.every((c) => c.status === 'completed' || c.status === 'skipped') && children.length > 0) status = 'completed'
    else if (children.some((c) => c.status === 'awaiting_input')) status = 'awaiting_input'

    const hasHitl = children.some((c) => c.equation_type === 'hitl')
    const isActionableItem = children.some(
      (c) => c.equation_type === 'hitl' && c.status !== 'completed' && isActionable(c),
    )
    const blockReason = classifyIterationBlock(status, w, children, allEquationsByKey, blockMemo)
    iterations.push({
      wrapperKey: w.equation_key,
      iterKey: iterKeyFromWrapper(w.equation_key),
      wrapper: w,
      equations: children,
      primary,
      status,
      hasMedia: !!(primary?.result_media_ids && primary.result_media_ids.length > 0),
      hasHitl,
      hasError: status === 'failed',
      isActionable: isActionableItem,
      isQueued: blockReason === 'cap',
      blockReason,
    })
  }
  return iterations
}

// Wrap a single non-foreach equation as a one-item GroupedIteration. Lets
// callers render an arbitrary output through IterationCard without special-
// casing the non-iterated path.
export function buildSyntheticIteration(
  eq: FlowEquation,
  allEquationsByKey: Map<string, FlowEquation>,
  opts: { isEquationActionable?: (eq: FlowEquation) => boolean } = {},
): GroupedIteration {
  const isActionable = opts.isEquationActionable || (() => false)
  const actionable = eq.equation_type === 'hitl' && eq.status !== 'completed' && isActionable(eq)
  const blockMemo = new Map<string, BlockReason>()
  const blockReason = classifyIterationBlock(eq.status, eq, [eq], allEquationsByKey, blockMemo)
  return {
    wrapperKey: eq.equation_key,
    iterKey: '',
    wrapper: eq,
    equations: [eq],
    primary: eq,
    status: eq.status,
    hasMedia: !!(eq.result_media_ids && eq.result_media_ids.length > 0),
    hasHitl: eq.equation_type === 'hitl',
    hasError: eq.status === 'failed',
    isActionable: actionable,
    isQueued: blockReason === 'cap',
    blockReason,
  }
}

export function groupEquationsForPhase(
  phaseEquations: FlowEquation[],
  allEquationsByKey: Map<string, FlowEquation>,
  opts: Options = {},
): StepItem[] {
  const isActionable = opts.isEquationActionable || (() => false)
  const phasePath = opts.phasePath

  // Iteration wrappers and loop primitives (foreach + hitl.approve) are
  // scaffolding; they may be filtered out of phaseEquations before we see
  // it. Pull them fresh from the full map, scoped by the caller-provided
  // phase path when present.
  const wrappers: FlowEquation[] = []
  const foreachByKey = new Map<string, FlowEquation>()
  const approveByKey = new Map<string, FlowEquation>()
  for (const eq of allEquationsByKey.values()) {
    const inPhase = !phasePath || phasePathMatches(eq.phase_path || [], phasePath)
    if (!inPhase) continue
    if (isIterationWrapper(eq)) wrappers.push(eq)
    else if (isForeachPrimitive(eq)) foreachByKey.set(eq.equation_key, eq)
    else if (isApprovePrimitive(eq)) approveByKey.set(eq.equation_key, eq)
  }

  // Index wrappers by their foreach group key.
  const wrappersByGroup = new Map<string, FlowEquation[]>()
  for (const w of wrappers) {
    const gk = groupKeyOfWrapper(w.equation_key)
    const list = wrappersByGroup.get(gk) || []
    list.push(w)
    wrappersByGroup.set(gk, list)
  }

  // Keys that belong to some group's subtree — we'll skip them in the
  // ungrouped pass. A key belongs to group G if it starts with
  // `{wrapperKey}/` for any wrapper in G, OR it *is* a wrapper of G, OR
  // it is G itself (the foreach primitive).
  const claimedKeys = new Set<string>()
  const iterationsByGroup = new Map<string, GroupedIteration[]>()
  const blockMemo = new Map<string, BlockReason>()

  for (const [groupKey, wrappers] of wrappersByGroup) {
    claimedKeys.add(groupKey)
    const iterations: GroupedIteration[] = []
    for (const w of wrappers) {
      claimedKeys.add(w.equation_key)
      const children: FlowEquation[] = []
      const prefix = w.equation_key + '/'
      for (const eq of allEquationsByKey.values()) {
        if (!eq.equation_key.startsWith(prefix)) continue
        claimedKeys.add(eq.equation_key)
        if (!equationIsRenderable(eq)) continue
        children.push(eq)
      }
      const primary = pickPrimary(children)
      // Iteration status rolls up from children, with the wrapper's own
      // failure state as the fallback (callback-build-time failures land on
      // the wrapper itself with no child to inherit from).
      let status = w.status
      if (children.some((c) => c.status === 'failed')) status = 'failed'
      else if (children.some((c) => c.status === 'computing')) status = 'computing'
      else if (children.every((c) => c.status === 'completed' || c.status === 'skipped') && children.length > 0) status = 'completed'
      else if (children.some((c) => c.status === 'awaiting_input')) status = 'awaiting_input'

      const hasHitl = children.some((c) => c.equation_type === 'hitl')
      const isActionableItem = children.some(
        (c) => c.equation_type === 'hitl' && c.status !== 'completed' && isActionable(c),
      )
      const blockReason = classifyIterationBlock(status, w, children, allEquationsByKey, blockMemo)

      iterations.push({
        wrapperKey: w.equation_key,
        iterKey: iterKeyFromWrapper(w.equation_key),
        wrapper: w,
        equations: children,
        primary,
        status,
        hasMedia: !!(primary?.result_media_ids && primary.result_media_ids.length > 0),
        hasHitl,
        hasError: status === 'failed',
        isActionable: isActionableItem,
        isQueued: blockReason === 'cap',
        blockReason,
      })
    }
    iterationsByGroup.set(groupKey, iterations)
  }

  // Render order: walk phaseEquations in their original order. When we hit
  // an equation that belongs to a group we haven't emitted yet, emit the
  // group in place of all its member equations and mark the group as done.
  const emittedGroups = new Set<string>()
  const out: StepItem[] = []
  for (const eq of phaseEquations) {
    if (claimedKeys.has(eq.equation_key)) {
      // Figure out which group this equation belongs to. For iteration
      // wrappers and children, that's the wrapper's foreach key. For the
      // foreach primitive itself, it's its own key.
      let groupKey: string | null = null
      if (isForeachPrimitive(eq)) groupKey = eq.equation_key
      else if (isIterationWrapper(eq)) groupKey = groupKeyOfWrapper(eq.equation_key)
      else {
        // A child equation — walk up its key to find an ancestor that is a
        // known group.
        let k = eq.equation_key
        while (k.length > 0) {
          const slash = k.lastIndexOf('/')
          if (slash < 0) break
          k = k.slice(0, slash)
          if (iterationsByGroup.has(k)) { groupKey = k; break }
        }
      }
      if (groupKey && !emittedGroups.has(groupKey)) {
        emittedGroups.add(groupKey)
        const iterations = iterationsByGroup.get(groupKey) || []
        // Look up the hitl.approve primitive globally — after a phase
        // rename, the primitive may have moved phases while existing
        // slot wrappers retain the old phase_path. The slot wrapper's
        // group key always points to the primitive, regardless of
        // whether they share a phase. Falls back to the phase-scoped
        // map for fast path.
        let fs = approveByKey.get(groupKey) || null
        if (!fs) {
          const candidate = allEquationsByKey.get(groupKey)
          if (candidate && isApprovePrimitive(candidate)) fs = candidate
        }
        if (fs) {
          // hitl.approve flattens into multiple top-level rows (one per
          // sub-step). No "Fill Slots" wrapper item — the primitive is
          // purely runtime; the UI presents its body as flat steps.
          for (const item of buildSlotGroupItems(fs, iterations, allEquationsByKey, blockMemo)) out.push(item)
        } else {
          const item = buildGroupItem(groupKey, foreachByKey.get(groupKey) || null, iterations)
          if (item) out.push(item)
        }
      }
      continue
    }
    if (!equationIsRenderable(eq)) continue
    out.push({ kind: 'equation', eq })
  }

  // Catch groups whose member equations didn't appear in phaseEquations
  // (e.g. foreach primitive lives in the phase but iteration wrappers get
  // assigned to a different phase — shouldn't happen today but cheap to
  // defend against). Preserves the render without duplicating.
  for (const [groupKey, iterations] of iterationsByGroup) {
    if (emittedGroups.has(groupKey)) continue
    let fs = approveByKey.get(groupKey) || null
    if (!fs) {
      const candidate = allEquationsByKey.get(groupKey)
      if (candidate && isApprovePrimitive(candidate)) fs = candidate
    }
    if (fs) {
      for (const item of buildSlotGroupItems(fs, iterations, allEquationsByKey, blockMemo)) out.push(item)
    } else {
      const item = buildGroupItem(groupKey, foreachByKey.get(groupKey) || null, iterations)
      if (item) out.push(item)
    }
  }

  return out
}

// Flatten a hitl.approve wrapper into one IterationGroupItem per
// equation-position within the slot body. This treats hitl.approve
// identically to a foreach whose iterations have a uniform body shape:
// each step in the body becomes its own top-level row, with N parallel
// iterations underneath. There is no hitl.approve "container" row — the
// primitive is purely a runtime concept.
//
// For the user's `tool() → hitl.approve()` flow, this produces:
//   - one row "Flux2 Klein 9B (×N)" — producer cells (default-collapsed
//     unless actionable, matching the foreach convention)
//   - one row "Approve (×N)" — HITL cells with persistent approve/replace,
//     auto-expanded + locked open while actionable (matching the HITL
//     convention)
function buildSlotGroupItems(
  approve: FlowEquation,
  slots: GroupedIteration[],
  allEquationsByKey: Map<string, FlowEquation>,
  blockMemo: Map<string, BlockReason>,
): IterationGroupItem[] {
  // Slots with no children yet are pre-expansion plumbing — the engine
  // hasn't materialized the per-slot generators. Skip until at least
  // one slot has visible body content (or has failed during expansion).
  const hasVisibleContent = slots.some(
    (s) => s.equations.length > 0 || s.wrapper.status === 'failed',
  )
  if (!hasVisibleContent) return []

  // The agent writes per-flow `instructions=` on `hitl.approve(...)`, but
  // it has no way to know the UI rolls N slots into one row. So the rollup
  // ignores the agent's text and uses canned copy that explains the
  // hitl.approve mechanic instead. (Single-cell HITL views still use the
  // agent's instructions — that surface is per-prompt context.)
  const FILL_SLOTS_APPROVE_INSTRUCTIONS =
    'Approve each — reject to regenerate that slot.'

  const subSteps = buildSubSteps(slots, allEquationsByKey, blockMemo)
  const out: IterationGroupItem[] = []

  for (const sub of subSteps) {
    // Per-sub-step group key: the sub-step's relative path scoped under
    // the hitl.approve wrapper, so two sibling hitl.approve with the same
    // sub-step paths don't collide.
    const groupKey = `${approve.equation_key}/${sub.relativePath}`

    const aggregate = {
      total: sub.iterations.length,
      completed: sub.aggregate.completed,
      failed: sub.aggregate.failed,
      computing: sub.aggregate.computing,
      pending: sub.aggregate.pending,
      actionable: sub.aggregate.actionable,
      queued: 0,
    }
    const totalDurationMs = aggregateDuration(
      sub.equations.filter((e): e is FlowEquation => e != null),
    )

    // For HITL approve sub-steps, mark each iteration's `isActionable`
    // by checking whether the equation is awaiting input. The existing
    // IterationGroup auto-expand + lock-open behavior keys off
    // aggregate.actionable, which is what we want: HITL group locks
    // open while there are pending approvals; producer group never
    // locks (no actionable iterations) so it follows the standard
    // default-collapsed-unless-failed rule.
    // For producer sub-steps, classify off the producer's own
    // equations. For HITL approve sub-steps, the approve equation
    // itself never carries media — look at the candidate producer
    // (the slot's non-HITL sibling that actually generated the value)
    // so the approve row picks the same layout as its companion
    // producer row above it.
    const classifyPrimaries: (FlowEquation | null)[] =
      sub.kind === 'hitl-approve'
        ? slots.map((slot) => candidateProducerForSlot(slot))
        : sub.equations
    out.push({
      kind: 'group',
      groupKey,
      foreach: approve,
      iterations: sub.iterations,
      aggregate,
      totalDurationMs,
      displayName: subStepDisplayName(sub, approve),
      cellMode: sub.kind === 'hitl-approve' ? 'hitl-approve' : 'tile',
      // Instructions strip lives on the HITL row only — that's where
      // the user reads them before deciding. The producer row doesn't
      // need them.
      instructions: sub.kind === 'hitl-approve' ? FILL_SLOTS_APPROVE_INSTRUCTIONS : undefined,
      // Pass the parent slots so HITL approve cells can find candidate
      // media via siblings (the auto-injected approve mirrors its asset
      // but its own result_media_ids is empty pre-completion).
      parentSlots: sub.kind === 'hitl-approve' ? slots : undefined,
      contentKind: classifyGroupContentKind(classifyPrimaries),
    })
  }

  return out
}

// Find the slot's candidate producer — the non-HITL equation whose
// output is being approved. SlotApproveCell uses this for the cell's
// thumbnail; the grouping pipeline uses it to classify the approve
// row as text- or media-shaped. Prefer the sibling with media (so a
// slot that produced an image is unambiguously media), fall back to
// any non-HITL equation so text-producing slots still resolve before
// a result lands.
export function candidateProducerForSlot(slot: GroupedIteration): FlowEquation | null {
  if (!slot?.equations || slot.equations.length === 0) return null
  const byKey = new Map(slot.equations.map((e) => [e.equation_key, e]))
  const approve = slot.equations.find(
    (e) => e.equation_type === 'hitl' && e.hitl_kind === 'approve',
  )
  if (approve) {
    for (const depKey of approve.dependencies || []) {
      const candidate = byKey.get(depKey)
      if (candidate && candidate.equation_type !== 'hitl') return candidate
    }
  }
  const withMedia = slot.equations.find(
    (e) => e.equation_type !== 'hitl'
      && e.result_media_ids
      && e.result_media_ids.length > 0,
  )
  if (withMedia) return withMedia
  return slot.equations.find((e) => e.equation_type !== 'hitl') ?? null
}

function subStepDisplayName(sub: SlotSubStep, approve: FlowEquation): string {
  // Match the HITL-elsewhere convention ("Your Turn" for actionable user
  // input). Bare "Approve" was ambiguous on a rolled-up row.
  if (sub.kind === 'hitl-approve') return 'Your Turn'
  // Producer rows surface the underlying tool/llm name when available,
  // matching the chrome of a normal foreach group row.
  if (sub.displayName && sub.displayName !== sub.relativePath) return sub.displayName
  if (sub.toolId) return sub.toolId
  return approve.display_name || sub.relativePath
}

// Transpose the slot bodies into per-step rows. Slots have keys like
// `{slot}/tool$0`, `{slot}/hitl.approve$0`. Two slots with identical body
// shapes share relative paths — `tool$0` and `hitl.approve$0` — so we
// can group their equations by relative-path-within-slot to recover the
// "step ×N parallel iterations" view the user expects.
//
// Order of sub-steps is taken from the first non-empty slot's body
// order. This is stable as long as the SDK emits equations in the same
// order across slots, which it does (the body callback is the same
// function for every slot — equations are registered in source order).
function buildSubSteps(
  slots: GroupedIteration[],
  allEquationsByKey: Map<string, FlowEquation>,
  blockMemo: Map<string, BlockReason>,
): SlotSubStep[] {
  const N = slots.length
  if (N === 0) return []

  // First pass: collect all relative paths in the order they first
  // appear (any slot suffices since body shape is identical).
  const orderedPaths: string[] = []
  const byPath = new Map<string, (FlowEquation | null)[]>()

  for (let s = 0; s < N; s++) {
    const slot = slots[s]
    const slotPrefix = slot.wrapperKey + '/'
    for (const eq of slot.equations) {
      if (!eq.equation_key.startsWith(slotPrefix)) continue
      const relPath = eq.equation_key.slice(slotPrefix.length)
      // Only direct children of the slot wrapper are sub-steps; deeper
      // descendants belong to one of those sub-steps' subgraphs and
      // shouldn't get their own row.
      if (relPath.includes('/')) continue
      let row = byPath.get(relPath)
      if (!row) {
        row = new Array(N).fill(null)
        byPath.set(relPath, row)
        orderedPaths.push(relPath)
      }
      row[s] = eq
    }
  }

  return orderedPaths.map((relPath) => {
    const equations = byPath.get(relPath)!
    // Pick a representative equation to derive display metadata. Prefer
    // the first non-null entry — across slots the type / display name
    // are the same, so any present slot works.
    const rep = equations.find((e): e is FlowEquation => e != null) ?? null
    const equationType = rep?.equation_type ?? 'unknown'
    const hitlKind = rep?.hitl_kind ?? null
    const toolId = rep?.tool_id ?? null
    const taskType = rep?.task_type ?? null
    const displayName = rep?.display_name || relPath

    let kind: SlotSubStep['kind'] = 'other'
    if (equationType === 'hitl' && hitlKind === 'approve') {
      kind = 'hitl-approve'
    } else if (
      equationType === 'tool_call'
      || equationType === 'llm_call'
      || equationType === 'code'
      || equationType === 'create_image'
      || equationType === 'create_layout'
      || equationType === 'create_grid'
      || equationType === 'create_set'
      || equationType === 'create_document'
    ) {
      kind = 'producer'
    }

    // Synthesize per-slot iteration handles. Each slot maps to exactly
    // one cell in the sub-step row, and the cell gets:
    //   - equations: just this sub-step's equation for the slot, so
    //     pickPrimary lands on the right node (no leaking the other
    //     sub-step's media into this row's tile)
    //   - the parent slot's wrapperKey so HITL cells can still find
    //     candidate media via siblings when needed
    const iterations: GroupedIteration[] = []
    for (let s = 0; s < N; s++) {
      const slot = slots[s]
      const eq = equations[s]
      const subEqs = eq ? [eq] : []
      const status = eq?.status ?? 'pending'
      // Sub-step cells are per-equation; classify the equation directly
      // rather than going through the slot wrapper so a tool$0 cell
      // downstream of a HITL gets 'human' rather than the slot's
      // wrapper-level reason.
      const blockReason = eq && status === 'pending'
        ? classifyEquationBlock(eq, allEquationsByKey, blockMemo)
        : null
      iterations.push({
        wrapperKey: slot.wrapperKey,
        iterKey: slot.iterKey,
        wrapper: slot.wrapper,
        equations: subEqs,
        primary: eq,
        status,
        hasMedia: !!(eq?.result_media_ids && eq.result_media_ids.length > 0),
        hasHitl: equationType === 'hitl',
        hasError: status === 'failed',
        // Sub-step is actionable for HITL approve when the equation is
        // a HITL awaiting input. The actual task lookup happens in the
        // cell, which has access to tasksByEquationKey.
        isActionable: kind === 'hitl-approve' && status !== 'completed',
        isQueued: blockReason === 'cap',
        blockReason,
      })
    }

    const aggregate = {
      total: N,
      completed: iterations.filter((i) => i.status === 'completed').length,
      failed: iterations.filter((i) => i.status === 'failed').length,
      computing: iterations.filter((i) => i.status === 'computing').length,
      pending: iterations.filter((i) => i.status === 'pending').length,
      actionable: iterations.filter((i) => i.isActionable).length,
    }

    return {
      relativePath: relPath,
      kind,
      equationType,
      hitlKind,
      toolId,
      taskType,
      displayName,
      equations,
      iterations,
      aggregate,
    }
  })
}

function buildGroupItem(
  groupKey: string,
  foreach: FlowEquation | null,
  iterations: GroupedIteration[],
): IterationGroupItem | null {
  // A foreach whose iterations have no user-visible child equations is graph
  // plumbing, not a step. Rendering it leaks "Gather Results" rows into the
  // Steps view with empty tiles and inflates phase progress counts.
  const hasVisibleIterationContent = iterations.some((i) =>
    i.equations.length > 0 || i.wrapper.status === 'failed',
  )
  if (!hasVisibleIterationContent) return null

  const aggregate = {
    total: iterations.length,
    completed: iterations.filter((i) => i.status === 'completed').length,
    failed: iterations.filter((i) => i.status === 'failed').length,
    computing: iterations.filter((i) => i.status === 'computing').length,
    pending: iterations.filter((i) => i.status === 'pending').length,
    actionable: iterations.filter((i) => i.isActionable).length,
    queued: iterations.filter((i) => i.isQueued).length,
  }
  const totalDurationMs = aggregateDuration(iterations.flatMap((i) => i.equations))
  return {
    kind: 'group',
    groupKey,
    foreach,
    iterations,
    aggregate,
    totalDurationMs,
    displayName: groupDisplayName(foreach, iterations),
    contentKind: classifyGroupContentKind(iterations.map((i) => i.primary)),
  }
}

// Decide whether a group of iterations renders as media tiles or text
// rows. The signal we trust most is "did anything actually produce
// media?" — once any sibling has populated `result_media_ids`, the row
// is media-shaped; otherwise we lean on equation-type hints (llm_call
// always produces a value, never media) so in-flight rows pick the
// right layout before any iteration completes.
export function classifyGroupContentKind(
  primaries: (FlowEquation | null)[],
): 'media' | 'text' {
  for (const p of primaries) {
    if (p?.result_media_ids && p.result_media_ids.length > 0) return 'media'
  }
  // No media observed yet. If every iteration's primary is an LLM
  // call, treat as text — the result will be JSON / a string. Mixed /
  // tool / code groups default to media so an empty grid of
  // placeholder tiles still reads as "image work in progress" rather
  // than flipping layouts mid-run.
  const types = new Set<string>()
  for (const p of primaries) if (p) types.add(p.equation_type)
  if (types.size === 1 && types.has('llm_call')) return 'text'
  // A foreach over `code()` ops with completed iterations and no media
  // is text-shaped (code returning a value). Only flip once the
  // iterations have actually finished — otherwise the placeholder
  // grid is fine.
  const allCodeAndDone = primaries.length > 0 && primaries.every(
    (p) => p?.equation_type === 'code' && p?.status === 'completed',
  )
  if (allCodeAndDone) return 'text'
  return 'media'
}
