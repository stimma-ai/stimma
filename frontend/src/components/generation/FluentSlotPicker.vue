<template>
  <!-- A slot's picker, open under its row in the list. Its variants are the writer's full
       texts, the words it keeps shown quieter; nothing ticked is any of them. A click ticks or
       unticks one (ctrl- or cmd-click too) and is where a range starts; shift-click sets every
       shown variant from there to here the way that one was left. A person adds Age (one range on a
       slider), Gender and Descent rows above the list; their picks narrow the
       list to the variants written from those seeds, and when few match, more are written for
       them. A slim foot holds More and a search that opens in place. A list of the user's own
       `{a|b}` opens here too, on its options. -->
  <div class="flex flex-col" data-picker-body data-escape-layer>
    <!-- A drilled-in filter: Age, Gender or Descent -->
    <template v-if="filter">
      <div class="shrink-0 px-1.5 pb-1">
        <button type="button" :class="[rowClass, 'text-content-secondary']" data-back @click="back">
          <span :class="tickClass"><ChevronLeftIcon class="w-3.5 h-3.5" /></span>
          <span class="flex-1">{{ backLabel }}</span>
        </button>
      </div>
      <div v-if="filter === 'descent' && !region" class="shrink-0 px-2 pb-1.5">
        <SearchField v-model="query" placeholder="Search" />
      </div>
      <div :style="{ maxHeight: listMax }" class="shrink-0 overflow-y-auto overscroll-contain px-1.5 pb-1.5 flex flex-col gap-px" data-list>
        <template v-if="filter === 'age'">
          <div class="px-2 pb-1 flex flex-col">
            <div class="pt-1 text-center text-xl font-semibold text-content tabular-nums" aria-live="polite" data-age-readout>{{ ageReadout }}</div>
            <div v-if="ageTop > ageMin" class="age-range relative h-10 coarse:h-12 mt-1">
              <div class="absolute inset-x-0 top-1/2 -translate-y-1/2 h-1 rounded-full bg-overlay-medium"></div>
              <div class="absolute top-1/2 -translate-y-1/2 h-1 rounded-full bg-selection" :style="{ left: `${agePct(lo)}%`, width: `${agePct(hi) - agePct(lo)}%` }"></div>
              <input type="range" aria-label="Youngest age" :min="ageMin" :max="ageTop" step="1" :value="lo" :aria-valuetext="ageLabel(lo)" :class="loOnTop ? 'z-20' : 'z-10'" @input="onLo" @change="commitAge" />
              <input type="range" aria-label="Oldest age" :min="ageMin" :max="ageTop" step="1" :value="hi" :aria-valuetext="ageLabel(hi)" class="z-[15]" @input="onHi" @change="commitAge" />
            </div>
            <div v-if="ageTop > ageMin" class="age-ticks relative h-4 text-[11px] text-content-muted tabular-nums">
              <span v-for="t in ageTicks" :key="t" class="absolute -translate-x-1/2" :style="{ left: `${agePct(t)}%` }">{{ ageLabel(t) }}</span>
            </div>
            <div class="flex flex-wrap gap-1.5 pt-3">
              <button type="button" :class="[chipClass, !pickedYearList.length ? chipOn : chipOff]" data-age-any @click="set(clearSeed(st, 'age', pool))">Any</button>
              <button
                v-for="p in agePresets" :key="p.label" type="button" :data-age-preset="p.label"
                :class="[chipClass, pickedYearList.length && !ageMixed && lo === p.lo && hi === p.hi ? chipOn : chipOff]"
                @click="lo = p.lo; hi = p.hi; commitAge()"
              >{{ p.label }}</button>
            </div>
          </div>
        </template>
        <template v-else-if="filter === 'gender'">
          <button type="button" :class="rowClass" data-gender-any @click="set(clearSeed(st, 'gender', pool))">
            <span :class="tickClass"><CheckIcon v-if="!genderPicks.length" class="w-3.5 h-3.5 text-selection" stroke-width="2.5" /></span>
            <span class="flex-1 text-content-secondary">Any</span>
          </button>
          <button v-for="g in genders" :key="g" type="button" :class="rowClass" :data-gender="g" @click="set(toggleGender(st, g, pool))">
            <span :class="tickClass"><CheckIcon v-if="genderPicks.includes(g)" class="w-3.5 h-3.5 text-selection" stroke-width="2.5" /></span>
            <span class="flex-1 text-content">{{ cap(g) }}</span>
          </button>
        </template>
        <template v-else-if="query.trim()">
          <button v-for="h in heritageMatches" :key="h.name" type="button" :class="rowClass" :data-heritage="h.name" @click="set(toggleHeritage(st, h.name, pool))">
            <span :class="tickClass"><CheckIcon v-if="heritagePicked(h.name) || regionPicked(h.region)" class="w-3.5 h-3.5 text-selection" stroke-width="2.5" /></span>
            <span class="flex-1 text-content">{{ h.name }}</span>
            <span class="shrink-0 text-[11px] text-content-muted">{{ h.region }}</span>
          </button>
          <div v-if="!heritageMatches.length" class="px-2 py-1.5 text-xs text-content-muted">No matches</div>
        </template>
        <template v-else-if="region">
          <button type="button" :class="rowClass" :data-region-any="region.id" @click="set(toggleRegion(st, region.id, pool))">
            <span :class="tickClass"><CheckIcon v-if="regionPicked(region.id)" class="w-3.5 h-3.5 text-selection" stroke-width="2.5" /></span>
            <span class="flex-1 text-content">All {{ region.id }}</span>
          </button>
          <button v-for="h in region.values" :key="h" type="button" :class="rowClass" :data-heritage="h" @click="set(toggleHeritage(st, h, pool))">
            <span :class="tickClass"><CheckIcon v-if="heritagePicked(h) || regionPicked(region.id)" class="w-3.5 h-3.5 text-selection" stroke-width="2.5" /></span>
            <span class="flex-1 text-content">{{ h }}</span>
          </button>
        </template>
        <template v-else>
          <button type="button" :class="rowClass" data-descent-any @click="set(clearSeed(st, 'descent', pool))">
            <span :class="tickClass"><CheckIcon v-if="!descentText" class="w-3.5 h-3.5 text-selection" stroke-width="2.5" /></span>
            <span class="flex-1 text-content-secondary">Any</span>
          </button>
          <button v-for="r in regions" :key="r.id" type="button" :class="rowClass" :data-region="r.id" @click="region = r">
            <span :class="tickClass"><CheckIcon v-if="regionPicked(r.id) || r.values.some(heritagePicked)" class="w-3.5 h-3.5 text-selection" stroke-width="2.5" /></span>
            <span class="flex-1 min-w-0 text-content">{{ r.id }}</span>
            <span class="shrink-0 text-[11px] text-selection">{{ regionNote(r) }}</span>
            <ChevronRightIcon class="w-3.5 h-4 shrink-0 text-content-muted" />
          </button>
        </template>
      </div>
    </template>

    <!-- The variants -->
    <template v-else>
      <!-- A person's Age, Gender and Descent sit in the list's own columns. -->
      <div v-if="person" class="shrink-0 pb-1 flex flex-col gap-px" data-filters>
        <button v-for="f in filters" :key="f.id" type="button" :class="subRowClass" :data-filter="f.id" @click="filter = f.id">
          <span class="pl-3 text-content-secondary">{{ f.label }}</span>
          <span :class="['min-w-0 break-words', f.text ? 'text-content' : 'text-content-muted']">{{ f.text || 'Any' }}</span>
          <ChevronRightIcon class="w-3.5 h-4 shrink-0 text-content-muted" />
        </button>
        <div class="mx-2 mt-1 border-t border-edge-subtle" />
      </div>

      <div ref="listRef" :style="{ maxHeight: listMax }" class="shrink-0 overflow-y-auto overscroll-contain px-1.5 pt-0.5 pb-1 flex flex-col gap-px" data-list>
        <template v-if="!ready">
          <div v-for="i in 5" :key="i" class="flex items-center gap-2 px-2 py-2"><span class="w-3.5" /><span class="h-2.5 rounded-full fluent-shimmer" :style="{ width: `${50 + ((i * 37) % 40)}%` }" /></div>
        </template>
        <template v-else>
          <template v-if="failed && !query.trim()">
            <div class="px-2 py-1.5 text-xs text-content-muted" data-failed>{{ program.unreachable.value ? 'Can’t reach your chat model' : 'Couldn’t vary this part' }}</div>
            <button type="button" :disabled="program.retrying.value" :class="[rowClass, 'disabled:opacity-50 disabled:pointer-events-none']" data-retry @click="program.retrySlots()">
              <span :class="tickClass"><Spinner v-if="program.retrying.value" size="sm" /><ArrowPathIcon v-else class="w-3.5 h-3.5 text-content-muted" /></span>
              <span class="flex-1 text-content-secondary">Try again</span>
            </button>
          </template>
          <div v-else-if="!all.length && !query.trim()" class="px-2 py-1.5 text-xs text-content-muted" data-none>No variants for this part yet</div>
          <div v-if="writingMore && !query.trim()" class="flex items-center gap-2 px-2 py-1.5 text-xs text-content-muted" data-writing-more>
            <span :class="tickClass"><Spinner size="sm" /></span>
            <span class="flex-1">Writing more…</span>
          </div>
          <template v-for="g in groups" :key="g.id">
            <!-- A variant, and on hover (always on touch) a trash that removes it for good. -->
            <div v-for="o in g.items" :key="o.text" class="group/variant flex items-stretch rounded-md hover:bg-overlay-subtle">
              <button type="button" :class="[rowClass, 'flex-1 min-w-0 hover:bg-transparent']" :data-variant="o.text" :aria-pressed="isPinned(o.text)" @mousedown="onRowMouseDown" @click="pick(o.text, $event)">
                <span :class="tickClass">
                  <CheckIcon v-if="isPinned(o.text)" class="w-3.5 h-3.5 text-selection" stroke-width="2.5" />
                  <span v-else-if="isFresh(o.text)" class="w-1.5 h-1.5 rounded-full bg-accent" title="New" data-new />
                </span>
                <span :class="['flex-1 min-w-0 leading-snug break-words', inPlay(o.text) ? 'text-content' : 'text-content-secondary']"><span v-for="(p, k) in pieces(o)" :key="k" :class="p.kept ? 'text-content-muted' : ''" :data-kept="p.kept ? '' : undefined">{{ p.t }}</span></span>
              </button>
              <button v-if="!isList" type="button" :disabled="removing === o.text" class="shrink-0 px-2 coarse:min-w-11 flex items-center justify-center rounded-md text-content-muted hover:text-red-400 opacity-0 group-hover/variant:opacity-100 focus-visible:opacity-100 coarse:opacity-100 disabled:pointer-events-none outline-none focus-visible:ring-1 focus-visible:ring-selection/60 transition-opacity" :aria-label="`Remove “${o.text}”`" title="Remove" :data-remove-variant="o.text" @click="remove(o.text)">
                <TrashIcon class="w-3.5 h-3.5" />
              </button>
            </div>
          </template>
          <template v-if="query.trim() && !rows.length">
            <div class="px-2 py-1.5 text-xs text-content-muted">No matches</div>
            <button v-if="!isList" type="button" :class="rowClass" data-add @click="add">
              <span :class="tickClass"><PlusIcon class="w-3.5 h-3.5 text-content-muted" /></span>
              <span class="min-w-0 break-words text-content-secondary">Add “{{ query.trim() }}”</span>
            </button>
          </template>
        </template>
      </div>
    </template>

    <!-- A slim foot: More, and a search that opens in place. Searching offers the matches
         whole: Select all, or Deselect all once they're all picked. -->
    <div v-if="!filter && ready" class="shrink-0 h-9 coarse:h-11 px-1.5 flex items-center gap-1 border-t border-edge-subtle" data-foot>
      <template v-if="searching">
        <div class="flex-1 min-w-0" @focusout="onSearchOut">
          <SearchField ref="searchRef" v-model="query" placeholder="Search" data-search @escape="closeSearch" />
        </div>
        <button v-if="query.trim() && rows.length" type="button" :class="footClass" :data-select-matches="allMatchesOn ? 'off' : 'on'" @mousedown.prevent @click="selectMatches">{{ allMatchesOn ? `Deselect all ${rows.length}` : `Select all ${rows.length}` }}</button>
      </template>
      <template v-else>
        <button v-if="!isList && !failed" type="button" :disabled="writingMore" :class="footClass" data-more @click="more">
          <Spinner v-if="writingMore" size="sm" /><SparklesIcon v-else class="w-3.5 h-3.5" />
          More
        </button>
        <span v-if="moreError" class="min-w-0 truncate text-[11px] text-content-muted" data-more-error>{{ moreError }}</span>
        <button type="button" class="ml-auto p-1.5 coarse:p-2.5 rounded-md text-content-muted hover:text-content hover:bg-overlay-subtle outline-none focus-visible:ring-1 focus-visible:ring-selection/60" aria-label="Search" data-search-open @click="openSearch">
          <MagnifyingGlassIcon class="w-3.5 h-3.5" />
        </button>
      </template>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { ArrowPathIcon, CheckIcon, ChevronLeftIcon, ChevronRightIcon, MagnifyingGlassIcon, PlusIcon, SparklesIcon, TrashIcon } from '@heroicons/vue/24/outline'
