<template>
  <!-- One choice's chooser. Nothing is ticked to begin with: the lit row at the top says what
       images get now, and clicking an option chooses it; clicking more adds them. What is
       chosen stays in view as chips above the list. Group chips filter the list; with only
       chips on, the top row chooses those groups whole. -->
  <div class="min-h-0 flex flex-col" :data-chooser="choice.id">
    <div v-if="searchable" class="shrink-0 px-2 pb-1.5" @keydown="onSearchKey">
      <SearchField ref="searchRef" v-model="query" placeholder="Search" />
    </div>

    <div v-if="parts.length" class="shrink-0 px-2 pb-1.5 flex flex-wrap gap-1 coarse:flex-nowrap coarse:overflow-x-auto coarse:[&>button]:shrink-0" role="group" aria-label="Groups">
      <button
        v-for="p in parts"
        :key="p.key"
        type="button"
        :aria-pressed="shownParts.has(p.key)"
        :data-part="p.part"
        :class="['px-2.5 py-0.5 coarse:py-1.5 rounded-full text-xs coarse:text-[13px] border transition-colors outline-none focus-visible:ring-1 focus-visible:ring-selection/60',
          shownParts.has(p.key) ? 'bg-overlay-medium text-content border-transparent' : 'bg-surface-raised border-transparent text-content-secondary hover:text-content hover:bg-surface-hover']"
        @click="togglePart(p.key)"
      >{{ partLabel(p.part) }}</button>
    </div>

    <!-- What is chosen, always in view -->
    <div v-if="tokens.length" class="shrink-0 px-2 pb-1.5 flex flex-wrap items-center gap-1 max-h-[5.5rem] overflow-y-auto" data-chosen>
      <span
        v-for="t in tokens"
        :key="tokenKey(t)"
        class="inline-flex max-w-full items-center gap-1 pl-2.5 pr-1 py-0.5 rounded-full text-xs bg-selection/15 text-selection"
      >
        <span class="truncate">{{ tokenText(choice, pool, t) }}</span>
        <button type="button" class="shrink-0 p-0.5 coarse:p-1.5 rounded-full hover:bg-selection/20" :aria-label="`Remove ${tokenText(choice, pool, t)}`" @click="toggle(t)">
          <XMarkIcon class="w-3 h-3" />
        </button>
      </span>
      <button v-if="tokens.length > 1" type="button" class="px-1.5 py-0.5 rounded-md text-[11px] text-content-muted hover:text-content hover:bg-overlay-subtle" data-clear @click="clear">Clear</button>
    </div>

    <div ref="listRef" :style="listStyle" class="shrink-0 overflow-y-auto overscroll-contain px-1.5 pb-1.5 flex flex-col gap-px">
      <!-- The lit row: what images get when nothing is chosen -->
      <button v-if="!filtered" type="button" :class="rowClass" data-default @click="chooseDefault">
        <span :class="tickClass"><CheckIcon v-if="defaultLit" class="w-3.5 h-3.5 text-selection" stroke-width="2.5" /></span>
        <span :class="['flex-1 min-w-0', defaultLit ? 'text-content font-medium' : 'text-content-secondary']">{{ defaultLabel }}</span>
      </button>
      <button v-if="filtered && partsOnly" type="button" :class="rowClass" data-any-part @click="toggleParts">
        <span :class="tickClass"><CheckIcon v-if="partsChosen" class="w-3.5 h-3.5 text-selection" stroke-width="2.5" /></span>
        <span :class="['flex-1 min-w-0', partsChosen ? 'text-content font-medium' : 'text-content-secondary']">Any {{ shownPartNames }}</span>
      </button>

      <template v-for="(z, i) in shownZones" :key="z.id">
        <div v-if="i > 0 || (filtered && zones.length > 1)" class="px-2 pt-2.5 pb-1 text-[11px] font-semibold text-content-tertiary">{{ z.title }}</div>
        <button v-if="z.id !== first && !filtered" type="button" :class="rowClass" :data-zone-any="z.id" @click="toggle({ kind: 'zone', zone: z.id })">
          <span :class="tickClass"><CheckIcon v-if="hasToken(state, { kind: 'zone', zone: z.id })" class="w-3.5 h-3.5 text-selection" stroke-width="2.5" /></span>
          <span :class="['flex-1 min-w-0', hasToken(state, { kind: 'zone', zone: z.id }) ? 'text-content font-medium' : 'text-content-secondary']">Any of these</span>
        </button>
        <div
          v-for="o in z.rows"
          :key="o"
          role="button"
          tabindex="0"
          :class="[rowClass, 'group/opt']"
          :data-option="o"
          :aria-pressed="hasToken(state, { kind: 'value', value: o })"
          @click="toggle({ kind: 'value', value: o })"
          @keydown.enter.self.prevent="toggle({ kind: 'value', value: o })"
          @keydown.space.self.prevent="toggle({ kind: 'value', value: o })"
        >
          <span :class="tickClass">
            <CheckIcon v-if="hasToken(state, { kind: 'value', value: o })" class="w-3.5 h-3.5 text-selection" stroke-width="2.5" />
            <CheckIcon v-else-if="changed && inPlay.has(o)" class="w-3.5 h-3.5 text-content-muted" stroke-width="2" />
          </span>
          <span v-if="swatches(o)" class="shrink-0 flex -space-x-1 mt-px">
            <span v-for="(c, j) in swatches(o)" :key="j" class="w-3.5 h-3.5 rounded-full border border-surface" :style="{ background: c }" />
          </span>
          <span :class="['flex-1 min-w-0 leading-snug break-words', inPlay.has(o) ? 'text-content' : 'text-content-secondary']">{{ shownOption(o) }}</span>
          <button
            v-if="program.isOwn(choice, o)"
            type="button"
            title="Delete option"
            :aria-label="`Delete ${valueText(pool, o)}`"
            class="shrink-0 -my-0.5 p-0.5 rounded text-content-muted hover:text-red-400 opacity-0 group-hover/opt:opacity-100 group-focus-within/opt:opacity-100 coarse:opacity-100"
            @click.stop="program.forgetOwn(choice, o)"
          >
            <TrashIcon class="w-3.5 h-3.5" />
          </button>
        </div>
      </template>

      <div v-if="hidden > 0" class="px-2 pt-1.5 text-[11px] text-content-muted font-mono tabular-nums" data-more-rows>{{ count(shownCount) }} of {{ count(matchCount) }}</div>
      <div v-if="writingOptions" class="flex items-center gap-2 px-2 py-1.5 text-xs text-content-muted" data-writing><Spinner size="sm" /> Writing options…</div>
      <template v-if="filtered && !matchCount">
        <div class="px-2 py-1.5 text-xs text-content-muted">No matches</div>
      </template>
      <button v-if="canAdd" type="button" :class="rowClass" data-add @click="add">
        <span :class="tickClass"><PlusIcon class="w-3.5 h-3.5 text-content-muted" /></span>
        <span class="min-w-0 break-words text-content-secondary">Add “{{ query.trim() }}”</span>
      </button>
    </div>

    <!-- Colors belong to the outfit -->
    <div v-if="followers.length" class="shrink-0 px-1.5 pb-1.5">
      <button v-for="f in followers" :key="f.id" type="button" :class="rowClass" :data-follower="f.id" @click="emit('drill', f.id)">
        <span class="w-24 shrink-0 text-content-secondary">{{ f.label }}</span>
        <span v-if="followerSwatches(f)" class="shrink-0 flex -space-x-1 mt-px">
          <span v-for="(c, j) in followerSwatches(f)" :key="j" class="w-3.5 h-3.5 rounded-full border border-surface" :style="{ background: c }" />
        </span>
        <span :class="['flex-1 min-w-0 truncate', isChanged(program.states.value[f.id]) ? 'text-selection' : 'text-content-muted']">{{ followerText(f) }}</span>
        <ChevronRightIcon class="w-3.5 h-4 shrink-0 text-content-muted" />
      </button>
    </div>

    <div v-if="canMore || canAsWritten || canLeaveOut" class="shrink-0 border-t border-edge-subtle px-2 py-1.5 flex items-center gap-1">
      <button v-if="canMore" type="button" :class="footClass" :disabled="writing" data-more @click="more">
        <Spinner v-if="writing" size="sm" /><SparklesIcon v-else class="w-3.5 h-3.5" />
        More like these
      </button>
      <span class="flex-1" />
      <button v-if="canAsWritten" type="button" :class="[footClass, asWritten ? 'text-selection' : '']" :aria-pressed="asWritten" data-as-written @click="toggleAsWritten">As written</button>
      <button v-if="canLeaveOut" type="button" :class="footClass" data-leave-out @click="leave">Leave out</button>
    </div>
    <div v-if="writeError" class="px-3 pb-2 text-[11px] text-red-400">{{ writeError }}</div>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { CheckIcon, ChevronRightIcon, PlusIcon, SparklesIcon, TrashIcon, XMarkIcon } from '@heroicons/vue/24/outline'
