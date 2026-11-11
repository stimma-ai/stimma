<template>
  <!-- A pick's options: tick to limit the draw (shift-click ticks a range), trash to
       delete, a field to add your own.
       Long lists (and any pick drawn from a list) get a search field and a scrolling
       list; list-drawn picks group their values from usual to rare. Ticked values always
       come first, whatever the search. -->
  <div class="min-h-0 flex flex-col">
    <template v-if="many">
      <div class="px-2 pb-1.5" @keydown="onSearchKey">
        <SearchField ref="searchRef" v-model="query" placeholder="Search options" />
      </div>
      <div v-if="vocab" class="px-3.5 pb-1 flex items-baseline gap-2 text-[11px] text-content-muted">
        <span class="flex-1 min-w-0 truncate">{{ listName }}</span>
        <span class="font-mono tabular-nums">{{ opts.length }}</span>
      </div>
    </template>

    <div
      ref="listRef"
      :class="['min-h-0 overflow-y-auto overscroll-contain px-1.5 pb-1.5 flex flex-col gap-px', many ? 'max-h-[min(26rem,50dvh)]' : '']"
    >
      <template v-for="e in entries" :key="e.key">
        <button
          v-if="e.type === 'group'"
          type="button"
          :aria-expanded="e.open"
          :data-group="e.group.tier"
          class="mt-1 first:mt-0 flex items-center gap-1.5 px-2 py-1 coarse:py-2.5 rounded-md text-xs font-semibold text-content-secondary hover:text-content hover:bg-overlay-subtle outline-none focus-visible:ring-1 focus-visible:ring-selection/60"
          @click="toggleGroup(e.group.tier, e.open)"
        >
          <Caret :open="e.open" class="opacity-70" />
          <span class="flex-1 text-left">{{ e.group.label }}</span>
          <span class="font-mono tabular-nums font-normal text-content-muted">{{ query.trim() ? e.group.items.length : e.group.total }}</span>
        </button>
        <div
          v-else-if="e.type === 'empty'"
          class="px-2 py-1.5 coarse:py-2.5 text-xs coarse:text-[13px] text-content-muted"
        >No matches</div>
        <button
          v-else-if="e.type === 'add'"
          type="button"
          class="flex items-center gap-2.5 px-2 py-1.5 coarse:py-2.5 rounded-md text-left text-xs coarse:text-[13px] text-content-secondary hover:text-content hover:bg-overlay-subtle outline-none focus-visible:ring-1 focus-visible:ring-selection/60"
          @click="add(query)"
        >
          <PlusIcon class="shrink-0 w-3.5 h-3.5 text-content-muted" />
          <span class="min-w-0 break-words">Add “{{ query.trim() }}”</span>
        </button>
        <div
          v-else
          :data-option="e.value"
          role="checkbox"
          :aria-checked="pinned.has(e.value)"
          tabindex="0"
          :class="['group/opt flex items-start gap-2.5 px-2 py-1.5 coarse:py-2.5 rounded-md cursor-pointer outline-none focus-visible:ring-1 focus-visible:ring-selection/60',
            pinned.has(e.value) ? 'bg-selection/10' : 'hover:bg-overlay-subtle']"
          @mousedown="onOptionMouseDown"
          @click="onOptionClick(e.value, $event)"
          @keydown.space.self.prevent="toggle(e.value)"
          @keydown.enter.self.prevent="toggle(e.value)"
        >
          <span
            :class="['mt-[2px] shrink-0 w-3.5 h-3.5 rounded-[4px] flex items-center justify-center border',
              pinned.has(e.value) ? 'bg-selection border-selection text-white' : 'border-edge-strong']"
          >
            <CheckIcon v-if="pinned.has(e.value)" class="w-2.5 h-2.5" stroke-width="3" />
          </span>
          <span :class="['flex-1 min-w-0 text-xs coarse:text-[13px] leading-snug break-words', pinned.has(e.value) ? 'text-content' : 'text-content-secondary group-hover/opt:text-content']">
            {{ shownOption(e.value) }}<span v-if="trigger(e.value)" class="ml-1.5 font-mono text-[10px] text-content-muted">{{ trigger(e.value) }}</span>
          </span>
          <button
            v-if="deletable && canDelete(props.choice, e.value)"
            type="button"
            title="Delete option"
            :aria-label="`Delete ${e.value}`"
            class="shrink-0 -my-0.5 p-0.5 rounded text-content-muted hover:text-red-400 opacity-0 group-hover/opt:opacity-100 focus-visible:opacity-100 coarse:opacity-100"
            @click.stop="del(e.value)"
          >
            <TrashIcon class="w-3.5 h-3.5" />
          </button>
        </div>
      </template>
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
import { CheckIcon, PlusIcon, TrashIcon } from '@heroicons/vue/24/outline'
import SearchField from '../ui/SearchField.vue'
import Caret from '../ui/Caret.vue'
import { useViewport } from '../../composables/useViewport'
import { MANY_OPTIONS, groupOpen, layoutOptions, type OptionGroup, shownOption } from '../../utils/programVocab'
import { deletable as canDelete, pinsFor, ticksOf, toggleTick } from '../../utils/programTicks'
import type { PromptProgram, ProgramChoice } from '../../composables/usePromptProgram'

const props = defineProps<{
  choice: ProgramChoice
  program: PromptProgram
  deletable?: boolean
  addable?: boolean
}>()

const { allowsAutofocus } = useViewport()