import SearchField from '../ui/SearchField.vue'
import Spinner from '../ui/Spinner.vue'
import { matchesQuery } from '../../utils/programVocab'
import {
  ageItems, cap, clearSeed, descentItems, genderItems, hasSeeds, keptPieces, lineString, lookOf, optionsOf,
  pickedHeritages, pickedYears, setPicked, shownVariants, slotFailed, toggleGender, toggleHeritage, toggleRegion, toggleValue,
  yearOfAge, setAgeRange,
} from '../../utils/programChoices'
import type { AgePicker, ChoiceState, Variant } from '../../utils/programWire'
import type { PromptProgram } from '../../composables/usePromptProgram'

type Stage = AgePicker['stages'][number]

const props = withDefaults(defineProps<{
  program: PromptProgram; id: string; listMax?: string
}>(), { listMax: '15rem' })
const emit = defineEmits<{
  (e: 'close'): void
}>()

const rowClass = 'w-full flex items-start gap-2 px-2 py-1.5 coarse:py-2.5 rounded-md text-left text-xs coarse:text-[13px] cursor-pointer hover:bg-overlay-subtle outline-none focus-visible:ring-1 focus-visible:ring-selection/60'
const subRowClass = 'grid grid-cols-[minmax(0,5fr)_minmax(0,7fr)_auto] items-start gap-x-3 w-full px-2 py-1.5 coarse:py-2.5 rounded-md text-left text-xs coarse:text-[13px] leading-snug cursor-pointer hover:bg-overlay-subtle outline-none focus-visible:ring-1 focus-visible:ring-selection/60'
const tickClass = 'shrink-0 w-3.5 h-4 flex items-center justify-center'
const footClass = 'flex items-center gap-1.5 px-2 py-1 coarse:py-2 text-xs rounded-md text-content-secondary hover:text-content hover:bg-overlay-subtle disabled:opacity-50 disabled:pointer-events-none'

