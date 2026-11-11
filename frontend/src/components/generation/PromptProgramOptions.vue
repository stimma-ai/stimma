<template>
  <!-- A pick's options, one flat list in the list's own order. A tick means the option can
       be drawn: everything starts ticked, unticking leaves a value out (shift-click does a
       range). Search and the list's parts only change what is shown; the All row and
       "Only these" then act on what is shown. A long list renders its first rows and is
       narrowed by searching.
       A list-bound choice the server places (programReach.ts) swaps the All row for its
       settings ("Just Irish · Similar 3 · Any 105"; the lit one is what a run draws from) and
       lists what fits first, then the rest after a "Beyond your prompt" line that stays in
       view until scrolled to. While searching, the All row is back: it acts on what is shown. -->
  <div class="min-h-0 flex flex-col">
    <div v-if="many" class="px-2 pb-1.5" @keydown="onSearchKey">
      <SearchField ref="searchRef" v-model="query" placeholder="Search" />
    </div>

    <div v-if="parts" class="px-2 pb-1.5 flex flex-wrap gap-1" role="group" :aria-label="partLabel(parts.name)">
      <button
        v-for="p in parts.values"
        :key="p"
        type="button"
        :aria-pressed="part === p"
        :data-part="p"
        :class="['px-2.5 py-0.5 coarse:py-1.5 rounded-full text-xs coarse:text-[13px] border transition-colors outline-none focus-visible:ring-1 focus-visible:ring-selection/60',
          part === p ? 'bg-selection/15 text-selection border-selection/40' : 'bg-surface-raised border-transparent text-content-secondary hover:text-content hover:bg-surface-hover']"
        @click="picked = part === p ? '' : p"
      >{{ partLabel(p) }}</button>
    </div>

    <div v-if="segmented" class="px-1.5 pb-1">
      <SegmentedControl block :model-value="lit" :options="segments" aria-label="Draw from" @update:model-value="choose" />
    </div>

    <div v-else class="px-1.5">
      <div
        data-all
        role="checkbox"
        :aria-checked="allState === 'some' ? 'mixed' : allState === 'all'"
        tabindex="0"
        class="flex items-center gap-2.5 px-2 py-1.5 coarse:py-2.5 rounded-md cursor-pointer hover:bg-overlay-subtle outline-none focus-visible:ring-1 focus-visible:ring-selection/60"
        @click="toggleAll"
        @keydown.space.self.prevent="toggleAll"
        @keydown.enter.self.prevent="toggleAll"
      >
        <span :class="[boxClass, allState === 'none' ? 'border-edge-strong' : 'bg-selection border-selection text-white']">
          <CheckIcon v-if="allState === 'all'" class="w-2.5 h-2.5" stroke-width="3" />
          <MinusIcon v-else-if="allState === 'some'" class="w-2.5 h-2.5" stroke-width="3" />
        </span>
        <span class="flex-1 min-w-0 text-xs coarse:text-[13px] text-content-secondary">{{ filtered ? `All ${count(seen.length)} shown` : 'All' }}</span>
        <button
          v-if="filtered && seen.length"
          type="button"
          class="shrink-0 -my-0.5 px-1.5 py-0.5 coarse:py-1.5 rounded-md text-xs coarse:text-[13px] text-accent hover:bg-overlay-subtle outline-none focus-visible:ring-1 focus-visible:ring-selection/60"
          @click.stop="onlyThese"
        >Only these</button>
      </div>
    </div>

    <div
      ref="listRef"
      :class="['min-h-0 overflow-y-auto overscroll-contain px-1.5 pb-1.5 flex flex-col gap-px', many ? 'max-h-[min(26rem,50dvh)]' : '']"
    >
      <template v-for="o in rows" :key="o">
      <div
        v-if="o === firstBeyond"
        data-beyond
        class="sticky -bottom-1.5 z-[1] flex items-center gap-2 px-2 pt-2.5 pb-1 bg-surface"
      >
        <span class="text-[11px] text-content-muted">Beyond your prompt</span>
        <span class="h-px flex-1 bg-edge-subtle" />
        <span class="text-[11px] text-content-muted font-mono tabular-nums">{{ count(beyondShown) }}</span>
      </div>
      <div
        :data-option="o"
        role="checkbox"
        :aria-checked="ticks.has(o)"
        tabindex="0"
        class="group/opt flex items-start gap-2.5 px-2 py-1.5 coarse:py-2.5 rounded-md cursor-pointer hover:bg-overlay-subtle outline-none focus-visible:ring-1 focus-visible:ring-selection/60"
        @mousedown="onOptionMouseDown"
        @click="onOptionClick(o, $event)"
        @keydown.space.self.prevent="toggle(o)"
        @keydown.enter.self.prevent="toggle(o)"
      >
        <span :class="[boxClass, 'mt-[2px]', ticks.has(o) ? 'bg-selection border-selection text-white' : 'border-edge-strong']">
          <CheckIcon v-if="ticks.has(o)" class="w-2.5 h-2.5" stroke-width="3" />
        </span>
        <span :class="['flex-1 min-w-0 text-xs coarse:text-[13px] leading-snug break-words', ticks.has(o) ? 'text-content' : 'text-content-muted']">
          {{ shownOption(o) }}<span v-if="trigger(o)" class="ml-1.5 font-mono text-[10px] text-content-muted">{{ trigger(o) }}</span>
        </span>
        <button
          type="button"
          :aria-label="`Only ${shownOption(o)}`"
          class="shrink-0 -my-0.5 px-1.5 py-0.5 rounded-md text-xs coarse:text-[13px] text-content-secondary hover:text-content hover:bg-overlay-subtle opacity-0 group-hover/opt:opacity-100 group-focus-within/opt:opacity-100 coarse:opacity-100 outline-none focus-visible:ring-1 focus-visible:ring-selection/60"
          @click.stop="only(o)"
        >Only</button>
        <button
          v-if="program.isOwn(choice, o)"
          type="button"
          title="Delete option"
          :aria-label="`Delete ${shownOption(o)}`"
          class="shrink-0 -my-0.5 p-0.5 rounded text-content-muted hover:text-red-400 opacity-0 group-hover/opt:opacity-100 group-focus-within/opt:opacity-100 coarse:opacity-100"
          @click.stop="forget(o)"
        >
          <TrashIcon class="w-3.5 h-3.5" />
        </button>
      </div>
      </template>
      <template v-if="!seen.length && filtered">
        <div class="px-2 py-1.5 coarse:py-2.5 text-xs coarse:text-[13px] text-content-muted">No matches</div>
        <button
          v-if="canAddQuery"
          type="button"
          class="flex items-center gap-2.5 px-2 py-1.5 coarse:py-2.5 rounded-md text-left text-xs coarse:text-[13px] text-content-secondary hover:text-content hover:bg-overlay-subtle outline-none focus-visible:ring-1 focus-visible:ring-selection/60"
          @click="addQuery"
        >
          <PlusIcon class="shrink-0 w-3.5 h-3.5 text-content-muted" />
          <span class="min-w-0 break-words">Add “{{ query.trim() }}”</span>
        </button>
      </template>
      <div v-if="seen.length > rows.length" data-more class="px-2 pt-1.5 text-[11px] text-content-muted font-mono tabular-nums">
        {{ count(rows.length) }} of {{ count(seen.length) }}
      </div>
    </div>

    <div v-if="addable" class="px-1.5 pb-1.5">
      <div class="flex items-center gap-2.5 px-2 py-1 rounded-md focus-within:bg-overlay-subtle">
        <PlusIcon class="shrink-0 w-3.5 h-3.5 text-content-muted" />
        <input
          class="flex-1 min-w-0 bg-transparent text-xs coarse:text-[13px] text-content placeholder:text-content-muted outline-none py-0.5"
          placeholder="Add your own…"
          :value="draft"
          @input="draft = ($event.target as HTMLInputElement).value"
          @keydown.enter="commit"
          @keydown.esc="onDraftEscape"
          @blur="commit"
        >
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { CheckIcon, MinusIcon, PlusIcon, TrashIcon } from '@heroicons/vue/24/outline'
import SearchField from '../ui/SearchField.vue'
import SegmentedControl from '../ui/SegmentedControl.vue'
import { useViewport } from '../../composables/useViewport'
import { MANY_OPTIONS, MAX_ROWS, partLabel, shownOption, shownOptions, standbyOf } from '../../utils/programVocab'
import { stateFor, ticksOf } from '../../utils/programTicks'
import { litSetting, reachOrder, reachSettings, ticksForSetting, type ReachKey } from '../../utils/programReach'
import type { PromptProgram, ProgramChoice } from '../../composables/usePromptProgram'

