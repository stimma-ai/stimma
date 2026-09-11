<script setup lang="ts">
/**
 * The selection island: a floating pill at the bottom of the canvas, the same
 * shape as the browser's selection bar, floating OVER the matte so nothing
 * about arming a tool ever pushes the canvas or the toolbars around.
 *
 * The island carries IDENTITY only — the pointer, the six tool slots, the
 * combine modes, invert/deselect — and never a parameter. Arming a tool
 * raises a panel above the island with that tool's FULL parameter set (the
 * same gesture the Object tool has always used for its prompt), so every
 * setting has exactly one home and the bar itself never reflows. Idle shows
 * no panel at all.
 *
 * Kin tools share a slot with a press-and-hold flyout (the two marquees, the
 * two lassos, the two gradients). A quick press selects the last-used member;
 * holding opens the flyout and releasing over a member selects it, matching
 * the standard graphics-editor gesture without making hover change the tool.
 *
 * Selection is workspace state, not a mode: clicking a tool arms it (the
 * pointer goes to the selection overlay, the open family is suspended, not
 * left). Grouped picks are idempotent; the pointer or a family control hands
 * the canvas back explicitly, while ungrouped tools retain their old toggle.
 */
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { XMarkIcon } from '@heroicons/vue/24/outline'
import Spinner from '../../components/ui/Spinner.vue'
import Tooltip from '../../components/ui/Tooltip.vue'
import PaintToolIcon from '../../components/generation/PaintToolIcon.vue'
import ToolIcon from './ToolIcon.vue'
import DeckSegments from './DeckSegments.vue'
import ParamDeck from './ParamDeck.vue'
import type { DeckParam } from './ParamDeck.vue'
import { DEFAULT_LINEAR_SOFTNESS, DEFAULT_RADIAL_FEATHER } from '../stack/regionMask'
import { SELECT_TOOLS, SELECT_TOOL_GROUPS, SELECTION_MODES } from '../stack/toolFamilies'
import type { SelectToolId, SelectionMode } from '../stack/toolFamilies'
import {
  FEATHER_SLIDER_MAX,
  featherPxFromSlider,
  featherSliderFromPx,
} from '../stack/featherScale'

const props = defineProps<{
  armed: SelectToolId | null
  /** Most recently used selection tool, including while the rail is idle. */
  lastUsed?: SelectToolId | null
  hasSelection: boolean
  combine: SelectionMode
  /**
   * The held-modifier combine preview (Shift add, Option subtract, both
   * intersect): what the NEXT gesture will use, without touching this
   * control's persistent mode.
   */
  combineOverride?: SelectionMode | null
  featherPx: number
  tolerance: number
  spread: number
  growPx: number
  antialias: boolean
  brushSize: number
  /** Ease on a fresh linear ramp, 0-100. */
  gradientSoftness: number
  /** Falloff share on a fresh ellipse, 2-100. */
  gradientFeather: number
  /**
   * The pointer — object select — is the workspace's IDLE state, not an armed
   * tool: this is true when no family is open and no region tool is armed.
   */
  pointerActive?: boolean
  /** A smart-selection request is in flight; the popup shares one busy state. */
  aiBusy?: boolean
  /** Delayed busy feedback; false keeps fast selections visually instant. */
  aiProgressVisible?: boolean
  /** Actual backend phase for the in-flight smart selection. */
  aiStage?: 'starting' | 'downloading_model' | 'loading' | 'processing_image' | 'selecting'
  /** The gesture the status row is reporting on. */
  aiAction?: 'find' | 'subject' | 'background' | 'sky' | 'canvas' | null
  /** The last smart-selection failure, shown until the next request/input. */
  aiError?: string | null
  /**
   * Phone layout (DESIGN.md §1.11): the island becomes a glass button on the
   * matte that opens a sheet of the tools, and an armed tool's parameters
   * become a strip over the bottom of the matte instead of a raised panel.
   */
  compact?: boolean
  /**
   * Compact: where the armed tool's panel renders (a teleport target selector,
   * the editor drawer's body). Without it the panel stays on the matte.
   */
  panelTarget?: string | null
}>()

const emit = defineEmits<{
  arm: [SelectToolId]
  /** Grouped-tool picks are idempotent: choosing the selected variant keeps it armed. */
  choose: [SelectToolId]
  pointer: []
  set: [Record<string, any>]
  invert: []
  clear: []
  morph: [number]
  /** The active gradient's falloff slider started or ended a gesture. */
  gradientAdjusting: [boolean]
  aiSelect: [{ prompt: string } | { intent: 'subject' | 'background' | 'sky' }]
  aiCancel: []
  /** Compact strip's Done: put the tool down, keep the selection and the family. */
  done: []
}>()