const listRef = ref<HTMLElement | null>(null)
const slot = computed(() => props.program.slotById.value[props.id] || null)
const choice = computed(() => props.program.byId.value[props.id] || null)
const isList = computed(() => !slot.value)
const st = computed<ChoiceState | null>(() => props.program.states.value[props.id] || null)
const pool = computed(() => props.program.poolOf(props.id))
const kind = computed(() => (isList.value ? 'varying' : lookOf(slot.value, st.value, pool.value)))
const ready = computed(() => isList.value || kind.value !== 'writing')
const person = computed(() => (slot.value?.kind === 'person' ? pool.value?.person || null : null))
// Its reading or its variants failed: it goes in as its words until tried again.
const failed = computed(() => !isList.value && slotFailed(slot.value, st.value, pool.value))

function set(next: ChoiceState | null) {
  props.program.setState(props.id, next)
}

const filter = ref<'age' | 'gender' | 'descent' | null>(null)
const region = ref<{ id: string; values: string[] } | null>(null)
const query = ref('')
watch(() => props.id, () => { filter.value = null; region.value = null; query.value = '' })
watch(filter, () => { query.value = ''; region.value = null; searching.value = false })

function back() {
  if (region.value) region.value = null
  else filter.value = null
  query.value = ''
}

const ageText = computed(() => lineString(ageItems(st.value, person.value?.age)))
const genderText = computed(() => lineString(genderItems(st.value)))
const descentText = computed(() => lineString(descentItems(st.value)))
const filters = computed(() => [
  ...(person.value?.age?.stages?.length ? [{ id: 'age' as const, label: person.value.age.label || 'Age', text: ageText.value }] : []),
  ...(person.value?.gender ? [{ id: 'gender' as const, label: person.value.gender.label || 'Gender', text: genderText.value }] : []),
  ...(person.value?.descent ? [{ id: 'descent' as const, label: person.value.descent.label || 'Descent', text: descentText.value }] : []),
])
const backLabel = computed(() => {
  if (filter.value === 'descent') return region.value ? region.value.id : 'Descent'
  if (filter.value === 'age') return 'Age'
  return 'Gender'
})

