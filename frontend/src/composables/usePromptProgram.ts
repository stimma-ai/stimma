import { computed, nextTick, onUnmounted, ref, watch, type ComputedRef, type Ref } from 'vue'
import axios from 'axios'
import { getApiBase } from '../apiConfig'
import { prepareBody, prepareErrorCode, prepareSettingsSig, readPending, shownKey, type PrepareInputs } from '../utils/fluentSubmit'
import {
  addOwn as addOwnTo, carriedIds, carryChoices, cleanState, followId, isChanged, keptPools, listChoiceAt, lookOf, numberRepeats, optionsOf as optionsIn,
  readChoices, resetState, wireState, type SlotLookKind,
} from '../utils/programChoices'
import type { ChoicePool, ChoiceState, PoolsResponse, PreparedProgram, PrepareResponse, ProgramChoice, ProgramChoices, ProgramSlot } from '../utils/programWire'
import { findLists } from '../utils/promptSyntax'
import type { ListLook, SlotLook, SlotMarks } from './promptSlotMarks'

export type { ChoicePool, ChoiceState, PreparedProgram, ProgramChoice, ProgramChoices, ProgramSlot } from '../utils/programWire'

/**
 * Fluent slots: in Fluent (not Direct or Raw) the user marks what varies with slots,
 * `<young man>`. Preparing answers at once from the prompt's parse: every slot is known
 * straight away, and fills in as the server reads it and writes its variants in the background
 * (it is looked up again while `working`). A run never waits for it: a slot not written yet goes
 * in as its words. This holds the prepared slots and choices for the current prompt, each slot's
 * pool of variants (/pools), what the user chose (utils/programChoices.ts), how each slot shows
 * in the text, and which row of the list under the prompt is open.
 *
 * What is chosen lives in promptOptions.programChoices, keyed by choice id, so it persists
 * per tool (the tool's shared workspace state) and rides presets with the rest of the
 * prompt's settings. A choice whose slot survives an edit of the prompt keeps it.
 */

export type ProgramStatus = 'off' | 'ready' | 'stale' | 'busy' | 'error'

/** Detail level, by its wire values: off is Yours, fill is Medium, expand is High. */
export type EnhanceLevel = 'off' | 'fill' | 'expand'

/** What row is open: a slot (by its place in the prompt and its words, so a slot just typed
    opens once it is prepared), or one choice (a list of the user's own). */
export type CardTarget = { slot: { n: number; words: string } } | { choice: string }
export interface OpenCard { target: CardTarget }

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
  /** Whether the caret is in the prompt box: an edit there is typing, and nothing is read or
      looked up until it pauses (`TYPING_IDLE_MS`), the caret leaves the slot, or the box. */
  inPrompt?: () => boolean
}

/** How long typing in the prompt pauses before it is read: long enough to ride over a breath
    mid-phrase, so a slot isn't read (or shown as being written) half typed. */
