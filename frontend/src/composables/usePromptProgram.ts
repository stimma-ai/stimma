import { computed, ref, watch, type ComputedRef, type Ref } from 'vue'
import axios from 'axios'
import { getApiBase } from '../apiConfig'

/**
 * Prompt programs: with Enhance on, the prompt is prepared once into a small program
 * (one model call, cached on the server) and every generation runs it. This holds
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
  /** The user's own {{name}} smart wildcard this choice fills. */
  wildcard?: string
}

export interface ProgramGroup { id: string; count: number; label: string; source: string; line?: number }

export interface ProgramLora { name: string; path: string; weight: number; trigger: string }

export interface PreparedProgram {
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
}

export interface ChoiceEdit { add?: string[]; remove?: string[]; off?: boolean }

export type ProgramStatus = 'off' | 'ready' | 'stale' | 'busy' | 'error'

interface Options {
  toolId: Ref<string | null>
  prompt: Ref<string>
  enabled: ComputedRef<boolean>
  loraItems: ComputedRef<Array<{ lora: string; weight: number }>>
  /** What the enhancer's style depends on: input images (count and ids), canvas size. */
  contextParams: ComputedRef<Record<string, any>>
  instructions: ComputedRef<string>
  projectId: Ref<number | null | undefined>
  promptOptions: Ref<any>
  setPromptOptions: (next: any) => void
}