// Variants -----------------------------------------------------------------------------------
const freshTexts = computed(() => props.program.fresh.value[props.id] || [])
const isFresh = (t: string) => freshTexts.value.includes(t)
const isPinned = (t: string) => !!st.value?.values?.includes(t)
// What the picks match, newest batch first; pinned texts the pool doesn't hold lead.
const all = computed<Variant[]>(() => {
  if (isList.value) return choice.value ? optionsOf(choice.value, pool.value, st.value).map(text => ({ text })) : []
  const shown = shownVariants(pool.value, st.value)
  const inPool = new Set((pool.value?.variants || []).map(v => v.text))
  const lead = shown.filter(v => !inPool.has(v.text) || (isFresh(v.text) && !isPinned(v.text)))
  return [...lead, ...shown.filter(v => !lead.includes(v))]
})
const rows = computed(() => (query.value.trim() ? all.value.filter(o => matchesQuery(o.text, query.value)) : all.value))
// One list in the pool's own order: it is drawn mixed, and is shown that way (no grouping by
// descent or anything else).
const groups = computed(() => [{ id: 'all', label: '', items: rows.value }])
// A click ticks or unticks one and is where a range starts (ctrl- or cmd-click the same);
// shift-click sets every shown variant from there to here the way that one was left.
const anchor = ref<string | null>(null)
watch(() => props.id, () => { anchor.value = null })
function onRowMouseDown(e: MouseEvent) {
  if (e.shiftKey) e.preventDefault()   // no text selection
}
function pick(text: string, e: MouseEvent) {
  const shown = groups.value.flatMap(g => g.items.map(o => o.text))
  const from = anchor.value ? shown.indexOf(anchor.value) : -1
  const to = shown.indexOf(text)
  if (e.shiftKey && from >= 0 && to >= 0) {
    set(setPicked(st.value, shown.slice(Math.min(from, to), Math.max(from, to) + 1), isPinned(anchor.value!)))
  } else {
    set(toggleValue(st.value, text))
    anchor.value = text
  }
}

