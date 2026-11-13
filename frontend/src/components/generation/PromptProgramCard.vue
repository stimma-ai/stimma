<template>
  <!-- A slot's card. A person or a camera opens on its details, one row each with what it is
       set to; a row leads to that detail's chooser, with a back arrow. Anything else, a
       builder with only one detail too, opens its chooser directly. A slot just typed shows "Writing options…" until it is read; one
       that couldn't be read went in as written, and offers to try again.
       Anchored to its pill (or the slot in the text) on desktop; a bottom sheet on touch. -->
  <Teleport to="body">
    <div v-if="card" class="fixed inset-0 z-menu" @click="program.close()">
      <div
        ref="menuRef"
        data-escape-layer
        data-program-card
        role="dialog"
        :aria-label="title || undefined"
        :class="['fixed z-menu bg-surface border border-edge-subtle rounded-lg shadow-lg max-w-[calc(100vw-16px)] flex flex-col', wide ? 'w-[420px]' : 'w-[340px]']"
        :style="menuStyle"
        @click.stop
      >
        <div class="shrink-0 px-3 pt-2.5 pb-1.5 flex items-center gap-1.5">
          <button
            v-if="stack.length"
            type="button"
            class="-ml-1.5 flex items-center gap-0.5 pl-0.5 pr-1.5 py-0.5 coarse:py-1.5 rounded-md text-xs text-content-secondary hover:text-content hover:bg-overlay-subtle"
            data-back
            :aria-label="`Back to ${backLabel}`"
            @click="back"
          >
            <ChevronLeftIcon class="w-3.5 h-3.5" />{{ backLabel }}
          </button>
          <span class="flex-1 min-w-0 truncate text-[13px] font-semibold text-content">{{ title }}</span>
        </div>

        <!-- Not read yet -->
        <div v-if="view.kind === 'pending'" class="px-3 pb-3 flex items-center gap-2 text-xs text-content-muted" data-writing>
          <Spinner size="sm" /> Writing options…
        </div>

        <!-- Went in as written: it couldn't be read this time -->
        <div v-else-if="view.kind === 'written'" class="px-1.5 pb-1.5 flex flex-col gap-px" data-written>
          <div :class="[rowClass, 'cursor-default hover:bg-transparent']">
            <span class="shrink-0 w-3.5 h-4 flex items-center justify-center"><CheckIcon class="w-3.5 h-3.5 text-selection" stroke-width="2.5" /></span>
            <span class="flex-1 min-w-0 text-content font-medium">As written</span>
          </div>
          <button type="button" :class="[rowClass, 'text-accent']" data-read-again @click="readAgain">
            <span class="shrink-0 w-3.5 h-4 flex items-center justify-center"><ArrowPathIcon class="w-3.5 h-3.5" /></span>
            <span class="flex-1 min-w-0">Try again</span>
          </button>
        </div>

        <!-- A builder: its details -->
        <template v-else-if="view.kind === 'panel'">
          <div :style="panelStyle" class="shrink-0 overflow-y-auto overscroll-contain px-1.5 pb-1.5 flex flex-col gap-px" data-panel>
            <button v-for="d in details" :key="d.id" type="button" :class="rowClass" :data-row="d.id" @click="drill(d.id)">
              <span class="w-24 shrink-0 text-content">{{ d.label }}</span>
              <span :class="['flex-1 min-w-0 truncate', rowChanged(d) ? 'text-selection' : 'text-content-muted']">{{ rowText(d) }}</span>
              <span
                v-if="rowChanged(d)"
                role="button"
                tabindex="0"
                class="shrink-0 p-0.5 coarse:p-2 coarse:-my-1.5 rounded-full text-selection hover:bg-selection/20"
                :aria-label="`Reset ${d.label}`"
                :data-reset="d.id"
                @click.stop="resetRow(d)"
                @keydown.enter.stop.prevent="resetRow(d)"
              >
                <XMarkIcon class="w-3 h-3" />
              </span>
              <ChevronRightIcon class="w-3.5 h-4 shrink-0 text-content-muted" />
            </button>
          </div>
          <div class="shrink-0 border-t border-edge-subtle px-2 py-1.5 flex items-center gap-1">
            <span class="flex-1" />
            <button type="button" :class="[footClass, slotAsWritten ? 'text-selection' : '']" :aria-pressed="slotAsWritten" data-as-written @click="toggleSlotAsWritten">As written</button>
          </div>
        </template>

        <!-- One choice -->
        <PromptProgramOptions
          v-else
          ref="optionsRef"
          :key="view.choice.id"
          :choice="view.choice"
          :own-slot="view.slot"
          :program="program"
          :anchor-bottom="card.anchor.bottom"
          @drill="drill"
          @left-out="afterLeaveOut"
        />
      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { computed, nextTick, onUnmounted, ref, watch } from 'vue'