const query = ref('')
const draft = ref('')
// Tier groups the person opened or closed (Usual starts open, the rest closed).
const opened = ref<Record<string, boolean>>({})
const listRef = ref<HTMLElement | null>(null)
const searchRef = ref<InstanceType<typeof SearchField> | null>(null)

const opts = computed(() => props.program.optionsOf(props.choice))
// What the card shows ticked: the pins, or for a choice that stands for the user's own words,
// those words (each image uses them until other options are ticked).
const pinned = computed(() => ticksOf(props.choice, props.program.pins.value[props.choice.id], opts.value))
const edit = computed(() => props.program.edits.value[props.choice.id] || {})
const vocab = computed(() => props.program.vocabOf(props.choice))
const many = computed(() => !!vocab.value || !!props.choice.cls || opts.value.length > MANY_OPTIONS)
const listName = computed(() => {
  const label = vocab.value?.label || ''
  return /\blist$/i.test(label) ? label : `${label} list`
})

type Entry =
  | { type: 'option'; key: string; value: string }
  | { type: 'group'; key: string; group: OptionGroup; open: boolean }
  | { type: 'empty'; key: string }
  | { type: 'add'; key: string }

const layout = computed(() => many.value
  ? layoutOptions(opts.value, pinned.value, query.value, vocab.value?.tiers)
  : null)

const entries = computed<Entry[]>(() => {
  const l = layout.value
  const opt = (value: string): Entry => ({ type: 'option', key: `o:${value}`, value })
  if (!l) return opts.value.map(opt)
  const out: Entry[] = l.pinned.map(opt)
  if (l.groups.length) {
    for (const g of l.groups) {
      const open = groupOpen(g, query.value, opened.value)
      // While searching, groups without a hit drop out of the way.
      if (query.value.trim() && !g.items.length) continue
      out.push({ type: 'group', key: `g:${g.tier}`, group: g, open })
      if (open) out.push(...g.items.map(opt))
    }
  } else {
    out.push(...l.flat.map(opt))
  }
  const q = query.value.trim()
  // Nothing matches: say so, and offer the search as an option of its own.
  if (q && !l.hits) {
    out.push({ type: 'empty', key: 'empty' })
    if (props.addable && !opts.value.includes(q)) out.push({ type: 'add', key: 'add' })
  }
  return out
})

function toggleGroup(tier: string, open: boolean) {
  opened.value = { ...opened.value, [tier]: !open }
}

// A different pick in the same card (a person's detail): start fresh.
watch(() => props.choice.id, () => {
  query.value = ''
  draft.value = ''
  opened.value = {}
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

function toggle(o: string) {
  props.program.setPins(props.choice.id, toggleTick(props.choice, props.program.pins.value[props.choice.id], opts.value, o))
  anchor.value = o
}

// Shift-click ticks (or unticks) every shown option between the last one clicked and
// this one. Ticked options float to the top of long lists, so the range is measured in
// the list's untouched order, the one you see before anything is ticked.
const anchor = ref<string | null>(null)
const naturalOrder = computed(() => {
  if (!many.value) return opts.value
  const l = layoutOptions(opts.value, [], '', vocab.value?.tiers)
  return l.groups.length ? l.groups.flatMap(g => g.items) : l.flat
})

function onOptionMouseDown(e: MouseEvent) {
  // Keep shift-click from selecting the text in between.
  if (e.shiftKey) e.preventDefault()
}

function onOptionClick(o: string, e: MouseEvent) {
  const order = naturalOrder.value
  const from = anchor.value ? order.indexOf(anchor.value) : -1
  const to = order.indexOf(o)
  if (!e.shiftKey || from < 0 || to < 0) { toggle(o); return }
  const shown = new Set(entries.value.flatMap(x => x.type === 'option' ? [x.value] : []))
  const range = order.slice(Math.min(from, to), Math.max(from, to) + 1).filter(x => shown.has(x))
  const on = !pinned.value.has(o)
  const next = new Set(pinned.value)
  for (const x of range) on ? next.add(x) : next.delete(x)
  props.program.setPins(props.choice.id, pinsFor(props.choice, next, opts.value))
  anchor.value = o
}

function del(o: string) {
  // One the user added just goes; anything else (seeds, list values and generated options
  // alike) is remembered as deleted for this pick, which keeps its id through prompt edits.
  const e = edit.value
  const userAdded = props.program.isOwn(props.choice, o)
  if (userAdded) void props.program.keepAddition(props.choice, o, false)
  const added = (e.add || []).filter(x => x !== o)
  const removed = userAdded ? e.remove : [...new Set([...(e.remove || []), o])]
  props.program.setEdit(props.choice.id, { ...e, add: added, remove: removed })
  props.program.setPins(props.choice.id, pinsFor(props.choice, [...pinned.value].filter(x => x !== o), opts.value))
}

function add(text: string) {
  const v = text.trim()
  if (!v || opts.value.includes(v)) return
  props.program.setEdit(props.choice.id, { ...edit.value, add: [...(edit.value.add || []), v] })
  void props.program.keepAddition(props.choice, v)
  void nextTick(() => {
    const list = listRef.value
    if (!list) return
    if (!many.value) { list.scrollTo({ top: list.scrollHeight }); return }
    const row = [...list.querySelectorAll<HTMLElement>('[data-option]')].find(r => r.dataset.option === v)
    row?.scrollIntoView({ block: 'nearest' })
  })
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
    const l = layout.value
    if (!l) return
    e.preventDefault()
    const hits = [...l.flat, ...l.groups.flatMap(g => g.items)]
    if (hits.length === 1) toggle(hits[0])
    else if (!hits.length && props.addable) { add(query.value); query.value = '' }
  }
}
</script>