// Search opens in place; with a search, the matches can be picked or unpicked together.
const searching = ref(false)
const searchRef = ref<InstanceType<typeof SearchField> | null>(null)
watch(() => props.id, () => { searching.value = false })
function openSearch() {
  searching.value = true
  void nextTick(() => searchRef.value?.focus())
}
function closeSearch() {
  query.value = ''
  searching.value = false
}
function onSearchOut(e: FocusEvent) {
  if (!query.value.trim() && !(e.currentTarget as Element).contains(e.relatedTarget as Node | null)) searching.value = false
}
const matchTexts = computed(() => rows.value.map(o => o.text))
const allMatchesOn = computed(() => matchTexts.value.length > 0 && matchTexts.value.every(isPinned))
function selectMatches() {
  set(setPicked(st.value, matchTexts.value, !allMatchesOn.value))
}

const inPlay = (t: string) => !st.value?.values?.length || isPinned(t)
// The words a variant keeps, and a person's descent and age when they're what was picked,
// show quieter (display only).
const heritages = computed(() => pickedHeritages(st.value?.seeds, person.value?.descent))
const years = computed(() => pickedYears(st.value?.seeds, person.value?.age))
function pieces(o: Variant) {
  if (!slot.value) return [{ t: o.text }]
  const also: string[] = []
  if (o.seeds?.descent && heritages.value.includes(o.seeds.descent)) also.push(`of ${o.seeds.descent} descent`, o.seeds.descent)
  const y = yearOfAge(o.seeds?.age)
  if (y !== null && years.value.includes(y)) also.push(`${y}-year-old`, `${y} years old`)
  return keptPieces(o.text, slot.value.words, pool.value?.keep, also)
}

