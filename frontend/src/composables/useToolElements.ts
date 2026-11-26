/**
 * Elements attached to a tool (ToolView's Elements section).
 *
 * The attached elements ride the tool's state (globalPrefs.elements). The resolver
 * (POST /api/elements/resolve) says which library images and LoRAs they put in the
 * tool's slots for the current prompt; this applies that plan to the slots without
 * touching what the user owns:
 *
 * - a slot image or LoRA an element placed is the element's (its pick), and may be
 *   swapped when the prompt changes;
 * - Keep makes a pick the user's (pinned): it stays and counts against the budget;
 * - removing or replacing a pick excludes it, so it isn't put back.
 *
 * Re-resolving is immediate on attach/detach and overrides, debounced while typing.
 * Run waits for the current prompt's plan (ensureResolved), so stale refs never go out.
 */

import axios from 'axios'
import { computed, inject, nextTick, provide, ref, watch, type InjectionKey, type Ref } from 'vue'
import { makeStorageKey } from '../utils/storageKeys'
import { syncedStorage } from '../utils/workspaceStore'
import { applyLoras, applyRefs, type LoraItem, type LoraPick, type RefPick, type ResolvedLora, type ResolvedRef, type SlotItem } from '../utils/elementSlots'

export type { ResolvedLora, ResolvedRef } from '../utils/elementSlots'

export interface AttachedElement {
  asset_id: number
  revision_id?: number | null
  name: string
  kind: string
  /** The element's library card (its bundle media: the tile). */
  media_id?: number | null
}

interface KeyRef { element_asset_id: number; key: string; kind: 'ref' | 'lora'; mediaId?: number; path?: string }

export interface ElementsPrefs {
  attached: AttachedElement[]
  refPicks: RefPick[]
  loraPicks: LoraPick[]
  kept: KeyRef[]
  excluded: KeyRef[]
}

export interface ResolutionPlan {
  mode: 'deterministic' | 'cached' | 'resolved' | 'fallback'
  key: string
  selected_refs: ResolvedRef[]
  selected_loras: ResolvedLora[]
  resolved_guidance: string
  warnings: string[]
  elements: Array<{ asset_id: number; revision_id: number; name: string; kind: string; instructions: Record<string, string> }>
}

export function emptyElementsPrefs(): ElementsPrefs {
  return { attached: [], refPicks: [], loraPicks: [], kept: [], excluded: [] }
}

export function normalizeElementsPrefs(value: any): ElementsPrefs {
  const v = value && typeof value === 'object' ? value : {}
  const list = (x: any) => (Array.isArray(x) ? x : [])
  return {
    attached: list(v.attached), refPicks: list(v.refPicks), loraPicks: list(v.loraPicks),
    kept: list(v.kept), excluded: list(v.excluded),
  }
}

// --- Recently used elements (the picker's "Used before") ----------------------------------

const RECENT_KEY = () => makeStorageKey('media_picker', 'recent_elements')

export function recentElementIds(): number[] {
  try {
    const parsed = JSON.parse(syncedStorage.getItem(RECENT_KEY()) || '[]')
    return Array.isArray(parsed) ? parsed.filter((x: any) => typeof x === 'number') : []
  } catch { return [] }
}

export function recordElementUse(assetId: number) {
  try {
    const ids = [assetId, ...recentElementIds().filter(id => id !== assetId)].slice(0, 60)
    syncedStorage.setItem(RECENT_KEY(), JSON.stringify(ids))
  } catch {}
}

// --- The composable ------------------------------------------------------------------------

export interface ToolElementsOptions {
  globalPrefs: Ref<any>
  toolLoras: Ref<LoraItem[]>
  toolId: () => string | null
  taskType: () => string | null
  /** Max reference images the tool's image slot takes (0: none). */
  maxRefs: () => number
  /** Whether element picks may go in the image slot now (not batch mode, an image slot). */
  refsAllowed: () => boolean
  parameters: () => Record<string, any>
  projectId: () => number | null
  debounceMs?: number
}

