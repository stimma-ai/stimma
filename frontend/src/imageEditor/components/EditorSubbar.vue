<script setup lang="ts">
/**
 * The active family's sub-toolbar, directly beneath the tool row.
 *
 * Holds only the HOT controls. Everything with a large surface — the whole
 * Adjust control set, per-engine brush settings — lives in the selected row's
 * inspector, which is what lets a 40-knob tool exist without a second layout
 * system. Nobody gets forty controls in a toolbar; nobody loses them either.
 */
import { computed, nextTick, ref, watch } from 'vue'
import {
  AdjustmentsHorizontalIcon,
  ClockIcon,
  XMarkIcon,
} from '@heroicons/vue/24/outline'
import ScrubValue from '../../components/ui/ScrubValue.vue'
import Tooltip from '../../components/ui/Tooltip.vue'
import ToolbarPopover from './ToolbarPopover.vue'
import ToolIcon from './ToolIcon.vue'
import BrushPicker from '../ported/BrushPicker.vue'
import ColorPicker from '../ported/ColorPicker.vue'
import PaintPicker from './PaintPicker.vue'
import PaintFillGroup from './PaintFillGroup.vue'
import ReferenceImageStrip from './ReferenceImageStrip.vue'
import ToolAdvancedParams, { filterScalarGroups } from './ToolAdvancedParams.vue'
import ExpandEdgesControl from './ExpandEdgesControl.vue'
import GenerationRunButton from './GenerationRunButton.vue'
import { useToolSchemaFeatures } from '../../composables/useToolSchemaFeatures'
import { OUTPAINT_EXPAND_FIELDS } from '../../utils/taskTypeValidation'
import { toolSupportsLoras } from '../../utils/loraSchema'

/** Mutable copy: the readonly tuple can't feed a `string[]` prop. */
const OUTPAINT_EXPAND_FIELDS_LIST = [...OUTPAINT_EXPAND_FIELDS]
import {
  CROP_ASPECTS,
} from '../stack/adjustSections'
import {
  PAINT_ENGINES, TEXT_STYLES,
  familyById,
} from '../stack/toolFamilies'
import {
  LOOK_CATEGORIES, AUTO_EDITS,
  PHOTOGRAPHIC_LEVEL_EDITS, CREATIVE_LEVEL_EDITS,
} from '../stack/adjustSections'
import type { FamilyId } from '../stack/toolFamilies'
import type { Paint } from '../ported/shapeTypes'
import type { IconName } from '../ported/icons'
import type { PaintGradientType } from '../stack/paintEngineSettings'
import { paintCss, paintSolid } from '../stack/paints'

const props = defineProps<{
  family: FamilyId
  sub: string | null
  state: Record<string, any>
  /** The catalog tool that will run the active Generate sub-tool. */
  toolLabel?: string | null
  busy?: boolean
  canRun?: boolean
  /** Verb for the run button: an iterating session says "Re-run". */
  runLabel?: string | null
  /**
   * Phone layout (DESIGN.md §1.11): the bar lives in the editor's drawer,
   * and each family's controls become stacked rows that scroll sideways
   * instead of one wrapping line. Same controls, same events.
   */
  compact?: boolean
}>()

/**
 * A logical row of the bar. On desktop `contents` dissolves the wrapper so
 * the chips keep wrapping in the bar's single flex line; on a phone it is a
 * touch-height row that scrolls sideways.
 */
const ROW = 'contents compact:flex compact:items-center compact:gap-1 compact:shrink-0 compact:min-h-11 compact:overflow-x-auto compact:[&>*]:shrink-0 compact:[scrollbar-width:none] compact:-mx-2 compact:px-2'

const emit = defineEmits<{
  sub: [string]
  set: [Record<string, any>, continuous?: boolean]
  commit: ['crop' | 'annotation']
  run: []
  openToolPicker: [MouseEvent]
  refreshLoras: [string]
  uploadLoras: [string, string, File[]]
}>()

const family = computed(() => familyById(props.family))

/** Stroke weights the width popover offers, in canvas pixels. */
const STROKE_WEIGHTS = [2, 4, 8, 14, 22]

/**
 * The universal shape effects, as a small icon menu.
 *
 * Gradient is not one: it is a color, chosen in the stroke or fill well.
 */
const SHAPE_EFFECTS = [
  { id: 'none', label: 'None' },
  { id: 'neon', label: 'Neon' },
] as const

/** The current effect's label, shown on the toolbar chip so the state reads at a glance. */
const shapeEffectLabel = computed(
  () => SHAPE_EFFECTS.find(fx => fx.id === (props.state.annotateShapeEffect ?? 'none'))?.label ?? 'None',
)

/** Which annotate sub-tools show which style controls. */
const strokeSubs = ['arrow', 'draw', 'rectangle', 'ellipse', 'line']
const fillSubs = ['rectangle', 'ellipse']
// Sharpie strokes take their glow from the brush, not the shape style, so the
// effect menu would lie on Draw.
const effectSubs = ['arrow', 'rectangle', 'ellipse', 'line']
/** Retouch brushes whose engine takes a strength/direction beyond the brush. */
const dodgeBurnSubs = ['dodge', 'burn']
const strengthSubs = ['sponge', 'blur', 'sharpen']

const standalonePaintEngines = PAINT_ENGINES.filter(engine =>
  engine.id !== 'fill' && engine.id !== 'gradient',
)