const TYPING_IDLE_MS = 1500

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

  // A choice saved before Keep my words went (`as_written`) is read as no choice.
  const states = computed<ProgramChoices>(() => readChoices(o.promptOptions.value?.programChoices))

  function writeStates(next: ProgramChoices) {
    o.setPromptOptions({ ...(o.promptOptions.value || {}), programChoices: next })
  }
  /** Set what one choice has chosen (null: nothing). */
  function setState(id: string, s: ChoiceState | null) {
    setStates({ [id]: s })
  }
  /** Set several at once (an image's choices, the agent): one write. */
  function setStates(patch: Record<string, ChoiceState | null>) {
    const next = { ...states.value }
    for (const [id, s] of Object.entries(patch)) {
      const clean = cleanState(s)
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
    for (const [id, s] of Object.entries(states.value)) if (byId.value[id] && s) out[id] = wireState(s)
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
    if (ids) {
      pools.value = carryChoices(pools.value, ids, prev, got)
      fresh.value = carryChoices(fresh.value, ids, prev, got)
    }
    program.value = got
    preparedSig.value = sig
    prune(got, ids, prev)
  }
  /** A /prepare answer that holds a program: one with slots, or the empty one of a prompt
      with nothing that varies. A cache-only miss is `{key: null}` alone. */
  const holdsProgram = (data: PrepareResponse | null | undefined) => !!data && (!!data.key || Array.isArray(data.slots))

  // Typing in the prompt box: nothing is looked up or read while it lasts, and the slot at the
  // caret doesn't show as being written. A pause, leaving the slot or the box ends it.
  const typing = ref(false)
  let typingTimer: ReturnType<typeof setTimeout> | null = null
  function stopTyping() {
    if (typingTimer) clearTimeout(typingTimer)
    typingTimer = null
    typing.value = false
  }
  // Sync, so the look-up below already knows an edit is typing.
  watch(() => o.prompt.value, () => {
    if (!o.inPrompt?.()) { stopTyping(); return }
    if (typingTimer) clearTimeout(typingTimer)
    typing.value = true
    typingTimer = setTimeout(doneTyping, TYPING_IDLE_MS)
  }, { flush: 'sync' })
  onUnmounted(() => { if (typingTimer) clearTimeout(typingTimer) })
  /** The prompt is done for now (a pause, leaving the box, Vim :w, Cmd/Ctrl+Enter): read it. A
      prepare in flight for older text queues this one behind it; a prompt that failed waits
      for an edit. */
  function doneTyping() {
    stopTyping()
    if (status.value === 'busy' || needsRead()) void prepare()
  }
  /** The caret left the slot just typed in, still typing elsewhere: that slot is done, read it. */
  function leftSlot() {
    if (status.value === 'busy' || needsRead()) void prepare()
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
      // Slots the server hasn't been asked to read yet (a tool just opened, a preset): ask now,
      // unless the user is still typing; the answer comes at once and the reading runs behind it.
      if (data.reading && !data.working && o.prepareWhenFound?.() && startedSig !== sig) void prepare()
      pollReading(data)
    } catch {
      // Not prepared yet: the next run prepares.
    }
  }

  // While the server reads this prompt's slots, look again now and then: slots fill in as
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

  /** The prompt in the box hasn't been sent for reading: stale, or looked up with slots still
      unread and nothing reading them (a look-up never starts reading). */
  function needsRead(): boolean {
    return readPending(status.value, program.value, startedSig === signature.value)
  }

  /** Before a run: start reading the prompt if it isn't yet. A run never waits for it: the
      server draws from whatever of the prompt is read by then (a slot not read yet goes in as
      its words). */
  function ensureReady() {
    if (needsRead()) void prepare()
  }

  /** Dev: what each part was read as, the seeds each slot's variants are written from, and
      one draw. */
  async function fetchProgramText(): Promise<{ program: string; reading: unknown }> {
    const sig = signature.value
    const { data } = await axios.post<PrepareResponse>(`${getApiBase()}/prompt-programs/prepare`, request({ cache_only: true, include_program: true }))
    if (!holdsProgram(data)) forget(sig)
    const program = data?.seeds || data?.example ? JSON.stringify({ seeds: data.seeds ?? null, example: data.example ?? null }, null, 2) : ''
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

  // Each slot's pool of variants (a list's options), as /pools says now. A slot's first
  // variants keep arriving for a while after preparing, and a pick or More like these writes
  // more: while any is being written, look again now and then.
  const pools = ref<Record<string, ChoicePool>>({})
  /** slot id -> the variants More like these just added (marked new in the picker). */
  const fresh = ref<Record<string, string[]>>({})
  let poolsTimer: ReturnType<typeof setTimeout> | null = null
  let poolsId = 0
  const writingNow = (data: PoolsResponse | null | undefined) => !!data?.more?.length
    || Object.values(data?.choices || {}).some(p => p.more || p.state === 'writing' || p.state === 'reading')
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
      if (writingNow(data) && rounds < 60) poolsTimer = setTimeout(() => { void fetchPools(rounds + 1) }, 2000)
    } catch { /* the variants shown still show */ }
  }
  // A slot's state moving on (read, then written) is news for its pool too.
  const slotStates = computed(() => slots.value.map(s => `${s.id}:${s.state || ''}`).join('|'))
  watch([() => program.value?.key, () => JSON.stringify(wireChoices.value), slotStates], () => { void fetchPools() })
  // A new key (the prompt was edited): the choices it still has keep their variants until the
  // new ones arrive.
  watch(() => program.value?.key, () => { pools.value = keptPools(pools.value, byId.value) })
  onUnmounted(() => { if (poolsTimer) clearTimeout(poolsTimer) })

  function poolOf(c: ProgramChoice | string): ChoicePool | null {
    return pools.value[typeof c === 'string' ? c : c.id] || null
  }
  function optionsOf(c: ProgramChoice): string[] {
    return optionsIn(c, poolOf(c), states.value[c.id])
  }

  /** More like these: the writer writes another batch for the slot, steered by what is picked
      (awaited: about 10 to 20 seconds). The new variants join its pool and are marked new.
      Resolves to how many came back; a chat model that can't be reached rejects. */
  async function moreLikeThese(id: string): Promise<number> {
    // The prompt may be edited while the batch is written: the answer follows its slot (followId),
    // and is dropped when that slot is gone, never shown on another.
    const start = program.value
    const { data } = await axios.post(`${getApiBase()}/prompt-programs/options`, request({
      cache_only: true, choice_id: id, choices: wireChoices.value, key: start?.key,
    }))
    const got: string[] = (Array.isArray(data?.options) ? data.options : []).filter((x: unknown) => typeof x === 'string' && x.trim())
    const here = followId(id, start, program.value)
    if (here === null) return 0
    fresh.value = { ...fresh.value, [here]: got }
    await fetchPools()
    const now = followId(id, start, program.value)
    if (now === null) return 0
    // Shown at once even if the pool read back before the batch was stored.
    const p = pools.value[now]
    if (p && got.length) {
      const have = new Set((p.variants || []).map(v => v.text))
      const missing = got.filter(t => !have.has(t))
      if (missing.length) pools.value = { ...pools.value, [now]: { ...p, variants: [...(p.variants || []), ...missing.map(text => ({ text }))], options: [...p.options, ...missing] } }
    }
    return got.length
  }

  /** Add the user's own variant and pin it. */
  function addOwn(id: string, text: string) {
    setState(id, addOwnTo(states.value[id], text))
  }

  // How each slot shows in the text --------------------------------------------------------

  /** How the slot stands now: its mark and its row. */
  function lookOfSlot(id: string): SlotLookKind {
    return lookOf(slotById.value[id], states.value[id], pools.value[id])
  }
  /** The prompt's own lists as the editor finds them in the text. */
  const listsInText = computed(() => findLists(o.prompt.value || ''))
  /** The editor's marks: one look per slot of the prepared program, by its place and words. A
      slot the editor has that isn't here yet (just typed) shows as still being written. */
  const marks = computed<SlotMarks | null>(() => {
    if (status.value === 'off') return null
    const looks: SlotLook[] = slots.value.map(s => ({ n: s.n, words: s.words, kind: lookOfSlot(s.id) }))
    // A list looks set once something is chosen for it; it has no state of being written.
    const lists: ListLook[] = []
    listsInText.value.forEach((l, i) => {
      const c = listChoiceAt(listsInText.value, choices.value, i + 1)
      const s = c ? states.value[c.id] : null
      if (!c || !isChanged(s)) return
      lists.push({ n: i + 1, items: l.items, kind: lookOf({ state: 'ready' }, s) })
    })
    return { looks, lists, fallback: 'writing', typing: typing.value }
  })

  // The open row ------------------------------------------------------------------------

  const openCard = ref<OpenCard | null>(null)

  /** The slot a card target names, in the program prepared now: by its place and words,
      else by its words when only one slot has them. Null while it is still being read. */
  function slotFor(t: { n: number; words: string }): ProgramSlot | null {
    const exact = slots.value.find(s => s.n === t.n && s.words === t.words)
    if (exact) return exact
    const same = slots.value.filter(s => s.words === t.words)
    return same.length === 1 ? same[0] : null
  }
  /** The choice id of the open row (null while none is, or its slot isn't prepared yet). */
  const openId = computed<string | null>(() => {
    const t = openCard.value?.target
    if (!t) return null
    return 'choice' in t ? (byId.value[t.choice] ? t.choice : null) : slotFor(t.slot)?.id ?? null
  })
  /** Open a row (a slot's, or a list of the user's own) by its choice id; the open one again
      closes it. */
  function toggleRow(id: string) {
    if (openId.value === id) { close(); return }
    const s = slotById.value[id]
    openCard.value = s ? { target: { slot: { n: s.n, words: s.words } } } : byId.value[id] ? { target: { choice: id } } : null
  }
  /** A slot in the text was clicked, or just made: open its row (the same one again closes it).
      `toggle` false always opens: a slot just added or made. */
  function openEditorSlot(e: { n: number; words: string }, toggle = true) {
    const s = slotFor(e)
    if (toggle && s && openId.value === s.id) { close(); return }
    openCard.value = { target: { slot: { n: e.n, words: e.words } } }
  }
  /** A list of the user's own was clicked in the text: open its row. One the program doesn't
      have yet (just typed) opens once the prompt is read. */
  function openEditorList(e: { n: number }) {
    const c = listChoiceAt(listsInText.value, choices.value, e.n)
    if (c) toggleRow(c.id)
    else if (needsRead()) void prepare()
  }
  function close() { openCard.value = null }
  // A row waiting on a slot that isn't read yet reads the prompt as soon as the prompt with
  // the slot has reached us (the editor may say so before or after the text changes).
  // Not while typing: the slot may be half typed (done typing reads it).
  watch([openCard, status, typing], () => {
    const t = openCard.value?.target
    if (typing.value) return
    if (t && 'slot' in t && needsRead() && slotFor(t.slot)?.state !== 'ready') void nextTick(() => { if (needsRead()) void prepare() })
  })
  // A list's row closes itself when its choice goes (a prepare without it).
  watch(() => {
    const t = openCard.value?.target
    return !!t && 'choice' in t && status.value === 'ready' && !byId.value[t.choice]
  }, (gone) => { if (gone) close() }, { flush: 'sync' })

  // Look up a prepared program when the tool or prompt settles (cheap, no model).
  let t: ReturnType<typeof setTimeout> | null = null
  // Look again when the inputs change, and when programs turn back on.
  // Not while typing: done typing reads what's there.
  watch([signature, () => o.enabled.value], () => {
    if (t) clearTimeout(t)
    if (typing.value) return
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
    program, status, error, unsupported, typing, doneTyping, leftSlot, slots, choices, byId, slotById, pools, fresh, states, openCard, openId, marks,
    lookup, prepare, needsRead, ensureReady, payload, fetchProgramText, previewRuns,
    poolOf, optionsOf, moreLikeThese, addOwn, setState, setStates, setValues, reset, resetAll, lookOfSlot,
    slotFor, toggleRow, openEditorList, openEditorSlot, close,
  }
}

export type PromptProgram = ReturnType<typeof usePromptProgram>

