<template>
  <!-- A slot's picker, opened from the slot in the text (or its line under the prompt):
       anchored there on desktop, the app's bottom sheet on a phone. Its options are variants:
       written phrases that keep the slot's words, which show quieter than what the writer
       added. Nothing is ticked to begin with; "Any of these" is lit. Clicking a variant pins
       it, clicking more adds them. A person also browses the two comprehensive lists, Descent
       (Region > heritage) and Gender; a pick there pins that seed, and the writer writes for
       it. A list of the user's own `{a|b}` opens here too, on its options. -->
  <Teleport to="body">
    <div v-if="card" class="fixed inset-0 z-menu" @click="program.close()">
      <div
        ref="menuRef"
        role="dialog"
        :aria-label="title"
        data-picker
        data-escape-layer
        class="fixed z-menu bg-surface border border-edge-subtle rounded-lg shadow-lg w-[400px] max-w-[calc(100vw-16px)] flex flex-col"
        :style="menuStyle"
        @click.stop
      >
        <!-- Header: the slot's words, and how it stands -->
        <div class="shrink-0 px-3 pt-2.5 pb-1.5 coarse:pt-4 flex items-center gap-2">
          <span class="flex-1 min-w-0 truncate text-[13px] font-semibold text-content" data-picker-title>{{ title }}</span>
          <span v-if="kind === 'keep'" class="shrink-0 flex items-center gap-1.5 text-[11px] text-selection" data-state="keep">
            <span class="w-3 h-[15px] rounded-[3px] ring-1 ring-selection/80 bg-selection/30 bg-cover bg-center" :style="thumbStyle" />From an image
          </span>
          <span v-else-if="kind === 'writing'" class="shrink-0 flex items-center gap-1.5 text-[11px] text-content-muted" data-state="writing"><Spinner size="sm" />Writing</span>
          <span v-else-if="STATE[kind]" class="shrink-0 text-[11px] text-selection" :data-state="kind">{{ STATE[kind] }}</span>
        </div>

        <!-- A person: variants, and the two comprehensive lists -->
        <div v-if="isPerson" class="shrink-0 px-2 pb-1.5">
          <SegmentedControl v-model="tab" block :options="tabs" aria-label="Show" />
        </div>

        <div v-if="tab !== 'gender' && (ready || isList)" class="shrink-0 px-2 pb-1.5">
          <SearchField ref="searchRef" v-model="query" :placeholder="tab === 'descent' ? 'Search heritages' : 'Search'" />
        </div>

        <!-- What is chosen, always in view -->
        <div v-if="tokens.length" class="shrink-0 px-2 pb-1.5 coarse:pb-2 flex flex-wrap items-center gap-1 coarse:gap-x-2 coarse:gap-y-3 max-h-[5.5rem] overflow-y-auto" data-chosen>
          <span v-for="t in tokens" :key="t.key" class="inline-flex max-w-full items-center gap-1 pl-2.5 pr-1 py-0.5 rounded-full text-xs coarse:text-[13px] bg-selection/15 text-selection">
            <span class="truncate">{{ t.text }}</span>
            <button type="button" class="group/x shrink-0 coarse:w-9 coarse:h-9 coarse:-my-2 coarse:-mr-1 flex items-center justify-center rounded-full" :aria-label="`Remove ${t.text}`" @click="t.remove()">
              <span class="p-0.5 rounded-full group-hover/x:bg-selection/20"><XMarkIcon class="w-3 h-3" /></span>
            </button>
          </span>
          <button v-if="tokens.length > 1" type="button" class="px-1.5 py-0.5 rounded-md text-[11px] text-content-muted hover:text-content hover:bg-overlay-subtle" data-clear @click="clearAll">Clear</button>
        </div>

        <div ref="listRef" :style="listStyle" class="shrink-0 coarse:shrink coarse:min-h-0 overflow-y-auto overscroll-contain px-1.5 pb-1.5 flex flex-col gap-px">
          <!-- Variants (a list's options) ------------------------------------------------ -->
          <template v-if="tab === 'variants'">
            <div v-if="kind === 'writing' && !isList" class="flex items-center gap-2 px-2 py-1.5 coarse:py-2.5 text-xs text-content-muted" data-writing><Spinner size="sm" /> Writing variants…</div>
            <template v-if="!filtered">
              <button v-if="ready || isList" type="button" :class="rowClass" data-any @click="set(chooseAny(st))">
                <span :class="tickClass"><CheckIcon v-if="anyLit" class="w-3.5 h-3.5 text-selection" stroke-width="2.5" /></span>
                <span :class="['flex-1 min-w-0', anyLit ? 'text-content font-medium' : 'text-content-secondary']">Any of these</span>
              </button>
              <button v-if="slot" type="button" :class="rowClass" data-as-written @click="set(st?.as_written ? chooseAny(st) : asWritten(st))">
                <span :class="tickClass"><CheckIcon v-if="st?.as_written" class="w-3.5 h-3.5 text-selection" stroke-width="2.5" /></span>
                <span :class="['flex-1 min-w-0', st?.as_written ? 'text-content font-medium' : 'text-content-secondary']">As written</span>
                <span class="shrink-0 max-w-[55%] truncate text-[11px] text-content-muted">{{ slot.words }}</span>
              </button>
              <button v-if="couldntWrite" type="button" :class="[rowClass, 'text-accent']" data-try-again @click="program.prepare()">
                <span :class="tickClass"><ArrowPathIcon class="w-3.5 h-3.5" /></span>
                <span class="flex-1 min-w-0">Try again</span>
              </button>
              <div v-if="rewriting" class="flex items-center gap-2 px-2 py-1.5 text-xs text-content-muted" data-rewriting><Spinner size="sm" /> Writing variants for {{ seedText }}…</div>
            </template>

            <template v-if="ready || isList">
              <div v-if="!filtered && rows.length" class="mx-2 my-1 border-t border-edge-subtle" />
              <button
                v-for="o in rows"
                :key="o.text"
                type="button"
                :class="rowClass"
                :data-variant="o.text"
                :aria-pressed="isPinned(o.text)"
                @mousedown="onRowMouseDown"
                @click="pick(o.text, $event)"
              >
                <span :class="tickClass">
                  <CheckIcon v-if="isPinned(o.text)" class="w-3.5 h-3.5 text-selection" stroke-width="2.5" />
                  <span v-else-if="isFresh(o.text)" class="w-1.5 h-1.5 rounded-full bg-accent" title="New" data-new />
                </span>
                <span :class="['flex-1 min-w-0 leading-snug break-words', inPlay(o.text) ? 'text-content' : 'text-content-secondary']">
                  <span v-for="(p, i) in pieces(o.text)" :key="i" :class="p.kept ? 'text-content-muted' : ''" :data-kept="p.kept ? '' : undefined">{{ p.t }}</span>
                </span>
              </button>
              <div v-if="filtered && !rows.length" class="px-2 py-1.5 text-xs text-content-muted">No matches</div>
              <button v-if="canAdd" type="button" :class="rowClass" data-add @click="add">
                <span :class="tickClass"><PlusIcon class="w-3.5 h-3.5 text-content-muted" /></span>
                <span class="min-w-0 break-words text-content-secondary">Add “{{ query.trim() }}”</span>
              </button>
            </template>
          </template>

          <!-- Descent: Region > heritage ------------------------------------------------- -->
          <template v-else-if="tab === 'descent'">
            <template v-if="filtered">
              <button v-for="h in heritageMatches" :key="h.name" type="button" :class="rowClass" :data-heritage="h.name" @click="set(toggleHeritage(st, h.name, pool))">
                <span :class="tickClass">
                  <CheckIcon v-if="heritagePicked(h.name)" class="w-3.5 h-3.5 text-selection" stroke-width="2.5" />
                  <CheckIcon v-else-if="regionPicked(h.region)" class="w-3.5 h-3.5 text-content-muted" stroke-width="2" />
                </span>
                <span class="flex-1 min-w-0 text-content">{{ h.name }}</span>
                <span class="shrink-0 text-[11px] text-content-muted">{{ h.region }}</span>
              </button>
              <div v-if="!heritageMatches.length" class="px-2 py-1.5 text-xs text-content-muted">No matches</div>
            </template>
            <template v-else-if="region">
              <button type="button" :class="[rowClass, 'text-content-secondary']" data-regions @click="region = null">
                <span :class="tickClass"><ChevronLeftIcon class="w-3.5 h-3.5" /></span>
                <span class="flex-1">All regions</span>
              </button>
              <button type="button" :class="rowClass" :data-region-any="region.id" @click="set(toggleRegion(st, region.id, pool))">
                <span :class="tickClass"><CheckIcon v-if="regionPicked(region.id)" class="w-3.5 h-3.5 text-selection" stroke-width="2.5" /></span>
                <span :class="['flex-1 min-w-0', regionPicked(region.id) ? 'text-content font-medium' : 'text-content-secondary']">Any from {{ region.id }}</span>
              </button>
              <div class="mx-2 my-1 border-t border-edge-subtle" />
              <button v-for="h in region.values" :key="h" type="button" :class="rowClass" :data-heritage="h" @click="set(toggleHeritage(st, h, pool))">
                <span :class="tickClass">
                  <CheckIcon v-if="heritagePicked(h)" class="w-3.5 h-3.5 text-selection" stroke-width="2.5" />
                  <CheckIcon v-else-if="regionPicked(region.id)" class="w-3.5 h-3.5 text-content-muted" stroke-width="2" />
                </span>
                <span class="flex-1 min-w-0 text-content">{{ h }}</span>
                <span v-if="descent?.in_pool?.[h]" class="shrink-0 text-[11px] text-content-muted tabular-nums">{{ descent.in_pool[h] }}</span>
              </button>
            </template>
            <template v-else>
              <button type="button" :class="rowClass" data-descent-any @click="set(clearSeed(st, 'descent', pool))">
                <span :class="tickClass"><CheckIcon v-if="!descentPicks" class="w-3.5 h-3.5 text-selection" stroke-width="2.5" /></span>
                <span :class="['flex-1 min-w-0', !descentPicks ? 'text-content font-medium' : 'text-content-secondary']">Any descent</span>
              </button>
              <div class="mx-2 my-1 border-t border-edge-subtle" />
              <ProgramDrillRow
                v-for="r in regions"
                :key="r.id"
                wide
                :data-region="r.id"
                :label="r.id"
                :text="regionText(r) || regionNote(st, r)"
                :changed="!!regionText(r)"
                :reset-key="r.id"
                @open="region = r"
                @reset="clearRegion(r)"
              />
            </template>
          </template>

          <!-- Gender, narrowed to what the words allow ----------------------------------- -->
          <template v-else>
            <button type="button" :class="rowClass" data-gender-any @click="set(clearSeed(st, 'gender', pool))">
              <span :class="tickClass"><CheckIcon v-if="!genderPicks.length" class="w-3.5 h-3.5 text-selection" stroke-width="2.5" /></span>
              <span :class="['flex-1 min-w-0', !genderPicks.length ? 'text-content font-medium' : 'text-content-secondary']">Any</span>
            </button>
            <div class="mx-2 my-1 border-t border-edge-subtle" />
            <button v-for="g in genders" :key="g" type="button" :class="rowClass" :data-gender="g" @click="set(toggleGender(st, g, pool))">
              <span :class="tickClass"><CheckIcon v-if="genderPicks.includes(g)" class="w-3.5 h-3.5 text-selection" stroke-width="2.5" /></span>
              <span class="flex-1 min-w-0 text-content">{{ cap(g) }}</span>
            </button>
          </template>
        </div>

        <div v-if="tab === 'variants' && slot && (ready || !isPerson)" class="shrink-0 border-t border-edge-subtle px-2 py-1.5 coarse:py-2 flex items-center gap-1">
          <button v-if="ready" type="button" :class="footClass" :disabled="writing" data-more @click="more">
            <Spinner v-if="writing" size="sm" /><SparklesIcon v-else class="w-3.5 h-3.5" />
            More like these
          </button>
          <span class="flex-1" />
          <button v-if="!isPerson" type="button" :class="[footClass, st?.off ? 'text-selection' : '']" :aria-pressed="!!st?.off" data-leave-out @click="leave">Leave out</button>
        </div>
        <div v-if="moreError" class="px-3 pb-2 text-[11px] text-red-400" data-more-error>{{ moreError }}</div>
      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { computed, nextTick, onUnmounted, ref, watch } from 'vue'
import { ArrowPathIcon, CheckIcon, ChevronLeftIcon, PlusIcon, SparklesIcon, XMarkIcon } from '@heroicons/vue/24/outline'
import SearchField from '../ui/SearchField.vue'
import SegmentedControl from '../ui/SegmentedControl.vue'
import Spinner from '../ui/Spinner.vue'
import ProgramDrillRow from './ProgramDrillRow.vue'
import { useAnchoredMenuPosition } from '../../composables/useContextMenuPosition'
import { useViewport } from '../../composables/useViewport'
import { matchesQuery } from '../../utils/programVocab'
import {
  asWritten, cap, chooseAny, clearSeed, hasSeeds, keptPieces, leaveOut, lookOf, optionsOf, regionNote, seedsText,
  shownVariants, toggleGender, toggleHeritage, toggleRegion, toggleValue,
} from '../../utils/programChoices'
import type { ChoiceState, Variant } from '../../utils/programWire'
import type { PromptProgram } from '../../composables/usePromptProgram'

const props = defineProps<{ program: PromptProgram }>()

const rowClass = 'w-full flex items-start gap-2 px-2 py-1.5 coarse:py-2.5 rounded-md text-left text-xs coarse:text-[13px] cursor-pointer hover:bg-overlay-subtle outline-none focus-visible:ring-1 focus-visible:ring-selection/60'
const tickClass = 'shrink-0 w-3.5 h-4 flex items-center justify-center'
const footClass = 'flex items-center gap-1.5 px-2 py-1 coarse:py-2 text-xs rounded-md text-content-secondary hover:text-content hover:bg-overlay-subtle disabled:opacity-50 disabled:pointer-events-none'
const STATE: Record<string, string> = { pinned: 'Pinned', several: 'Chosen', off: 'Left out', written: 'As written' }

const card = computed(() => props.program.openCard.value)
const menuRef = ref<HTMLElement | null>(null)
const listRef = ref<HTMLElement | null>(null)
const searchRef = ref<InstanceType<typeof SearchField> | null>(null)
const anchorRect = computed(() => card.value?.anchor ?? null)
const visible = computed(() => !!card.value)
const { menuStyle } = useAnchoredMenuPosition(menuRef, anchorRect, visible, { gap: 6 })

const { isCoarsePointer } = useViewport()
const listStyle = computed(() => ({
  maxHeight: isCoarsePointer.value ? 'max(12rem, calc(var(--sheet-menu-max-h) - 170px))'
    : `max(12rem, min(26rem, calc(100dvh - ${Math.round((anchorRect.value?.bottom || 0) + 190)}px)))`,
}))

// What it is open on: a slot (by its place and words: one just typed opens before it is read)
// or a list of the user's own.
const target = computed(() => card.value?.target ?? null)
const slot = computed(() => {
  const t = target.value
  if (!t) return null
  if ('slot' in t) return props.program.slotFor(t.slot)
  const c = props.program.byId.value[t.choice]
  return c?.slot ? props.program.slotById.value[c.slot] || null : null
})
const choice = computed(() => {
  const t = target.value
  if (!t) return null
  if ('choice' in t) return props.program.byId.value[t.choice] || null
  return slot.value ? props.program.byId.value[slot.value.id] || null : null
})
const id = computed(() => choice.value?.id || slot.value?.id || '')
const isList = computed(() => !!choice.value && !choice.value.slot)
const title = computed(() => {
  const t = target.value
  if (isList.value) return choice.value!.label
  return slot.value?.words || (t && 'slot' in t ? t.slot.words : '')
})
const st = computed<ChoiceState | null>(() => (id.value ? props.program.states.value[id.value] || null : null))
const pool = computed(() => (id.value ? props.program.poolOf(id.value) : null))
const kind = computed(() => (isList.value ? lookOf({ state: 'ready' }, st.value) : lookOf(slot.value, st.value, pool.value)))
const ready = computed(() => !!slot.value && kind.value !== 'writing' && slot.value.state !== 'as_written')
/** Its reading or its writer gave nothing this time: it stands as its words. */
const couldntWrite = computed(() => !!slot.value && slot.value.state === 'as_written' && !pool.value?.variants?.length)
const thumbStyle = computed(() => {
  const src = typeof st.value?.from === 'number' ? props.program.thumbOf(st.value.from) : null
  return src ? { backgroundImage: `url("${src.replace(/"/g, '%22')}")` } : {}
})

function set(next: ChoiceState | null) {
  if (id.value) props.program.setState(id.value, next)
}

const isPerson = computed(() => slot.value?.kind === 'person' && !!pool.value?.person)
const tab = ref<'variants' | 'descent' | 'gender'>('variants')
const query = ref('')
const region = ref<{ id: string; values: string[] } | null>(null)
const writing = ref(false)
const moreError = ref('')
watch(() => card.value, (c) => {
  tab.value = 'variants'
  query.value = ''
  region.value = null
  moreError.value = ''
  writing.value = false
  if (c && !isCoarsePointer.value) void nextTick(() => searchRef.value?.focusQuietly?.())
})
watch(tab, () => { query.value = ''; region.value = null; if (listRef.value) listRef.value.scrollTop = 0 })

const descent = computed(() => pool.value?.person?.descent || null)
const gender = computed(() => pool.value?.person?.gender || null)
const descentPicks = computed(() => (st.value?.seeds?.descent?.values?.length || 0) + (st.value?.seeds?.descent?.groups?.region?.length || 0))
const genderPicks = computed(() => st.value?.seeds?.gender?.values || [])
const tabs = computed(() => [
  { label: 'Variants', value: 'variants', count: st.value?.values?.length || undefined },
  { label: descent.value?.label || 'Descent', value: 'descent', count: descentPicks.value || undefined },
  { label: gender.value?.label || 'Gender', value: 'gender', count: genderPicks.value.length || undefined },
])

// Variants -----------------------------------------------------------------------------------
const filtered = computed(() => !!query.value.trim())
const freshTexts = computed(() => props.program.fresh.value[id.value] || [])
const isFresh = (t: string) => freshTexts.value.includes(t)
const isPinned = (t: string) => !!st.value?.values?.includes(t)
const all = computed<Variant[]>(() => {
  if (isList.value) return optionsOf(choice.value!, pool.value, st.value).map(text => ({ text }))
  // Pins the pool doesn't hold lead (shownVariants), then what More like these just wrote, so
  // it is in view, then the rest of the pool.
  const shown = shownVariants(pool.value, st.value)
  const inPool = new Set((pool.value?.variants || []).map(v => v.text))
  const lead = shown.filter(v => !inPool.has(v.text) || (isFresh(v.text) && !isPinned(v.text)))
  return [...lead, ...shown.filter(v => !lead.includes(v))]
})
const rows = computed(() => (filtered.value ? all.value.filter(o => matchesQuery(o.text, query.value)) : all.value))
const canAdd = computed(() => filtered.value && !all.value.some(o => o.text.toLowerCase() === query.value.trim().toLowerCase()))
const anyLit = computed(() => !st.value?.values?.length && !st.value?.off && !st.value?.as_written)
const inPlay = (t: string) => !st.value?.values?.length || isPinned(t)
const rewriting = computed(() => !isList.value && ready.value && hasSeeds(st.value) && !!pool.value?.more)
const seedText = computed(() => seedsText(st.value) || 'what you picked')
const pieces = (text: string) => (slot.value ? keptPieces(text, slot.value.words, pool.value?.keep) : [{ t: text }])

// A click pins one or un-pins it; shift-click takes the range from the last one clicked, as
// the last click left it (pinning or un-pinning), across what is shown.
const anchor = ref<string | null>(null)
watch(() => card.value, () => { anchor.value = null })
function onRowMouseDown(e: MouseEvent) {
  if (e.shiftKey) e.preventDefault()   // no text selection
}
function pick(text: string, e: MouseEvent) {
  const shown = rows.value.map(o => o.text)
  const from = anchor.value ? shown.indexOf(anchor.value) : -1
  const to = shown.indexOf(text)
  if (e.shiftKey && from >= 0 && to >= 0) {
    const range = shown.slice(Math.min(from, to), Math.max(from, to) + 1)
    const on = isPinned(anchor.value!)
    const values = (st.value?.off || st.value?.as_written ? [] : st.value?.values || []).filter(v => !range.includes(v))
    set({ ...(st.value?.seeds ? { seeds: st.value.seeds } : {}), ...(st.value?.add?.length ? { add: st.value.add } : {}), values: on ? [...values, ...range] : values })
  } else {
    set(toggleValue(st.value, text))
    anchor.value = text
  }
}

async function more() {
  if (!id.value || writing.value) return
  writing.value = true
  moreError.value = ''
  const at = id.value
  try {
    const n = await props.program.moreLikeThese(at)
    if (at !== id.value) return
    if (!n) moreError.value = 'Nothing new came back. Try again.'
    else if (listRef.value) listRef.value.scrollTop = 0
  } catch (e: any) {
    const detail = e?.response?.data?.detail
    if (at === id.value) moreError.value = (typeof detail === 'string' ? detail : detail?.message) || 'Couldn’t write more just now.'
  } finally {
    if (at === id.value) writing.value = false
  }
}
function add() {
  if (id.value) props.program.addOwn(id.value, query.value)
  query.value = ''
}
function leave() {
  if (st.value?.off) { set(chooseAny(st.value)); return }
  set(leaveOut(st.value))
  props.program.close()
}

// Descent and gender -------------------------------------------------------------------------
/** Regions, each with only the heritages the slot's words allow. */
const regions = computed(() => {
  const fits = descent.value?.fits?.length ? new Set(descent.value.fits) : null
  return (descent.value?.parts || []).map(p => ({ id: p.id, values: fits ? p.values.filter(v => fits.has(v)) : p.values })).filter(p => p.values.length)
})
const regionOf = computed(() => new Map(regions.value.flatMap(r => r.values.map(h => [h, r.id] as const))))
const heritageMatches = computed(() => [...regionOf.value].filter(([h]) => matchesQuery(h, query.value)).map(([name, r]) => ({ name, region: r })))
const regionPicked = (r: string) => !!st.value?.seeds?.descent?.groups?.region?.includes(r)
const heritagePicked = (h: string) => !!st.value?.seeds?.descent?.values?.includes(h)
function regionText(r: { id: string; values: string[] }): string {
  if (regionPicked(r.id)) return 'Any'
  return r.values.filter(heritagePicked).join(', ')
}
function clearRegion(r: { id: string; values: string[] }) {
  let next = st.value
  if (regionPicked(r.id)) next = toggleRegion(next, r.id, pool.value)
  for (const h of r.values) if (next?.seeds?.descent?.values?.includes(h)) next = toggleHeritage(next, h, pool.value)
  set(next)
}
const genders = computed(() => (gender.value?.fits?.length ? gender.value.fits : gender.value?.options || []))

// Chips: everything chosen for this slot -----------------------------------------------------
const tokens = computed(() => {
  const s = st.value
  if (!s || s.off || s.as_written) return []
  return [
    ...(s.seeds?.descent?.groups?.region || []).map(r => ({ key: `r:${r}`, text: r, remove: () => set(toggleRegion(st.value, r, pool.value)) })),
    ...(s.seeds?.descent?.values || []).map(h => ({ key: `h:${h}`, text: h, remove: () => set(toggleHeritage(st.value, h, pool.value)) })),
    ...(s.seeds?.gender?.values || []).map(g => ({ key: `g:${g}`, text: cap(g), remove: () => set(toggleGender(st.value, g, pool.value)) })),
    ...(tab.value === 'variants' ? [] : (s.values || []).map(t => ({ key: `v:${t}`, text: t, remove: () => set(toggleValue(st.value, t)) }))),
  ]
})
function clearAll() {
  const add = st.value?.add?.length ? { add: st.value.add } : {}
  set(Object.keys(add).length ? add : null)
}

// Keyboard: the picker is teleported to the end of the page, so focus moves into it when it
// opens, Tab stays inside, and focus goes back to what opened it. Escape steps back out: the
// search, then the region, then the picker.
let returnTo: HTMLElement | null = null
function focusables(): HTMLElement[] {
  return [...(menuRef.value?.querySelectorAll<HTMLElement>('button:not([disabled]), input:not([disabled]), [tabindex]:not([tabindex="-1"])') || [])]
}
function onKey(e: KeyboardEvent) {
  if (e.key === 'Escape') {
    e.preventDefault()
    if (query.value) query.value = ''
    else if (region.value) region.value = null
    else props.program.close()
  } else if (e.key === 'Tab') {
    const list = focusables()
    if (!list.length) return
    const i = list.indexOf(document.activeElement as HTMLElement)
    const next = e.shiftKey ? (i <= 0 ? list.length - 1 : i - 1) : (i === -1 || i === list.length - 1 ? 0 : i + 1)
    list[next].focus()
    e.preventDefault()
  }
}
watch(visible, (open) => {
  if (open) {
    returnTo = document.activeElement instanceof HTMLElement ? document.activeElement : null
    window.addEventListener('keydown', onKey)
  } else {
    window.removeEventListener('keydown', onKey)
    const to = returnTo
    returnTo = null
    if (to?.isConnected && !to.closest('.cm-editor')) to.focus()
  }
})
onUnmounted(() => window.removeEventListener('keydown', onKey))
</script>
