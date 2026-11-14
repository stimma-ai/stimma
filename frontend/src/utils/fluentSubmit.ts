// Tool View's prompt feature (PROMPT_BRAND): the decisions a run makes about how its
// prompt is sent. Pure, so the matrix is testable without mounting Tool View.

import type { ProgramStatus } from '../composables/usePromptProgram'
import { isInsufficientBalanceCode, isLlmSetupCode } from './llmErrorCodes.ts'
import { imageParts, type ImageWorld } from './fromImage.ts'

/** How the prompt is read for this run. With no chat model, everything but Raw is Direct:
    lists, saved wildcards and segments fill, brackets unwrap, # lines drop, no model.
    Direct with a chat model is improved at the Detail level, as Fluent is. */
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
  /** Direct can improve this tool's prompt (directImproves): it describes a picture or a
      clip, not an edit, a sound or a structured format. */
  directImproves?: boolean
  /** Fields the per-image enhancer reads (model, isVideo, mode, …). */
  enhance: Record<string, any>
  /** What the prepared program carries, or undefined when no program runs. */
  program: any
}

/** The prompt menu's LoRA choices as Fluent sends them: on unless switched off. */
export function loraChoices(saved: any): { loraTriggers: boolean; loraNotes: boolean } {
  return { loraTriggers: saved?.loraTriggers !== false, loraNotes: saved?.loraNotes !== false }
}

/** What the editor asks /prompt-programs/prepare with. A program depends on the prompt and
    the tool, never on the model's settings, the LoRAs or the canvas. */
export interface PrepareInputs {
  toolId: string | null
  prompt: string
  projectId: number | null | undefined
}

/** The body of a prepare (and options, pools, preview) request. */
export function prepareBody(i: PrepareInputs, extra: Record<string, any> = {}): Record<string, any> {
  return {
    tool_id: i.toolId,
    prompt: i.prompt || '',
    project_id: i.projectId ?? null,
    ...extra,
  }
}

/** Everything but the prompt text that decides the program: a change means preparing again. */
export function prepareSettingsSig(i: PrepareInputs): string {
  return JSON.stringify({ tool: i.toolId })
}

/** Whether the prompt in the box still has to be sent for reading: it is stale, or a look-up
    (which never starts reading) answered with something still to read and nothing reading it,
    and this prompt's read hasn't been started: slots not read yet, or readings kept from before
    an edit that the server has yet to check. */
export function readPending(status: ProgramStatus, program: { reading?: boolean; working?: boolean } | null | undefined,
  started: boolean): boolean {
  if (status === 'stale') return true
  return status === 'ready' && !!program?.reading && !program?.working && !started
}

/** The key of the prepared program the editor shows, when it was prepared under the settings
    in effect now: a prepare of an edited prompt sends it, so the slots the edit kept keep their
    readings (and stay ready) while the server checks the edit. */
export function shownKey(program: { key?: string | null } | null | undefined, preparedSig: string | null,
  settingsSig: string): string | null {
  if (!program?.key || !preparedSig) return null
  try {
    return JSON.parse(preparedSig)?.settings === settingsSig ? program.key : null
  } catch {
    return null
  }
}

/** The promptOptions a submit sends, from the ones saved on the tool. */
export function shapePromptOptions(saved: any, c: PromptOptionsContext): any {
  if (!saved) return saved
  // Without the feature, settings a newer build saved (Raw, Direct, the LoRA choices)
  // don't apply: the prompt goes the classic way.
  const base = !c.fluentOn
    ? (({ raw: _r, direct: _d, loraTriggers: _t, loraNotes: _n, ...rest }) => rest)(saved)
    // The LoRA choices go explicitly; the backend only adds trigger words when asked to.
    : { ...saved, ...loraChoices(saved) }
  if (base.raw) {
    return { ...base, raw: true, autoImprove: { ...base.autoImprove, enabled: false }, translate: { ...base.translate, enabled: false } }
  }
  const way = c.fluentOn ? effectiveWay({ raw: false, direct: !!base.direct, llmUnconfigured: c.llmUnconfigured }) : null
  // Tools with no prompt input have nothing to enhance or translate: stale UI state from
  // another tool never reaches them. Classic builds send an enabled Enhance even with no
  // chat model, so it fails visibly; with the feature on, no chat model means Direct, with
  // nothing improved. Direct with a chat model is improved at the Detail level where the
  // prompt describes a picture.
  let enhanceOn = c.toolHasPrompt && !!base.autoImprove?.enabled
    && (way !== 'direct' || (!c.llmUnconfigured && !!c.directImproves))
  // A tool that can't be prepared hides Detail level and says it writes a fuller prompt.
  if (way === 'fluent' && c.unsupported && c.toolHasPrompt) enhanceOn = true
  return {
    ...base,
    autoImprove: { ...base.autoImprove, enabled: enhanceOn, ...c.enhance },
    translate: { ...base.translate, enabled: c.toolHasPrompt && !c.llmUnconfigured && !!base.translate?.enabled },
    program: way === 'direct' ? undefined : c.program,
  }
}