import { ArrowPathIcon, CheckIcon, ChevronLeftIcon, ChevronRightIcon, XMarkIcon } from '@heroicons/vue/24/outline'
import Spinner from '../ui/Spinner.vue'
import PromptProgramOptions from './PromptProgramOptions.vue'
import { useAnchoredMenuPosition } from '../../composables/useContextMenuPosition'
import { useViewport } from '../../composables/useViewport'
import { isChanged, isOff, offLabel, pillValue, resetState } from '../../utils/programChoices'
import type { PromptProgram, ProgramChoice, ProgramSlot } from '../../composables/usePromptProgram'

const props = defineProps<{ program: PromptProgram }>()

const rowClass = 'w-full flex items-start gap-2 px-2 py-1.5 coarse:py-2.5 rounded-md text-left text-xs coarse:text-[13px] cursor-pointer hover:bg-overlay-subtle outline-none focus-visible:ring-1 focus-visible:ring-selection/60'
const footClass = 'flex items-center gap-1.5 px-2 py-1 coarse:py-2 text-xs rounded-md text-content-secondary hover:text-content hover:bg-overlay-subtle'

const card = computed(() => props.program.openCard.value)
const menuRef = ref<HTMLElement | null>(null)
const optionsRef = ref<InstanceType<typeof PromptProgramOptions> | null>(null)
const anchorRect = computed(() => card.value?.anchor ?? null)
const visible = computed(() => !!card.value)
const { menuStyle } = useAnchoredMenuPosition(menuRef, anchorRect, visible, { gap: 6 })

const { isCoarsePointer } = useViewport()
const panelStyle = computed(() => ({
  maxHeight: isCoarsePointer.value ? 'calc(var(--sheet-menu-max-h) - 80px)'
    : `max(12rem, min(32rem, calc(100dvh - ${Math.round((anchorRect.value?.bottom || 0) + 80)}px)))`,
}))

// Where the card opened, and what was stepped through to get here (choice ids).
const stack = ref<string[]>([])
watch(() => card.value, () => { stack.value = [] })

type View =
  | { kind: 'pending'; words: string }
  | { kind: 'written'; words: string }
  | { kind: 'panel'; slot: ProgramSlot }
  | { kind: 'choice'; choice: ProgramChoice; slot: ProgramSlot | null }

function choiceView(c: ProgramChoice): View {
  const slot = c.slot ? props.program.slotById.value[c.slot] : null
  // A slot that is this one choice can be drawn as written.
  return { kind: 'choice', choice: c, slot: slot && !props.program.isBuilder(slot) ? slot : null }
}
const topView = computed<View | null>(() => {
  const t = card.value?.target
  if (!t) return null
  if ('choice' in t) {
    const c = props.program.byId.value[t.choice]
    return c ? choiceView(c) : null
  }
  const slot = props.program.slotFor(t.slot)
  // Stuck: the prompt couldn't be read, or its reading stopped without this slot.
  const stuck = props.program.status.value === 'error' || (props.program.status.value === 'ready' && !props.program.program.value?.working)
  if (!slot) return { kind: stuck ? 'written' : 'pending', words: t.slot.words }
  if (props.program.isBuilder(slot)) return { kind: 'panel', slot }
  // One row (an animal with only its kind varying): straight to its options, no level to step back to.
  const c = props.program.detailsOf(slot)[0]
  if (c) return choiceView(c)
  return { kind: slot.degraded || slot.state === 'ready' || stuck ? 'written' : 'pending', words: t.slot.words }
})
const view = computed<View>(() => {
  const id = stack.value[stack.value.length - 1]
  const c = id ? props.program.byId.value[id] : null
  return c ? choiceView(c) : topView.value || { kind: 'pending', words: '' }
})
// A slot not read yet is titled by its words, as its label would start.
const labelOf = (v: View | null) => !v ? '' : v.kind === 'pending' || v.kind === 'written' ? v.words.charAt(0).toUpperCase() + v.words.slice(1) : v.kind === 'panel' ? v.slot.label : (v.slot?.label || v.choice.label)
const title = computed(() => labelOf(view.value))
const backLabel = computed(() => {
  const prev = stack.value[stack.value.length - 2]
  const c = prev ? props.program.byId.value[prev] : null
  return c ? c.label : labelOf(topView.value)
})
const wide = computed(() => view.value.kind === 'choice' && props.program.optionsOf(view.value.choice).some(o => o.length > 32))