export function useToolElements(opts: ToolElementsOptions) {
  const debounceMs = opts.debounceMs ?? 700
  const prefs = computed<ElementsPrefs>(() => normalizeElementsPrefs(opts.globalPrefs.value.elements))
  const plan = ref<ResolutionPlan | null>(null)
  const working = ref(false)
  let inflight: Promise<ResolutionPlan | null> | null = null
  let timer: ReturnType<typeof setTimeout> | null = null
  let spinnerTimer: ReturnType<typeof setTimeout> | null = null
  let applying = false
  let generation = 0

  function write(next: ElementsPrefs) {
    opts.globalPrefs.value.elements = next.attached.length || next.kept.length ? next : null
  }

  const attached = computed(() => prefs.value.attached)

  function attach(el: AttachedElement) {
    const p = prefs.value
    if (p.attached.some(a => a.asset_id === el.asset_id)) return
    recordElementUse(el.asset_id)
    write({ ...p, attached: [...p.attached, el] })
  }

  function detach(assetId: number) {
    const p = prefs.value
    const items = (opts.globalPrefs.value.inputImages || []) as SlotItem[]
    const mine = new Set(p.refPicks.filter(r => r.element_asset_id === assetId).map(r => r.mediaId))
    applying = true
    if (mine.size) opts.globalPrefs.value.inputImages = items.filter(i => i.mediaId == null || !mine.has(i.mediaId))
    const loraResult = applyLoras(opts.toolLoras.value, p.loraPicks.filter(l => l.element_asset_id === assetId), [])
    opts.toolLoras.value = loraResult.loras
    write({
      attached: p.attached.filter(a => a.asset_id !== assetId),
      refPicks: p.refPicks.filter(r => r.element_asset_id !== assetId),
      loraPicks: p.loraPicks.filter(l => l.element_asset_id !== assetId),
      kept: p.kept.filter(k => k.element_asset_id !== assetId),
      excluded: p.excluded.filter(k => k.element_asset_id !== assetId),
    })
    nextTick(() => { applying = false })
  }

  function elementById(id: number) {
    return prefs.value.attached.find(a => a.asset_id === id) ?? null
  }

  /** The element that put this library image in a slot (null when the user did, or kept it). */
  function forMedia(mediaId: number | null | undefined) {
    if (mediaId == null) return null
    const pick = prefs.value.refPicks.find(r => r.mediaId === +mediaId)
    return pick ? elementById(pick.element_asset_id) : null
  }

  function forLora(path: string | null | undefined) {
    if (!path) return null
    const pick = prefs.value.loraPicks.find(l => l.path === path)
    return pick ? elementById(pick.element_asset_id) : null
  }

  /** The user keeps a pick: it becomes theirs and the element stops changing it. */
  function keepMedia(mediaId: number) {
    const p = prefs.value
    const pick = p.refPicks.find(r => r.mediaId === mediaId)
    if (!pick) return
    write({
      ...p,
      refPicks: p.refPicks.filter(r => r !== pick),
      kept: [...p.kept, { element_asset_id: pick.element_asset_id, key: pick.member_key, kind: 'ref', mediaId }],
    })
  }

  // The user removed or replaced a pick (it's gone from the slots), or changed an element
  // LoRA: picks that vanished are excluded; a LoRA whose weight they changed is kept.
  function reconcile() {
    if (applying) return
    const p = prefs.value
    if (!p.attached.length) return
    const slotIds = new Set(((opts.globalPrefs.value.inputImages || []) as SlotItem[]).map(i => i.mediaId))
    const loras = opts.toolLoras.value
    const goneRefs = opts.refsAllowed() ? p.refPicks.filter(r => !slotIds.has(r.mediaId)) : []
    const goneLoras: LoraPick[] = []
    const keptLoras: LoraPick[] = []
    for (const pick of p.loraPicks) {
      const item = loras.find(l => l.lora === pick.path)
      if (!item || !item.enabled) goneLoras.push(pick)
      else if (Math.abs(item.weight - pick.weight) > 1e-6) keptLoras.push(pick)
    }
    const keptGone = p.kept.filter(k => k.kind === 'ref' ? !slotIds.has(k.mediaId) : !loras.some(l => l.lora === k.path && l.enabled))
    if (!goneRefs.length && !goneLoras.length && !keptLoras.length && !keptGone.length) return
    write({
      ...p,
      refPicks: p.refPicks.filter(r => !goneRefs.includes(r)),
      loraPicks: p.loraPicks.filter(l => !goneLoras.includes(l) && !keptLoras.includes(l)),
      kept: [
        ...p.kept.filter(k => !keptGone.includes(k)),
        ...keptLoras.map(l => ({ element_asset_id: l.element_asset_id, key: l.lora_key, kind: 'lora' as const, path: l.path })),
      ],
      excluded: [
        ...p.excluded,
        ...goneRefs.map(r => ({ element_asset_id: r.element_asset_id, key: r.member_key, kind: 'ref' as const })),
        ...goneLoras.map(l => ({ element_asset_id: l.element_asset_id, key: l.lora_key, kind: 'lora' as const })),
      ],
    })
  }

  function requestBody() {
    const p = prefs.value
    const items = (opts.globalPrefs.value.inputImages || []) as SlotItem[]
    const owned = new Set(p.refPicks.map(r => r.mediaId))
    const keptRefs = p.kept.filter(k => k.kind === 'ref')
    const keptIds = new Set(keptRefs.map(k => k.mediaId))
    const pair = (k: KeyRef, field: string) => ({ element_asset_id: k.element_asset_id, [field]: k.key })
    const refsAllowed = opts.refsAllowed()
    return {
      elements: p.attached.map(a => ({ asset_id: a.asset_id, revision_id: a.revision_id ?? null })),
      tool_id: opts.toolId(),
      task_type: opts.taskType(),
      prompt: opts.globalPrefs.value.prompt || '',
      parameters: opts.parameters(),
      enhance_enabled: !!opts.globalPrefs.value.promptOptions?.autoImprove?.enabled,
      project_id: opts.projectId(),
      overrides: {
        // With no image slot to fill, the budget is zero.
        user_ref_count: refsAllowed
          ? items.filter(i => !(i.mediaId != null && (owned.has(i.mediaId) || keptIds.has(i.mediaId)))).length
          : opts.maxRefs(),
        pinned_refs: keptRefs.map(k => pair(k, 'member_key')),
        excluded_refs: p.excluded.filter(k => k.kind === 'ref').map(k => pair(k, 'member_key')),
        pinned_loras: p.kept.filter(k => k.kind === 'lora').map(k => pair(k, 'lora_key')),
        excluded_loras: p.excluded.filter(k => k.kind === 'lora').map(k => pair(k, 'lora_key')),
      },
    }
  }

  function apply(result: ResolutionPlan) {
    const p = prefs.value
    applying = true
    let refPicks = p.refPicks
    if (opts.refsAllowed()) {
      const current = (opts.globalPrefs.value.inputImages || []) as SlotItem[]
      const refs = applyRefs(current, p.refPicks, result.selected_refs, opts.maxRefs())
      if (refs.items.length !== current.length || refs.items.some((item, i) => item !== current[i])) {
        opts.globalPrefs.value.inputImages = refs.items
      }
      refPicks = refs.picks
    }
    const loraResult = applyLoras(opts.toolLoras.value, p.loraPicks, result.selected_loras)
    if (JSON.stringify(loraResult.loras) !== JSON.stringify(opts.toolLoras.value)) opts.toolLoras.value = loraResult.loras
    const revisions = new Map(result.elements.map(e => [e.asset_id, e]))
    write({
      ...p,
      attached: p.attached.map(a => {
        const r = revisions.get(a.asset_id)
        return r ? { ...a, revision_id: r.revision_id, name: r.name || a.name, kind: r.kind || a.kind } : a
      }),
      refPicks,
      loraPicks: loraResult.picks,
    })
    plan.value = result
    nextTick(() => { applying = false })
  }

  async function resolveNow(): Promise<ResolutionPlan | null> {
    if (timer) { clearTimeout(timer); timer = null }
    reconcile()
    const gen = ++generation
    if (!prefs.value.attached.length || !opts.toolId()) {
      if (prefs.value.refPicks.length || prefs.value.loraPicks.length) {
        apply({ mode: 'deterministic', key: '', selected_refs: [], selected_loras: [], resolved_guidance: '', warnings: [], elements: [] })
      }
      plan.value = null
      return null
    }
    if (spinnerTimer) clearTimeout(spinnerTimer)
    spinnerTimer = setTimeout(() => { if (gen === generation && inflight) working.value = true }, 150)
    const request = (async () => {
      try {
        const { data } = await axios.post('/api/elements/resolve', requestBody())
        if (gen !== generation) return inflight ? await inflight : plan.value
        apply(data as ResolutionPlan)
        if ((data as ResolutionPlan).warnings?.length) console.info('[elements]', (data as ResolutionPlan).warnings.join(' '))
        return data as ResolutionPlan
      } catch (e) {
        // Resolving never blocks a run: the slots stay as they are.
        console.warn('[elements] resolve failed', e)
        return plan.value
      } finally {
        if (gen === generation) {
          working.value = false
          inflight = null
        }
      }
    })()
    inflight = request
    return request
  }

  function schedule(immediate: boolean) {
    if (timer) clearTimeout(timer)
    if (immediate) { void resolveNow(); return }
    timer = setTimeout(() => { timer = null; void resolveNow() }, debounceMs)
  }

  /** Run's gate: the plan for the prompt as it is now. */
  async function ensureResolved(): Promise<ResolutionPlan | null> {
    if (!prefs.value.attached.length) return null
    if (timer) return resolveNow()
    if (inflight) return inflight
    if (!plan.value) return resolveNow()
    return plan.value
  }

  // Immediate on attach/detach, Keep, tool switch and the user's slot edits; debounced on typing.
  const structuralKey = computed(() => JSON.stringify({
    a: prefs.value.attached.map(a => a.asset_id),
    k: prefs.value.kept, x: prefs.value.excluded,
    t: opts.toolId(), e: !!opts.globalPrefs.value.promptOptions?.autoImprove?.enabled,
  }))
  watch(structuralKey, () => schedule(true))
  watch(() => opts.globalPrefs.value.prompt, () => { if (prefs.value.attached.length) schedule(false) })
  watch(
    () => [((opts.globalPrefs.value.inputImages || []) as SlotItem[]).map(i => i.mediaId), opts.toolLoras.value.map(l => [l.lora, l.weight, l.enabled])],
    () => { if (!applying) reconcile() },
    { deep: true },
  )

  /** What the prompt writers read (promptOptions.elementContext). */
  function elementContext() {
    const current = plan.value
    if (!current || !current.elements.length) return null
    return {
      guidance: current.resolved_guidance || '',
      elements: current.elements.map(e => ({ asset_id: e.asset_id, name: e.name, instructions: e.instructions })),
    }
  }

  /** The job's _elements: which elements it ran with, and how each reached the output. */
  function jobElements(enhanceOn: boolean) {
    const p = prefs.value
    if (!p.attached.length) return null
    const current = plan.value
    return p.attached.map(a => {
      const carriers: string[] = []
      if (p.refPicks.some(r => r.element_asset_id === a.asset_id) || p.kept.some(k => k.element_asset_id === a.asset_id && k.kind === 'ref')) carriers.push('refs')
      if (p.loraPicks.some(l => l.element_asset_id === a.asset_id) || p.kept.some(k => k.element_asset_id === a.asset_id && k.kind === 'lora')) carriers.push('lora')
      if (enhanceOn && current?.elements.some(e => e.asset_id === a.asset_id && (e.instructions?.enhance || '').trim())) carriers.push('prompt')
      return { asset_id: a.asset_id, revision_id: a.revision_id ?? null, carrier: carriers.join(',') || null }
    })
  }

  /** For the tool's agent: what's attached, what each placed, and the instructions it follows. */
  function agentState() {
    const current = plan.value
    if (!prefs.value.attached.length) return null
    return {
      guidance: current?.resolved_guidance || '',
      warnings: current?.warnings || [],
      elements: prefs.value.attached.map(a => {
        const e = current?.elements.find(x => x.asset_id === a.asset_id)
        return {
          name: a.name,
          kind: a.kind,
          references: current?.selected_refs.filter(r => r.element_asset_id === a.asset_id).map(r => r.member_key) ?? [],
          loras: current?.selected_loras.filter(l => l.element_asset_id === a.asset_id).map(l => l.lora_key) ?? [],
          instructions: e?.instructions ?? {},
        }
      }),
    }
  }

  return {
    attached, plan, working, attach, detach, forMedia, forLora, keepMedia,
    ensureResolved, resolveNow, elementContext, jobElements, agentState,
  }
}

export type ToolElements = ReturnType<typeof useToolElements>

export const TOOL_ELEMENTS_KEY: InjectionKey<ToolElements> = Symbol('toolElements')

export function provideToolElements(value: ToolElements) {
  provide(TOOL_ELEMENTS_KEY, value)
}

/** The tool's elements, for slot tiles and LoRA rows (null outside a tool). */
export function injectToolElements(): ToolElements | null {
  return inject(TOOL_ELEMENTS_KEY, null)
}
