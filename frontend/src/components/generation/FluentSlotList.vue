<template>
  <!-- Under the prompt box: every part of the prompt that can vary, in the prompt's order. Its
       words, then what it does: "40 options" (a quiet spinner while more are written), what it's limited to (a person's
       picks a line each: age, gender, descent; many picks read "Korean, Irish +28"; open, "3 of
       30" with Clear), or “its words” when it can't vary; a shimmer while its first variants are
       written. Clicking a row (or the part in the prompt) opens its picker right under the row.
       A row flashes when something is used in it from an image. Then, quietly, what's worth
       trying. -->
  <div v-if="program.status.value !== 'off' && (rows.length || chips)" ref="rootRef" class="px-1 py-1 flex flex-col" data-slot-list>
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
        <!-- Its words; open, the slot's way right after them (Add Detail or Add Variety). -->
        <span :class="['min-w-0 break-words', openId === r.id ? 'text-content' : 'text-content-tertiary']" data-words>{{ r.words }}<FluentSlotWay v-if="openId === r.id && r.slot && r.wayShown" :program="program" :id="r.id" :slot-kind="slotKind" @vary-slot="(s) => emit('vary-slot', s)" /></span>
        <span class="min-w-0 break-words flex flex-col gap-0.5" data-value>
          <!-- An open person's picks are its Age, Gender and Descent rows, just below. -->
          <template v-if="!(openId === r.id && r.person && r.value.kind === 'restricted')">
            <!-- Its first options being written: a shimmer as tall as a line of text, so the row
                 keeps its height when the count arrives. -->
            <span v-if="r.value.kind === 'writing'" class="flex items-center h-[1.375em]" aria-label="Writing"><span class="w-16 h-2.5 rounded-full fluent-shimmer" /></span>
            <!-- The count, and while more are written a small spinner in a place kept for it. -->
            <span v-else-if="r.value.kind === 'varying'" class="inline-flex items-center gap-1.5 text-content-muted tabular-nums">{{ r.value.text }}<span class="w-2 h-2 shrink-0"><span v-if="r.value.more" class="block w-2 h-2 rounded-full border border-content-muted/25 border-t-content-muted/70 animate-spin" aria-label="Writing more" data-more-spinner /></span></span>
            <span v-else-if="r.value.kind === 'words'" class="text-content">{{ r.value.text }}</span>
            <span v-else class="flex flex-col text-content">
              <span v-for="(l, i) in r.value.lines" :key="i">{{ l.shown }}<span v-if="l.more" class="ml-1 text-content-tertiary tabular-nums" data-more-count>+{{ l.more }}</span></span>
            </span>
          </template>
          <!-- Couldn't be varied (its reading or its variants failed, nothing the user chose):
               quietly, with one way to try again. -->
          <span v-if="r.value.kind === 'words' && r.value.failed" class="flex items-center gap-1.5 text-[11px] text-content-muted" data-failed>
            {{ program.unreachable.value ? 'Can’t reach your chat model' : 'Couldn’t vary this' }}<span aria-hidden="true">·</span><button type="button" :disabled="program.retrying.value" class="px-1 -mx-1 coarse:py-1 rounded text-content-tertiary hover:text-content hover:bg-overlay-subtle disabled:opacity-50 disabled:pointer-events-none outline-none focus-visible:ring-1 focus-visible:ring-selection/60" data-retry @click.stop="program.retrySlots()">Try again</button>
          </span>
          <!-- Open and limited: how many of the pool, and back to any. -->
          <span v-if="openId === r.id && r.of" class="flex items-center gap-1.5 text-[11px] text-content-muted tabular-nums" data-of>
            {{ r.of }}<span aria-hidden="true">·</span><button type="button" class="px-1 -mx-1 coarse:py-1 rounded text-content-tertiary hover:text-content hover:bg-overlay-subtle outline-none focus-visible:ring-1 focus-visible:ring-selection/60" data-clear @click.stop="clear(r.id)">Clear</button>
          </span>
        </span>
        <!-- Open, Remove (the brackets come off, its words stay); then the disclosure, › closed,
             ⌄ open. Remove's place is kept on every row, so a row doesn't shift as it opens. -->
        <span class="flex items-start gap-1.5">
          <button
            type="button"
            :class="['-my-0.5 p-0.5 coarse:-my-2 coarse:p-2 rounded text-content-muted hover:text-content hover:bg-overlay-subtle outline-none focus-visible:ring-1 focus-visible:ring-selection/60', openId === r.id && r.slot ? '' : 'invisible']"
            :tabindex="openId === r.id && r.slot ? 0 : -1"
            :aria-hidden="openId === r.id && r.slot ? undefined : 'true'"
            title="Remove"
            aria-label="Remove"
            data-remove-slot
            @click.stop="removeSlot(r.id)"
            @keydown.stop
          ><XMarkIcon class="w-3.5 h-3.5" /></button>
          <ChevronRightIcon :class="['w-3.5 h-4 shrink-0 transition-transform duration-150 ease-out', openId === r.id ? 'rotate-90 text-content-secondary' : 'text-content-muted opacity-60 group-hover:opacity-100']" />
        </span>
      </div>

      <Transition :css="false" @enter="grow" @leave="shrink">
        <div v-if="openId === r.id" class="overflow-hidden" data-inline-picker>
          <FluentSlotPicker :program="program" :id="r.id"  class="pb-0.5" @close="program.close()" />
        </div>
      </Transition>
    </div>

    <!-- Suggestions: one quiet row, gone when there's nothing to offer. Phrases first, each
         named by Suggest's label: Add Detail keeps the words and makes each picture a specific
         one ("Add Detail: dog"), Add Variety lets in others of their kind ("Add Variety:
         hairstyle"); then + chips, each a slot to write in (the camera, a face). -->
    <div v-if="chips" class="mt-1 px-1 flex flex-wrap items-center gap-x-3 gap-y-0.5" data-slot-adds>
      <div v-if="s.phrases.length" class="flex flex-wrap items-center gap-0.5" data-suggest-group="phrases">
        <button
          v-for="p in s.phrases"
          :key="`p${p.from}`"
          type="button"
          :class="chipClass"
          :data-slot-vary="p.text"
          :data-way="p.way"
          @mousedown.prevent
          @click="emit('vary', p)"
        ><ArrowsPointingOutIcon v-if="p.way === 'any'" class="w-3 h-3 text-selection" /><ArrowsPointingInIcon v-else class="w-3 h-3 text-selection" />{{ phraseLabel(p) }}</button>
      </div>
      <div v-if="s.adds.length" class="flex flex-wrap items-center gap-0.5" data-suggest-group="adds">
        <button
          v-for="a in s.adds"
          :key="a.key"
          type="button"
          :class="chipClass"
          :data-slot-add="a.key"
          @mousedown.prevent
          @click="emit('add', a)"
        ><PlusIcon class="w-3 h-3" />{{ a.label }}</button>
      </div>
      <!-- An answer on its way: placeholders the first time, one quiet pill after the chips
           that stay while it comes. -->
      <div v-if="s.loading" class="flex items-center gap-1.5 py-1 coarse:py-1.5" data-suggest-loading aria-label="Finding suggestions">
        <span v-for="w in (s.phrases.length + s.adds.length ? [40] : [64, 56, 44])" :key="w" class="inline-block h-3 rounded-full fluent-shimmer" :style="{ width: `${w}px` }" />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { ArrowsPointingInIcon, ArrowsPointingOutIcon, ChevronRightIcon, PlusIcon, XMarkIcon } from '@heroicons/vue/24/outline'
import FluentSlotPicker from './FluentSlotPicker.vue'
import FluentSlotWay from './FluentSlotWay.vue'
import { inPlayCount, optionsOf, resetState, rowValue, type RowValue } from '../../utils/programChoices'
import { slotFlash } from '../../composables/slotFlash'
import type { PromptProgram } from '../../composables/usePromptProgram'
import { phraseLabel, type SuggestedAdd, type SuggestedPhrase, type Suggestions } from '../../composables/usePromptSuggestions'

const props = defineProps<{
  program: PromptProgram; suggestions?: Suggestions | null
  /** The kind of a slot's words, for the picker's Add Variety (the prompt editor's slotKind). */
  slotKind?: (slot: { n: number; words: string }) => Promise<string>
}>()
const emit = defineEmits<{
  (e: 'vary', phrase: SuggestedPhrase): void
  (e: 'add', add: SuggestedAdd): void
  (e: 'remove-slot', slot: { n: number; words: string }): void
  (e: 'vary-slot', slot: { n: number; words: string; kind: string }): void
}>()

const s = computed<Suggestions>(() => props.suggestions ?? { phrases: [], adds: [] })
const chips = computed(() => s.value.phrases.length + s.value.adds.length > 0 || !!s.value.loading)
const chipClass = 'shrink-0 inline-flex items-center gap-1 pl-1.5 pr-2 py-1 coarse:py-1.5 coarse:min-h-11 rounded-full text-[11px] coarse:text-xs text-content-muted hover:text-content hover:bg-overlay-subtle outline-none focus-visible:ring-1 focus-visible:ring-selection/60 transition-colors'

const rootRef = ref<HTMLElement | null>(null)
const openId = computed(() => props.program.openId.value)
const flashId = computed(() => slotFlash.value?.id ?? null)

/** `slot`: a slot (not a list of the user's own), so it has a way and can be removed; `wayShown`:
    its way can be told (not while it is first being read, unless the user chose one). */
interface Row { id: string; words: string; person: boolean; value: RowValue; of: string | null; slot: boolean; wayShown: boolean }
const ofText = (c: { of: number; total: number } | null) => (c ? `${c.of} of ${c.total}` : null)
/** Each slot's last count while it varied, by id and words (display only). */
const lastCount = new Map<string, string>()
const rows = computed<Row[]>(() => {
  const p = props.program
  const out: Row[] = []
  for (const s of p.slots.value) {
    if (!p.byId.value[s.id]) continue
    const pool = p.poolOf(s.id)
    const st = p.states.value[s.id]
    let value = rowValue(s, st, pool)
    // Read again (a new way, a retry): the count it had stays, with the spinner, rather than
    // the first-write shimmer coming back.
    const key = `${s.id}:${s.words}`
    if (value.kind === 'varying') lastCount.set(key, value.text)
    else if (value.kind === 'writing' && lastCount.has(key)) value = { kind: 'varying', text: lastCount.get(key)!, more: true }
    const total = pool?.variants?.length ?? pool?.options?.length ?? 0
    out.push({ id: s.id, words: s.words, person: s.kind === 'person' && !!pool?.person && value.kind !== 'words', value,
      of: value.kind === 'restricted' ? ofText(inPlayCount(pool, st, total)) : null,
      slot: true, wayShown: s.state !== 'reading' || !!st?.mode })
  }
  for (const c of p.choices.value) {
    if (c.slot) continue
    const st = p.states.value[c.id]
    const options = optionsOf(c, p.poolOf(c.id), st)
    const value = rowValue(null, st, p.poolOf(c.id), options)
    out.push({ id: c.id, words: c.label, person: false, value, of: value.kind === 'restricted' ? ofText(inPlayCount(null, st, options.length)) : null, slot: false, wayShown: false })
  }
  return out
})

/** Take a slot's brackets off (its words stay), closing its row. */
function removeSlot(id: string) {
  const s = props.program.slotById.value[id]
  if (!s) return
  props.program.close()
  emit('remove-slot', { n: s.n, words: s.words })
}

/** Clear: back to any of them (the user's own variants stay). */
function clear(id: string) {
  props.program.setState(id, resetState(props.program.states.value[id]))
}

// A click outside the list closes the open row; a click on a part in the prompt switches to it.
function onOutside(e: PointerEvent) {
  if (!openId.value) return
  const t = e.target as Element | null
  if (t?.closest?.('[data-slot-list], [data-slot-way-menu], .cm-slot-mark, .cm-list-mark')) return
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