const toolById = Object.fromEntries(SELECT_TOOLS.map(tool => [tool.id, tool]))
const armedTool = computed(() => (props.armed ? toolById[props.armed] : null))

/** Each slot shows its last-used member; arming any member claims the slot. */
const groupCurrent = ref<Record<string, SelectToolId>>(
  Object.fromEntries(SELECT_TOOL_GROUPS.map(group => [group.id, group.members[0]]))
)
watch([() => props.armed, () => props.lastUsed], ([armed, lastUsed]) => {
  const current = armed ?? lastUsed
  if (!current) return
  const group = SELECT_TOOL_GROUPS.find(g => g.members.includes(current))
  if (group) groupCurrent.value[group.id] = current
}, { immediate: true })
watch(() => props.armed, () => emit('gradientAdjusting', false))

/** Photoshop-style grouped tools: click uses the visible tool; hold opens the
 * menu, then release over a row to choose it in the same gesture. */
const GROUP_HOLD_MS = 350
const openGroup = ref<string | null>(null)
let holdTimer: ReturnType<typeof setTimeout> | null = null
let groupPress: {
  groupId: string
  current: SelectToolId
  pointerId: number
  opened: boolean
} | null = null

function clearHoldTimer() {
  if (holdTimer) clearTimeout(holdTimer)
  holdTimer = null
}

function removePressListeners() {
  window.removeEventListener('pointerup', finishGroupPress, true)
  window.removeEventListener('pointercancel', cancelGroupPress, true)
}

function startGroupPress(
  groupId: string,
  current: SelectToolId,
  event: PointerEvent,
) {
  if (event.button !== 0) return
  event.preventDefault()
  event.stopPropagation()
  clearHoldTimer()
  removePressListeners()
  groupPress = { groupId, current, pointerId: event.pointerId, opened: false }
  holdTimer = setTimeout(() => {
    if (!groupPress || groupPress.pointerId !== event.pointerId) return
    groupPress.opened = true
    openGroup.value = groupId
  }, GROUP_HOLD_MS)
  window.addEventListener('pointerup', finishGroupPress, true)
  window.addEventListener('pointercancel', cancelGroupPress, true)
}

function finishGroupPress(event: PointerEvent) {
  const press = groupPress
  if (!press || event.pointerId !== press.pointerId) return
  clearHoldTimer()
  removePressListeners()
  groupPress = null
  if (!press.opened) {
    chooseGroupTool(press.current)
    return
  }

  // elementFromPoint follows the pointer even though the press began on the
  // slot button, so press-drag-release selects a row in one continuous move.
  const target = document.elementFromPoint(event.clientX, event.clientY)
    ?.closest<HTMLElement>('[data-select-tool]')
  const id = target?.dataset.selectTool as SelectToolId | undefined
  const group = SELECT_TOOL_GROUPS.find(candidate => candidate.id === press.groupId)
  if (id && group?.members.includes(id)) chooseGroupTool(id)
  // Releasing on the original slot leaves the menu open for an ordinary click.
}

function cancelGroupPress(event?: PointerEvent) {
  if (event && groupPress && event.pointerId !== groupPress.pointerId) return
  clearHoldTimer()
  removePressListeners()
  groupPress = null
}

function chooseGroupTool(id: SelectToolId) {
  const group = SELECT_TOOL_GROUPS.find(candidate => candidate.members.includes(id))
  if (group) groupCurrent.value[group.id] = id
  openGroup.value = null
  emit('choose', id)
}

/** Native keyboard activation has no pointer sequence; keep it one-step. */
function onGroupButtonClick(id: SelectToolId, event: MouseEvent) {
  if (event.detail === 0) chooseGroupTool(id)
}

function onOutsidePointerDown(event: PointerEvent) {
  const target = event.target as HTMLElement | null
  if (
    openGroup.value
    && !target?.closest(`[data-select-group="${openGroup.value}"]`)
  ) {
    openGroup.value = null
  }
}

function onWindowKeydown(event: KeyboardEvent) {
  if (event.key !== 'Escape') return
  // Waiting on a model is the one thing Esc should reach first: cancelling the
  // request is what the user means, not leaving the tool that issued it. The
  // listener is capture-phase so the editor's own Esc never sees this one.
  if (props.aiBusy) {
    emit('aiCancel')
    event.stopPropagation()
    event.preventDefault()
    return
  }
  openGroup.value = null
}

