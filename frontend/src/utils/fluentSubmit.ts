// Tool View's prompt feature (PROMPT_BRAND): the decisions a run makes about how its
// prompt is sent. Pure, so the matrix is testable without mounting Tool View.

import type { ProgramStatus } from '../composables/usePromptProgram'

/** How the prompt is read for this run. With no chat model, everything but Raw is Direct:
    lists, saved wildcards and segments fill, brackets unwrap, # lines drop, no model. */
export type PromptWay = 'fluent' | 'direct' | 'raw'

export function effectiveWay(o: { raw: boolean; direct: boolean; llmUnconfigured: boolean }): PromptWay {
  if (o.raw) return 'raw'
  if (o.direct || o.llmUnconfigured) return 'direct'
  return 'fluent'
}

export interface PromptOptionsContext {
  /** The feature ships in this build (promptBrand.ts). Off: the classic pipeline. */
  fluentOn: boolean
  /** No chat model at all: the run is Direct whatever is saved. */
  llmUnconfigured: boolean
  toolHasPrompt: boolean
  /** The tool's prompt format can't be prepared (Ideogram JSON, MiniMax H3): the prompt
      is written fuller per image instead, which is what the menu promises there. */
  unsupported: boolean
  /** Fields the per-image enhancer reads (model, isVideo, mode, …). */
  enhance: Record<string, any>
  /** What the prepared program carries, or undefined when no program runs. */
  program: any
}

/** The promptOptions a submit sends, from the ones saved on the tool. */
export function shapePromptOptions(saved: any, c: PromptOptionsContext): any {
  if (!saved) return saved
  // Without the feature, settings a newer build saved (Raw, Direct, the LoRA choices)
  // don't apply: the prompt goes the classic way.
  const base = !c.fluentOn
    ? (({ raw: _r, direct: _d, loraTriggers: _t, loraNotes: _n, ...rest }) => rest)(saved)
    // The LoRA choices go explicitly; the backend only adds trigger words when asked to.
    : { ...saved, loraTriggers: saved.loraTriggers !== false, loraNotes: saved.loraNotes !== false }
  if (base.raw) {
    return { ...base, raw: true, autoImprove: { ...base.autoImprove, enabled: false }, translate: { ...base.translate, enabled: false } }
  }
  const way = c.fluentOn ? effectiveWay({ raw: false, direct: !!base.direct, llmUnconfigured: c.llmUnconfigured }) : null
  // Tools with no prompt input have nothing to enhance or translate: stale UI state from
  // another tool never reaches them. Classic builds send an enabled Enhance even with no
  // chat model, so it fails visibly; with the feature on, no chat model means Direct.
  let enhanceOn = c.toolHasPrompt && !!base.autoImprove?.enabled && way !== 'direct'
  // A tool that can't be prepared hides Detail level and says it writes a fuller prompt.
  if (way === 'fluent' && c.unsupported && c.toolHasPrompt) enhanceOn = true
  return {
    ...base,
    autoImprove: { ...base.autoImprove, enabled: enhanceOn, ...c.enhance },
    translate: { ...base.translate, enabled: c.toolHasPrompt && !c.llmUnconfigured && !!base.translate?.enabled },
    program: way === 'direct' ? undefined : c.program,
  }
}

/** What a Generate-forever slot does while the prompt isn't prepared. */
export type ForeverSlot =
  /** Run the last prepared prompt (and maybe start preparing the new one). */
  | { kind: 'previous'; prompt: string; prepare: boolean }
  /** Reading the prompt failed: stop, with the reason. Never keep running an old prompt. */
  | { kind: 'failed' }
  /** Prepare first, like Generate. */
  | { kind: 'prepare' }
  /** Nothing to wait for. */
  | { kind: 'ready' }

export function foreverSlot(o: { needsPrepare: boolean; status: ProgramStatus; readyPrompt: string | null; editing: boolean }): ForeverSlot {
  if (!o.needsPrepare) return { kind: 'ready' }
  if (o.status === 'error') return { kind: 'failed' }
  if (o.readyPrompt) return { kind: 'previous', prompt: o.readyPrompt, prepare: !o.editing && o.status === 'stale' }
  return { kind: 'prepare' }
}

/** The code a failed prepare request carries. Only no response at all (timeout,
    network) means the chat model couldn't be reached; a server error is just a failure. */
export function prepareErrorCode(e: any): string | undefined {
  const detail = e?.response?.data?.detail
  if (detail && typeof detail === 'object' && detail.code) return detail.code
  return e?.response ? undefined : 'llm_unavailable'
}

/** Plain words by cause, for a run that couldn't read its prompt. */
export function prepareFailure(code: string | undefined, brand: string): { message: string; action: 'settings' | 'retry' } {
  if (code === 'llm_not_configured') return { message: `${brand} needs a chat model, so nothing ran.`, action: 'settings' }
  const message = code === 'llm_unavailable'
    ? 'Can’t reach your chat model, so nothing ran.'
    : code === 'prepare_timeout'
      ? 'Your chat model took too long to read this prompt, so nothing ran.'
      : `${brand} couldn’t read this prompt, so nothing ran.`
  return { message, action: 'retry' }
}

/** What Generation details may offer for an earlier image's draws. */
export interface RunActions {
  /** "Same draws, new seed": only against the program the image was made from. */
  replay: boolean
  /** Why replay isn't offered, when it isn't. */
  reason?: string
  /** "Use these choices": the image's picks that the current prompt still offers. */
  pins: Record<string, string[]>
}

export function programRunActions(
  run: any,
  current: { key: string | null; status: ProgramStatus; optionsOf: (id: string) => string[] | null },
): RunActions {
  const pins: Record<string, string[]> = {}
  for (const d of run?.draws || []) {
    if (d.kind === 'param' || d.hidden) continue
    const value = String(d.value)
    if (current.optionsOf(d.id)?.includes(value)) pins[d.id] = [value]
  }
  if (current.status === 'off') return { replay: false, reason: 'Not available with your current prompt settings.', pins }
  if (!run?.key || current.status !== 'ready' || run.key !== current.key) {
    return { replay: false, reason: 'Your prompt has changed since this image was made.', pins }
  }
  return { replay: true, pins }
}

/** The input images one job's prompt is read with. In batch mode each job carries one of
    the batched images (plus any fixed reference images), so the prompt is read for that. */
export function jobContextImages<T>(o: { inputImages: T[]; refImages: T[]; batchMode: boolean; batchField?: string | null }): T[] {
  const batched = o.batchMode && (o.batchField || 'input_images') === 'input_images'
  return [...(batched ? o.inputImages.slice(0, 1) : o.inputImages), ...o.refImages]
}
