/**
 * Post-processing chain data model.
 *
 * A chain is a linear, ordered list of media→media steps attached to a tool/
 * preset that runs automatically after a base generation. It is "just more
 * tool state": it rides toolState.postProcessingChain, presets, and each
 * generated image's lineage (parameters.post_processing_chain — only the
 * steps that ran).
 */

export type ChainStepKind = 'tool' | 'filter'

export interface ChainStep {
  /** Stable per-instance id for drag/reorder and agent addressing. */
  id: string
  kind: ChainStepKind
  /** Disabled steps are kept in the chain and skipped on run. */
  enabled: boolean
  // kind: "tool"
  tool_id?: string
  task_type?: string
  /** Display name snapshot so the card renders even if the tool is offline. */
  tool_name?: string
  // kind: "filter"
  filter_id?: string
  /** Param values; for tool steps these overlay the tool's schema defaults. */
  settings: Record<string, any>
}

export interface PostProcessingChain {
  /** The header On/Off toggle — gates auto-run after generation. */
  enabled: boolean
  steps: ChainStep[]
}

/**
 * The shape recorded in lineage (generation_metadata.parameters.
 * post_processing_chain): only the steps that ran, no per-instance ids,
 * no enabled flags (everything recorded ran).
 */
export interface RecordedChainStep {
  kind: ChainStepKind
  tool_id?: string
  task_type?: string
  tool_name?: string
  filter_id?: string
  settings: Record<string, any>
}

export function emptyChain(): PostProcessingChain {
  return { enabled: false, steps: [] }
}

export function normalizeChain(value: any): PostProcessingChain {
  if (!value || typeof value !== 'object') return emptyChain()
  const steps = Array.isArray(value.steps) ? value.steps : []
  return {
    enabled: value.enabled === true,
    steps: steps
      .filter((s: any) => s && (s.kind === 'tool' ? s.tool_id : s.filter_id))
      .map((s: any) => ({
        id: s.id || newStepId(),
        kind: s.kind === 'filter' ? 'filter' : 'tool',
        enabled: s.enabled !== false,
        tool_id: s.tool_id,
        task_type: s.task_type,
        tool_name: s.tool_name,
        filter_id: s.filter_id,
        settings: s.settings && typeof s.settings === 'object' ? { ...s.settings } : {},
      })),
  }
}

export function newStepId(): string {
  return `step-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`
}

/** Match key for remix merging — per-instance ids don't survive sessions. */
export function stepMatchKey(step: { kind: ChainStepKind; tool_id?: string; filter_id?: string }): string {
  return `${step.kind}:${step.kind === 'tool' ? step.tool_id : step.filter_id}`
}

/** Enabled steps in run order, in the lineage record shape. */
export function toRecordedSteps(chain: PostProcessingChain): RecordedChainStep[] {
  return chain.steps
    .filter(s => s.enabled)
    .map(s => {
      const rec: RecordedChainStep = { kind: s.kind, settings: { ...s.settings } }
      if (s.kind === 'tool') {
        rec.tool_id = s.tool_id
        rec.task_type = s.task_type
        rec.tool_name = s.tool_name
      } else {
        rec.filter_id = s.filter_id
      }
      return rec
    })
}

/**
 * Remix restore — LoRA-style non-destructive merge of a recorded chain into
 * the on-screen chain:
 * - each recorded step enables + reconfigures its on-screen match (by
 *   kind + tool_id/filter_id; duplicates match greedily by position), or is
 *   added if missing;
 * - on-screen steps not in the recorded set are disabled (kept, not removed);
 * - active steps are reordered to the recorded order; disabled extras keep
 *   their relative placement.
 */
export function mergeRecordedChain(
  current: PostProcessingChain,
  recorded: RecordedChainStep[],
): PostProcessingChain {
  const remaining = current.steps.map(s => ({ step: s, used: false }))

  const active: ChainStep[] = recorded.map(rec => {
    const key = stepMatchKey(rec)
    const match = remaining.find(r => !r.used && stepMatchKey(r.step) === key)
    if (match) {
      match.used = true
      return {
        ...match.step,
        enabled: true,
        settings: { ...rec.settings },
        ...(rec.kind === 'tool'
          ? { task_type: rec.task_type ?? match.step.task_type, tool_name: rec.tool_name ?? match.step.tool_name }
          : {}),
      }
    }
    return {
      id: newStepId(),
      kind: rec.kind,
      enabled: true,
      tool_id: rec.tool_id,
      task_type: rec.task_type,
      tool_name: rec.tool_name,
      filter_id: rec.filter_id,
      settings: { ...rec.settings },
    }
  })

  const extras: ChainStep[] = remaining
    .filter(r => !r.used)
    .map(r => ({ ...r.step, enabled: false }))

  return {
    enabled: recorded.length > 0 ? true : current.enabled,
    steps: [...active, ...extras],
  }
}

/** Task types an STP tool step may have (image→image family + video transitions). */
export const CHAIN_TOOL_TASK_TYPES = [
  'filter',
  'image-to-image',
  'upscale-image',
  'image-to-video',
  'upscale-video',
] as const

/** Steps that take an image and emit an image. */
const IMAGE_IN_IMAGE_OUT = new Set(['filter', 'image-to-image', 'upscale-image'])

export function stepInputMedia(taskType: string | undefined, kind: ChainStepKind): 'image' | 'video' {
  if (kind === 'filter') return 'image'
  return taskType === 'upscale-video' ? 'video' : 'image'
}

export function stepOutputMedia(taskType: string | undefined, kind: ChainStepKind): 'image' | 'video' {
  if (kind === 'filter') return 'image'
  if (taskType && IMAGE_IN_IMAGE_OUT.has(taskType)) return 'image'
  return taskType === 'image-to-video' || taskType === 'upscale-video' ? 'video' : 'image'
}

/**
 * Walk the enabled chain and compute the running media type entering each
 * step (by step id), plus the ids of enabled steps whose input type doesn't
 * match. Used by both the Add menu (filter offerings) and the cards (flag
 * incompatible steps); the executor enforces the same rule server-side.
 */
export function chainMediaFlow(chain: PostProcessingChain): {
  inputTypeByStepId: Record<string, 'image' | 'video'>
  incompatibleStepIds: Set<string>
  finalType: 'image' | 'video'
} {
  let running: 'image' | 'video' = 'image'
  const inputTypeByStepId: Record<string, 'image' | 'video'> = {}
  const incompatibleStepIds = new Set<string>()
  for (const step of chain.steps) {
    inputTypeByStepId[step.id] = running
    if (!step.enabled) continue
    if (stepInputMedia(step.task_type, step.kind) !== running) {
      incompatibleStepIds.add(step.id)
      continue // an incompatible step is skipped; running type unchanged
    }
    running = stepOutputMedia(step.task_type, step.kind)
  }
  return { inputTypeByStepId, incompatibleStepIds, finalType: running }
}