onMounted(() => {
  window.addEventListener('pointerdown', onOutsidePointerDown)
  window.addEventListener('keydown', onWindowKeydown, true)
})
onBeforeUnmount(() => {
  cancelGroupPress()
  window.removeEventListener('pointerdown', onOutsidePointerDown)
  window.removeEventListener('keydown', onWindowKeydown, true)
})

/** Combine describes how the next gesture meets the visible selection, so its
 * state remains visible/editable after a one-shot workflow disarms the tool. */
const combineEnabled = computed(() => props.armed !== null || props.hasSelection)

/**
 * The armed tool's parameters, in bar order. Feather is selection-edge state
 * shared by every geometric tool; the rest belong to one tool each. A ramp's
 * ease and an ellipse's falloff are the same idea and deliberately not the
 * same number: 100% softness on a ramp has no edge left, while 100% feather
 * on an ellipse still ends somewhere.
 */
interface PanelSlider {
  label: string
  min: number
  max: number
  unit: string
  value: number
  readout: number
  /** What a phone's long-press reset returns to. */
  initial: number
  set: (value: number) => void
  previewsGradient?: boolean
}

const featherSlider = (): PanelSlider => ({
  label: 'Feather',
  min: 0, max: FEATHER_SLIDER_MAX, unit: 'px',
  value: featherSliderFromPx(props.featherPx),
  readout: props.featherPx,
  initial: 0,
  set: value => emit('set', { featherPx: featherPxFromSlider(value) }),
})

const plainSlider = (
  label: string, key: string, value: number, min: number, max: number, unit: string,
  initial: number, previewsGradient = false,
): PanelSlider => ({
  label, min, max, unit, value, readout: value, initial,
  set: v => emit('set', { [key]: v }),
  previewsGradient,
})

function beginSliderAdjustment(slider: PanelSlider) {
  if (slider.previewsGradient) emit('gradientAdjusting', true)
}

function setSliderValue(slider: PanelSlider, value: number) {
  beginSliderAdjustment(slider)
  slider.set(value)
}

function finishSliderAdjustment(slider: PanelSlider) {
  if (slider.previewsGradient) emit('gradientAdjusting', false)
}

const panelSliders = computed<PanelSlider[]>(() => {
  switch (props.armed) {
    case 'wand': return [
      plainSlider('Threshold', 'tolerance', props.tolerance, 1, 100, '', 8),
      plainSlider('Spread', 'spread', props.spread, 0, 100, '%', 100),
      plainSlider('Grow', 'growPx', props.growPx, -40, 40, 'px', 0),
      featherSlider(),
    ]
    case 'brush': return [
      plainSlider('Brush', 'selectBrushSize', props.brushSize, 8, 300, 'px', 80),
      featherSlider(),
    ]
    case 'linear': return [
      plainSlider('Softness', 'gradientSoftness', props.gradientSoftness, 0, 100, '', DEFAULT_LINEAR_SOFTNESS, true),
    ]
    case 'radial': return [
      plainSlider('Feather', 'gradientFeather', props.gradientFeather, 2, 100, '', DEFAULT_RADIAL_FEATHER, true),
    ]
    case 'rect': case 'ellipse': case 'lasso': case 'magnetic': return [featherSlider()]
    default: return []
  }
})

/** Phone: the same sliders as a parameter grid and one dial (DESIGN.md §3.6a). */
const deckActive = ref<string | null>(null)
const deckParams = computed<DeckParam[]>(() => panelSliders.value.map(slider => ({
  key: slider.label, label: slider.label, value: slider.value, min: slider.min, max: slider.max,
  step: 1, default: slider.initial, format: () => `${slider.readout}${slider.unit}`,
})))
function onDeckChange(key: string, value: number) {
  const slider = panelSliders.value.find(s => s.label === key)
  if (slider) setSliderValue(slider, value)
}
function onDeckCommit(key: string) {
  const slider = panelSliders.value.find(s => s.label === key)
  if (slider) finishSliderAdjustment(slider)
}

/**
 * The Object tool's panel content keeps prompt/click selection together with
 * the two whole-image BEN2 intents. The typed prompt survives a run —
 * re-running and refining are the common follow-ups.
 *
 * The three gestures are NOT peers, so they are not three buttons: naming a
 * thing is the field's own action and submits from inside it, while subject
 * and background are one-tap picks below an "or". Whichever one is running,
 * the picks give way to a single status row, so the spinner and its Cancel are
 * always in the same place instead of hiding inside whichever control was hit.
 */