const props = defineProps<{
  choice: ProgramChoice
  program: PromptProgram
  addable?: boolean
}>()

const { allowsAutofocus } = useViewport()

const boxClass = 'shrink-0 w-3.5 h-3.5 rounded-[4px] flex items-center justify-center border'
const count = (n: number) => n.toLocaleString('en-US')

const query = ref('')
const draft = ref('')
const picked = ref('')
const listRef = ref<HTMLElement | null>(null)
const searchRef = ref<InstanceType<typeof SearchField> | null>(null)

const opts = computed(() => props.program.optionsOf(props.choice))
const edit = computed(() => props.program.edits.value[props.choice.id] || {})
const vocab = computed(() => props.program.vocabOf(props.choice))
// Values drawn only when ticked (a list's opt-in values) start unticked, and the All row
// and "Only these" leave them alone unless they are all that is shown.
const standby = computed(() => standbyOf(vocab.value))
const ticks = computed(() => ticksOf(props.choice, props.program.pins.value[props.choice.id], edit.value, opts.value, standby.value))
const many = computed(() => !!vocab.value || !!props.choice.cls || opts.value.length > MANY_OPTIONS)

const parts = computed(() => vocab.value?.parts?.values.length ? vocab.value.parts : null)
const part = computed(() => parts.value?.values.includes(picked.value) ? picked.value : '')
const filtered = computed(() => !!query.value.trim() || !!part.value)

