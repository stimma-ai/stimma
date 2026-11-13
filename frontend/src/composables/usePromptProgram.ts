import { computed, nextTick, onUnmounted, ref, watch, type ComputedRef, type Ref } from 'vue'
import axios from 'axios'
import { getApiBase } from '../apiConfig'
import { prepareBody, prepareErrorCode, prepareSettingsSig, readPending, shownKey, type PrepareInputs } from '../utils/fluentSubmit'
import { additionList, isOwnOption } from '../utils/programAdditions'
import { carriedIds, carryChoices, cleanState, isBuilder as isBuilderOf, keptPools, numberRepeats, optionsOf as optionsIn, resetState, rowsOf } from '../utils/programChoices'
import type { ChoicePool, ChoiceState, PoolsResponse, PreparedProgram, PrepareResponse, ProgramChoice, ProgramChoices, ProgramSlot } from '../utils/programWire'

export type { ChoicePool, ChoiceState, PreparedProgram, ProgramChoice, ProgramChoices, ProgramSlot } from '../utils/programWire'

/**
 * Fluent slots: in Fluent (not Direct or Raw) the user marks what varies with slots,
 * `<young man>`. Preparing answers at once from the prompt's parse: every slot shows as a pill
 * straight away, and fills in as the server reads each one in the background (it is looked up
 * again while `working`). A run never waits for it: a slot not read yet goes in as its words.
 * This holds the prepared slots and choices for the current prompt, each choice's options
 * (/pools), what the user chose (utils/programChoices.ts), and which card is open.
 *
 * What is chosen lives in promptOptions.programChoices, keyed by choice id, so it persists
 * per tool (the tool's shared workspace state) and rides presets with the rest of the
 * prompt's settings. A choice whose slot survives an edit of the prompt keeps it.
 */

export type ProgramStatus = 'off' | 'ready' | 'stale' | 'busy' | 'error'

/** Detail level, by its wire values: off is Yours, fill is Medium, expand is High. */
export type EnhanceLevel = 'off' | 'fill' | 'expand'

/** What a card is open on: a slot (by its place in the prompt and its words, so a slot just
    typed opens before it is prepared), or one choice. */
export type CardTarget = { slot: { n: number; words: string } } | { choice: string }
export interface OpenCard { target: CardTarget; anchor: DOMRect }

interface Options {
  toolId: Ref<string | null>
  prompt: Ref<string>
  enabled: ComputedRef<boolean>
  projectId: Ref<number | null | undefined>
  promptOptions: Ref<any>
  setPromptOptions: (next: any) => void
  /** Whether a prompt found unprepared is read right away: not while the user is in the
      prompt box (it's read when they're done), the tool is still loading, or in the background. */
  prepareWhenFound?: () => boolean
}