/** Whether Direct improves this tool's prompt: one that describes a picture or a clip.
    An edit instruction, a sound and a structured format (Ideogram JSON, MiniMax H3) go as
    filled. Mirrors the backend's program_supported (routes/generation.py). */
export function directImproves(t: { ideogram: boolean; h3: boolean; audio: boolean; inputImageCount: number }): boolean {
  return !t.ideogram && !t.h3 && !t.audio && t.inputImageCount === 0
}

/** A run's tile in the strip, from the click until its job is queued: while the prompt is
    read, then while this image's details are drawn and checked to fit together. */
export const PREPARING_LABEL = 'Preparing your prompt…'
export const DRAWING_LABEL = 'Choosing details…'

/** What a Generate-forever slot does while the prompt isn't prepared. */
export type ForeverSlot =
  /** Run the last prepared prompt (and maybe start preparing the new one). */
  | { kind: 'previous'; prompt: string; prepare: boolean }
  /** Reading this prompt failed: run it anyway, on its words as written, while the server
      tries again in the background. Never the old prompt: it isn't what's in the box. */
  | { kind: 'words' }
  /** Prepare first, like Generate. */
  | { kind: 'prepare' }
  /** Nothing to wait for. */
  | { kind: 'ready' }

export function foreverSlot(o: { needsPrepare: boolean; status: ProgramStatus; readyPrompt: string | null; editing: boolean }): ForeverSlot {
  if (!o.needsPrepare) return { kind: 'ready' }
  if (o.status === 'error') return { kind: 'words' }
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

/** The codes a prompt that couldn't be read comes back with, from /prompt-programs/prepare
    or a submit that prepared itself: no chat model, or one that didn't answer; a slot
    reading it got wrong (`reader_failed`, HTTP 424); a prompt too long to read; a run that
    waited too long for its reading. */
const PREPARE_CODES = new Set(['llm_not_configured', 'llm_unavailable', 'reader_failed', 'prepare_timeout', 'program_failed', 'prompt_too_long'])
export function isPrepareFailureCode(code: string | null | undefined): boolean {
  return !!code && (PREPARE_CODES.has(code) || isInsufficientBalanceCode(code) || isLlmSetupCode(code))
}

/** What the prompt's status place says while this prompt runs on its words as written,
    by cause: something the user can fix says that, with its one action. Never "nothing ran":
    the run goes ahead. */
export interface FallbackNotice { head: string; body?: string; action: 'retry' | 'settings' | 'none' }

export const WORDS_AS_WRITTEN = 'Using your words as written for now'

export function fallbackNotice(code: string | null | undefined, brand: string): FallbackNotice {
  if (code === 'llm_not_configured' || isLlmSetupCode(code)) return { head: `${brand} needs a chat model`, body: 'Using your words as written.', action: 'settings' }
  if (isInsufficientBalanceCode(code)) return { head: 'Your chat model has no balance left', body: 'Using your words as written for now.', action: 'settings' }
  if (code === 'prompt_too_long') return { head: 'This prompt is too long to read', body: 'Using your words as written. Shorten it for variety.', action: 'none' }
  if (code === 'llm_unavailable') return { head: 'Can’t reach your chat model', body: 'Using your words as written for now.', action: 'retry' }
  return { head: WORDS_AS_WRITTEN, action: 'retry' }
}

/** What an earlier image's draws may still do here. */
export interface RunActions {
  /** "Same draws, new seed": only against the program the image was made from. */
  replay: boolean
  /** Why replay isn't offered, when it isn't. */
  reason?: string
  /** "Use" (from an image): the image was made from slots, and some of what it drew is still
      a part of the prompt. */
  use: boolean
}

export function programRunActions(
  run: any,
  current: { key: string | null; status: ProgramStatus; world: ImageWorld | null },
): RunActions {
  const use = current.status === 'ready' && !!current.world && imageParts(run, current.world).some(p => p.here)
  if (current.status === 'off') return { replay: false, reason: 'Not available with your current prompt settings.', use }
  // Made while the prompt couldn't be read: from the words as written there are no draws to
  // repeat; from the same words' earlier settings, only its picks that still apply.
  if (run?.fallback?.rung === 'words') return { replay: false, reason: 'Made from your words as written.', use }
  if (run?.fallback?.rung === 'previous') return { replay: false, reason: 'Made with this prompt’s earlier settings.', use }
  if (!run?.key || current.status !== 'ready' || run.key !== current.key) {
    return { replay: false, reason: 'Your prompt has changed since this image was made.', use }
  }
  return { replay: true, use }
}