import SearchField from '../ui/SearchField.vue'
import Spinner from '../ui/Spinner.vue'
import { useViewport } from '../../composables/useViewport'
import { MANY_OPTIONS, MAX_ROWS, matchesQuery, shownOption } from '../../utils/programVocab'
import {
  PALETTE_CLS, asWrittenState, defaultZone, drawable, groupMembers, hasToken, isAsWritten, isChanged, leaveOut, partLabel,
  pillValue, resetState, swatchesOf, toggleToken, tokenText, tokensOf, valueText, zonesOf, type Token,
} from '../../utils/programChoices'
import type { PromptProgram, ProgramChoice, ProgramSlot } from '../../composables/usePromptProgram'

const props = defineProps<{
  choice: ProgramChoice
  program: PromptProgram
  /** The slot, when this choice is all of it: its words can be drawn as written. */
  ownSlot?: ProgramSlot | null
  /** Where the card hangs from, for the list's height. */
  anchorBottom?: number
}>()
const emit = defineEmits<{ (e: 'drill', id: string): void; (e: 'left-out'): void }>()

const rowClass = 'w-full flex items-start gap-2 px-2 py-1.5 coarse:py-2.5 rounded-md text-left text-xs coarse:text-[13px] cursor-pointer hover:bg-overlay-subtle outline-none focus-visible:ring-1 focus-visible:ring-selection/60'
const tickClass = 'shrink-0 w-3.5 h-4 flex items-center justify-center'
const footClass = 'flex items-center gap-1.5 px-2 py-1 coarse:py-2 text-xs rounded-md text-content-secondary hover:text-content hover:bg-overlay-subtle disabled:opacity-50 disabled:pointer-events-none'
const count = (n: number) => n.toLocaleString('en-US')