const aiPrompt = ref('')
/** One-shot distance used by the Expand/Contract selection actions. */
const edgeAmount = ref(8)
const shownAiError = ref<string | null>(null)
const aiInput = ref<HTMLInputElement | null>(null)
watch(() => props.aiError, value => { shownAiError.value = value ?? null })
watch(() => props.armed, armed => {
  if (armed === 'object') nextTick(() => aiInput.value?.focus())
  else shownAiError.value = null
})

function submitAiPrompt() {
  const prompt = aiPrompt.value.trim()
  if (!prompt || props.aiBusy) return
  emit('aiSelect', { prompt })
}

function selectIntent(intent: 'subject' | 'background' | 'sky') {
  if (props.aiBusy) return
  emit('aiSelect', { intent })
}

/** What the status row says while a request runs, named after the gesture. */
const aiStatusLabel = computed(() => {
  if (props.aiStage === 'downloading_model') return 'Downloading selection model…'
  if (props.aiStage === 'loading') return 'Loading selection model…'
  if (props.aiStage === 'processing_image') return 'Processing image…'
  if (props.aiStage === 'starting') return 'Starting smart selection…'
  switch (props.aiAction) {
    case 'find': return `Finding “${aiPrompt.value.trim()}”…`
    case 'subject': return 'Selecting subject…'
    case 'background': return 'Selecting background…'
    case 'sky': return 'Selecting sky…'
    default: return 'Selecting object…'
  }
})

function morphSelection(direction: 1 | -1) {
  const amount = Math.max(1, Math.min(100, Math.round(Number(edgeAmount.value) || 1)))
  edgeAmount.value = amount
  emit('morph', amount * direction)
}

function buttonClass(active: boolean, enabled = true) {
  if (!enabled) return 'text-content-tertiary/50 cursor-default'
  return active
    ? 'bg-selection/15 text-content'
    : 'text-content-secondary hover:text-content hover:bg-overlay-subtle'
}
</script>