/** Photoshop's five gradient geometries, in its familiar order. */
const paintGradientTypes: Array<{
  id: PaintGradientType
  label: string
  icon: IconName
}> = [
  { id: 'linear', label: 'Linear', icon: 'gradientLinear' },
  { id: 'radial', label: 'Radial', icon: 'gradientRadial' },
  { id: 'angle', label: 'Angle', icon: 'gradientAngle' },
  { id: 'reflected', label: 'Reflected', icon: 'gradientReflected' },
  { id: 'diamond', label: 'Diamond', icon: 'gradientDiamond' },
]

/**
 * A SELECTED shape overrides the sub-tool: the controls shown are the ones the
 * shape actually has, and they read/write its values. With nothing selected
 * they are the latent tool's initial conditions.
 */
const shapeKind = computed<string | null>(() => props.state.selectedShapeKind ?? null)

const strokeKinds = ['arrow', 'curved-arrow', 'line', 'path', 'rectangle', 'ellipse']
const fillKinds = ['rectangle', 'ellipse']
const effectKinds = ['arrow', 'curved-arrow', 'line', 'rectangle', 'ellipse']

const showStroke = computed(() =>
  shapeKind.value ? strokeKinds.includes(shapeKind.value) : strokeSubs.includes(props.sub ?? '')
)
const showFill = computed(() =>
  shapeKind.value ? fillKinds.includes(shapeKind.value) : fillSubs.includes(props.sub ?? '')
)
const showEffect = computed(() =>
  shapeKind.value ? effectKinds.includes(shapeKind.value) : effectSubs.includes(props.sub ?? '')
)
const showText = computed(() =>
  shapeKind.value ? shapeKind.value === 'text' : props.sub === 'text'
)

/**
 * Whether this slot can hold a gradient.
 *
 * Pen strokes are stamped pixels rather than a path the canvas can hand a
 * gradient to, so Draw's color is a flat one — offering the tab there would
 * be a promise the renderer cannot keep.
 */
const allowGradient = computed(() =>
  shapeKind.value ? shapeKind.value !== 'path' : props.sub !== 'draw'
)

/** A well previews whatever paint it holds, gradient included. */
function wellCss(paint: Paint | null) {
  return paintCss(paint)
}

/**
 * Whether the active model tool has any parameters the Advanced popover would
 * show. When it wouldn't, the ⚙ does not render at all — an affordance that
 * opens "this tool has no additional parameters" is a broken promise.
 */
const activeToolRef = computed(() => props.state.activeTool ?? null)
const { groupedGenericParams } = useToolSchemaFeatures({
  tool: activeToolRef,
  availableLoras: computed(() => []),
})
const hasAdvancedParams = computed(() => filterScalarGroups(
  groupedGenericParams.value,
  props.sub === 'expand' ? OUTPAINT_EXPAND_FIELDS_LIST : undefined,
).length > 0 || toolSupportsLoras(activeToolRef.value))

/**
 * The prompt is one quiet line that grows with its content (capped at ~4
 * lines) so the bar holds its 1-row height until somebody actually writes.
 */
const promptEl = ref<HTMLTextAreaElement | null>(null)
function resizePrompt() {
  const el = promptEl.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = `${Math.min(el.scrollHeight, 96)}px`
}
watch(
  () => [props.state.prompt, props.sub],
  () => nextTick(resizePrompt),
  { immediate: true },
)

function chipClass(active: boolean, pending = false) {
  if (pending) return 'text-content-tertiary/60 cursor-not-allowed'
  return active
    ? 'bg-selection/15 text-content'
    : 'text-content-secondary hover:text-content hover:bg-overlay-subtle'
}
</script>