const { allowsAutofocus, isCoarsePointer } = useViewport()

const query = ref('')
const shownParts = ref<Set<string>>(new Set())
const listRef = ref<HTMLElement | null>(null)
const searchRef = ref<InstanceType<typeof SearchField> | null>(null)
const writing = ref(false)
const writeError = ref('')

const pool = computed(() => props.program.poolOf(props.choice))
const state = computed(() => props.program.states.value[props.choice.id] || null)
const zones = computed(() => zonesOf(props.choice, pool.value, state.value))
const first = computed(() => defaultZone(props.choice))
const options = computed(() => zones.value.flatMap(z => z.options))
const tokens = computed(() => tokensOf(state.value))
const changed = computed(() => isChanged(state.value))
const inPlay = computed(() => drawable(props.choice, pool.value, state.value) || new Set<string>())

const isList = computed(() => props.choice.source === 'list')
const isFollower = computed(() => !!props.choice.follows)
const searchable = computed(() => options.value.length > MANY_OPTIONS || (!isList.value && !isFollower.value))

// The list takes the room left under the card's anchor, so the card itself never has to
// scroll. On a phone the card is a sheet from the bottom, and the list takes a share of it.
const listStyle = computed(() => ({
  maxHeight: isCoarsePointer.value ? 'max(9rem, calc(var(--sheet-menu-max-h) - 330px))'
    : `max(10rem, min(24rem, calc(100dvh - ${Math.round((props.anchorBottom || 0) + 270)}px)))`,
}))

// Groups --------------------------------------------------------------------------------
const parts = computed(() => Object.entries(pool.value?.groups || {}).flatMap(([facet, byPart]) =>
  Object.keys(byPart).filter(p => byPart[p]?.length).map(part => ({ key: JSON.stringify([facet, part]), facet, part }))))
const partOf = (key: string) => { const [facet, part] = JSON.parse(key) as [string, string]; return { facet, part } }
const inShownParts = computed(() => {
  const out = new Set<string>()
  for (const key of shownParts.value) { const { facet, part } = partOf(key); for (const o of groupMembers(pool.value, facet, part)) out.add(o) }
  return out
})
const filtered = computed(() => !!query.value.trim() || shownParts.value.size > 0)
const partsOnly = computed(() => shownParts.value.size > 0 && !query.value.trim())
const partsChosen = computed(() => [...shownParts.value].every(k => hasToken(state.value, { kind: 'group', ...partOf(k) })))
const shownPartNames = computed(() => [...shownParts.value].map(k => partLabel(partOf(k).part)).join(' or '))
function togglePart(key: string) {
  const next = new Set(shownParts.value)
  next.has(key) ? next.delete(key) : next.add(key)
  shownParts.value = next
  if (listRef.value) listRef.value.scrollTop = 0
}
function toggleParts() {
  const on = partsChosen.value
  let s = state.value
  for (const k of shownParts.value) {
    const t: Token = { kind: 'group', ...partOf(k) }
    if (hasToken(s, t) === on) s = toggleToken(props.choice, s, t)
  }
  props.program.setState(props.choice.id, s)
}