// More: awaited; a seed pick's batch arrives by itself (`more` on the pool).
const asking = ref(false)
const moreError = ref('')
const writingMore = computed(() => asking.value || (!!pool.value?.more && hasSeeds(st.value)))
watch(() => props.id, () => { asking.value = false; moreError.value = '' })
async function more() {
  if (asking.value) return
  const at = props.id
  asking.value = true
  moreError.value = ''
  try {
    const n = await props.program.moreLikeThese(at)
    if (at !== props.id) return
    if (!n) moreError.value = 'Nothing new this time'
    else if (listRef.value) listRef.value.scrollTop = 0
  } catch {
    if (at === props.id) moreError.value = 'Couldn’t write more just now'
  } finally {
    if (at === props.id) asking.value = false
  }
}
function add() {
  props.program.addOwn(props.id, query.value)
  query.value = ''
}
// Remove a variant for good; one that was picked is unpicked.
const removing = ref<string | null>(null)
watch(() => props.id, () => { removing.value = null })
async function remove(text: string) {
  const at = props.id
  removing.value = text
  moreError.value = ''
  try {
    await props.program.removeVariant(at, text)
    if (anchor.value === text) anchor.value = null
  } catch {
    if (at === props.id) moreError.value = 'Couldn’t remove that just now'
  } finally {
    if (at === props.id) removing.value = null
  }
}

