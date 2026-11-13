<template>
  <!-- A slot's card. A person or a camera opens on its details, one row each with what it is
       set to; a row leads to that detail's chooser, with a back arrow. A detail made of parts
       (a face) leads to its parts, one row each, and each part to its chooser; a list browsed by
       region (descent) leads to its regions, each to its values. Anything else, a
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
            <ProgramDrillRow
              v-for="d in details"
              :key="d.id"
              :data-row="d.id"
              :label="d.label"
              :text="rowText(d)"
              :changed="rowChanged(d)"
              :reset-key="d.id"
              @open="drill(d.id)"
              @reset="resetRow(d)"
            />
          </div>
          <div class="shrink-0 border-t border-edge-subtle px-2 py-1.5 flex items-center gap-1">
            <span class="flex-1" />
            <button type="button" :class="[footClass, slotAsWritten ? 'text-selection' : '']" :aria-pressed="slotAsWritten" data-as-written @click="toggleSlotAsWritten">As written</button>
          </div>
        </template>

        <!-- A detail made of parts (a face): any of it, or its parts one by one -->
        <template v-else-if="view.kind === 'parts'">
          <div :style="panelStyle" class="shrink-0 overflow-y-auto overscroll-contain px-1.5 pb-1.5 flex flex-col gap-px" :data-parts="view.choice.id">
            <button type="button" :class="rowClass" data-default @click="chooseWhole">
              <span class="shrink-0 w-3.5 h-4 flex items-center justify-center"><CheckIcon v-if="wholeLit" class="w-3.5 h-3.5 text-selection" stroke-width="2.5" /></span>
              <span :class="['flex-1 min-w-0', wholeLit ? 'text-content font-medium' : 'text-content-secondary']">Any {{ view.choice.label.toLowerCase() }}</span>
            </button>
            <!-- Values chosen for the whole (kept from an earlier image) -->
            <div v-if="wholeTokens.length" class="px-2 py-1 flex flex-wrap items-center gap-1" data-chosen>
              <span v-for="t in wholeTokens" :key="JSON.stringify(t)" class="inline-flex max-w-full items-center gap-1 pl-2.5 pr-1 py-0.5 rounded-full text-xs coarse:text-[13px] bg-selection/15 text-selection">
                <span class="truncate">{{ tokenText(view.choice, program.poolOf(view.choice), t) }}</span>
                <button type="button" class="shrink-0 p-0.5 rounded-full hover:bg-selection/20" :aria-label="`Remove ${tokenText(view.choice, program.poolOf(view.choice), t)}`" @click="dropWholeToken(t)">
                  <XMarkIcon class="w-3 h-3" />
                </button>
              </span>
            </div>
            <ProgramDrillRow
              v-for="d in partRows"
              :key="d.id"
              :data-row="d.id"
              :label="d.label"
              :text="partText(d, program.poolOf(d), program.states.value[d.id])"
              :changed="isChanged(program.states.value[d.id])"
              :reset-key="d.id"
              @open="drill(d.id)"
              @reset="program.reset([d.id])"
            />
          </div>
          <div v-if="wholeOn" class="shrink-0 border-t border-edge-subtle px-2 py-1.5 flex items-center gap-1">
            <span class="flex-1" />
            <button type="button" :class="footClass" data-leave-out @click="leaveWhole">Leave out</button>
          </div>
        </template>

        <!-- One choice -->
        <PromptProgramOptions
          v-else
          ref="optionsRef"
          :key="`${view.choice.id}|${view.within || ''}`"
          :choice="view.choice"
          :own-slot="view.slot"
          :within="view.within"
          :program="program"
          :anchor-bottom="card.anchor.bottom"
          @drill="drill"
          @drill-part="drillPart"
          @left-out="afterLeaveOut"
        />
      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { computed, nextTick, onUnmounted, ref, watch } from 'vue'
import { ArrowPathIcon, CheckIcon, ChevronLeftIcon, XMarkIcon } from '@heroicons/vue/24/outline'
import Spinner from '../ui/Spinner.vue'
import PromptProgramOptions from './PromptProgramOptions.vue'
import ProgramDrillRow from './ProgramDrillRow.vue'
import { useAnchoredMenuPosition } from '../../composables/useContextMenuPosition'
import { useViewport } from '../../composables/useViewport'
import { detailsAsWritten, isChanged, isOff, leaveOut, offLabel, partLabel, partText, partsText, pillValue, resetState, toggleDetailsAsWritten, toggleToken, tokenText, tokensOf, turnOn, type Token } from '../../utils/programChoices'
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

// Where the card opened, and what was stepped through to get here: choices, and a part of
// one (a region of descent).
type Step = { id: string; part?: string }
const stack = ref<Step[]>([])
watch(() => card.value, () => { stack.value = [] })

type View =
  | { kind: 'pending'; words: string }
  | { kind: 'written'; words: string }
  | { kind: 'panel'; slot: ProgramSlot }
  | { kind: 'parts'; choice: ProgramChoice }
  | { kind: 'choice'; choice: ProgramChoice; slot: ProgramSlot | null; within?: string }