// How far the choice reaches, as the server placed its options: the settings row, and the
// list split into what fits and what is beyond the prompt.
const own = computed(() => new Set(opts.value.filter(o => props.program.isOwn(props.choice, o))))
const reach = computed(() => vocab.value?.reach || null)
const settings = computed(() => reachSettings(reach.value, opts.value, own.value))
const segmented = computed(() => settings.value.length > 1 && !filtered.value)
const lit = computed(() => litSetting(settings.value, ticks.value, standby.value))
const segments = computed(() => {
  const out: Array<{ label: string; value: string; count?: number }> = settings.value.map(s => ({
    label: s.label, value: s.key, count: s.values.length > 1 ? s.values.length : undefined,
  }))
  // Ticks that match no setting read as the person's own selection, lit first.
  if (lit.value === 'yours') out.unshift({ label: 'Yours', value: 'yours', count: [...ticks.value].filter(t => !own.value.has(t)).length })
  if (lit.value === 'none') out.unshift({ label: 'None', value: 'none' })
  return out
})
function choose(key: string | number) {
  if (key === 'yours' || key === 'none' || key === lit.value) return
  write(ticksForSetting(settings.value, key as ReachKey, ticks.value, standby.value))
}
const split = computed(() => reachOrder(opts.value, reach.value, own.value))
const beyond = computed(() => new Set(split.value.beyond))

// The list's own order (what fits first, when the choice is placed). In a list too long to
// show whole, the person's own additions lead, so one just added is in view.
const order = computed(() => {
  if (beyond.value.size) return [...split.value.inside, ...split.value.beyond]
  if (opts.value.length <= MAX_ROWS || !edit.value.add?.length) return opts.value
  const own = new Set(edit.value.add)
  return [...opts.value.filter(o => own.has(o)), ...opts.value.filter(o => !own.has(o))]
})
const seen = computed(() => shownOptions(order.value, query.value, part.value, parts.value))
const rows = computed(() => seen.value.length > MAX_ROWS ? seen.value.slice(0, MAX_ROWS) : seen.value)
const firstBeyond = computed(() => rows.value.find(o => beyond.value.has(o)) ?? null)
const beyondShown = computed(() => seen.value.filter(o => beyond.value.has(o)).length)
const bulk = computed(() => {
  if (!standby.value.size) return seen.value
  const regular = seen.value.filter(o => !standby.value.has(o))
  return regular.length ? regular : seen.value
})
const allState = computed<'all' | 'some' | 'none'>(() => {
  const on = ticks.value
  if (bulk.value.length && bulk.value.every(o => on.has(o))) return 'all'
  return seen.value.some(o => on.has(o)) ? 'some' : 'none'
})
const canAddQuery = computed(() => {
  const q = query.value.trim()
  return !!q && !!props.addable && !opts.value.includes(q)
})