/** Read the slot again: the next prepare reads what went in as written. */
function readAgain() {
  void props.program.prepare()
}

function drill(id: string) {
  stack.value = [...stack.value, id]
}
function back() {
  stack.value = stack.value.slice(0, -1)
}
function afterLeaveOut() {
  if (stack.value.length) back()
  else props.program.close()
}

// The builder's rows ---------------------------------------------------------------------
const panelSlot = computed(() => (view.value.kind === 'panel' ? view.value.slot : null))
const details = computed(() => (panelSlot.value ? props.program.detailsOf(panelSlot.value) : []))
/** A detail with what goes with it (an outfit and its colors). */
const withFollowers = (d: ProgramChoice) => [d, ...(props.program.followers.value[d.id] || [])]
const rowChanged = (d: ProgramChoice) => withFollowers(d).some(c => isChanged(props.program.states.value[c.id]))
function rowText(d: ProgramChoice): string {
  const s = props.program.states.value[d.id]
  if (isOff(d, s)) return offLabel(d.label).toLowerCase()
  const said = pillValue(d, props.program.poolOf(d), s)
  if (said) return said
  if (rowChanged(d)) return 'Any'
  // Untouched: the slot's own words for it, when they settle it.
  const key = panelSlot.value ? d.id.slice(panelSlot.value.id.length + 1) : ''
  return panelSlot.value?.stated?.[key] || ''
}
function resetRow(d: ProgramChoice) {
  props.program.reset(withFollowers(d).map(c => c.id))
}
// As written: every detail left out, which leaves the slot's own words.
const allIds = computed(() => panelSlot.value?.details.filter(id => props.program.byId.value[id]) || [])
const slotAsWritten = computed(() => allIds.value.length > 0
  && allIds.value.every(id => isOff(props.program.byId.value[id], props.program.states.value[id]))
  && allIds.value.some(id => props.program.states.value[id]?.off))
function toggleSlotAsWritten() {
  const st = props.program.states.value
  props.program.setStates(Object.fromEntries(allIds.value.map(id => [id, slotAsWritten.value ? resetState(st[id]) : { off: true, ...(st[id]?.add?.length ? { add: st[id].add } : {}) }])))
}

// Keyboard: the card is teleported to the end of the page, so focus moves into it when
// it opens, Tab stays inside, and focus goes back to what opened it. Escape steps back out:
// the search, then the chooser, then the card.
let returnTo: HTMLElement | null = null
function focusables(): HTMLElement[] {
  return [...(menuRef.value?.querySelectorAll<HTMLElement>('button:not([disabled]), input:not([disabled]), [tabindex]:not([tabindex="-1"])') || [])]
}
function onKey(e: KeyboardEvent) {
  if (e.key === 'Escape') {
    e.preventDefault()
    if (optionsRef.value?.clearQuery()) return
    if (stack.value.length) back()
    else props.program.close()
  } else if (e.key === 'Tab') {
    const all = focusables()
    if (!all.length) return
    const i = all.indexOf(document.activeElement as HTMLElement)
    const next = e.shiftKey ? (i <= 0 ? all.length - 1 : i - 1) : (i === -1 || i === all.length - 1 ? 0 : i + 1)
    all[next].focus()
    e.preventDefault()
  }
}
watch(visible, (open) => {
  if (open) {
    returnTo = document.activeElement instanceof HTMLElement ? document.activeElement : null
    window.addEventListener('keydown', onKey)
    void nextTick(() => { if (!menuRef.value?.contains(document.activeElement)) focusables()[0]?.focus({ preventScroll: true }) })
  } else {
    window.removeEventListener('keydown', onKey)
    const to = returnTo
    returnTo = null
    if (to?.isConnected) to.focus()
  }
})
onUnmounted(() => window.removeEventListener('keydown', onKey))
</script>
