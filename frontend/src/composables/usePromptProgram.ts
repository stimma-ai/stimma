import { computed, onUnmounted, ref, watch, type ComputedRef, type Ref } from 'vue'
import axios from 'axios'
import { getApiBase } from '../apiConfig'
import type { ChoiceVocab } from '../utils/programVocab'
import { shownOption } from '../utils/programVocab'
import { programSections } from '../utils/programChoiceLayout'
import { DECLINED_CODE, prepareBody, prepareErrorCode, prepareSettingsSig, type PrepareInputs } from '../utils/fluentSubmit'
import { createChoiceCard } from '../utils/choiceCard'
import { isLimited, ticksOf } from '../utils/programTicks'

export type { ChoiceVocab } from '../utils/programVocab'

/**
 * Prompt programs: in Fluent (not Direct or Raw) the prompt is prepared once into a small
 * program (the model is called once, cached on the server) and every generation runs it.
 * Detail level decides how much the program adds: Yours keeps the user's words, Medium
 * adds what the model needs, High fills in the rest. This holds
 * the prepared program for the current prompt, its status, and the user's pins and
 * edits to its choices. Pins and edits live in promptOptions, so they persist per
 * tool and ride presets like the rest of the prompt's settings.
 */

export interface ProgramChoice {
  id: string
  kind: 'pick' | 'lora' | 'param'
  label: string
  source: 'text' | 'list' | 'added'
  line?: number
  options: string[]
  hidden?: boolean
  follows?: string
  parent?: string
  when?: string[]
  group?: string
  index?: number
  attr?: string
  /** One value for every subject (the user asked for the same: matching outfits). */
  shared?: boolean
  /** The user's own {{name}} smart wildcard this choice fills. */
  wildcard?: string
  /** The vocabulary list this pick draws from; its options are the list's values. */
  cls?: string
  /** The user's own words this choice stands for ("yellow ferrari"): every image uses them
      until the user ticks other options. */
  said?: string
}

export interface ProgramGroup { id: string; count: number; label: string; source: string; line?: number }

export interface ProgramLora { name: string; path: string; weight: number; trigger: string }

export interface PreparedProgram {
  /** false: prepared at Detail level Yours or Medium (the user's words kept). Dev dialog only. */
  elaborate?: boolean
  enhance?: EnhanceLevel
  key: string
  choices: ProgramChoice[]
  groups: ProgramGroup[]
  params: Record<string, { type?: string; minimum?: number; maximum?: number }>
  loras: ProgramLora[]
  lora_choices: Record<string, string[]>
  example: string
  warnings?: string[]
  seconds?: number
  program?: string
  // Dev details the program dialog shows.
  attempts?: number
  mode?: string
  upsample_seconds?: number
}

/** POST /prompt-programs/pools. Bound picks carry the whole list (uncapped) and a `vocab` entry. */
export interface PoolsResponse {
  options: Record<string, string[]>
  more: string[]
  vocab?: Record<string, ChoiceVocab>
}

export interface ChoiceEdit { add?: string[]; remove?: string[]; off?: boolean }

export type ProgramStatus = 'off' | 'ready' | 'stale' | 'busy' | 'error'

/** Detail level, by its wire values: off is Yours (the user's words), fill is Medium (adds
    only what the model needs), expand is High (fills in the details left open). */
export type EnhanceLevel = 'off' | 'fill' | 'expand'

interface Options {
  toolId: Ref<string | null>
  prompt: Ref<string>
  enabled: ComputedRef<boolean>
  /** Detail level. */
  enhance: ComputedRef<EnhanceLevel>
  /** Tell the model the user's LoRA notes. */
  loraNotes: ComputedRef<boolean>
  /** The prompt menu's "Trigger words": tell the writer the on LoRAs' trigger words. */
  loraTriggers: ComputedRef<boolean>
  loraItems: ComputedRef<Array<{ lora: string; weight: number; enabled?: boolean }>>
  /** What the enhancer's style depends on: input images (count and ids), canvas size. */
  contextParams: ComputedRef<Record<string, any>>
  instructions: ComputedRef<string>
  projectId: Ref<number | null | undefined>
  promptOptions: Ref<any>
  setPromptOptions: (next: any) => void
}

/** How often the editor looks for a program the server prepared in the background after a failure. */
const ERROR_POLL_MS = 15_000

