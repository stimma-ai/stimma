<template>
  <!-- Under the prompt box: every part of the prompt that can vary, in the prompt's order. Its
       words, then what it does: "Varied" (open, "40 options"), what it's limited to (a person's
       picks a line each: age, gender, descent; many picks read "Korean, Irish +28"; open, "3 of
       30" with Clear), or “its words” when it can't vary; a shimmer while its first variants are
       written. Clicking a row (or the part in the prompt) opens its picker right under the row.
       A row flashes when something is used in it from an image. Then, quietly, what's worth
       adding. -->
  <div v-if="program.status.value !== 'off' && (rows.length || adds.length)" ref="rootRef" class="px-1 py-1 flex flex-col" data-slot-list>
    <div
      v-for="r in rows"
      :key="r.id"
      :class="['rounded-md transition-colors', flashId === r.id ? 'bg-selection/25 duration-75' : openId === r.id ? 'bg-overlay-subtle duration-700' : 'duration-700']"
      :data-row-wrap="r.id"
      :data-open="openId === r.id ? '' : undefined"
      :data-flash="flashId === r.id ? '' : undefined"
    >
      <div
        role="button"
        tabindex="0"
        :class="['group grid grid-cols-[minmax(0,5fr)_minmax(0,7fr)_auto] items-start gap-x-3 w-full px-2 py-1.5 coarse:py-2.5 coarse:min-h-11 rounded-md text-left text-xs coarse:text-[13px] leading-snug cursor-pointer outline-none focus-visible:ring-1 focus-visible:ring-selection/60 transition-colors duration-150',
          openId === r.id ? 'bg-selection/10 hover:bg-selection/[0.16] rounded-b-none' : 'hover:bg-overlay-subtle']"
        :data-row="r.id"
        :data-kind="r.value.kind"
        :aria-expanded="openId === r.id"
        @click="program.toggleRow(r.id)"
        @keydown.enter.self.prevent="program.toggleRow(r.id)"
        @keydown.space.self.prevent="program.toggleRow(r.id)"
      >
        <span :class="['min-w-0 break-words', openId === r.id ? 'text-content' : 'text-content-tertiary']">{{ r.words }}</span>
        <span class="min-w-0 break-words flex flex-col gap-0.5" data-value>
          <!-- An open person's picks are its Age, Gender and Descent rows, just below. -->
          <template v-if="!(openId === r.id && r.person && r.value.kind === 'restricted')">
            <span v-if="r.value.kind === 'writing'" class="inline-block align-middle w-16 h-2.5 rounded-full fluent-shimmer" aria-label="Writing" />
            <span v-else-if="r.value.kind === 'varying'" class="text-content-muted tabular-nums">{{ openId === r.id ? r.value.text : 'Varied' }}</span>
            <span v-else-if="r.value.kind === 'words'" class="text-content">{{ r.value.text }}</span>
            <span v-else class="flex flex-col text-content">
              <span v-for="(l, i) in r.value.lines" :key="i">{{ l.shown }}<span v-if="l.more" class="ml-1 text-content-tertiary tabular-nums" data-more-count>+{{ l.more }}</span></span>
            </span>
          </template>
          <!-- Open and limited: how many of the pool, and back to any. -->
          <span v-if="openId === r.id && r.of" class="flex items-center gap-1.5 text-[11px] text-content-muted tabular-nums" data-of>
            {{ r.of }}<span aria-hidden="true">·</span><button type="button" class="px-1 -mx-1 coarse:py-1 rounded text-content-tertiary hover:text-content hover:bg-overlay-subtle outline-none focus-visible:ring-1 focus-visible:ring-selection/60" data-clear @click.stop="clear(r.id)">Clear</button>
          </span>
        </span>
        <!-- Disclosure: › closed, ⌄ open. -->
        <ChevronRightIcon :class="['w-3.5 h-4 shrink-0 transition-transform duration-150 ease-out', openId === r.id ? 'rotate-90 text-content-secondary' : 'text-content-muted opacity-60 group-hover:opacity-100']" data-disclosure />
      </div>

      <Transition :css="false" @enter="grow" @leave="shrink">
        <div v-if="openId === r.id" class="overflow-hidden" data-inline-picker>
          <FluentSlotPicker :program="program" :id="r.id" class="pb-0.5" @close="program.close()" />
        </div>
      </Transition>
    </div>

    <!-- Worth adding: one quiet line, gone when there's nothing to offer. -->
    <div v-if="adds.length" class="mt-1 px-1 flex flex-nowrap items-center gap-0.5 overflow-hidden" data-slot-adds>
      <button
        v-for="a in adds"
        :key="a.name"
        type="button"
        :disabled="!!adding"
        :aria-busy="adding === a.name || undefined"
        class="shrink-0 inline-flex items-center gap-1 pl-1.5 pr-2 py-1 coarse:py-1.5 coarse:min-h-11 rounded-full text-[11px] coarse:text-xs text-content-muted hover:text-content hover:bg-overlay-subtle disabled:pointer-events-none outline-none focus-visible:ring-1 focus-visible:ring-selection/60 transition-colors"
        :data-slot-add="a.name"
        @mousedown.prevent
        @click="emit('add', a.name)"
      ><Spinner v-if="adding === a.name" size="sm" /><PlusIcon v-else class="w-3 h-3" />{{ a.label }}</button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { ChevronRightIcon, PlusIcon } from '@heroicons/vue/24/outline'