// The list ------------------------------------------------------------------------------
const matches = (o: string) => {
  const q = query.value.trim()
  if (q && !matchesQuery(valueText(pool.value, o), q) && !matchesQuery(o, q)) return false
  return !shownParts.value.size || inShownParts.value.has(o)
}
const matched = computed(() => zones.value.map(z => ({ ...z, rows: filtered.value ? z.options.filter(matches) : z.options })))
const matchCount = computed(() => matched.value.reduce((n, z) => n + z.rows.length, 0))
// A long list (thousands of faces) renders its first rows; the search narrows it.
const shownZones = computed(() => {
  let room = MAX_ROWS
  return matched.value.map((z) => {
    const rows = z.rows.slice(0, Math.max(0, room))
    room -= rows.length
    return { ...z, rows }
  }).filter((z, i) => z.rows.length || (i > 0 && !filtered.value && z.options.length))
})
const shownCount = computed(() => shownZones.value.reduce((n, z) => n + z.rows.length, 0))
const hidden = computed(() => matchCount.value - shownCount.value)

const defaultLit = computed(() => !changed.value || (zones.value.length > 1 && hasToken(state.value, { kind: 'zone', zone: first.value })))
const defaultLabel = computed(() => (zones.value.length > 1 && zones.value[0].title) || `Any ${props.choice.label.toLowerCase()}`)
/** The lit row. With several zones it is the default zone, which can be chosen beside
    others; with one, it puts the choice back. */
function chooseDefault() {
  if (!changed.value) return
  if (zones.value.length > 1) toggle({ kind: 'zone', zone: first.value })
  else props.program.setState(props.choice.id, resetState(state.value))
}

function toggle(t: Token) {
  props.program.setState(props.choice.id, toggleToken(props.choice, state.value, t))
}
function clear() {
  props.program.setState(props.choice.id, resetState(state.value))
}
const tokenKey = (t: Token) => t.kind === 'value' ? `v:${t.value}` : t.kind === 'zone' ? `z:${t.zone}` : `g:${t.facet}:${t.part}`

const palette = computed(() => props.choice.cls === PALETTE_CLS)
const swatches = (o: string) => (palette.value ? swatchesOf(o) : null)

// Adding --------------------------------------------------------------------------------
const canAdd = computed(() => {
  const q = query.value.trim()
  return !!q && !isList.value && !isFollower.value && !options.value.includes(q) && !matchCount.value
})
function add() {
  props.program.addOwn(props.choice, query.value)
  query.value = ''
  if (listRef.value) listRef.value.scrollTop = 0
}

const writingOptions = computed(() => !!pool.value?.more)
const canMore = computed(() => !isList.value && !isFollower.value)
async function more() {
  if (writing.value) return
  writing.value = true
  writeError.value = ''
  try {
    await props.program.suggestOptions(props.choice)
    if (listRef.value) listRef.value.scrollTop = 0
  } catch (e: any) {
    const d = e?.response?.data?.detail
    writeError.value = (typeof d === 'string' ? d : d?.message) || 'Couldn’t write new options.'
  } finally {
    writing.value = false
  }
}

// As written, Leave out ------------------------------------------------------------------
const canAsWritten = computed(() => !!props.ownSlot)
const asWritten = computed(() => isAsWritten(props.ownSlot, state.value))
function toggleAsWritten() {
  if (!props.ownSlot) return
  props.program.setState(props.choice.id, asWritten.value ? resetState(state.value) : asWrittenState(props.ownSlot, state.value))
}
const canLeaveOut = computed(() => !isFollower.value && !state.value?.off)
function leave() {
  props.program.setState(props.choice.id, leaveOut(state.value))
  emit('left-out')
}

// Colors --------------------------------------------------------------------------------
const followers = computed(() => props.program.followers.value[props.choice.id] || [])
function followerText(f: ProgramChoice): string {
  const s = props.program.states.value[f.id]
  if (s?.off) return 'left out'
  return pillValue(f, props.program.poolOf(f), s) || 'Any'
}
function followerSwatches(f: ProgramChoice): string[] | null {
  const t = tokensOf(props.program.states.value[f.id])
  return f.cls === PALETTE_CLS && t.length === 1 && t[0].kind === 'value' ? swatchesOf(t[0].value) : null
}

// Keys and focus --------------------------------------------------------------------------
function onSearchKey(e: KeyboardEvent) {
  if (e.key !== 'Enter') return
  e.preventDefault()
  const rows = shownZones.value.flatMap(z => z.rows)
  if (rows.length === 1) toggle({ kind: 'value', value: rows[0] })
  else if (canAdd.value) add()
}
/** Escape clears the search first; true when it did. */
function clearQuery(): boolean {
  if (!query.value && !shownParts.value.size) return false
  query.value = ''
  shownParts.value = new Set()
  return true
}
defineExpose({ clearQuery })

function focusSearch() {
  if (!allowsAutofocus.value) return
  void nextTick(() => { if (searchable.value) searchRef.value?.focusQuietly() })
}
watch(() => props.choice.id, () => {
  query.value = ''
  shownParts.value = new Set()
  writeError.value = ''
  focusSearch()
})
onMounted(focusSearch)
</script>