<template>
  <!-- The host positions this root (absolute over the matte); that same
       positioning is what the raised panel's `absolute bottom-full` anchors
       to, so the wrapper must NOT add a position class of its own. -->
  <div :class="compact ? 'w-auto' : 'w-max'">
  <template v-if="compact">
    <!-- The matte pill. Idle it says Select and arms the last tool; with a
         selection it names it and carries Deselect; armed it names the tool
         in the selection color and hands the pointer back on tap. -->
    <div class="flex items-center gap-1.5">
      <button
        type="button"
        class="min-h-11 pl-2.5 pr-3 rounded-lg backdrop-blur border text-[12.5px] font-medium flex items-center gap-1.5"
        :class="armed
          ? 'bg-selection/30 text-white border-selection/50'
          : hasSelection ? 'bg-black/60 text-selection border-selection/40' : 'bg-black/60 text-white border-white/10'"
        :aria-label="armed ? `${armedTool?.label} armed. Done` : hasSelection ? 'Edit selection' : 'Select'"
        :aria-pressed="!!armed"
        data-select-pill
        @click="armed ? emit('done') : emit('choose', lastUsed ?? 'lasso')"
      >
        <ToolIcon
          :name="armed ? armedTool!.icon : (hasSelection && lastUsed ? toolById[lastUsed].icon : 'lasso')"
          :size="16"
        />
        {{ armed ? armedTool?.label : hasSelection ? 'Selection' : 'Select' }}
      </button>
      <button
        v-if="hasSelection && !armed"
        type="button"
        class="min-h-11 min-w-11 rounded-lg bg-black/60 backdrop-blur border border-white/10 text-white flex items-center justify-center"
        aria-label="Deselect"
        @click="emit('clear')"
      >
        <XMarkIcon class="w-4 h-4" />
      </button>
    </div>

    <!-- Armed: the tool's parameters, in the drawer (the host names the
         target) so the picture stays clear; the host's strip shows the tools
         beneath. The same set the raised panel shows on desktop; Done hands
         the canvas back and the family's controls return underneath. -->
    <Teleport v-if="armed && panelTarget" :to="panelTarget" defer>
      <div class="pb-1 flex flex-col" data-select-panel>
        <!-- What can be done to the selection that exists. Bare verbs, no fills. -->
        <div v-if="hasSelection" class="flex items-center min-h-11 -mx-2">
          <button type="button" class="min-h-11 px-2.5 text-[13px] font-medium rounded-md text-content-secondary" @click="emit('invert')">Invert</button>
          <button type="button" class="min-h-11 px-2.5 text-[13px] font-medium rounded-md text-content-secondary" @click="emit('clear')">Deselect</button>
          <span class="flex-1" />
          <button type="button" class="min-h-11 px-2.5 text-[13px] font-medium rounded-md text-content-secondary flex items-center gap-1.5" @click="morphSelection(1)">
            <PaintToolIcon name="maskExpand" class="w-4 h-4" />
            Expand
          </button>
          <button type="button" class="min-h-11 px-2.5 text-[13px] font-medium rounded-md text-content-secondary flex items-center gap-1.5" @click="morphSelection(-1)">
            <PaintToolIcon name="maskContract" class="w-4 h-4" />
            Contract
          </button>
        </div>

        <template v-if="armed === 'object'">
          <div class="relative transition-opacity" :class="aiProgressVisible ? 'opacity-60' : ''">
            <input
              ref="aiInput"
              v-model="aiPrompt"
              type="text"
              placeholder="Describe what to select, or tap it…"
              aria-label="Describe what to select"
              class="w-full min-h-11 pl-3 pr-11 text-[15px] rounded-md bg-overlay-subtle text-content
                     placeholder:text-content-tertiary border outline-none transition-colors"
              :class="shownAiError ? 'border-red-400/70' : 'border-transparent focus:border-accent'"
              :disabled="aiBusy"
              @input="shownAiError = null"
              @keydown.enter.prevent="submitAiPrompt"
            />
            <button
              v-if="aiPrompt.trim()"
              type="button"
              class="absolute right-1 top-1/2 -translate-y-1/2 w-9 h-9 rounded-md
                     flex items-center justify-center bg-accent text-white"
              aria-label="Find"
              :disabled="aiBusy"
              @click="submitAiPrompt"
            >
              <ToolIcon name="cornerDownLeft" :size="15" />
            </button>
          </div>
          <div class="min-h-11 flex items-center gap-1.5 pt-1.5">
            <template v-if="!aiProgressVisible">
              <button
                v-for="intent in (['subject', 'background', 'sky'] as const)"
                :key="intent"
                type="button"
                class="flex-1 min-h-11 flex items-center justify-center gap-1.5 rounded-md text-[13px] font-medium
                       bg-overlay-subtle text-content-secondary capitalize"
                :disabled="aiBusy"
                @click="selectIntent(intent)"
              >
                <ToolIcon :name="intent === 'subject' ? 'person' : intent === 'background' ? 'image' : 'sun'" :size="15" />
                {{ intent }}
              </button>
            </template>
            <template v-else>
              <Spinner size="sm" />
              <span class="flex-1 min-w-0 truncate text-[13px] text-content-secondary">{{ aiStatusLabel }}</span>
              <button
                type="button"
                class="min-h-11 px-3 text-[13px] font-medium rounded-md text-content-secondary"
                @click="emit('aiCancel')"
              >
                Cancel
              </button>
            </template>
          </div>
          <p v-if="shownAiError && !aiBusy" role="alert" class="pt-1 text-xs text-red-400">
            {{ shownAiError }}
          </p>
        </template>

        <template v-else>
          <ParamDeck
            :params="deckParams"
            :active="deckActive"
            @update:active="deckActive = $event"
            @change="onDeckChange"
            @commit="onDeckCommit"
          />
          <label
            v-if="armed === 'wand'"
            class="flex items-center gap-2 min-h-11 text-[13px] text-content-secondary"
          >
            <input
              type="checkbox"
              class="accent-accent w-5 h-5"
              :checked="antialias"
              @change="emit('set', { antialias: ($event.target as HTMLInputElement).checked })"
            />
            Anti-alias
          </label>
        </template>

        <!-- How the next gesture meets what is selected. -->
        <DeckSegments
          :model-value="combineOverride ?? combine"
          :options="SELECTION_MODES"
          aria-label="Combine mode"
          tone="selection"
          :disabled="!combineEnabled"
          @update:model-value="emit('set', { combine: $event })"
        />
      </div>
    </Teleport>
  </template>
  <template v-else>
  <!-- The armed tool's panel, raised over the island. One home for every
       parameter: the Object tool brings its prompt, everything else brings
       its sliders. Disarming folds it away. -->
  <Transition
    enter-active-class="transition duration-150 ease-out"
    enter-from-class="opacity-0 translate-y-1"
    leave-active-class="transition duration-100 ease-in"
    leave-to-class="opacity-0 translate-y-1"
  >
    <div
      v-if="armed"
      class="absolute bottom-full mb-1 left-1/2 -translate-x-1/2 w-max
             px-3 py-2
             bg-surface border border-edge-subtle rounded-lg shadow-lg"
    >
      <template v-if="armed === 'object'">
        <div class="w-96">
          <!-- Naming a thing is the FIELD's action: it submits from inside the
               field, so nothing about it reads as a peer of the picks below. -->
          <div class="relative transition-opacity" :class="aiProgressVisible ? 'opacity-60' : ''">
            <input
              ref="aiInput"
              v-model="aiPrompt"
              type="text"
              placeholder="Describe what to select, or click it on canvas…"
              aria-label="Describe what to select"
              class="w-full pl-2.5 pr-9 py-1.5 text-xs rounded-md bg-overlay-subtle text-content
                     placeholder:text-content-tertiary border outline-none transition-colors"
              :class="shownAiError ? 'border-red-400/70' : 'border-transparent focus:border-accent'"
              :style="aiBusy ? { cursor: aiProgressVisible ? 'progress' : 'default' } : undefined"
              :disabled="aiBusy"
              @input="shownAiError = null"
              @keydown.enter.prevent="submitAiPrompt"
            />
            <Transition
              enter-active-class="transition duration-150 ease-out"
              enter-from-class="opacity-0 scale-75"
              leave-active-class="transition duration-100 ease-in"
              leave-to-class="opacity-0 scale-75"
            >
              <button
                v-if="aiPrompt.trim()"
                type="button"
                class="absolute right-1 top-1/2 -translate-y-1/2 w-6 h-6 rounded-md
                       flex items-center justify-center bg-accent text-white transition-colors
                       hover:bg-accent/90 focus-visible:outline-none focus-visible:ring-2 ring-accent/60"
                aria-label="Find"
                title="Find (Enter)"
                :disabled="aiBusy"
                @click="submitAiPrompt"
              >
                <ToolIcon name="cornerDownLeft" :size="13" />
              </button>
            </Transition>
          </div>

          <!-- One zone, fixed height: the picks while idle, the status row
               while anything runs. Cancel never moves. -->
          <div class="h-14">
            <div v-if="!aiProgressVisible" class="h-full flex flex-col justify-end">
              <div class="flex items-center gap-2 py-1.5 text-[10px] leading-4 text-content-muted select-none">
                <span class="flex-1 h-px bg-edge-subtle" />
                or
                <span class="flex-1 h-px bg-edge-subtle" />
              </div>
              <div class="grid grid-cols-3 gap-1.5">
                <button
                  type="button"
                  class="h-7 flex items-center justify-center gap-1.5 rounded-md text-xs font-medium
                         bg-overlay-subtle text-content-secondary transition-colors
                         hover:bg-overlay-hover hover:text-content
                         focus-visible:outline-none focus-visible:ring-2 ring-accent/60"
                  :disabled="aiBusy"
                  @click="selectIntent('subject')"
                >
                  <ToolIcon name="person" :size="13" />
                  Subject
                </button>
                <button
                  type="button"
                  class="h-7 flex items-center justify-center gap-1.5 rounded-md text-xs font-medium
                         bg-overlay-subtle text-content-secondary transition-colors
                         hover:bg-overlay-hover hover:text-content
                         focus-visible:outline-none focus-visible:ring-2 ring-accent/60"
                  :disabled="aiBusy"
                  @click="selectIntent('background')"
                >
                  <ToolIcon name="image" :size="13" />
                  Background
                </button>
                <button
                  type="button"
                  class="h-7 flex items-center justify-center gap-1.5 rounded-md text-xs font-medium
                         bg-overlay-subtle text-content-secondary transition-colors
                         hover:bg-overlay-hover hover:text-content
                         focus-visible:outline-none focus-visible:ring-2 ring-accent/60"
                  :disabled="aiBusy"
                  @click="selectIntent('sky')"
                >
                  <ToolIcon name="sun" :size="13" />
                  Sky
                </button>
              </div>
            </div>
            <div v-else class="h-full flex items-center gap-2">
              <Spinner size="sm" />
              <span class="flex-1 min-w-0 truncate text-xs text-content-secondary">
                {{ aiStatusLabel }}
              </span>
              <button
                type="button"
                class="px-2.5 py-1.5 text-xs font-medium rounded-md transition-colors
                       focus-visible:outline-none focus-visible:ring-2 ring-accent/60"
                :class="buttonClass(false)"
                @click="emit('aiCancel')"
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
        <span class="sr-only" role="status" aria-live="polite">
          {{ aiProgressVisible ? aiStatusLabel : '' }}
        </span>
        <p v-if="shownAiError && !aiBusy" role="alert" class="mt-1.5 text-xs text-red-400">
          {{ shownAiError }}
        </p>
      </template>

      <div v-else class="flex items-center gap-3">
        <span class="flex items-center gap-1.5 text-xs font-medium text-content-secondary">
          <ToolIcon v-if="armedTool" :name="armedTool.icon" />
          {{ armedTool?.label }}
        </span>
        <span class="w-px h-5 bg-edge-subtle" />
        <label
          v-for="slider in panelSliders"
          :key="slider.label"
          class="flex items-center gap-2 text-xs text-content-tertiary"
        >
          <span>{{ slider.label }}</span>
          <input
            type="range" class="w-24"
            :min="slider.min" :max="slider.max"
            :value="slider.value"
            @pointerdown="beginSliderAdjustment(slider)"
            @input="setSliderValue(slider, Number(($event.target as HTMLInputElement).value))"
            @change="finishSliderAdjustment(slider)"
            @pointerup="finishSliderAdjustment(slider)"
            @pointercancel="finishSliderAdjustment(slider)"
            @blur="finishSliderAdjustment(slider)"
          />
          <span class="tabular-nums w-10 text-content-secondary">{{ slider.readout }}{{ slider.unit }}</span>
        </label>
        <label
          v-if="armed === 'wand'"
          class="flex items-center gap-1.5 text-xs text-content-secondary cursor-pointer"
        >
          <input
            type="checkbox"
            class="accent-accent"
            :checked="antialias"
            @change="emit('set', { antialias: ($event.target as HTMLInputElement).checked })"
          />
          Anti-alias
        </label>
      </div>
    </div>
  </Transition>

  <div
    class="flex items-center gap-1 px-2.5 py-1.5 w-max
           bg-surface border border-edge-subtle rounded-lg shadow-lg"
  >
    <!-- The pointer: grab and edit the things on the canvas (annotations).
         Users think "select" is one idea whether the thing is pixels or an
         object, so it lives here with the region tools rather than inside
         Annotate. Clicking it leaves whatever mode is open — it IS idle. -->
    <Tooltip text="Select objects">
      <button
        type="button"
        class="p-1.5 rounded-md transition-colors focus-visible:outline-none focus-visible:ring-2 ring-accent/60"
        :class="buttonClass(!!pointerActive)"
        aria-label="Select objects"
        :aria-pressed="!!pointerActive"
        @click="emit('pointer')"
      >
        <ToolIcon name="mousePointer" />
      </button>
    </Tooltip>
    <span class="w-px h-5 bg-edge-subtle mx-1" />

    <span
      v-for="group in SELECT_TOOL_GROUPS"
      :key="group.id"
      class="relative"
      :data-select-group="group.id"
    >
      <Tooltip
        v-if="group.members.length === 1"
        :text="toolById[group.members[0]].hint ?? `Select — ${toolById[group.members[0]].label}`"
      >
        <button
          type="button"
          class="p-1.5 rounded-md transition-colors focus-visible:outline-none focus-visible:ring-2 ring-accent/60"
          :class="buttonClass(armed === group.members[0])"
          :aria-label="`Select — ${toolById[group.members[0]].label}`"
          :aria-pressed="armed === group.members[0]"
          @click="emit('arm', group.members[0])"
        >
          <ToolIcon :name="toolById[group.members[0]].icon" />
        </button>
      </Tooltip>
      <template v-else>
        <!-- Quick press arms the visible member. Hold opens the menu; the
             corner tick is the quiet affordance that more tools live here. -->
        <button
          type="button"
          class="relative p-1.5 rounded-md transition-colors focus-visible:outline-none focus-visible:ring-2 ring-accent/60"
          :class="buttonClass(armed === groupCurrent[group.id])"
          :aria-label="`Select — ${toolById[groupCurrent[group.id]].label}`"
          :aria-pressed="armed === groupCurrent[group.id]"
          aria-haspopup="menu"
          :aria-expanded="openGroup === group.id"
          @pointerdown="startGroupPress(group.id, groupCurrent[group.id], $event)"
          @click.prevent="onGroupButtonClick(groupCurrent[group.id], $event)"
          @keydown.down.prevent="openGroup = group.id"
        >
          <ToolIcon :name="toolById[groupCurrent[group.id]].icon" />
          <svg
            viewBox="0 0 6 6" aria-hidden="true"
            class="absolute right-[3px] bottom-[3px] w-1.5 h-1.5 text-content-tertiary pointer-events-none"
          ><path d="M6 0v6H0z" fill="currentColor" /></svg>
        </button>
        <!-- The padding is a bridge for a held pointer moving into the menu. -->
        <div
          v-if="openGroup === group.id"
          class="absolute bottom-full left-1/2 -translate-x-1/2 pb-1 z-menu"
        >
          <div
            class="flex flex-col gap-0.5 p-1 bg-surface border border-edge-subtle rounded-lg shadow-lg"
            role="menu"
          >
            <button
              v-for="id in group.members"
              :key="id"
              type="button"
              role="menuitemradio"
              :aria-checked="armed === id"
              :data-select-tool="id"
              class="flex items-center gap-2 px-2 py-1.5 rounded-md text-xs whitespace-nowrap transition-colors"
              :class="buttonClass(armed === id)"
              :title="toolById[id].hint"
              @click.stop="chooseGroupTool(id)"
            >
              <ToolIcon :name="toolById[id].icon" />
              {{ toolById[id].label }}
            </button>
          </div>
        </div>
      </template>
    </span>

    <span class="w-px h-5 bg-edge-subtle mx-1" />

    <!-- Held modifiers preview the NEXT gesture's mode without moving the
         persistent control: the overridden option lights up while the sticky
         choice stays where the person put it. -->
    <Tooltip v-for="option in SELECTION_MODES" :key="option.id" :text="option.label">
      <button
        type="button"
        class="p-1.5 rounded-md transition-colors"
        :class="buttonClass((combineOverride ?? combine) === option.id, combineEnabled)"
        :aria-label="option.label"
        :aria-pressed="combine === option.id"
        :disabled="!combineEnabled"
        @click="emit('set', { combine: option.id })"
      >
        <ToolIcon :name="option.icon" />
      </button>
    </Tooltip>

    <span class="w-px h-5 bg-edge-subtle mx-1" />

    <span v-if="hasSelection" class="flex items-center gap-1.5">
      <Tooltip :text="`Contract selection by ${edgeAmount} pixels`">
        <button
          type="button"
          class="p-1.5 rounded-md text-content-secondary hover:text-content hover:bg-overlay-subtle"
          :aria-label="`Contract selection by ${edgeAmount} pixels`"
          @click="morphSelection(-1)"
        >
          <PaintToolIcon name="maskContract" />
        </button>
      </Tooltip>
      <Tooltip :text="`Expand selection by ${edgeAmount} pixels`">
        <button
          type="button"
          class="p-1.5 rounded-md text-content-secondary hover:text-content hover:bg-overlay-subtle"
          :aria-label="`Expand selection by ${edgeAmount} pixels`"
          @click="morphSelection(1)"
        >
          <PaintToolIcon name="maskExpand" />
        </button>
      </Tooltip>
      <label class="flex items-center gap-0.5 text-xs text-content-tertiary">
        <input
          v-model.number="edgeAmount"
          type="number"
          min="1"
          max="100"
          aria-label="Selection edge amount in pixels"
          class="w-9 px-1.5 py-1 text-right font-mono tabular-nums text-content bg-overlay-subtle
                 rounded-md border border-transparent outline-none focus:border-accent
                 focus-visible:ring-2 ring-accent/40 [appearance:textfield]
                 [&::-webkit-inner-spin-button]:appearance-none [&::-webkit-outer-spin-button]:appearance-none"
          @change="edgeAmount = Math.max(1, Math.min(100, Math.round(Number(edgeAmount) || 1)))"
        />
        <span class="font-mono">px</span>
      </label>
    </span>

    <span v-if="hasSelection" class="w-px h-5 bg-edge-subtle mx-1" />

    <button
      type="button"
      class="px-2.5 py-1.5 text-xs rounded-md whitespace-nowrap"
      :class="buttonClass(false, hasSelection)"
      :disabled="!hasSelection"
      @click="emit('invert')"
    >
      Invert
    </button>
    <button
      type="button"
      class="px-2.5 py-1.5 text-xs rounded-md whitespace-nowrap"
      :class="buttonClass(false, hasSelection)"
      :disabled="!hasSelection"
      @click="emit('clear')"
    >
      Deselect
    </button>
  </div>
  </template>
  </div>
</template>