export function usePromptProgram(o: Options) {
  const program = ref<PreparedProgram | null>(null)
  const preparedSig = ref<string | null>(null)
  const busy = ref(false)
  const error = ref<{ sig: string; message: string; code?: string } | null>(null)
  // Formats that are still enhanced per image (MiniMax H3, Ideogram JSON) have no program.
  const unsupportedSig = ref<string | null>(null)

  const inputs = (): PrepareInputs => ({
    toolId: o.toolId.value,
    prompt: o.prompt.value || '',
    loras: o.loraItems.value,
    parameters: o.contextParams.value,
    instructions: o.instructions.value || '',
    enhance: o.enhance.value,
    loraNotes: o.loraNotes.value,
    loraTriggers: o.loraTriggers.value,
    projectId: o.projectId.value,
  })
  /** Everything but the prompt text: a prompt prepared under the same settings can still run. */
  const settingsSig = computed(() => prepareSettingsSig(inputs()))
  const signature = computed(() => JSON.stringify({ prompt: (o.prompt.value || '').trim(), settings: settingsSig.value }))
  // The last prompt that was prepared, with the settings it was prepared under. Generate
  // forever keeps running it while a newer version of the prompt is being written or prepared.
  const lastReady = ref<{ prompt: string; settings: string } | null>(null)
  function markReady(sig: string) {
    try {
      const { prompt, settings } = JSON.parse(sig)
      if (prompt) lastReady.value = { prompt, settings }
    } catch { /* not ours */ }
  }
  /** The last prepared prompt, if it still fits the current settings. */
  function readyPrompt(): string | null {
    const r = lastReady.value
    return r && r.settings === settingsSig.value ? r.prompt : null
  }

  const status = computed<ProgramStatus>(() => {
    if (!o.enabled.value || !(o.prompt.value || '').trim()) return 'off'
    if (unsupportedSig.value === signature.value) return 'off'
    if (busy.value) return 'busy'
    if (error.value && error.value.sig === signature.value) return 'error'
    return program.value && preparedSig.value === signature.value ? 'ready' : 'stale'
  })

  /** This tool's prompt format can't be prepared (Ideogram JSON, MiniMax H3): each image's
      prompt is written fuller instead, and Detail level isn't offered. */
  const unsupported = computed(() => unsupportedSig.value !== null && unsupportedSig.value === signature.value)

  const pins = computed<Record<string, string[]>>(() => o.promptOptions.value?.programPins || {})
  const edits = computed<Record<string, ChoiceEdit>>(() => o.promptOptions.value?.programEdits || {})

  function writeOptions(patch: Record<string, any>) {
    o.setPromptOptions({ ...(o.promptOptions.value || {}), ...patch })
  }
  function setPins(id: string, values: string[]) {
    const next = { ...pins.value }
    if (values.length) next[id] = values
    else delete next[id]
    writeOptions({ programPins: next })
  }
  function setManyPins(values: Record<string, string[]>) {
    writeOptions({ programPins: { ...pins.value, ...values } })
  }
  function setEdit(id: string, edit: ChoiceEdit) {
    const next = { ...edits.value }
    const clean: ChoiceEdit = {}
    if (edit.add?.length) clean.add = edit.add
    if (edit.remove?.length) clean.remove = edit.remove
    if (edit.off) clean.off = true
    if (Object.keys(clean).length) next[id] = clean
    else delete next[id]
    writeOptions({ programEdits: next })
  }

  function request(extra: Record<string, any> = {}) {
    return prepareBody(inputs(), extra)
  }

  let lookupId = 0
  /** The server no longer has the program we showed as prepared (its cache was
      cleared or reset): drop it so the next run prepares. */
  function forget(sig: string) {
    if (preparedSig.value !== sig) return
    program.value = null
    preparedSig.value = null
  }
  /** Load the prepared program for the current inputs if the server has one. Never calls a model. */
  async function lookup() {
    if (status.value === 'off' || busy.value) return
    const sig = signature.value
    const id = ++lookupId
    try {
      const { data } = await axios.post(`${getApiBase()}/prompt-programs/prepare`, request({ cache_only: true }))
      if (id !== lookupId || sig !== signature.value) return
      if (data?.unsupported) { unsupportedSig.value = sig; return }
      if (!data?.key) { forget(sig); return }
      program.value = data
      preparedSig.value = sig
      if (error.value?.sig === sig) error.value = null  // prepared since (the server's background try)
      markReady(sig)
    } catch (e: any) {
      // Not prepared yet: the next run prepares. Unless the chat model declined this prompt
      // (the server's background try may have met that since we last heard): then say so.
      if (id !== lookupId || sig !== signature.value || prepareErrorCode(e) !== DECLINED_CODE) return
      forget(sig)
      error.value = { sig, code: DECLINED_CODE, message: e?.response?.data?.detail?.message || 'Couldn’t read this prompt.' }
    }
  }

  // The prepare in flight, so concurrent runs wait on it instead of starting another.
  let inFlight: { sig: string; force: boolean; done: Promise<boolean> } | null = null
  // At most one more, for the newest prompt: a prompt that changes again while one is
  // being prepared waits its turn rather than piling another model call on top.
  let queued: { done: Promise<boolean> } | null = null

  /** Prepare for the current inputs (the model call happens here, if needed). */
  function prepare(force = false): Promise<boolean> {
    const sig = signature.value
    if (inFlight && inFlight.sig === sig && (inFlight.force || !force)) return inFlight.done
    if (inFlight) {
      if (!queued) {
        const done = inFlight.done.catch(() => false).then(() => { queued = null; return prepare(force) })
        queued = { done }
      }
      return queued.done
    }
    const done = prepareNow(sig, force).finally(() => { if (inFlight?.done === done) inFlight = null })
    inFlight = { sig, force, done }
    return done
  }

  async function prepareNow(sig: string, force: boolean): Promise<boolean> {
    busy.value = true
    try {
      // The program shown now is what this prompt edits: its writer session continues from it.
      const { data } = await axios.post(`${getApiBase()}/prompt-programs/prepare`,
        request({ force, base_key: force ? null : program.value?.key ?? null }))
      if (data?.unsupported) {
        unsupportedSig.value = sig
        return true
      }
      markReady(sig)  // runnable now, whatever the box says by the time it's back
      if (sig !== signature.value) return true  // the prompt moved on; its own prepare will follow
      program.value = data
      preparedSig.value = sig
      error.value = null
      return true
    } catch (e: any) {
      const detail = e?.response?.data?.detail
      const code = prepareErrorCode(e)
      error.value = { sig, code, message: (typeof detail === 'string' ? detail : detail?.message) || 'Couldn’t read this prompt.' }
      return false
    } finally {
      if (!inFlight || inFlight.sig === sig) busy.value = false
    }
  }

  /** New ideas: read the prompt again from scratch. What the user ticked or added
      survives: anything the new set lacks comes back as their own option. */
  async function rethink(): Promise<boolean> {
    const keep = choices.value.map(c => ({ id: c.id, values: [...(edits.value[c.id]?.add || []), ...(pins.value[c.id] || [])] }))
    if (!(await prepare(true))) return false
    for (const k of keep) {
      const c = byId.value[k.id]
      if (!c) continue
      const have = new Set(optionsOf(c))
      const missing = [...new Set(k.values)].filter(v => !have.has(v))
      if (!missing.length) continue
      const e = edits.value[c.id] || {}
      setEdit(c.id, { ...e, add: [...(e.add || []), ...missing], remove: (e.remove || []).filter(v => !missing.includes(v)) })
    }
    return true
  }

  /** True when a run would have to wait for preparing first. */
  function needsPrepare(): boolean {
    return status.value !== 'off' && status.value !== 'ready'
  }

  /** Before a run: prepare if out of date. Returns false when no program is ready, so the
      run goes on its words as written: after a failure for this prompt it doesn't prepare
      again here (the server is already trying again; Try again prepares now). */
  async function ensureReady(): Promise<boolean> {
    // "Ready" is what the editor last saw; confirm the server still has it (cheap, no model).
    if (status.value === 'ready') await lookup()
    if (status.value === 'error') {
      await lookup()  // the server's background try may have landed
      if (status.value === 'error') return false
    }
    // Re-check after each prepare: the prompt may have changed while it ran.
    for (let i = 0; i < 3 && needsPrepare(); i++) {
      if (!(await prepare())) return false
    }
    return true
  }


  async function fetchProgramText(): Promise<{ program: string; enhanced: string }> {
    const sig = signature.value
    const { data } = await axios.post(`${getApiBase()}/prompt-programs/prepare`, request({ cache_only: true, include_program: true }))
    if (!data?.key) forget(sig)
    return { program: data?.program || '', enhanced: data?.enhanced || '' }
  }

  /** The card's More like these (adds options) and Reroll all (replaces every option,
      and clears the pins on it). One small model call; the result lives in the edits. */
  async function suggestOptions(c: ProgramChoice, mode: 'more' | 'reroll', count = 6): Promise<void> {
    const current = optionsOf(c)
    const { data } = await axios.post(`${getApiBase()}/prompt-programs/options`, request({
      cache_only: true, choice_id: c.id, existing: current, count, key: program.value?.key,
    }))
    const fresh: string[] = (data?.options || []).filter((x: string) => !current.includes(x))
    if (!fresh.length) return
    const e = edits.value[c.id] || {}
    if (mode === 'more') {
      setEdit(c.id, { ...e, add: [...(e.add || []), ...fresh] })
    } else {
      setEdit(c.id, { ...e, remove: [...c.options], add: fresh })
      setPins(c.id, [])
    }
  }

  /** Dev debugging: a few runs with the current pins and edits, no model call. */
  async function previewRuns(n = 5): Promise<Array<{ prompt: string; draws: any[]; params: Record<string, any> }>> {
    const out = []
    for (let i = 0; i < n; i++) {
      const { data } = await axios.post(`${getApiBase()}/prompt-programs/preview`, request({
        cache_only: true, pins: pins.value, edits: edits.value, seed: Math.floor(Math.random() * 2 ** 31),
      }))
      out.push(data)
    }
    return out
  }

  /** What a submit carries. `fixed` replays an earlier image's draws exactly. */
  function payload(fixed?: Record<string, any>, drawSeed?: number) {
    if (status.value === 'off') return undefined
    return {
      enabled: true,
      pins: pins.value,
      edits: edits.value,
      loras: o.loraItems.value.map(i => ({ lora: i.lora, weight: i.weight, enabled: !!i.enabled })),
      ...(fixed ? { fixed } : {}),
      // Its own seed, never the image's. Absent: each image draws fresh.
      ...(drawSeed != null ? { draw_seed: drawSeed } : {}),
    }
  }

  // Choices as the editor shows them -------------------------------------------------

  const choices = computed(() => (program.value?.choices || []).filter(c => !c.hidden))
  const byId = computed(() => Object.fromEntries(choices.value.map(c => [c.id, c])))

  // What each generated choice draws from now: its seeds plus the options generated in the
  // background (they keep arriving for a while after preparing).
  const pools = ref<Record<string, string[]>>({})
  // Bound picks' lists: name, closed or open, and each value's tier.
  const vocab = ref<Record<string, ChoiceVocab>>({})
  let poolsTimer: ReturnType<typeof setTimeout> | null = null
  let poolsId = 0
  async function fetchPools(rounds = 0) {
    if (poolsTimer) { clearTimeout(poolsTimer); poolsTimer = null }
    if (status.value !== 'ready') return
    const sig = signature.value
    const id = ++poolsId
    try {
      const { data } = await axios.post<PoolsResponse>(`${getApiBase()}/prompt-programs/pools`, request({ pins: pins.value, key: program.value?.key }))
      if (id !== poolsId || sig !== signature.value) return
      pools.value = data?.options || {}
      vocab.value = data?.vocab || {}
      if ((data?.more || []).length && rounds < 20) poolsTimer = setTimeout(() => { void fetchPools(rounds + 1) }, 3000)
    } catch { /* the seeds still show */ }
  }
  watch([() => program.value?.key, pins], () => { void fetchPools() })
  onUnmounted(() => { if (poolsTimer) clearTimeout(poolsTimer) })

  function optionsOf(c: ProgramChoice): string[] {
    const e = edits.value[c.id] || {}
    const removed = new Set(e.remove || [])
    // Sets: a bound pick's list runs to hundreds of values.
    const seeds = new Set(c.options)
    const base = [...c.options, ...(pools.value[c.id] || []).filter(x => !seeds.has(x))]
    const have = new Set(base)
    return [...base.filter(x => !removed.has(x)), ...(e.add || []).filter(x => !have.has(x))]
  }

  /** The list a bound pick draws from, once the pools have said (null for other picks). */
  function vocabOf(c: ProgramChoice): ChoiceVocab | null {
    return vocab.value[c.id] || null
  }

  function visible(c: ProgramChoice): boolean {
    if (edits.value[c.id]?.off) return false
    if (!c.parent) return true
    const parent = byId.value[c.parent]
    if (!parent || edits.value[parent.id]?.off) return false
    const p = (pins.value[parent.id] || []).filter(v => parent.options.includes(v))
    return !p.length || p.some(v => (c.when || []).includes(v))
  }

  const sections = computed(() => programSections(
    choices.value.filter(visible), program.value?.groups || [],
  ))

  function valueText(c: ProgramChoice): string {
    if (c.kind === 'param') return `${c.options[0]}–${c.options[1]}`
    const all = optionsOf(c)
    const p = [...ticksOf(c, pins.value[c.id], all)]
    if (!p.length) return all.length === 1 ? '1 option' : `${all.length} options`
    if (p.length === 1) return shownOption(p[0])
    return `${p.length} of ${all.length}`
  }
  /** The user limited what this choice draws (ticks other than its own default). */
  function isPinned(c: ProgramChoice) {
    return c.kind !== 'param' && isLimited(c, pins.value[c.id], optionsOf(c))
  }
  /** The pill shows its value: when limited, or when it draws the user's own words. */
  function showsValue(c: ProgramChoice) {
    return isPinned(c) || (c.kind === 'pick' && !!c.said && optionsOf(c).includes(c.said))
  }

  /** LoRA rows the prompt controls: path → the choice that picks it. */
  const loraControl = computed<Record<string, { choiceId: string; label: string }>>(() => {
    const out: Record<string, { choiceId: string; label: string }> = {}
    const p = program.value
    if (!p || status.value === 'off') return out
    for (const [cid, names] of Object.entries(p.lora_choices || {})) {
      const c = byId.value[cid]
      for (const n of names) {
        const lo = p.loras.find(l => l.name === n)
        if (lo) out[lo.path] = { choiceId: cid, label: c?.label || cid }
      }
    }
    return out
  })

  /** Parameters the prompt controls: name → the choice and its range. */
  const paramControl = computed<Record<string, { choiceId: string; range: string }>>(() => {
    const out: Record<string, { choiceId: string; range: string }> = {}
    if (status.value === 'off') return out
    for (const c of choices.value) {
      if (c.kind === 'param') out[c.id.replace(/^param\./, '')] = { choiceId: c.id, range: valueText(c) }
    }
    return out
  })

  // Which choice card is open, and where it hangs from. It closes itself when its choice
  // goes (a new prepare without it), and never opens on one that isn't shown.
  const { openCard, open, close } = createChoiceCard(byId)

  // Look up a prepared program when the tool or prompt settles (cheap, no model).
  let t: ReturnType<typeof setTimeout> | null = null
  // Look again when the inputs change, and when programs turn back on (back to Fluent
  // from Direct or Raw): a lookup that landed while they were off was skipped.
  watch([signature, () => o.enabled.value], () => {
    if (t) clearTimeout(t)
    t = setTimeout(lookup, 400)
  }, { immediate: true })
  // Coming back to the window: the server may have changed under us.
  const onFocus = () => { void lookup() }
  window.addEventListener('focus', onFocus)
  onUnmounted(() => window.removeEventListener('focus', onFocus))
  // While this prompt runs on its words as written, the server keeps trying to read it in
  // the background: look now and then, so the editor (and the next run) pick it up.
  let errorPoll: ReturnType<typeof setInterval> | null = null
  watch(status, (s) => {
    if (s === 'error' && !errorPoll) errorPoll = setInterval(() => { void lookup() }, ERROR_POLL_MS)
    if (s !== 'error' && errorPoll) { clearInterval(errorPoll); errorPoll = null }
  })
  onUnmounted(() => { if (errorPoll) clearInterval(errorPoll) })

  return {
    program, status, error, unsupported, pins, edits, choices, sections, byId, openCard,
    prepare, rethink, ensureReady, needsPrepare, readyPrompt, payload, fetchProgramText, previewRuns, suggestOptions,
    setPins, setManyPins, setEdit, optionsOf, vocabOf, valueText, isPinned, showsValue,
    loraControl, paramControl, open, close,
  }
}

export type PromptProgram = ReturnType<typeof usePromptProgram>
