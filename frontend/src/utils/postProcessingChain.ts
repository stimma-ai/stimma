/**
 * Post-processing chain data model.
 *
 * A chain is a linear, ordered list of media→media steps attached to a tool/
 * preset that runs automatically after a base generation. It is "just more
 * tool state": it rides toolState.postProcessingChain, presets, and each
 * generated image's lineage (parameters.post_processing_chain — only the
 * steps that ran).
 */

import { getChainFilterAccepts } from '@stimma/image-editor'
import { DEFAULT_PROMPT_OPTIONS, type PromptOptions } from '../composables/useGenerationPreferences'

export type ChainStepKind = 'tool' | 'filter'

/** Enhance/Translate toggles for a step's prompt — same raw shape
 *  AIPromptEditor emits (the shared PromptOptions). */
export type ChainStepPromptOptions = PromptOptions

/**
 * The prompt options a tool step starts with — ToolView's own new-state
 * defaults (Enhance ON), so a chain-step prompt behaves exactly like one
 * typed in the editor. Tool steps ALWAYS carry promptOptions; this is
 * enforced wherever steps enter the model (add / normalize / remix-merge).
 */
export function defaultChainStepPromptOptions(): ChainStepPromptOptions {
  return clonePromptOptions(DEFAULT_PROMPT_OPTIONS)
}

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
  /** Enhance/Translate toggles for this step's prompt (tool steps only).
      Kept OUT of `settings` — settings is sent verbatim as STP params. */
  promptOptions?: ChainStepPromptOptions
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
  promptOptions?: ChainStepPromptOptions
}

function clonePromptOptions(po: ChainStepPromptOptions): ChainStepPromptOptions {
  return {
    autoImprove: { ...po.autoImprove },
    varyPrompt: { ...po.varyPrompt },
    ...(po.translate ? { translate: { ...po.translate } } : {}),
  }
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
        // Tool steps always carry promptOptions (missing = pre-feature state,
        // which gets ToolView's defaults, Enhance ON — not "everything off").
        ...(s.kind !== 'filter'
          ? {
              promptOptions: s.promptOptions && typeof s.promptOptions === 'object'
                ? clonePromptOptions(s.promptOptions)
                : defaultChainStepPromptOptions(),
            }
          : {}),
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
        if (s.promptOptions) rec.promptOptions = clonePromptOptions(s.promptOptions)
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
        // Pre-feature lineage has no promptOptions — restore to the defaults,
        // same as normalizeChain (tool steps always carry promptOptions).
        promptOptions: rec.promptOptions
          ? clonePromptOptions(rec.promptOptions)
          : (rec.kind === 'tool' ? defaultChainStepPromptOptions() : undefined),
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
      ...(rec.kind === 'tool'
        ? { promptOptions: rec.promptOptions ? clonePromptOptions(rec.promptOptions) : defaultChainStepPromptOptions() }
        : {}),
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
  'remove-background',
  'image-to-video',
  'video-to-video',
  'upscale-video',
] as const

/** Steps that take an image and emit an image. */
const IMAGE_IN_IMAGE_OUT = new Set(['image-to-image', 'upscale-image', 'remove-background'])

// Media a tool-step task type takes/emits. Filters are NOT special-cased here;
// they declare their accepted media (getChainFilterAccepts) and preserve the
// running type (image→image, video→video) — see stepAcceptedMedia / chainMediaFlow.
export function stepInputMedia(taskType: string | undefined, _kind: ChainStepKind = 'tool'): 'image' | 'video' {
  return taskType === 'upscale-video' || taskType === 'video-to-video' ? 'video' : 'image'
}

export function stepOutputMedia(taskType: string | undefined, _kind: ChainStepKind = 'tool'): 'image' | 'video' {
  if (taskType && IMAGE_IN_IMAGE_OUT.has(taskType)) return 'image'
  return taskType === 'image-to-video' || taskType === 'video-to-video' || taskType === 'upscale-video' ? 'video' : 'image'
}

/**
 * Media types a step accepts as input — the single notion both insertion and
 * compatibility use, for tool and filter steps alike. Filters declare theirs
 * (default both); tool steps take the one type their task implies.
 */
export function stepAcceptedMedia(
  step: { kind: ChainStepKind; task_type?: string; filter_id?: string }
): Array<'image' | 'video'> {
  if (step.kind === 'filter') return getChainFilterAccepts(step.filter_id || '')
  return [stepInputMedia(step.task_type, 'tool')]
}

/**
 * Walk the enabled chain and compute the running media type entering each
 * step (by step id), plus the ids of enabled steps whose input type doesn't
 * match. Used by both the Add menu (offerings + insertion point) and the
 * cards (flag incompatible steps); the executor enforces the same rule
 * server-side.
 *
 * `initial` is the base generation's output type (a chain on a video tool
 * starts from a video).
 */
export function chainMediaFlow(chain: PostProcessingChain, initial: 'image' | 'video' = 'image'): {
  inputTypeByStepId: Record<string, 'image' | 'video'>
  incompatibleStepIds: Set<string>
  finalType: 'image' | 'video'
  /** Running media type entering each insertion position (0..steps.length). */
  positionTypes: Array<'image' | 'video'>
} {
  let running: 'image' | 'video' = initial
  const inputTypeByStepId: Record<string, 'image' | 'video'> = {}
  const incompatibleStepIds = new Set<string>()
  const positionTypes: Array<'image' | 'video'> = []
  for (const step of chain.steps) {
    positionTypes.push(running)
    inputTypeByStepId[step.id] = running
    if (!step.enabled) continue
    // Filters declare which media they accept (default both) and preserve the
    // running type. A filter is compatible iff it accepts what's flowing —
    // same accepted-media notion tool steps use, no special media-agnostic case.
    if (step.kind === 'filter') {
      if (!stepAcceptedMedia(step).includes(running)) {
        incompatibleStepIds.add(step.id) // skipped; running type unchanged
      }
      continue // filters never change the running media type
    }
    if (!stepAcceptedMedia(step).includes(running)) {
      incompatibleStepIds.add(step.id)
      continue // an incompatible step is skipped; running type unchanged
    }
    running = stepOutputMedia(step.task_type, step.kind)
  }
  positionTypes.push(running)
  return { inputTypeByStepId, incompatibleStepIds, finalType: running, positionTypes }
}

/**
 * Where a new step taking `inputType` should be inserted: the LAST position
 * whose running media type matches. An image step added to a chain that
 * already transitions to video lands just before the video transition —
 * adding earlier-stage steps never requires removing later ones.
 * Returns -1 when no position accepts the input type.
 */
export function defaultInsertIndex(
  chain: PostProcessingChain,
  inputType: 'image' | 'video' | Array<'image' | 'video'>,
  initial: 'image' | 'video' = 'image',
): number {
  const accepts = Array.isArray(inputType) ? inputType : [inputType]
  const { positionTypes } = chainMediaFlow(chain, initial)
  for (let p = positionTypes.length - 1; p >= 0; p--) {
    if (accepts.includes(positionTypes[p])) return p
  }
  return -1
}