/** How often the editor looks for a program the server prepared in the background after a failure. */
const ERROR_POLL_MS = 15_000
/** How often, and how many times, the editor looks again while the server is still reading slots. */
const READING_POLL_MS = 1_200
const READING_POLLS = 150

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

  /** This tool's prompt format can't be prepared (Ideogram JSON, MiniMax H3). */
  const unsupported = computed(() => unsupportedSig.value !== null && unsupportedSig.value === signature.value)

  // What is chosen ---------------------------------------------------------------------

  const states = computed<ProgramChoices>(() => o.promptOptions.value?.programChoices || {})

  function writeStates(next: ProgramChoices) {
    o.setPromptOptions({ ...(o.promptOptions.value || {}), programChoices: next })
  }
  /** Set what one choice has chosen (null: nothing). */
  function setState(id: string, s: ChoiceState | null) {
    const c = byId.value[id]
    const clean = c ? cleanState(c, s) : s
    const next = { ...states.value }
    if (clean) next[id] = clean
    else delete next[id]
    writeStates(next)
  }
  /** Set several at once (an image's choices, the agent): one write. */
  function setStates(patch: Record<string, ChoiceState | null>) {
    const next = { ...states.value }
    for (const [id, s] of Object.entries(patch)) {
      const c = byId.value[id]
      const clean = c ? cleanState(c, s) : s
      if (clean) next[id] = clean
      else delete next[id]
    }
    writeStates(next)
  }
  /** Limit a choice to these values; none of them: back to how it starts. */
  function setValues(id: string, values: string[]) {
    const s = states.value[id]
    setState(id, values.length ? { values, ...(s?.add?.length ? { add: s.add } : {}) } : resetState(s))
  }
  function reset(ids: string[]) {
    setStates(Object.fromEntries(ids.map(id => [id, resetState(states.value[id])])))
  }
  function resetAll() {
    reset(Object.keys(states.value))
  }
  /** What is sent: the choices this program has. */
  const wireChoices = computed<ProgramChoices>(() => {
    const out: ProgramChoices = {}
    for (const [id, s] of Object.entries(states.value)) if (byId.value[id] && s) out[id] = s
    return out
  })
  /** A prepare for the prompt in the box landed: what was chosen follows each part to its id
      there (`ids`, from carriedIds), and choices for parts that went with an edit go. */
  function prune(p: PreparedProgram, ids: Record<string, string> | null, prev: PreparedProgram | null) {
    const next = carryChoices(states.value, ids, prev, p)
    const same = Object.keys(next).length === Object.keys(states.value).length
      && Object.entries(next).every(([id, s]) => states.value[id] === s)
    if (!same) writeStates(next)
  }

  function request(extra: Record<string, any> = {}) {
    return prepareBody(inputs(), extra)
  }

  function landed(p: PrepareResponse, sig: string) {
    const got: PreparedProgram = { ...p, key: p.key ?? null, slots: p.slots || [], choices: p.choices || [] }
    const prev = program.value
    const ids = carriedIds(prev, got)
    if (ids) pools.value = carryChoices(pools.value, ids, prev, got)
    program.value = got
    preparedSig.value = sig
    prune(got, ids, prev)
  }
  /** A /prepare answer that holds a program: one with slots, or the empty one of a prompt
      with nothing that varies. A cache-only miss is `{key: null}` alone. */
  const holdsProgram = (data: PrepareResponse | null | undefined) => !!data && (!!data.key || Array.isArray(data.slots))

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
      const { data } = await axios.post<PrepareResponse>(`${getApiBase()}/prompt-programs/prepare`,
        request({ cache_only: true, key: shownKey(program.value, preparedSig.value, settingsSig.value) }))
      if (id !== lookupId || sig !== signature.value) return
      if (data?.unsupported) { unsupportedSig.value = sig; return }
      if (!holdsProgram(data)) {
        forget(sig)
        // Nothing prepared for what's here (a tool just opened, a preset, a remix): read it
        // now, so a run doesn't start by waiting. Not while typing (done typing reads it),
        // and not a prompt that failed (the server retries those).
        if (status.value === 'stale' && o.prepareWhenFound?.()) void prepare()
        return
      }
      landed(data, sig)
      if (error.value?.sig === sig) error.value = null  // prepared since (the server's background try)
      markReady(sig)
      // Slots the server hasn't been asked to read yet (a tool just opened, a preset): ask now,
      // unless the user is still typing; the answer comes at once and the reading runs behind it.
      if (data.reading && !data.working && o.prepareWhenFound?.() && startedSig !== sig) void prepare()
      pollReading(data)
    } catch {
      // Not prepared yet: the next run prepares.
    }
  }

  // While the server reads this prompt's slots, look again now and then: pills fill in as
  // each reading lands.
  let readingTimer: ReturnType<typeof setTimeout> | null = null
  let readingPolls = 0
  let startedSig: string | null = null
  function pollReading(data: PrepareResponse) {
    if (readingTimer) { clearTimeout(readingTimer); readingTimer = null }
    if (!data.working) { readingPolls = 0; return }
    if (++readingPolls > READING_POLLS) return
    readingTimer = setTimeout(() => { readingTimer = null; void lookup() }, READING_POLL_MS)
  }
  onUnmounted(() => { if (readingTimer) clearTimeout(readingTimer) })

  // The prepare in flight, so concurrent runs wait on it instead of starting another.
  let inFlight: { sig: string; force: boolean; done: Promise<boolean> } | null = null
  // At most one more, for the newest prompt.
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
    startedSig = sig
    readingPolls = 0
    lookupId++  // a look-up sent before this answers from before the read started: drop it
    try {
      const { data } = await axios.post<PrepareResponse>(`${getApiBase()}/prompt-programs/prepare`,
        request({ force, key: shownKey(program.value, preparedSig.value, settingsSig.value) }))
      if (data?.unsupported) {
        unsupportedSig.value = sig
        return true
      }
      markReady(sig)  // runnable now, whatever the box says by the time it's back
      if (sig !== signature.value) {
        // The inputs moved on while this ran, and their lookup was skipped (busy): look now.
        setTimeout(() => { void lookup() }, 0)
        return true
      }
      landed(data, sig)
      error.value = null
      pollReading(data)
      return true
    } catch (e: any) {
      const detail = e?.response?.data?.detail
      const code = prepareErrorCode(e)
      error.value = { sig, code, message: (typeof detail === 'string' ? detail : detail?.message) || 'Couldn’t read this prompt.' }
      if (sig !== signature.value) setTimeout(() => { void lookup() }, 0)
      return false
    } finally {
      if (!inFlight || inFlight.sig === sig) busy.value = false
    }
  }

  /** A run never waits for preparing: the server draws from whatever of the prompt is read
      by then (a slot not read yet goes in as its words). */
  function needsPrepare(): boolean {
    return false
  }

  /** The prompt in the box hasn't been sent for reading: stale, or looked up with slots still
      unread and nothing reading them (a look-up never starts reading). */
  function needsRead(): boolean {
    return readPending(status.value, program.value, startedSig === signature.value)
  }

  /** Before a run: start reading the prompt if it isn't yet, and go on at once. */
  async function ensureReady(): Promise<boolean> {
    if (needsRead()) void prepare()
    return true
  }

  /** Dev: what each part was read as, the picks made from that, and one draw. */
  async function fetchProgramText(): Promise<{ program: string; reading: unknown }> {
    const sig = signature.value
    const { data } = await axios.post<PrepareResponse>(`${getApiBase()}/prompt-programs/prepare`, request({ cache_only: true, include_program: true }))
    if (!holdsProgram(data)) forget(sig)
    const program = data?.picks ? JSON.stringify({ picks: data.picks, example: data.example }, null, 2) : ''
    return { program, reading: data?.readings ?? null }
  }

  /** Dev debugging: a few runs with what is chosen, no model call. */
  async function previewRuns(n = 5): Promise<Array<{ prompt: string; draws: any[] }>> {
    const out = []
    for (let i = 0; i < n; i++) {
      const { data } = await axios.post(`${getApiBase()}/prompt-programs/preview`, request({
        cache_only: true, choices: wireChoices.value, seed: Math.floor(Math.random() * 2 ** 31),
      }))
      out.push(data)
    }
    return out
  }

  /** What a submit carries as promptOptions.program. `fixed` replays an earlier image's draws exactly. */
  function payload(fixed?: Record<string, any>, drawSeed?: number) {
    if (status.value === 'off') return undefined
    return {
      enabled: true,
      choices: wireChoices.value,
      ...(fixed ? { fixed } : {}),
      // Its own seed, never the image's. Absent: each image draws fresh.
      ...(drawSeed != null ? { draw_seed: drawSeed } : {}),
    }
  }

  // Slots and choices -----------------------------------------------------------------

  // The same words in brackets twice are two people (or things): when their labels match,
  // they read "Friend 1", "Friend 2", in the prompt's order.
  const slots = computed<ProgramSlot[]>(() => numberRepeats([...(program.value?.slots || [])].sort((a, b) => a.n - b.n)))
  const choices = computed(() => (program.value?.choices || []).filter(c => !c.hidden))
  const byId = computed<Record<string, ProgramChoice>>(() => Object.fromEntries(choices.value.map(c => [c.id, c])))
  const slotById = computed<Record<string, ProgramSlot>>(() => Object.fromEntries(slots.value.map(s => [s.id, s])))
  /** The choices that go with another (an outfit's colors), by the one they follow. */
  const followers = computed(() => {
    const out: Record<string, ProgramChoice[]> = {}
    for (const c of choices.value) if (c.follows && byId.value[c.follows]) (out[c.follows] ||= []).push(c)
    return out
  })

  // Each choice's options now: its zones, groups, tiers and short forms, plus the options
  // written in the background (they keep arriving for a while after preparing).
  const pools = ref<Record<string, ChoicePool>>({})
  let poolsTimer: ReturnType<typeof setTimeout> | null = null
  let poolsId = 0
  async function fetchPools(rounds = 0) {
    if (poolsTimer) { clearTimeout(poolsTimer); poolsTimer = null }
    // A prompt with nothing that varies has no pools.
    if (status.value !== 'ready' || !program.value?.key) return
    const sig = signature.value
    const id = ++poolsId
    try {
      const { data } = await axios.post<PoolsResponse>(`${getApiBase()}/prompt-programs/pools`,
        request({ key: program.value?.key, choices: wireChoices.value }))
      if (id !== poolsId || sig !== signature.value) return
      pools.value = data?.choices || {}
      if ((data?.more?.length || Object.values(pools.value).some(p => p.more)) && rounds < 20) poolsTimer = setTimeout(() => { void fetchPools(rounds + 1) }, 3000)
    } catch { /* the prepared options still show */ }
  }
  watch([() => program.value?.key, () => JSON.stringify(wireChoices.value)], () => { void fetchPools() })
  // A new key (the prompt was edited): the choices it still has keep their options until the
  // new ones arrive.
  watch(() => program.value?.key, () => { pools.value = keptPools(pools.value, byId.value) })
  onUnmounted(() => { if (poolsTimer) clearTimeout(poolsTimer) })

  function poolOf(c: ProgramChoice): ChoicePool | null {
    return pools.value[c.id] || null
  }
  function optionsOf(c: ProgramChoice): string[] {
    return optionsIn(c, poolOf(c), states.value[c.id])
  }

  /** More like these: one small model call, for the choice's default zone. The new options
      join the user's own, so they stay in its list and are sent with it. */
  async function suggestOptions(c: ProgramChoice, count = 6): Promise<number> {
    const current = optionsOf(c)
    const { data } = await axios.post(`${getApiBase()}/prompt-programs/options`, request({
      cache_only: true, choice_id: c.id, existing: current, count, key: program.value?.key,
      ...(c.zones?.length ? { zone: c.zones[0].id } : {}),
    }))
    const fresh: string[] = (data?.options || []).filter((x: string) => !current.includes(x))
    if (!fresh.length) return 0
    const s = states.value[c.id] || {}
    setState(c.id, { ...s, add: [...fresh, ...(s.add || [])] })
    return fresh.length
  }

  /** An option the user typed into a list-bound choice's card is kept for that list, so
      later prompts offer it too; forgetting one of their own options forgets it there. */
  async function keepAddition(c: ProgramChoice, text: string, keep = true) {
    const cls = additionList(c)
    if (!cls) return
    try {
      await axios.post(`${getApiBase()}/prompt-programs/additions${keep ? '' : '/remove'}`, { cls, text })
      void fetchPools()
    } catch { /* still added (or deleted) here */ }
  }
  function isOwn(c: ProgramChoice, option: string): boolean {
    return isOwnOption(option, states.value[c.id], poolOf(c))
  }
  /** Add the user's own option and choose it. */
  function addOwn(c: ProgramChoice, text: string) {
    const v = text.trim()
    if (!v) return
    const s = states.value[c.id] || {}
    const base = s.off ? { add: s.add } : s
    const known = optionsOf(c).includes(v)
    setState(c.id, { ...base, add: known ? base.add : [v, ...(base.add || [])], values: [...(base.values || []).filter(x => x !== v), v] })
    if (!known) void keepAddition(c, v)
  }
  /** Forget one of the user's own options. */
  function forgetOwn(c: ProgramChoice, option: string) {
    const s = states.value[c.id] || {}
    setState(c.id, { ...s, add: (s.add || []).filter(x => x !== option), values: (s.values || []).filter(x => x !== option) })
    void keepAddition(c, option, false)
  }

  // The open card ---------------------------------------------------------------------

  const openCard = ref<OpenCard | null>(null)

  /** The slot a card target names, in the program prepared now: by its place and words,
      else by its words when only one slot has them. Null while it is still being read. */
  function slotFor(t: { n: number; words: string }): ProgramSlot | null {
    const exact = slots.value.find(s => s.n === t.n && s.words === t.words)
    if (exact) return exact
    const same = slots.value.filter(s => s.words === t.words)
    return same.length === 1 ? same[0] : null
  }

  function anchorOf(at: Element | DOMRect | null | undefined): DOMRect | null {
    if (!at) return null
    return at instanceof Element ? at.getBoundingClientRect() : at
  }
  /** Open a slot's card: its builder (a person, a camera) or its chooser. */
  function openSlot(slotId: string, at: Element | DOMRect | null | undefined) {
    const s = slotById.value[slotId]
    const anchor = anchorOf(at)
    if (!s || !anchor) return
    openCard.value = { target: { slot: { n: s.n, words: s.words } }, anchor }
  }
  /** Open one choice's chooser. */
  function openChoice(id: string | null | undefined, at: Element | DOMRect | null | undefined) {
    const anchor = anchorOf(at)
    if (!id || !anchor || !byId.value[id]) return
    openCard.value = { target: { choice: id }, anchor }
  }
  /** The editor's slot was clicked, or just made: open its card. A slot not prepared yet
      opens on "Writing options…" and fills in when the prompt is read. */
  function openEditorSlot(e: { n: number; words: string; rect: DOMRect }) {
    openCard.value = { target: { slot: { n: e.n, words: e.words } }, anchor: e.rect }
  }
  function close() { openCard.value = null }
  // A card waiting on a slot that isn't read yet reads the prompt as soon as the prompt with
  // the slot has reached us (the editor may say so before or after the text changes).
  watch([openCard, status], () => {
    const t = openCard.value?.target
    if (t && 'slot' in t && needsRead() && slotFor(t.slot)?.state !== 'ready') void nextTick(() => { if (needsRead()) void prepare() })
  })
  // A choice card closes itself when its choice goes (a prepare without it).
  watch(() => {
    const t = openCard.value?.target
    return !!t && 'choice' in t && status.value === 'ready' && !byId.value[t.choice]
  }, (gone) => { if (gone) close() }, { flush: 'sync' })

  /** A builder slot's details as its card lists them: an outfit's colors sit inside the outfit. */
  function detailsOf(slot: ProgramSlot): ProgramChoice[] {
    return rowsOf(slot, id => byId.value[id])
  }
  /** A slot whose card lists its details: more than one row (programChoices.isBuilder). */
  function isBuilder(slot: ProgramSlot): boolean {
    return isBuilderOf(slot, id => byId.value[id])
  }

  // Look up a prepared program when the tool or prompt settles (cheap, no model).
  let t: ReturnType<typeof setTimeout> | null = null
  // Look again when the inputs change, and when programs turn back on.
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
    program, status, error, unsupported, slots, choices, byId, slotById, followers, pools, states, openCard,
    lookup, prepare, needsRead, ensureReady, needsPrepare, readyPrompt, payload, fetchProgramText, previewRuns,
    poolOf, optionsOf, suggestOptions, isOwn, addOwn, forgetOwn, setState, setStates, setValues, reset, resetAll,
    slotFor, detailsOf, isBuilder, openSlot, openChoice, openEditorSlot, close,
  }
}

export type PromptProgram = ReturnType<typeof usePromptProgram>