export function usePromptProgram(o: Options) {
  const program = ref<PreparedProgram | null>(null)
  const preparedSig = ref<string | null>(null)
  const busy = ref(false)
  const error = ref<{ sig: string; message: string } | null>(null)
  // Formats that are still enhanced per image (MiniMax H3, Ideogram JSON) have no program.
  const unsupportedSig = ref<string | null>(null)
  // Which choice card is open, and where it hangs from.
  const openCard = ref<{ id: string; anchor: DOMRect } | null>(null)

  const signature = computed(() => JSON.stringify({
    tool: o.toolId.value,
    prompt: (o.prompt.value || '').trim(),
    loras: o.loraItems.value.map(i => [i.lora, i.weight]),
    context: o.contextParams.value,
    instructions: o.instructions.value,
  }))

  const status = computed<ProgramStatus>(() => {
    if (!o.enabled.value || !(o.prompt.value || '').trim()) return 'off'
    if (unsupportedSig.value === signature.value) return 'off'
    if (busy.value) return 'busy'
    if (error.value && error.value.sig === signature.value) return 'error'
    return program.value && preparedSig.value === signature.value ? 'ready' : 'stale'
  })

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
    return {
      tool_id: o.toolId.value,
      prompt: o.prompt.value || '',
      loras: o.loraItems.value.map(i => ({ lora: i.lora, weight: i.weight })),
      parameters: o.contextParams.value,
      instructions: o.instructions.value || '',
      project_id: o.projectId.value ?? null,
      ...extra,
    }
  }

  let lookupId = 0
  /** Load the prepared program for the current inputs if the server has one. Never calls a model. */
  async function lookup() {
    if (status.value === 'off' || busy.value) return
    const sig = signature.value
    const id = ++lookupId
    try {
      const { data } = await axios.post(`${getApiBase()}/prompt-programs/prepare`, request({ cache_only: true }))
      if (id !== lookupId || sig !== signature.value) return
      if (data?.unsupported) { unsupportedSig.value = sig; return }
      if (!data?.key) return
      program.value = data
      preparedSig.value = sig
    } catch {
      // Not prepared yet: the dot says so; Run prepares.
    }
  }

  /** Prepare for the current inputs (the model call happens here, if needed). */
  async function prepare(force = false): Promise<boolean> {
    const sig = signature.value
    busy.value = true
    try {
      const { data } = await axios.post(`${getApiBase()}/prompt-programs/prepare`, request({ force }))
      if (data?.unsupported) {
        unsupportedSig.value = sig
        return true
      }
      program.value = data
      preparedSig.value = sig
      error.value = null
      return true
    } catch (e: any) {
      const detail = e?.response?.data?.detail
      error.value = { sig, message: (typeof detail === 'string' ? detail : detail?.message) || 'Couldn’t prepare this prompt.' }
      return false
    } finally {
      busy.value = false
    }
  }

  /** Before a run: prepare if out of date. Returns false if the run should not start. */
  async function ensureReady(): Promise<boolean> {
    if (status.value === 'off') return true
    if (status.value === 'ready') return true
    return prepare()
  }

  async function fetchProgramText(): Promise<{ program: string; enhanced: string }> {
    const { data } = await axios.post(`${getApiBase()}/prompt-programs/prepare`, request({ cache_only: true, include_program: true }))
    return { program: data.program || '', enhanced: data.enhanced || '' }
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
  function payload(fixed?: Record<string, any>) {
    if (status.value === 'off') return undefined
    return {
      enabled: true,
      pins: pins.value,
      edits: edits.value,
      loras: o.loraItems.value.map(i => ({ lora: i.lora, weight: i.weight })),
      ...(fixed ? { fixed } : {}),
    }
  }

  // Choices as the editor shows them -------------------------------------------------

  const choices = computed(() => (program.value?.choices || []).filter(c => !c.hidden))
  const byId = computed(() => Object.fromEntries(choices.value.map(c => [c.id, c])))

  function optionsOf(c: ProgramChoice): string[] {
    const e = edits.value[c.id] || {}
    const removed = new Set(e.remove || [])
    return [...c.options.filter(x => !removed.has(x)), ...(e.add || []).filter(x => !c.options.includes(x))]
  }

  function visible(c: ProgramChoice): boolean {
    if (edits.value[c.id]?.off) return false
    if (!c.parent) return true
    const parent = byId.value[c.parent]
    if (!parent || edits.value[parent.id]?.off) return false
    const p = (pins.value[parent.id] || []).filter(v => parent.options.includes(v))
    return !p.length || p.some(v => (c.when || []).includes(v))
  }

  /** Top-level rows: plain choices, and one row per group (People ×3). */
  const rows = computed(() => {
    const out: Array<{ kind: 'choice'; choice: ProgramChoice } | { kind: 'group'; group: ProgramGroup; members: ProgramChoice[] }> = []
    const seenGroups = new Set<string>()
    for (const c of choices.value) {
      if (c.group) {
        if (seenGroups.has(c.group)) continue
        seenGroups.add(c.group)
        const group = program.value?.groups.find(g => g.id === c.group)
          || { id: c.group, count: 0, label: c.group, source: 'text' }
        out.push({ kind: 'group', group, members: choices.value.filter(m => m.group === c.group) })
      } else if (visible(c)) {
        out.push({ kind: 'choice', choice: c })
      }
    }
    return out
  })

  function valueText(c: ProgramChoice): string {
    if (c.kind === 'param') return `${c.options[0]}–${c.options[1]}`
    const all = optionsOf(c)
    const p = (pins.value[c.id] || []).filter(v => all.includes(v))
    if (!p.length) return c.kind === 'lora' ? `any of ${all.length}` : 'any'
    if (p.length === 1) return p[0]
    return `${p.length} of ${all.length}`
  }
  function isPinned(c: ProgramChoice) {
    return c.kind !== 'param' && (pins.value[c.id] || []).some(v => optionsOf(c).includes(v))
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

  function open(id: string, el: Element | null) {
    if (!el) return
    openCard.value = { id, anchor: el.getBoundingClientRect() }
  }
  function close() { openCard.value = null }

  // Look up a prepared program when the tool or prompt settles (cheap, no model).
  let t: ReturnType<typeof setTimeout> | null = null
  watch(signature, () => {
    if (t) clearTimeout(t)
    t = setTimeout(lookup, 400)
  }, { immediate: true })

  return {
    program, status, error, signature, pins, edits, choices, rows, byId, openCard,
    prepare, ensureReady, payload, lookup, fetchProgramText, previewRuns,
    setPins, setManyPins, setEdit, optionsOf, valueText, isPinned, visible,
    loraControl, paramControl, open, close,
  }
}

export type PromptProgram = ReturnType<typeof usePromptProgram>