<template>
  <!-- A container: every narrow-state decision in here keys off the BAR's
       width, not the viewport's — the resizable sidebar makes them unrelated. -->
  <div
    class="@container flex items-center gap-1.5 flex-wrap border-b border-edge-subtle bg-surface px-4 py-2"
    :class="compact && '!flex-col !items-stretch !flex-nowrap !gap-1 !px-3 !py-1 !border-b-0'"
  >
    <!-- Sub-tools, for the families that have them. Retouch lays its own out:
         its bar is two jobs, not one list. -->
    <template v-if="family.subTools.length && family.id !== 'retouch'">
      <div :class="ROW">
      <template
        v-for="option in family.subTools"
        :key="option.id"
      >
        <Tooltip
          :text="option.pending ? 'Not built yet' : option.hint ?? option.label"
        >
          <button
            type="button"
            class="inline-flex items-center gap-1.5 px-2 py-1.5 text-xs rounded-md compact:min-h-11 compact:px-3 compact:text-[13px] compact:whitespace-nowrap transition-colors"
            :class="chipClass(sub === option.id, option.pending)"
            :disabled="option.pending"
            :aria-label="option.label"
            @click="emit('sub', option.id)"
          >
            <ToolIcon v-if="option.icon" :name="option.icon" />
            <!-- In a narrow bar the labels are what force the chip row to
                 wrap; iconed chips drop them and keep their tooltips. -->
            <span
              v-if="compact || !option.icon || option.labeled"
              :class="option.icon && 'hidden @xl:inline compact:inline'"
            >{{ option.label }}</span>
          </button>
        </Tooltip>
      </template>
      </div>
      <span class="w-px h-5 bg-edge-subtle mx-1 compact:hidden" />
    </template>

    <!-- Retouch's chip row: every tool is a brush; the picker sits with the
         chips because it belongs to whichever brush is armed. Patch is
         selection-driven, so it alone has no brush. -->
    <template v-if="family.id === 'retouch'">
      <div :class="ROW">
      <template
        v-for="option in family.subTools"
        :key="option.id"
      >
        <Tooltip :text="option.pending ? 'Not built yet' : option.hint ?? option.label">
          <button
            type="button"
            class="inline-flex items-center gap-1.5 px-2 py-1.5 text-xs rounded-md compact:min-h-11 compact:px-3 compact:text-[13px] compact:whitespace-nowrap transition-colors"
            :class="chipClass(sub === option.id, option.pending)"
            :disabled="option.pending"
            :aria-label="option.label"
            @click="emit('sub', option.id)"
          >
            <ToolIcon v-if="option.icon" :name="option.icon" />
            <!-- In a narrow bar the labels are what force the chip row to
                 wrap; iconed chips drop them and keep their tooltips. -->
            <span
              v-if="compact || !option.icon || option.labeled"
              :class="option.icon && 'hidden @xl:inline compact:inline'"
            >{{ option.label }}</span>
          </button>
        </Tooltip>
      </template>
      </div>

      <!-- The sub-tool chip beside this says what work is being authored.
           The brush only defines its region; it is not itself a Paint stroke. -->
      <ToolbarPopover
        v-if="sub !== 'patch'"
        :label="`${Math.round(state.retouchBrush.size)}px`"
        :width="336"
      >
        <template #trigger>
          <span
            class="w-4 h-4 rounded-full bg-content"
            :style="{
              opacity: state.retouchBrush.opacity / 100,
              filter: `blur(${(100 - state.retouchBrush.hardness) / 40}px)`,
            }"
          />
        </template>
        <BrushPicker
          :model-value="state.retouchBrush"
          :stroke-color="state.paintColor"
          @update:model-value="emit('set', { retouchBrush: $event })"
        />
      </ToolbarPopover>

      <!-- Strength for the photographic brushes. These seed the region the
           next gesture creates; the landed region's own values then live in
           its Properties, where they stay adjustable. -->
      <template v-if="dodgeBurnSubs.includes(sub ?? '')">
        <label class="flex items-center gap-2 text-xs text-content-tertiary">
          Exposure
          <input
            type="range" min="1" max="100" class="w-20"
            :value="state.retouchExposure"
            @input="emit('set', { retouchExposure: Number(($event.target as HTMLInputElement).value) })"
          />
          <span class="w-8 text-right font-mono tabular-nums text-content-secondary">
            {{ state.retouchExposure }}%
          </span>
        </label>
        <div :class="ROW">
        <button
          v-for="range in ['shadows', 'midtones', 'highlights']"
          :key="range"
          type="button"
          class="px-2 py-1.5 text-xs rounded-md compact:min-h-11 compact:px-3 compact:text-[13px] compact:whitespace-nowrap capitalize"
          :class="chipClass(state.retouchRange === range)"
          @click="emit('set', { retouchRange: range })"
        >
          {{ range }}
        </button>
        </div>
      </template>
      <template v-else-if="strengthSubs.includes(sub ?? '')">
        <label class="flex items-center gap-2 text-xs text-content-tertiary">
          Strength
          <input
            type="range" min="1" max="100" class="w-20"
            :value="state.retouchStrength"
            @input="emit('set', { retouchStrength: Number(($event.target as HTMLInputElement).value) })"
          />
          <span class="w-8 text-right font-mono tabular-nums text-content-secondary">
            {{ state.retouchStrength }}%
          </span>
        </label>
        <template v-if="sub === 'sponge'">
          <button
            type="button"
            class="px-2 py-1.5 text-xs rounded-md compact:min-h-11 compact:px-3 compact:text-[13px] compact:whitespace-nowrap"
            :class="chipClass(state.retouchSaturate)"
            @click="emit('set', { retouchSaturate: true })"
          >
            Saturate
          </button>
          <button
            type="button"
            class="px-2 py-1.5 text-xs rounded-md compact:min-h-11 compact:px-3 compact:text-[13px] compact:whitespace-nowrap"
            :class="chipClass(!state.retouchSaturate)"
            @click="emit('set', { retouchSaturate: false })"
          >
            Desaturate
          </button>
        </template>
      </template>
    </template>

    <!-- Crop ------------------------------------------------------------ -->
    <template v-if="family.id === 'crop'">
      <div :class="ROW">
      <button
        v-for="preset in CROP_ASPECTS"
        :key="preset.id"
        type="button"
        class="px-2.5 py-1.5 text-xs rounded-md compact:min-h-11 compact:px-3 compact:text-[13px] compact:whitespace-nowrap transition-colors"
        :class="chipClass(state.cropAspect === preset.id)"
        @click="emit('set', { cropAspect: preset.id })"
      >
        {{ preset.label }}
      </button>
      </div>
      <span class="w-px h-5 bg-edge-subtle mx-1 compact:hidden" />
      <!-- The lollipop on the crop is the primary straightening control; this
           mirrors it for fine values and shows the angle in degrees. -->
      <!-- Shown as the angle the PICTURE turns, which is what the user sees
           and the opposite sign of the crop window's own tilt. -->
      <div :class="ROW">
      <label class="flex items-center gap-2 text-xs text-content-tertiary compact:flex-1 compact:text-[13px]">
        Straighten
        <input
          type="range" min="-0.7854" max="0.7854" step="0.002" class="w-28 compact:flex-1 compact:w-auto"
          :value="-(state.rotation ?? 0)"
          @input="emit(
            'set',
            { rotation: -Number(($event.target as HTMLInputElement).value) },
            true,
          )"
          @change="emit('commit', 'crop')"
        />
        <span class="tabular-nums w-10">{{ (-(state.rotation ?? 0) * 180 / Math.PI).toFixed(1) }}°</span>
      </label>
      <button
        v-if="state.rotation"
        type="button"
        class="px-2 py-1.5 text-xs rounded-md compact:min-h-11 compact:px-3 compact:text-[13px] compact:whitespace-nowrap text-content-secondary hover:text-content hover:bg-overlay-subtle"
        @click="emit('set', { rotation: 0 })"
      >
        Reset
      </button>
      </div>
      <div :class="ROW">
      <button type="button" class="px-2.5 py-1.5 text-xs rounded-md compact:min-h-11 compact:px-3 compact:text-[13px] compact:whitespace-nowrap compact:flex-1" :class="chipClass(false)" @click="emit('set', { rotateQuarter: true })">
        Rotate 90°
      </button>
      <button type="button" class="px-2.5 py-1.5 text-xs rounded-md compact:min-h-11 compact:px-3 compact:text-[13px] compact:whitespace-nowrap compact:flex-1" :class="chipClass(!!state.flipX)" @click="emit('set', { flipX: !state.flipX })">
        Flip H
      </button>
      <button type="button" class="px-2.5 py-1.5 text-xs rounded-md compact:min-h-11 compact:px-3 compact:text-[13px] compact:whitespace-nowrap compact:flex-1" :class="chipClass(!!state.flipY)" @click="emit('set', { flipY: !state.flipY })">
        Flip V
      </button>
      </div>
    </template>

    <!-- Generate --------------------------------------------------------- -->
    <template v-else-if="family.id === 'generate'">
      <!-- Remove/Repaint/Cutout/Expand are one explicit model run over the
           shared selection. The bar itself is the surface — no card floating
           inside it. One invariant grammar: the SUBJECT on the left (prompt,
           hint sentence, or the four edges — the only part that changes per
           tool), the control cluster on the right in fixed order: model ·
           advanced · hot params · Run. Slots disappear per tool;
           they never reorder. Every provider parameter still lives behind
           Advanced. -->
      <div
        v-if="sub"
        class="flex w-full flex-wrap items-center gap-x-2.5 gap-y-2"
        :class="(sub === 'remove' || sub === 'cutout') && 'py-0.5'"
      >
        <!-- Subject: Repaint's prompt — the one input that IS an input.
             References ride inside it as attachment chips, like a chat
             composer, instead of claiming a second full-width row. -->
        <div
          v-if="sub === 'repaint'"
          class="flex min-w-64 flex-1 basis-80 items-center gap-2 rounded-md bg-overlay-subtle px-2.5
                 border border-transparent focus-within:border-accent compact:basis-full compact:min-w-0"
        >
          <textarea
            ref="promptEl"
            rows="1"
            class="flex-1 min-w-0 py-1.5 text-sm bg-transparent text-content resize-none compact:py-3 compact:text-[15px]
                   overflow-y-auto placeholder:text-content-muted focus-visible:outline-none"
            placeholder="Describe the changes for the selected area"
            :value="state.prompt"
            @input="emit('set', { prompt: ($event.target as HTMLTextAreaElement).value })"
            @keydown.enter.meta="emit('run')"
          />
          <ReferenceImageStrip
            v-if="state.referenceMax > 0 || state.referenceImages?.length"
            inline
            :model-value="state.referenceImages || []"
            :min-items="state.referenceMin || 0"
            :max-items="state.referenceMax || 0"
            :disabled="busy"
            @update:model-value="emit('set', { referenceImages: $event })"
          />

          <!-- Prompt history lives with the prompt. Rendered only when there
               IS history — inside the field a permanently disabled clock
               would be clutter, not an affordance. -->
          <ToolbarPopover
            v-if="state.recentRepaintPrompts?.length"
            label=""
            :width="320"
            :chevron="false"
            close-on-select
            aria-label="Recent Repaint prompts"
          >
            <template #trigger>
              <ClockIcon class="w-3.5 h-3.5" />
            </template>
            <div class="space-y-1">
              <p class="px-2 pb-1 text-xs font-semibold text-content-secondary">
                Recent prompts
              </p>
              <!-- The row is the container so the whole strip highlights and
                   reveals its remove control; the prompt and the × are
                   siblings, not nested buttons. Only the prompt closes the
                   popover, so removing several in a row keeps it open. -->
              <div
                v-for="recent in state.recentRepaintPrompts"
                :key="recent"
                class="group/recent flex items-center gap-1 rounded-md pr-1
                       hover:bg-overlay-subtle"
              >
                <button
                  type="button"
                  data-close-popover
                  class="min-w-0 flex-1 rounded-md px-2 py-2 text-left text-xs leading-5
                         text-content-secondary group-hover/recent:text-content
                         focus-visible:outline-none focus-visible:ring-2 ring-accent/60"
                  @click="emit('set', { prompt: recent })"
                >
                  {{ recent }}
                </button>
                <button
                  type="button"
                  class="grid h-6 w-6 shrink-0 place-items-center rounded-md
                         text-content-tertiary opacity-0 transition-opacity
                         group-hover/recent:opacity-100 hover:text-content
                         focus-visible:opacity-100 focus-visible:outline-none
                         focus-visible:ring-2 ring-accent/60"
                  aria-label="Remove from recent prompts"
                  @click="emit('set', { removeRecentPrompt: recent })"
                >
                  <XMarkIcon class="w-3.5 h-3.5" />
                </button>
              </div>
            </div>
          </ToolbarPopover>
        </div>

        <!-- Subject: Expand's four edges, inline — they ARE the tool's input. -->
        <ExpandEdgesControl
          v-else-if="sub === 'expand'"
          class="min-w-0 flex-1 basis-80 @2xl:basis-[29rem]"
          :edges="state.expandEdges"
          :frame-width="state.frameWidth"
          :frame-height="state.frameHeight"
          :disabled="busy"
          @update="emit('set', { expandEdges: $event })"
        />

        <!-- Subject: no prompt, no fake input — the hint is just a sentence. -->
        <p v-else class="min-w-48 flex-1 basis-64 truncate text-sm text-content-muted compact:basis-full compact:whitespace-normal compact:min-h-11 compact:flex compact:items-center">
          {{ sub === 'cutout'
            ? 'Makes the background transparent.'
            : 'Select the area to remove, then Run.' }}
        </p>

        <!-- No ml-auto: on a shared line the flex-1 subject already pushes the
             cluster to the right edge, and on its own (wrapped) line it sits
             flush left under the subject instead of drifting to the far right
             with dead space beside it. -->
        <div class="flex min-w-0 max-w-full items-center gap-2 compact:w-full compact:min-h-11">
          <button
            type="button"
            class="inline-flex min-w-0 max-w-56 items-center gap-1.5 truncate rounded-md px-2 py-1.5
                   text-xs text-content-secondary hover:bg-overlay-subtle hover:text-content
                   compact:min-h-11 compact:px-3 compact:text-[13px] compact:bg-overlay-subtle compact:flex-1 compact:max-w-none"
            @click="emit('openToolPicker', $event)"
          >
            <span class="truncate">{{ toolLabel || 'No tool' }}</span>
            <svg viewBox="0 0 24 24" class="h-3 w-3 shrink-0" fill="none" stroke="currentColor" stroke-width="2">
              <path d="m6 9 6 6 6-6" stroke-linecap="round" stroke-linejoin="round" />
            </svg>
          </button>

          <ToolbarPopover
            v-if="state.activeTool && hasAdvancedParams"
            label=""
            :width="360"
            :chevron="false"
            aria-label="Advanced settings"
          >
            <template #trigger>
              <AdjustmentsHorizontalIcon class="h-4 w-4" />
            </template>
            <ToolAdvancedParams
              :tool="state.activeTool"
              :values="state.toolParams || {}"
              :exclude="sub === 'expand' ? OUTPAINT_EXPAND_FIELDS_LIST : undefined"
              :lora-tool-id="state.loraToolId"
              :is-refreshing-loras="state.isRefreshingLoras"
              :is-uploading-lora="state.isUploadingLora"
              :lora-upload-progress="state.loraUploadProgress"
              :lora-upload-file-name="state.loraUploadFileName"
              @update="(name, value) => emit('set', { toolParamPatch: { [name]: value } })"
              @refresh-loras="emit('refreshLoras', $event)"
              @upload-loras="(toolId, loraToolId, files) => emit('uploadLoras', toolId, loraToolId, files)"
            />
          </ToolbarPopover>

          <GenerationRunButton
            :count="state.candidateCount"
            :variations="sub !== 'cutout'"
            :disabled="!canRun"
            :loading="busy"
            :label="runLabel ?? undefined"
            @run="emit('run')"
            @update:count="emit('set', { candidateCount: $event })"
          />
        </div>
      </div>

    </template>

    <!-- Paint ----------------------------------------------------------- -->
    <template v-else-if="family.id === 'paint'">
      <div :class="ROW">
      <Tooltip
        v-for="engine in compact ? PAINT_ENGINES : standalonePaintEngines"
        :key="engine.id"
        :text="engine.pending ? 'Not built yet' : engine.hint ?? engine.label"
      >
        <button
          type="button"
          class="inline-flex items-center gap-1.5 px-2 py-1.5 text-xs rounded-md compact:min-h-11 compact:px-3 compact:text-[13px] compact:whitespace-nowrap transition-colors"
          :class="chipClass(state.engineId === engine.id, engine.pending)"
          :disabled="engine.pending"
          :aria-label="engine.label"
          @click="emit('set', { engineId: engine.id })"
        >
          <ToolIcon :name="engine.icon" />
          <span class="hidden compact:inline">{{ engine.label }}</span>
        </button>
      </Tooltip>
      <PaintFillGroup
        v-if="!compact"
        :active="state.engineId"
        :current="state.paintFillEngineId"
        @select="emit('set', { engineId: $event })"
      />
      </div>
      <span class="w-px h-5 bg-edge-subtle mx-1 compact:hidden" />
      <!-- A brush is not a property of the layer it painted, so it hangs off
           the toolbar rather than appearing in the Edits inspector. -->
      <ToolbarPopover
        v-if="state.engineId === 'paint' || state.engineId === 'erase'"
        :label="`${Math.round(state.paintBrush.size)}px`"
        :width="336"
      >
        <template #trigger>
          <span
            class="w-4 h-4 rounded-full bg-content"
            :style="{
              opacity: state.paintBrush.opacity / 100,
              filter: `blur(${(100 - state.paintBrush.hardness) / 40}px)`,
            }"
          />
        </template>
        <BrushPicker
          :model-value="state.paintBrush"
          :is-eraser="state.engineId === 'erase'"
          :stroke-color="state.paintColor"
          @update:model-value="emit('set', { paintBrush: $event })"
        />
      </ToolbarPopover>
      <!-- Erase has no color: its stroke is an alpha mask. -->
      <ToolbarPopover
        v-if="state.engineId !== 'erase' && state.engineId !== 'gradient'"
        label="Color"
        :width="292"
      >
        <template #trigger>
          <span
            class="w-4 h-4 rounded-md border border-edge-subtle"
            :style="{ background: wellCss(state.paintColor) }"
          />
        </template>
        <ColorPicker
          :model-value="state.paintColor"
          :image-palette="state.imagePalette"
          embedded
          @update:model-value="emit('set', { paintColor: $event })"
        />
      </ToolbarPopover>
      <template v-if="state.engineId === 'gradient'">
        <ToolbarPopover label="Gradient" :width="292">
          <template #trigger>
            <span
              class="w-16 h-4 rounded-md border border-edge-subtle"
              :style="{ background: wellCss(state.paintGradient) }"
            />
          </template>
          <PaintPicker
            :model-value="state.paintGradient"
            :image-palette="state.imagePalette"
            gradient-only
            @update:model-value="emit('set', { paintGradient: $event })"
          />
        </ToolbarPopover>

        <Tooltip
          v-for="option in paintGradientTypes"
          :key="option.id"
          :text="`${option.label} gradient`"
        >
          <button
            type="button"
            class="inline-flex items-center px-2 py-1.5 text-xs rounded-md compact:min-h-11 compact:px-3 compact:text-[13px] compact:whitespace-nowrap transition-colors"
            :class="chipClass(state.paintGradientType === option.id)"
            :aria-label="`${option.label} gradient`"
            :aria-pressed="state.paintGradientType === option.id"
            @click="emit('set', { paintGradientType: option.id })"
          >
            <ToolIcon :name="option.icon" />
          </button>
        </Tooltip>

        <Tooltip text="Reverse gradient colors">
          <button
            type="button"
            class="inline-flex items-center gap-1.5 px-2 py-1.5 text-xs rounded-md compact:min-h-11 compact:px-3 compact:text-[13px] compact:whitespace-nowrap transition-colors"
            :class="chipClass(state.paintGradientReverse)"
            :aria-pressed="state.paintGradientReverse"
            @click="emit('set', { paintGradientReverse: !state.paintGradientReverse })"
          >
            <ToolIcon name="arrowsSwap" />
            Reverse
          </button>
        </Tooltip>
      </template>
      <span class="w-px h-5 bg-edge-subtle mx-1 compact:hidden" />
      <button
        type="button"
        class="px-2.5 py-1.5 text-xs rounded-md compact:min-h-11 compact:px-3 compact:text-[13px] compact:whitespace-nowrap text-content-secondary hover:text-content hover:bg-overlay-subtle"
        @click="emit('set', { newLayer: true })"
      >
        New layer
      </button>
    </template>

    <!-- Adjust: the addable edits. Each click makes its own focused step —
         an Auto, a group edit, a look — whose controls live in its Properties.
         One rule for the whole bar: it offers what you can ADD. With a
         workspace selection live, an added edit is scoped to it (the tooltips
         say so).

         Three runs, separated: what the picture can be given automatically,
         the photographic corrections, and the things that ADD a look. Eleven
         labelled chips in one undifferentiated line is what made this wrap. -->
    <template v-else-if="family.id === 'levels'">
      <div :class="ROW">
      <!-- The Autos behind one chip. They are three variants of a single act —
           let the histogram decide — and spelled out across the bar they took a
           third of its width for the least specific thing on it.

           They stay whole-image even while a selection exists: their seeds come
           from the full-frame histogram, and scoping the result of a global
           computation would be quietly wrong (plan §14, Q15). -->
      <ToolbarPopover label="Auto" :width="196" close-on-select>
        <template #trigger>
          <ToolIcon name="wand" />
        </template>
        <button
          v-for="auto in AUTO_EDITS"
          :key="auto.id"
          type="button"
          data-close-popover
          class="w-full flex items-center gap-2.5 px-2 py-1.5 rounded-md text-left transition-colors
                 text-content-secondary hover:text-content hover:bg-overlay-subtle"
          @click="emit('set', { auto: auto.id })"
        >
          <ToolIcon :name="auto.icon" />
          <span class="text-xs">{{ auto.label }}</span>
        </button>
        <p v-if="state.hasSelection" class="px-2 pt-2 text-[11px] text-content-tertiary">
          Autos read the whole frame, so they apply to the whole image.
        </p>
      </ToolbarPopover>

      <span class="w-px h-5 bg-edge-subtle mx-1 compact:hidden" />
      <Tooltip
        v-for="edit in PHOTOGRAPHIC_LEVEL_EDITS"
        :key="edit.id"
        :text="state.hasSelection ? `${edit.label} — applies to the selection` : edit.label"
      >
        <button
          type="button"
          class="inline-flex items-center gap-1.5 px-2 py-1.5 text-xs rounded-md compact:min-h-11 compact:px-3 compact:text-[13px] compact:whitespace-nowrap
                 text-content-secondary hover:text-content hover:bg-overlay-subtle"
          :aria-label="edit.label"
          @click="emit('set', { addLevel: edit.id })"
        >
          <ToolIcon :name="edit.icon" />
          {{ edit.label }}
        </button>
      </Tooltip>

      <!-- Effects, Stylize and Looks: the run that ADDS rather than corrects. -->
      <span class="w-px h-5 bg-edge-subtle mx-1 compact:hidden" />
      <Tooltip
        v-for="edit in CREATIVE_LEVEL_EDITS"
        :key="edit.id"
        :text="state.hasSelection ? `${edit.label} — applies to the selection` : edit.label"
      >
        <button
          type="button"
          class="inline-flex items-center gap-1.5 px-2 py-1.5 text-xs rounded-md compact:min-h-11 compact:px-3 compact:text-[13px] compact:whitespace-nowrap
                 text-content-secondary hover:text-content hover:bg-overlay-subtle"
          :aria-label="edit.label"
          @click="emit('set', { addLevel: edit.id })"
        >
          <ToolIcon :name="edit.icon" />
          {{ edit.label }}
        </button>
      </Tooltip>
      <!-- Looks closes the same run: a starting point rather than a dial, and
           the only entry whose tiles have to be LOOKED at to be chosen — which
           is why it toggles a strip instead of adding a step outright. -->
      <button
        type="button"
        class="inline-flex items-center gap-1.5 px-2 py-1.5 text-xs rounded-md compact:min-h-11 compact:px-3 compact:text-[13px] compact:whitespace-nowrap transition-colors"
        :class="chipClass(!!state.looksOpen)"
        :aria-expanded="!!state.looksOpen"
        @click="emit('set', { looksOpen: !state.looksOpen })"
      >
        <ToolIcon name="image" />
        Looks
      </button>
      </div>

      <!-- One row that scrolls, rather than wrapping: the strip is a strip,
           and wrapping it would push the canvas down every time it grew.

           It runs edge to edge. The negative margins cancel the bar's own
           padding so the scroll TRACK spans the full width and sits on the
           bar's bottom border, and the lead-in padding lives INSIDE the
           overflow region so the first tile still clears the edge. Leaving the
           bar's padding on instead insets the track on three sides, which
           reads as a stray scrollbar floating in the middle of the bar. -->
      <div
        v-if="state.looksOpen"
        class="w-[calc(100%+2rem)] min-w-0 mt-2 -mx-4 -mb-2 px-4
               flex items-start gap-1.5 overflow-x-auto custom-scrollbar"
      >
        <template v-for="(category, index) in LOOK_CATEGORIES" :key="category.id">
          <span v-if="index" class="w-px h-10 bg-edge-subtle mx-1 shrink-0" />
          <Tooltip
            v-for="look in category.looks"
            :key="look.id"
            :text="state.hasSelection
              ? `${category.label} · ${look.label} — applies to the selection`
              : `${category.label} · ${look.label}`"
          >
            <button
              type="button"
              class="w-20 shrink-0 rounded-md p-0.5 transition-colors"
              :class="state.appliedLookIds?.includes(look.id)
                ? 'bg-selection/25 text-content'
                : 'text-content-tertiary hover:text-content hover:bg-overlay-subtle'"
              @click="emit('set', { applyLook: look.id })"
            >
              <img
                v-if="state.lookThumbs?.[look.id]"
                :src="state.lookThumbs[look.id]"
                class="w-full h-16 rounded-media object-cover"
                alt=""
              />
              <div v-else class="w-full h-16 rounded-media bg-matte" />
              <span class="block text-[10px] leading-tight truncate">{{ look.label }}</span>
            </button>
          </Tooltip>
        </template>
      </div>
    </template>

    <!-- Annotate: the latent shape's full initial conditions, compact — every
         control is an icon opening a popover. With a shape selected the same
         controls edit it, so the strip doubles as a remote for the selection. -->
    <template v-else-if="family.id === 'annotate'">
      <div :class="[ROW, 'compact:flex-wrap compact:overflow-visible']">
      <template v-if="showStroke">
        <!-- Stroke weight -->
        <ToolbarPopover label="" :width="148">
          <template #trigger>
            <svg viewBox="0 0 16 16" class="w-4 h-4" fill="currentColor" aria-label="Stroke width">
              <rect x="2" y="3" width="12" height="1" rx="0.5" />
              <rect x="2" y="6.5" width="12" height="2" rx="1" />
              <rect x="2" y="10.5" width="12" height="3.5" rx="1.5" />
            </svg>
          </template>
          <button
            v-for="weight in STROKE_WEIGHTS"
            :key="weight"
            type="button"
            class="w-full flex items-center gap-3 px-2 py-1.5 rounded-md transition-colors"
            :class="state.annotateStrokeWidth === weight
              ? 'bg-selection/15 text-content'
              : 'text-content-secondary hover:text-content hover:bg-overlay-subtle'"
            @click="emit('set', { annotateStrokeWidth: weight })"
          >
            <span
              class="flex-1 rounded-full bg-current"
              :style="{ height: Math.min(weight, 12) + 'px' }"
            />
            <span class="text-[11px] tabular-nums w-8 text-right">{{ weight }}px</span>
          </button>
        </ToolbarPopover>

        <!-- Stroke color: a ring, because the stroke is an outline. -->
        <ToolbarPopover :label="compact ? 'Stroke' : ''" aria-label="Stroke color" :width="292">
          <template #trigger>
            <span
              class="w-4 h-4 rounded-full ring-inset"
              aria-label="Stroke color"
              :style="{
                background: wellCss(allowGradient ? state.annotatePaint : paintSolid(state.annotatePaint)),
                mask: 'radial-gradient(circle, transparent 0 34%, #000 34%)',
                WebkitMask: 'radial-gradient(circle, transparent 0 34%, #000 34%)',
              }"
            />
          </template>
          <PaintPicker
            :model-value="allowGradient ? state.annotatePaint : paintSolid(state.annotatePaint)"
            :image-palette="state.imagePalette"
            :allow-gradient="allowGradient"
            @update:model-value="emit('set', { annotatePaint: $event })"
          />
        </ToolbarPopover>

        <!-- Fill: a solid square, because the fill is the inside. -->
        <ToolbarPopover v-if="showFill" :label="compact ? 'Fill' : ''" aria-label="Fill color" :width="292">
          <template #trigger>
            <span
              class="w-4 h-4 rounded-[4px] border border-edge-subtle"
              aria-label="Fill color"
              :style="state.annotateFillColor
                ? { background: wellCss(state.annotateFillColor) }
                : { background: 'repeating-linear-gradient(45deg, transparent 0 3px, rgba(255,255,255,.25) 3px 5px)' }"
            />
          </template>
          <button
            type="button"
            class="w-full mb-2 px-2 py-1.5 text-xs rounded-md compact:min-h-11 compact:px-3 compact:text-[13px] compact:whitespace-nowrap text-left transition-colors"
            :class="!state.annotateFillColor
              ? 'bg-selection/15 text-content'
              : 'text-content-secondary hover:text-content hover:bg-overlay-subtle'"
            @click="emit('set', { annotateFillColor: null })"
          >
            No fill
          </button>
          <PaintPicker
            :model-value="state.annotateFillColor ?? { r: 0, g: 0, b: 0, a: 0.5 }"
            :image-palette="state.imagePalette"
            :allow-gradient="allowGradient"
            @update:model-value="emit('set', { annotateFillColor: $event })"
          />
        </ToolbarPopover>

        <!-- Effect: none, or the neon glow. -->
        <ToolbarPopover v-if="showEffect" :label="shapeEffectLabel" :width="148">
          <template #trigger>
            <span class="sr-only">Effect</span>
          </template>
          <button
            v-for="fx in SHAPE_EFFECTS"
            :key="fx.id"
            type="button"
            class="w-full flex items-center gap-3 px-2 py-1.5 rounded-md transition-colors"
            :class="(state.annotateShapeEffect ?? 'none') === fx.id
              ? 'bg-selection/15 text-content'
              : 'text-content-secondary hover:text-content hover:bg-overlay-subtle'"
            @click="emit('set', { annotateShapeEffect: fx.id })"
          >
            <svg viewBox="0 0 24 16" class="w-6 h-4 shrink-0" fill="none">
              <path
                v-if="fx.id === 'neon'"
                d="M2 8 h20" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"
                style="filter: drop-shadow(0 0 3px currentColor)"
              />
              <path v-else d="M2 8 h20" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" />
            </svg>
            <span class="text-xs">{{ fx.label }}</span>
          </button>
        </ToolbarPopover>
      </template>

      <template v-if="showText">
        <!-- Text color shares the stroke well; the presets carry the rest. -->
        <ToolbarPopover :label="compact ? 'Text color' : ''" aria-label="Text color" :width="292">
          <template #trigger>
            <span
              class="w-4 h-4 rounded-full"
              aria-label="Text color"
              :style="{
                background: wellCss(state.annotatePaint),
                mask: 'radial-gradient(circle, transparent 0 34%, #000 34%)',
                WebkitMask: 'radial-gradient(circle, transparent 0 34%, #000 34%)',
              }"
            />
          </template>
          <PaintPicker
            :model-value="state.annotatePaint"
            :image-palette="state.imagePalette"
            :allow-gradient="allowGradient"
            @update:model-value="emit('set', { annotatePaint: $event })"
          />
        </ToolbarPopover>
        <button
          v-for="style in TEXT_STYLES"
          :key="style.id"
          type="button"
          class="px-2.5 py-1.5 text-xs rounded-md compact:min-h-11 compact:px-3 compact:text-[13px] compact:whitespace-nowrap transition-colors"
          :class="chipClass(state.textStyle === style.id)"
          @click="emit('set', { textStyle: style.id })"
        >
          {{ style.label }}
        </button>
      </template>

      <!-- Opacity, inline: one slider does not deserve a popover. -->
      <label
        v-if="sub !== 'redact'"
        class="flex items-center gap-2 text-xs text-content-tertiary compact:flex-1 compact:basis-full compact:min-w-0"
        title="Opacity"
      >
        <span class="hidden compact:inline">Opacity</span>
        <svg viewBox="0 0 16 16" class="w-4 h-4 compact:hidden" fill="none" stroke="currentColor">
          <circle cx="8" cy="8" r="6" />
          <path d="M8 2 a6 6 0 0 1 0 12 Z" fill="currentColor" stroke="none" opacity="0.5" />
        </svg>
        <input
          type="range" min="10" max="100" class="w-20 compact:flex-1 compact:w-auto compact:min-w-16"
          :value="Math.round((state.annotateOpacity ?? 1) * 100)"
            @input="emit(
              'set',
              { annotateOpacity: Number(($event.target as HTMLInputElement).value) / 100 },
              true,
            )"
            @change="emit('commit', 'annotation')"
        />
      </label>
      </div>
    </template>

  </div>
</template>