// A different pick in the same card (a person's detail): start fresh.
watch(() => props.choice.id, () => {
  query.value = ''
  draft.value = ''
  picked.value = ''
  anchor.value = null
  focusSearch()
})
onMounted(focusSearch)
function focusSearch() {
  if (!allowsAutofocus.value) return
  void nextTick(() => { if (many.value) searchRef.value?.focusQuietly() })
}

const lora = (name: string) => props.program.program.value?.loras.find(l => l.name === name)
function trigger(o: string): string {
  return props.choice.kind === 'lora' ? (lora(o)?.trigger || '').split(',')[0] : ''
}

function write(next: Iterable<string>) {
  props.program.setTicks(props.choice.id, stateFor(props.choice, next, opts.value, standby.value))
}

function toggle(o: string) {
  const next = new Set(ticks.value)
  next.has(o) ? next.delete(o) : next.add(o)
  write(next)
  anchor.value = o
}

// One of the person's own options (typed here, or kept for this list from an earlier prompt)
// can be forgotten: it leaves this choice and the list.
function forget(o: string) {
  const e = edit.value
  void props.program.keepAddition(props.choice, o, false)
  const rest = opts.value.filter(x => x !== o)
  props.program.setTicks(props.choice.id, stateFor(props.choice, [...ticks.value].filter(x => x !== o), rest, standby.value),
    { ...e, add: (e.add || []).filter(x => x !== o) })
}

function only(o: string) {
  write([o])
  anchor.value = o
}

function toggleAll() {
  const next = new Set(ticks.value)
  if (allState.value === 'all') for (const o of seen.value) next.delete(o)
  else for (const o of bulk.value) next.add(o)
  write(next)
}

function onlyThese() {
  write(bulk.value)
}

// Shift-click ticks (or unticks) every shown option between the last one clicked and
// this one. The range is measured in the whole list, so it can start from an option the
// search has since hidden.
const anchor = ref<string | null>(null)

function onOptionMouseDown(e: MouseEvent) {
  // Keep shift-click from selecting the text in between.
  if (e.shiftKey) e.preventDefault()
}

function onOptionClick(o: string, e: MouseEvent) {
  const all = order.value
  const from = anchor.value ? all.indexOf(anchor.value) : -1
  const to = all.indexOf(o)
  if (!e.shiftKey || from < 0 || to < 0) { toggle(o); return }
  const shown = new Set(seen.value)
  const on = !ticks.value.has(o)
  const next = new Set(ticks.value)
  for (const x of all.slice(Math.min(from, to), Math.max(from, to) + 1)) {
    if (!shown.has(x)) continue
    on ? next.add(x) : next.delete(x)
  }
  write(next)
  anchor.value = o
}

// The person's own option joins the list ticked, whatever else is, and is kept for this
// list so later prompts offer it too.
function add(text: string) {
  const v = text.trim()
  if (!v || opts.value.includes(v)) return
  const e = edit.value
  const next = { ...e, add: [...(e.add || []), v], remove: (e.remove || []).filter(x => x !== v) }
  props.program.setTicks(props.choice.id, stateFor(props.choice, [...ticks.value, v], [...opts.value, v], standby.value), next)
  void props.program.keepAddition(props.choice, v)
  void nextTick(() => {
    const list = listRef.value
    if (!list) return
    const row = [...list.querySelectorAll<HTMLElement>('[data-option]')].find(r => r.dataset.option === v)
    row?.scrollIntoView({ block: 'nearest' })
  })
}

function addQuery() {
  add(query.value)
  query.value = ''
}

function commit() {
  add(draft.value)
  draft.value = ''
}

function onDraftEscape(e: KeyboardEvent) {
  if (!draft.value) return
  draft.value = ''
  e.stopPropagation()
}

function onSearchKey(e: KeyboardEvent) {
  if (e.key === 'Escape' && query.value) {
    // Clear the search first; the next Escape is the card's.
    query.value = ''
    e.stopPropagation()
    e.preventDefault()
  } else if (e.key === 'Enter') {
    e.preventDefault()
    if (seen.value.length === 1) toggle(seen.value[0])
    else if (!seen.value.length && canAddQuery.value) addQuery()
  }
}
</script>