// Filters ------------------------------------------------------------------------------------
/** Regions, each with only the heritages the slot's words allow. */
const regions = computed(() => {
  const d = person.value?.descent
  const fits = d?.fits?.length ? new Set(d.fits) : null
  return (d?.parts || []).map(p => ({ id: p.id, values: fits ? p.values.filter(v => fits.has(v)) : p.values })).filter(p => p.values.length)
})
const heritageMatches = computed(() => regions.value.flatMap(r => r.values.map(name => ({ name, region: r.id }))).filter(h => matchesQuery(h.name, query.value)))
const regionPicked = (r: string) => !!st.value?.seeds?.descent?.groups?.region?.includes(r)
const heritagePicked = (h: string) => !!st.value?.seeds?.descent?.values?.includes(h)
function regionNote(r: { id: string; values: string[] }) {
  if (regionPicked(r.id)) return 'all'
  const on = r.values.filter(heritagePicked)
  return on.length > 2 ? `${on[0]} +${on.length - 1}` : on.join(', ')
}
const genderPicks = computed(() => st.value?.seeds?.gender?.values || [])
const genders = computed(() => {
  const g = person.value?.gender
  return g?.fits?.length ? g.fits : g?.options || []
})
// Age: the stages this person may be.
const stages = computed<Stage[]>(() => {
  const a = person.value?.age
  const ok = new Set(a?.options || [])
  return (a?.stages || []).filter(x => !ok.size || ok.has(x.id))
})
const pickedYearList = computed(() => pickedYears(st.value?.seeds, person.value?.age))
// One range on a slider. The oldest band ("80+") is one stop at its end, not thirty.
const ageYears = computed(() => [...new Set(stages.value.flatMap(a => a.years))].sort((x, z) => x - z))
const ageMin = computed(() => ageYears.value[0] ?? 0)
const ageMax = computed(() => ageYears.value.at(-1) ?? 0)
const ageOpen = computed(() => stages.value.some(a => a.id === '80+') && ageMax.value > 80)
const ageTop = computed(() => (ageOpen.value ? 80 : ageMax.value))
const ageLabel = (y: number) => (ageOpen.value && y === ageTop.value ? `${y}+` : `${y}`)
const agePct = (y: number) => (ageTop.value > ageMin.value ? ((y - ageMin.value) / (ageTop.value - ageMin.value)) * 100 : 0)
const lo = ref(0)
const hi = ref(0)
const shown = ref([0, 0])   // where the handles stood when the saved pick was last shown
function syncAge() {
  const ys = pickedYearList.value
  lo.value = ys.length ? Math.min(Math.max(ys[0], ageMin.value), ageTop.value) : ageMin.value
  hi.value = ys.length ? Math.max(Math.min(ys.at(-1)!, ageTop.value), lo.value) : ageTop.value
  shown.value = [lo.value, hi.value]
}
// Keyed by value: a pool refresh mid-drag must not snap the handles back.
watch(() => `${pickedYearList.value.join()}|${ageMin.value}|${ageTop.value}`, syncAge, { immediate: true })
const rangeYears = (a: number, b: number) => ageYears.value.filter(y => y >= a && y <= (b === ageTop.value ? ageMax.value : b))
// Picks the slider can't show as one range (saved before it): its hull, said as they are.
const ageMixed = computed(() => {
  const ys = pickedYearList.value
  return lo.value === shown.value[0] && hi.value === shown.value[1] && ys.length > 0 && ys.join() !== rangeYears(lo.value, hi.value).join()
})
const ageReadout = computed(() => {
  if (ageMixed.value) return ageText.value
  if (!pickedYearList.value.length && lo.value === ageMin.value && hi.value === ageTop.value) return 'Any age'
  return lo.value === hi.value ? ageLabel(lo.value) : hi.value === ageTop.value && ageOpen.value ? `${lo.value}+` : `${lo.value}–${hi.value}`
})
// The higher handle stays on top, but when both sit together at the top only the low one can move.
const loOnTop = computed(() => lo.value === hi.value && lo.value > (ageMin.value + ageTop.value) / 2)
const ageTicks = computed(() => {
  const out = [ageMin.value]
  for (let d = Math.ceil((ageMin.value + 1) / 10) * 10; d < ageTop.value; d += 10) if (d - ageMin.value >= 6 && ageTop.value - d >= 6) out.push(d)
  return [...out, ageTop.value]
})
function onLo(e: Event) {
  const el = e.target as HTMLInputElement
  lo.value = Math.min(Number(el.value), hi.value)
  el.value = String(lo.value)
}
function onHi(e: Event) {
  const el = e.target as HTMLInputElement
  hi.value = Math.max(Number(el.value), lo.value)
  el.value = String(hi.value)
}
function commitAge() {
  if (lo.value === ageMin.value && hi.value === ageTop.value) {
    if (pickedYearList.value.length) set(clearSeed(st.value, 'age', pool.value))
    return
  }
  const ys = rangeYears(lo.value, hi.value)
  const next = ys.length ? setAgeRange(st.value, ys[0], ys.at(-1)!, pool.value) : undefined
  if (next === undefined) syncAge()
  else set(next)
}
const agePresets = computed(() => [[18, 24], [25, 34], [35, 44], [45, 54], [55, 64], [65, Infinity]]
  .map(([a, b]) => ({ label: b === Infinity ? `${a}+` : `${a}–${b}`, lo: a, hi: b === Infinity ? ageTop.value : b }))
  .filter(p => p.lo >= ageMin.value && p.lo <= p.hi && p.hi <= ageTop.value && !(p.lo === ageMin.value && p.hi === ageTop.value)
    && setAgeRange(null, p.lo, p.hi === ageTop.value ? ageMax.value : p.hi, pool.value) !== undefined))