import Spinner from '../ui/Spinner.vue'
import FluentSlotPicker from './FluentSlotPicker.vue'
import { inPlayCount, optionsOf, resetState, rowValue, type RowValue } from '../../utils/programChoices'
import { slotFlash } from '../../composables/slotFlash'
import type { PromptProgram } from '../../composables/usePromptProgram'
import type { SuggestedAdd } from '../../composables/usePromptSuggestions'

const props = withDefaults(defineProps<{ program: PromptProgram; adds?: SuggestedAdd[]; adding?: string | null }>(), { adds: () => [], adding: null })
const emit = defineEmits<{ (e: 'add', name: string): void }>()

const rootRef = ref<HTMLElement | null>(null)
const openId = computed(() => props.program.openId.value)
const flashId = computed(() => slotFlash.value?.id ?? null)

interface Row { id: string; words: string; person: boolean; value: RowValue; of: string | null }
const ofText = (c: { of: number; total: number } | null) => (c ? `${c.of} of ${c.total}` : null)
const rows = computed<Row[]>(() => {
  const p = props.program
  const out: Row[] = []
  for (const s of p.slots.value) {
    if (!p.byId.value[s.id]) continue
    const pool = p.poolOf(s.id)
    const st = p.states.value[s.id]
    const value = rowValue(s, st, pool)
    const total = pool?.variants?.length ?? pool?.options?.length ?? 0
    out.push({ id: s.id, words: s.words, person: s.kind === 'person' && !!pool?.person && value.kind !== 'words', value,
      of: value.kind === 'restricted' ? ofText(inPlayCount(pool, st, total)) : null })
  }
  for (const c of p.choices.value) {
    if (c.slot) continue
    const st = p.states.value[c.id]
    const options = optionsOf(c, p.poolOf(c.id), st)
    const value = rowValue(null, st, p.poolOf(c.id), options)
    out.push({ id: c.id, words: c.label, person: false, value, of: value.kind === 'restricted' ? ofText(inPlayCount(null, st, options.length)) : null })
  }
  return out
})

/** Clear: back to any of them (the user's own variants stay). */
function clear(id: string) {
  props.program.setState(id, resetState(props.program.states.value[id]))
}

// A click outside the list closes the open row; a click on a part in the prompt switches to it.
function onOutside(e: PointerEvent) {
  if (!openId.value) return
  const t = e.target as Element | null
  if (t?.closest?.('[data-slot-list], .cm-slot-mark, .cm-list-mark')) return
  props.program.close()
}
onMounted(() => document.addEventListener('pointerdown', onOutside, true))
onUnmounted(() => document.removeEventListener('pointerdown', onOutside, true))

// Once it has opened, the open row is scrolled into view if it's below the fold.
watch(openId, (id) => {
  if (!id) return
  setTimeout(() => rootRef.value?.querySelector(`[data-row-wrap="${CSS.escape(id)}"]`)?.scrollIntoView({ block: 'nearest', behavior: 'smooth' }), 200)
})

// The inline picker opens and closes with a short height ease.
const EASE = 'height 170ms cubic-bezier(.2,.7,.3,1), opacity 140ms ease'
function grow(el: Element, done: () => void) {
  const e = el as HTMLElement
  const h = e.scrollHeight
  Object.assign(e.style, { height: '0px', opacity: '0' })
  requestAnimationFrame(() => {
    Object.assign(e.style, { transition: EASE, height: `${h}px`, opacity: '1' })
    setTimeout(() => { Object.assign(e.style, { transition: '', height: '' }); done() }, 180)
  })
}
function shrink(el: Element, done: () => void) {
  const e = el as HTMLElement
  Object.assign(e.style, { height: `${e.scrollHeight}px` })
  requestAnimationFrame(() => {
    Object.assign(e.style, { transition: EASE, height: '0px', opacity: '0' })
    setTimeout(done, 180)
  })
}
</script>

<style>
/* A value still being written: a quiet shimmer (no Tailwind utility draws a moving sheen). */
.fluent-shimmer {
  background-color: rgb(var(--color-text-muted-rgb) / 0.12);
  background-image: linear-gradient(100deg, transparent 20%, rgb(var(--color-text-muted-rgb) / 0.22) 50%, transparent 80%);
  background-size: 220% 100%;
  animation: fluent-shimmer 1.4s linear infinite;
}
@keyframes fluent-shimmer { from { background-position: 120% 0; } to { background-position: -120% 0; } }
</style>