function choiceView(c: ProgramChoice, within?: string): View {
  if (props.program.partsOf(c).length) return { kind: 'parts', choice: c }
  const slot = c.slot ? props.program.slotById.value[c.slot] : null
  // A slot that is this one choice can be drawn as written; what goes with it (an outfit's
  // colors) is a choice of its own.
  const own = slot && !props.program.isBuilder(slot) && props.program.detailsOf(slot)[0]?.id === c.id
  return { kind: 'choice', choice: c, slot: own ? slot : null, ...(within ? { within } : {}) }
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
  const step = stack.value[stack.value.length - 1]
  const c = step ? props.program.byId.value[step.id] : null
  return c ? choiceView(c, step!.part) : topView.value || { kind: 'pending', words: '' }
})
// A slot not read yet is titled by its words, as its label would start.
const labelOf = (v: View | null) => !v ? '' : v.kind === 'pending' || v.kind === 'written' ? v.words.charAt(0).toUpperCase() + v.words.slice(1) : v.kind === 'panel' ? v.slot.label : v.kind === 'parts' ? v.choice.label : v.within ? partLabel(v.within) : (v.slot?.label || v.choice.label)
const title = computed(() => labelOf(view.value))
const backLabel = computed(() => {
  const prev = stack.value[stack.value.length - 2]
  const c = prev ? props.program.byId.value[prev.id] : null
  return c ? (prev!.part ? partLabel(prev!.part) : c.label) : labelOf(topView.value)
})
const wide = computed(() => view.value.kind === 'choice' && props.program.optionsOf(view.value.choice).some(o => o.length > 32))

/** Read the slot again: the next prepare reads what went in as written. */
function readAgain() {
  void props.program.prepare()
}

function drill(id: string) {
  stack.value = [...stack.value, { id }]
}
/** Into one part of the choice shown (a region of descent). */
function drillPart(part: string) {
  if (view.value.kind === 'choice') stack.value = [...stack.value, { id: view.value.choice.id, part }]
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
/** A detail with what goes with it (an outfit and its colors, a face and its parts). */
const withFollowers = (d: ProgramChoice) => [d, ...(props.program.followers.value[d.id] || []), ...props.program.partsOf(d)]
const rowChanged = (d: ProgramChoice) => withFollowers(d).some(c => isChanged(props.program.states.value[c.id]))
function rowText(d: ProgramChoice): string {
  const s = props.program.states.value[d.id]
  // A face with parts chosen is those parts.
  const parts = partsText(props.program.partsOf(d), props.program.states.value, props.program.pools.value)
  if (parts) return parts
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
// A detail made of parts (a face) ---------------------------------------------------------
const whole = computed(() => (view.value.kind === 'parts' ? view.value.choice : null))
const partRows = computed(() => (whole.value ? props.program.partsOf(whole.value) : []))
const wholeState = computed(() => (whole.value ? props.program.states.value[whole.value.id] || null : null))
const wholeTokens = computed(() => tokensOf(wholeState.value))
const partsChosen = computed(() => partRows.value.some(d => isChanged(props.program.states.value[d.id])))
/** "Any face": one subtle detail of any part, with no part and no value chosen. */
// A face starts left out unless the prompt asked for it; either way it is drawn once on.
const wholeLit = computed(() => !!whole.value && !isOff(whole.value, wholeState.value) && !wholeTokens.value.length && !partsChosen.value)
/** The face is drawn now: on (as it starts, or turned on) or some part chosen. */
const wholeOn = computed(() => !!whole.value && (!isOff(whole.value, wholeState.value) || partsChosen.value))
function chooseWhole() {
  if (!whole.value || wholeLit.value) return
  const st = props.program.states.value
  props.program.setStates({
    [whole.value.id]: whole.value.starts_off ? turnOn(wholeState.value) : resetState(wholeState.value),
    ...Object.fromEntries(partRows.value.map(d => [d.id, resetState(st[d.id])])),
  })
}
function dropWholeToken(t: Token) {
  if (whole.value) props.program.setState(whole.value.id, toggleToken(whole.value, wholeState.value, t))
}
function leaveWhole() {
  if (!whole.value) return
  const st = props.program.states.value
  props.program.setStates({
    [whole.value.id]: leaveOut(wholeState.value, whole.value),
    ...Object.fromEntries(partRows.value.map(d => [d.id, resetState(st[d.id])])),
  })
  afterLeaveOut()
}

// As written: every detail left out, which leaves the slot's own words.
const byId = (id: string) => props.program.byId.value[id]
const slotAsWritten = computed(() => !!panelSlot.value && detailsAsWritten(panelSlot.value, byId, props.program.states.value))
function toggleSlotAsWritten() {
  if (panelSlot.value) props.program.setStates(toggleDetailsAsWritten(panelSlot.value, byId, props.program.states.value))
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