const chipClass = 'px-2.5 py-1 coarse:py-2 rounded-full text-xs tabular-nums outline-none focus-visible:ring-1 focus-visible:ring-selection/60'
const chipOn = 'bg-selection/15 text-selection font-medium'
const chipOff = 'bg-surface text-content-secondary hover:text-content'

// Esc steps back out: the search, then a drill-in, then the picker.
function onKey(e: KeyboardEvent) {
  if (e.key !== 'Escape') return
  // From the prompt (a slot clicked in the text keeps focus there), Esc still closes the row,
  // unless the editor has a popup of its own open: that Esc is the popup's.
  const editor = (e.target as Element | null)?.closest?.('.cm-editor')
  if (editor && editor.querySelector('.cm-tooltip')) return
  // The way menu in the row above takes its own Escape.
  if (document.querySelector('[data-slot-way-menu]')) return
  e.preventDefault()
  e.stopPropagation()
  if (query.value) query.value = ''
  else if (searching.value) searching.value = false
  else if (filter.value) back()
  else emit('close')
}
onMounted(() => {
  window.addEventListener('keydown', onKey, true)
})
onUnmounted(() => {
  window.removeEventListener('keydown', onKey, true)
})
</script>

<style scoped>
/* Two native range inputs share one track: only their thumbs take the pointer. The inputs
   overhang the track by half a thumb so a thumb's center lands on the fill's ends and ticks. */
.age-range, .age-ticks { --thumb: 20px; margin-inline: calc(var(--thumb) / 2); }
@media (pointer: coarse) { .age-range, .age-ticks { --thumb: 28px; } }
.age-range input {
  position: absolute; top: 50%; left: calc(var(--thumb) / -2); width: calc(100% + var(--thumb)); height: var(--thumb);
  margin: 0; transform: translateY(-50%); background: transparent; pointer-events: none; -webkit-appearance: none; appearance: none; outline: none;
}
.age-range input::-webkit-slider-runnable-track { height: var(--thumb); background: transparent; }
.age-range input::-moz-range-track { height: var(--thumb); background: transparent; }
.age-range input::-webkit-slider-thumb {
  -webkit-appearance: none; pointer-events: auto; cursor: grab; width: var(--thumb); height: var(--thumb); border-radius: 9999px;
  background: #fff; border: 1px solid rgb(0 0 0 / 0.15); box-shadow: 0 1px 4px rgb(0 0 0 / 0.4);
}
.age-range input::-moz-range-thumb {
  pointer-events: auto; cursor: grab; width: var(--thumb); height: var(--thumb); border-radius: 9999px;
  background: #fff; border: 1px solid rgb(0 0 0 / 0.15); box-shadow: 0 1px 4px rgb(0 0 0 / 0.4);
}
.age-range input:focus-visible::-webkit-slider-thumb { box-shadow: 0 0 0 3px rgb(var(--color-selection-rgb) / 0.5); }
.age-range input:focus-visible::-moz-range-thumb { box-shadow: 0 0 0 3px rgb(var(--color-selection-rgb) / 0.5); }
.age-range input:active::-webkit-slider-thumb { cursor: grabbing; }
</style>
