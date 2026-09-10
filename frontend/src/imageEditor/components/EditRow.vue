<script setup lang="ts">
/**
 * One row in the Edits list.
 *
 * The row grammar IS the cost signal: the eye toggle, drag grip and candidate
 * chips respond to the hand and are free; anything that costs money is a
 * button, never a slider. Rows carry no price badges — the shape of the control
 * says it.
 *
 * Layout law for the Edits list (EditRow and BaseRow both obey it, which is
 * what makes the column read):
 *   - The square preview is the row's anchor: one size, one position, in every
 *     row, so the list reads as a single column of images down the panel.
 *   - The title's first line centers on the square. Subtitles and chips flow
 *     BELOW that line, growing the row downward — so a row with one line and a
 *     row with four still align at the top, against their squares.
 *   - Controls live to the right of the text, in one cluster: eye, then
 *     remove. Both are permanent — whether a step is on, and the way to take
 *     it off, are not things to go hunting for under the cursor. Only
 *     Resample, which costs money, waits for hover.
 *
 * Rows hold identity, eye, candidates and advisory state only. The full control
 * surface for a selected row lives in the inspector below the stack, because a
 * 40-knob tool cannot live in a 42px row. There is no row overflow menu: a
 * menu of mostly-disabled verbs is not a control surface, it is a place things
 * go to be undiscoverable.
 *
 * Reordering is drag, and only drag.
 */
import { computed, ref, watch } from 'vue'
import {
  EyeIcon, EyeSlashIcon, TrashIcon, ArrowPathIcon,
  ChevronDownIcon, ChevronRightIcon,
} from '@heroicons/vue/24/outline'
import DragGrip from '../../components/ui/DragGrip.vue'
import IconButton from '../../components/ui/IconButton.vue'
import Tooltip from '../../components/ui/Tooltip.vue'
import { getTaskTypeIconSvg } from '../../utils/taskTypeIcons'
import { sanitizeSvg } from '../../utils/sanitizeHtml'
import { ROW_SQUARE, ROW_COLUMN, ROW_COLUMN_INLINE } from './rowLayout'
import { photoAdjustmentGroup } from '../stack/adjustSections'
import {
  generativeOpHasEditableMask,
  maskComponentLabel,
  maskComponentModeLabel,
  opMaskComponents,
  regionMaskComponents,
} from '../stack/maskComponents'
import type { MaskComponent, Op, RetouchRegion } from '../stack/types'
import type { Staleness } from '../stack/stackState'
import {
  adjacentCandidateIndex,
  candidateNavigationDelta,
} from '../stack/candidateNavigation'
import {
  groupCandidateBatches,
  type PendingCandidateBatch,
} from '../stack/candidateBatches'

interface CandidateThumb {
  id: string
  url: string
  fromPreviousState?: boolean
  batchId?: string
}

const props = defineProps<{
  op: Op
  selected: boolean
  staleness: Staleness
  /** Candidate thumbnails, resolved by the parent. */
  candidateThumbs?: CandidateThumb[]
  /** Jobs still running for this op. */
  pendingCount?: number
  /** In-flight slots grouped by the generation invocation that owns them. */
  pendingBatches?: PendingCandidateBatch[]
  /** Blast-radius preview: this row would be disturbed by the hovered gesture. */
  previewStaleness?: Staleness | null
  /** Its spatial payload no longer intersects the frame. */
  outOfFrame?: boolean
  resampling?: boolean
  draggable?: boolean
  /** This row is the one being dragged — it reads as lifted out of the list. */
  dragging?: boolean
  /** The image as of this step — the row's square. Absent until first render. */
  preview?: string
  /** Selected child in the one hierarchical Retouch row. */
  selectedRegionId?: string | null
  /** Selected mask component inside the selected adjustment region. */
  selectedMaskComponentId?: string | null
  /** A semantic component being re-segmented right now. */
  recomputingMaskComponentId?: string | null
  /** This generative op's mask (parent or a component) is the selection. */
  generativeMaskSelected?: boolean
  /** Share of this op's composed mask its picked sample never painted. */
  coverageDebt?: number
  /** Debt below this is feather noise, not missing pixels. */
  coverageDebtThreshold?: number
}>()

const emit = defineEmits<{
  select: []
  /** Double-click: re-enter a container op's session. */
  reenter: []
  toggle: [boolean]
  pick: [string]
  remove: []
  resample: []
  toggleRegion: [string, boolean]
  removeRegion: [string]
  selectRegion: [string]
  hoverRegion: [string | null]
  /** Mask component rows under a scoped adjustment's Mask sub-item. */
  selectMaskComponent: [string, string]
  hoverMaskComponent: [string, string | null]
  toggleMaskComponent: [string, string, boolean]
  removeMaskComponent: [string, string]
  /** Trash on the Mask parent: apply the adjustment to the whole image. */
  removeMask: [string]
  /** Hovering a Retouch parent previews every child location. */
  hoverRetouch: [boolean]
  /** Hovering a gesture affordance — drives the blast-radius tint. */
  intentHover: [boolean]
  dragStart: [DragEvent]
  dragEnd: []
}>()

const anyOp = computed(() => props.op as any)


const candidates = computed(() => props.candidateThumbs || [])
const candidateRows = computed(() => groupCandidateBatches(
  candidates.value.map((candidate, flatIndex) => ({ ...candidate, flatIndex })),
  props.pendingBatches?.length
    ? props.pendingBatches
    : props.pendingCount
      ? [{ batchId: 'pending-candidates', count: props.pendingCount }]
      : [],
))
const picked = computed(() => anyOp.value.picked || null)
/** A chosen patch is still useful identity while an exact composite preview is unavailable. */
const displayPreview = computed(() =>
  props.preview
  || candidates.value.find(candidate => candidate.id === picked.value)?.url
  || candidates.value[0]?.url
  || ''
)
const staged = computed(() => candidates.value.length > 0 && !picked.value)
const isGenerative = computed(() => props.op.class === 'patch')
const retouchRegions = computed(() =>
  anyOp.value.exec?.kind === 'retouch-regions' ? anyOp.value.regions ?? [] : []
)
/**
 * Regions are stored oldest-first because that is their compositing order,
 * but the editor's lists consistently present the newest operation first.
 */
const displayedRetouchRegions = computed(() => [...retouchRegions.value].reverse())
/**
 * A scoped Adjust step is one adjustment region wearing a row: the row IS the
 * region, so listing "1 region" under it is forensic noise. Real Retouch
 * containers (repairs, or several regions) keep the list.
 */
const showsRegionList = computed(() =>
  retouchRegions.value.length > 1
  || (
    retouchRegions.value.length === 1
    && !(
      retouchRegions.value[0].kind === 'adjust'
      || !!photoAdjustmentGroup(String(retouchRegions.value[0].kind))
    )
  )
)
const hasSpatialFeedback = computed(() =>
  retouchRegions.value.length > 0
  || (props.op.class === 'patch' && !!anyOp.value.mask_ref)
)
const regionsExpanded = ref(false)
watch(
  () => props.selectedRegionId,
  id => {
    if (id && retouchRegions.value.some((region: any) => region.id === id)) {
      regionsExpanded.value = true
    }
  },
)

/**
 * A scoped adjustment is one region wearing a row, and its ONE effective mask
 * is a child worth naming: the Mask sub-item lists the editable components
 * the mask is calculated from. Real Retouch containers (repairs) keep their
 * flat region list instead — a repair's mask is the repair.
 */
const adjustmentMaskRegion = computed<RetouchRegion | null>(() => {
  if (retouchRegions.value.length !== 1) return null
  const region = retouchRegions.value[0] as RetouchRegion
  const isAdjustment = region.kind === 'adjust'
    || region.kind === 'look'
    || !!photoAdjustmentGroup(String(region.kind))
  return isAdjustment ? region : null
})
const maskComponents = computed<MaskComponent[]>(() =>
  adjustmentMaskRegion.value
    ? regionMaskComponents(adjustmentMaskRegion.value)
    : [],
)
/**
 * The row's ONE mask target: a scoped adjustment's region, or a generative
 * op's own editable mask (Remove, Regenerate — never Expand or a cutout).
 * Only a region's mask is removable into "Whole image"; a maskless
 * generative edit is undefined, so its Mask parent carries no trash.
 */
const maskTarget = computed<{
  id: string
  components: MaskComponent[]
  removable: boolean
} | null>(() => {
  if (adjustmentMaskRegion.value && maskComponents.value.length) {
    return {
      id: adjustmentMaskRegion.value.id,
      components: maskComponents.value,
      removable: true,
    }
  }
  if (generativeOpHasEditableMask(anyOp.value)) {
    const components = opMaskComponents(anyOp.value)
    if (components.length) {
      return { id: props.op.id, components, removable: false }
    }
  }
  return null
})
/**
 * The Mask parent reads selected while the step's mask session is armed with
 * no individual component picked — the visible "gestures land here" signal.
 */
const maskParentActive = computed(() =>
  !props.selectedMaskComponentId
  && !!maskTarget.value
  && (props.generativeMaskSelected
    || maskTarget.value.id === props.selectedRegionId),
)
const maskExpanded = ref(false)
// Selecting a component from anywhere (a fresh capture included) reveals it.
watch(
  () => props.selectedMaskComponentId,
  id => {
    if (id && maskTarget.value?.components.some(component => component.id === id)) {
      maskExpanded.value = true
    }
  },
)
// A mask that has grown real structure is worth showing when its row opens.
watch(
  () => props.selected,
  selected => {
    if (selected && (maskTarget.value?.components.length ?? 0) > 1) {
      maskExpanded.value = true
    }
  },
)

function regionLabel(region: any): string {
  if (region.label) return region.label
  const kind = String(region.kind || 'region')
  // Adjustment regions read as their group ('Point color', 'Grading'), the
  // same name the chip that created them carried.
  const group = photoAdjustmentGroup(kind)
  if (group) return group.label
  return `${kind.charAt(0).toUpperCase()}${kind.slice(1)}`
}

function onRowMouseEnter() {
  if (hasSpatialFeedback.value) emit('hoverRetouch', true)
}

function onRowMouseLeave() {
  if (hasSpatialFeedback.value) emit('hoverRetouch', false)
}

function onRowClick(event: MouseEvent) {
  // A click on the row should hand it real keyboard focus. Controls stop their
  // own clicks, so focusing here never steals focus from an eye, trash button,
  // candidate, or other nested control.
  const row = event.currentTarget as HTMLElement
  row.focus({ preventScroll: true })
  emit('select')
}

function onCandidateClick(event: MouseEvent, candidateId: string) {
  // WebKit on macOS does not consistently focus a button when it is clicked.
  // The indigo picked ring was therefore visible while A/D and the arrow keys
  // still went to the parent row. Make the candidate the real focus owner.
  const button = event.currentTarget as HTMLButtonElement
  button.focus({ preventScroll: true })
  emit('select')
  emit('pick', candidateId)
}

function onCandidateKeydown(event: KeyboardEvent, index: number) {
  const delta = candidateNavigationDelta(event.key)
  if (delta === null) return

  event.preventDefault()
  event.stopPropagation()
  const next = adjacentCandidateIndex(candidates.value.length, index, delta)
  if (next < 0 || next === index) return
  const strips = (event.currentTarget as HTMLElement).closest('[data-candidate-rows]')
  const nextButton = strips?.querySelector(
    `[data-candidate-index="${next}"]`,
  ) as HTMLElement | null
  nextButton?.focus({ preventScroll: true })
  emit('select')
  emit('pick', candidates.value[next].id)
}

/**
 * Coverage debt: the composed mask asks for pixels the picked sample never
 * painted. Wears the same amber dot as input staleness — informational,
 * never a blocker — and Resample is what settles it.
 */
const measuredDebt = computed(() =>
  (props.coverageDebt ?? 0) >= (props.coverageDebtThreshold ?? 0.01)
  && !!(anyOp.value.mask_components?.length),
)
/**
 * Staged candidates cannot be measured against the mask (nothing composites
 * until a pick), but a recipe existing at all means the mask was edited
 * after they were sampled — the advisory holds either way.
 */
const debtAdvisory = computed(() =>
  measuredDebt.value
  || (!!(anyOp.value.mask_components?.length) && staged.value),
)
const advisory = computed(() => props.staleness === 'advisory' || debtAdvisory.value)
const advisoryText = computed(() => {
  if (measuredDebt.value) {
    return `${Math.max(1, Math.round((props.coverageDebt ?? 0) * 100))}% of the mask has no generated pixels · Re-run`
  }
  if (debtAdvisory.value) return 'Mask edited after sampling · Re-run'
  return 'Sampled against an earlier state · Re-run'
})
const previewTint = computed(() =>
  props.previewStaleness === 'advisory' ? 'ring-1 ring-amber-500/20' : ''
)
</script>

<template>
  <!-- `dragging` lifts the row: the one you are carrying reads as no longer
       in place, so the drop line is read against the list the move leaves. -->
  <div
    :data-op-id="op.id"
    :style="{ '--edit-actions-width': isGenerative ? '138px' : '94px' }"
    tabindex="0"
    class="group flex items-start gap-1.5 px-2 py-2 rounded-md cursor-default transition-colors
           focus-visible:outline-none focus-visible:ring-2 ring-accent/60"
    :class="[
      selected ? 'bg-selection/15' : 'hover:bg-overlay-subtle',
      previewTint,
      dragging && 'opacity-40',
    ]"
    :draggable="draggable"
    :aria-current="selected ? 'true' : undefined"
    @click="onRowClick"
    @keydown.enter.self.prevent="emit('select')"
    @dblclick="emit('reenter')"
    @dragstart="emit('dragStart', $event)"
    @dragend="emit('dragEnd')"
    @mouseenter="onRowMouseEnter"
    @mouseleave="onRowMouseLeave"
  >
    <!-- Drag grip. Hovering it previews what the move would disturb. -->
    <span
      v-if="draggable"
      :class="[
        ROW_COLUMN_INLINE,
        'shrink-0 text-content-tertiary opacity-0 group-hover:opacity-100 cursor-grab active:cursor-grabbing compact:hidden',
      ]"
      @mouseenter="emit('intentHover', true)"
      @mouseleave="emit('intentHover', false)"
    >
      <DragGrip class="w-2.5 h-4" />
    </span>

    <!-- The image as of this step. A hidden step shows what the stack looks
         like without it, dimmed — the eye is no longer beside the label, so
         the square carries the disabled state. -->
    <div :class="[ROW_SQUARE, 'compact:w-11 compact:h-11', !op.enabled && 'opacity-40']">
      <img v-if="displayPreview" :src="displayPreview" class="w-full h-full object-cover" alt="" />
      <div
        v-else
        class="w-full h-full bg-surface-raised"
        :class="(pendingCount || resampling) && 'animate-pulse'"
      />
    </div>

    <div :class="['min-w-0 flex-1 compact:min-h-11', ROW_COLUMN]">
      <div class="flex items-center gap-1.5 compact:min-h-11">
        <span class="text-sm truncate" :class="op.enabled ? 'text-content' : 'text-content-tertiary'">
          {{ op.label }}
        </span>
        <!-- Advisory: informational, never a blocker. Pixel-deterministic. -->
        <Tooltip v-if="advisory" :text="advisoryText">
          <span class="w-1.5 h-1.5 rounded-full bg-amber-400/80 shrink-0" />
        </Tooltip>
      </div>
      <!-- No sampling-tool line. Which model made the pixels is provenance,
           not identity: it is the same for a whole session's worth of rows, so
           it earns none of a 320px panel and says nothing about the step. The
           step's name says what it did; the receipt lives in the metadata. -->

      <!-- The step's single effective Mask — a scoped adjustment's, or a
           generative edit's — expandable into the editable components it is
           calculated from. The edit, its Mask, and the components are three
           distinct things, and the hierarchy says so. -->
      <template v-if="maskTarget">
        <div
          class="group/mask mt-1 -mr-[62px] compact:-mr-[var(--edit-actions-width)] min-w-0 flex items-center gap-1 py-0.5
                 text-xs text-content-secondary rounded-md cursor-default"
          :class="maskParentActive ? 'bg-selection/15' : 'hover:bg-overlay-subtle'"
          @click.stop="emit('selectRegion', maskTarget.id)"
          @mouseenter="emit('hoverRegion', maskTarget.id)"
          @mouseleave="emit('hoverRegion', null)"
        >
          <button
            type="button"
            class="-ml-0.5 inline-flex items-center text-content-tertiary
                   hover:text-content-secondary rounded-sm focus-visible:outline-none
                   focus-visible:ring-2 ring-accent/60"
            :aria-expanded="maskExpanded"
            aria-label="Show mask components"
            @click.stop="maskExpanded = !maskExpanded"
          >
            <ChevronDownIcon v-if="maskExpanded" class="w-3 h-3" />
            <ChevronRightIcon v-else class="w-3 h-3" />
          </button>
          <span class="min-w-0 flex-1 truncate">Mask</span>
          <Tooltip v-if="maskTarget.removable" text="Remove the mask — apply to the whole image">
            <IconButton
              variant="danger"
              class="opacity-0 group-hover/mask:opacity-100 focus-visible:opacity-100 coarse:opacity-100"
              @click.stop="emit('removeMask', maskTarget.id)"
            >
              <TrashIcon class="w-3.5 h-3.5" />
            </IconButton>
          </Tooltip>
        </div>
        <div v-if="maskExpanded" class="-mr-[62px] compact:-mr-[var(--edit-actions-width)] flex flex-col">
          <div
            v-for="(component, componentIndex) in maskTarget.components"
            :key="component.id"
            class="group/component min-w-0 flex items-center gap-1 py-0.5 pl-4 text-xs
                   text-content-secondary rounded-md cursor-default"
            :class="[
              component.enabled === false && 'opacity-45',
              selectedMaskComponentId === component.id
                ? 'bg-selection/15'
                : 'hover:bg-overlay-subtle',
            ]"
            @click.stop="emit('selectMaskComponent', maskTarget.id, component.id)"
            @mouseenter="emit('hoverMaskComponent', maskTarget.id, component.id)"
            @mouseleave="emit('hoverMaskComponent', maskTarget.id, null)"
          >
            <span class="min-w-0 flex-1 truncate">
              <template v-if="maskComponentModeLabel(component, componentIndex)">
                <span class="text-content-tertiary">
                  {{ maskComponentModeLabel(component, componentIndex) }} ·
                </span>
                {{ maskComponentLabel(component) }}
              </template>
              <template v-else>{{ maskComponentLabel(component) }}</template>
            </span>
            <ArrowPathIcon
              v-if="recomputingMaskComponentId === component.id"
              class="w-3.5 h-3.5 shrink-0 animate-spin text-content-tertiary"
            />
            <Tooltip :text="component.enabled === false ? 'Show this component' : 'Hide this component'">
              <IconButton
                @click.stop="emit(
                  'toggleMaskComponent',
                  maskTarget.id,
                  component.id,
                  component.enabled === false,
                )"
              >
                <EyeIcon v-if="component.enabled !== false" class="w-3.5 h-3.5" />
                <EyeSlashIcon v-else class="w-3.5 h-3.5" />
              </IconButton>
            </Tooltip>
            <!-- Every component deletes individually — coverage starts at
                 nothing and each mode means what it says, so no removal ever
                 reinterprets what remains. Deleting the LAST one deletes the
                 mask itself, so it only exists where that has a meaning:
                 an adjustment goes back to Whole image; a generative edit
                 keeps its final component. -->
            <Tooltip
              v-if="maskTarget.removable || maskTarget.components.length > 1"
              :text="maskTarget.components.length === 1
                ? 'Remove the mask — apply to the whole image'
                : 'Remove this component'"
            >
              <IconButton
                variant="danger"
                @click.stop="emit('removeMaskComponent', maskTarget.id, component.id)"
              >
                <TrashIcon class="w-3.5 h-3.5" />
              </IconButton>
            </Tooltip>
          </div>
        </div>
      </template>

      <!-- Retouch is the stack's one hierarchy level. Gestures are folded
           into editable regions inside one top-level edit, never promoted to
           peer rows beside Crop, Adjust, Paint, and the base image. -->
      <template v-if="showsRegionList">
        <button
          type="button"
          class="mt-1 -ml-0.5 inline-flex items-center gap-1 text-xs text-content-tertiary
                 hover:text-content-secondary rounded-sm focus-visible:outline-none
                 focus-visible:ring-2 ring-accent/60"
          :aria-expanded="regionsExpanded"
          @click.stop="regionsExpanded = !regionsExpanded"
        >
          <ChevronDownIcon v-if="regionsExpanded" class="w-3 h-3" />
          <ChevronRightIcon v-else class="w-3 h-3" />
          {{ retouchRegions.length }} {{ retouchRegions.length === 1 ? 'region' : 'regions' }}
        </button>
        <!-- Extend through the parent's trailing control columns so nested
             eye/trash buttons land on the exact same vertical rails. -->
        <div v-if="regionsExpanded" class="mt-1 -mr-[62px] compact:-mr-[var(--edit-actions-width)] flex flex-col">
          <div
            v-for="region in displayedRetouchRegions"
            :key="region.id"
            class="group/region min-w-0 flex items-center gap-1 py-0.5 pl-1 text-xs
                   text-content-secondary rounded-md cursor-default"
            :class="[
              !region.enabled && 'opacity-45',
              selectedRegionId === region.id ? 'bg-selection/15' : 'hover:bg-overlay-subtle',
            ]"
            @click.stop="emit('selectRegion', region.id)"
            @mouseenter="emit('hoverRegion', region.id)"
            @mouseleave="emit('hoverRegion', null)"
          >
            <span
              class="w-1.5 h-1.5 rounded-full shrink-0"
              :class="region.enabled ? 'bg-selection' : 'bg-content-tertiary'"
            />
            <span class="min-w-0 flex-1 truncate">{{ regionLabel(region) }}</span>
            <Tooltip :text="region.enabled ? 'Hide this region' : 'Show this region'">
              <IconButton
                @click.stop="emit('toggleRegion', region.id, !region.enabled)"
              >
                <EyeIcon v-if="region.enabled" class="w-3.5 h-3.5" />
                <EyeSlashIcon v-else class="w-3.5 h-3.5" />
              </IconButton>
            </Tooltip>
            <Tooltip text="Remove this region">
              <IconButton
                variant="danger"
                aria-label="Remove this region"
                @click.stop="emit('removeRegion', region.id)"
              >
                <TrashIcon class="w-3.5 h-3.5" />
              </IconButton>
            </Tooltip>
          </div>
        </div>
      </template>

      <p v-if="outOfFrame" class="mt-1 text-xs text-content-tertiary">Out of frame</p>

      <!-- One horizontal strip per paid invocation. Re-running the operation
           adds a row below instead of squeezing every result onto one line. -->
      <div
        v-if="candidateRows.length"
        data-candidate-rows
        class="flex flex-col items-start gap-1.5 mt-1.5"
      >
        <div
          v-for="(candidateRow, rowIndex) in candidateRows"
          :key="candidateRow.id"
          class="flex items-center gap-1.5"
          role="group"
          :aria-label="`Generation ${rowIndex + 1}`"
        >
          <button
            v-for="candidate in candidateRow.candidates"
            :key="candidate.id"
            type="button"
            :data-candidate-index="candidate.flatIndex"
            :aria-label="`Candidate ${candidate.flatIndex + 1} of ${candidates.length}`"
            :aria-pressed="candidate.id === picked"
            class="relative w-10 h-10 rounded-media overflow-hidden bg-matte transition-shadow focus-visible:outline-none focus-visible:ring-2 ring-accent/60"
            :class="candidate.id === picked ? 'ring-2 ring-selection' : 'opacity-70 hover:opacity-100'"
            @click.stop="onCandidateClick($event, candidate.id)"
            @keydown="onCandidateKeydown($event, candidate.flatIndex)"
          >
            <img :src="candidate.url" class="w-full h-full object-cover" alt="" />
            <span
              v-if="candidate.fromPreviousState"
              class="absolute bottom-0.5 right-0.5 w-1.5 h-1.5 rounded-full bg-amber-400/90"
            />
          </button>
          <div
            v-for="n in candidateRow.pendingCount"
            :key="`pending-${candidateRow.id}-${n}`"
            class="relative w-10 h-10 shrink-0 rounded-media overflow-hidden bg-matte"
            aria-hidden="true"
          >
            <span
              class="absolute inset-0 animate-shimmer bg-gradient-to-r from-transparent
                     via-content/15 to-transparent bg-[length:300%_100%]"
            />
          </div>
        </div>
      </div>
      <p v-if="staged" class="mt-1 text-xs text-content-tertiary">Pick one to apply it.</p>
    </div>

    <!-- Control cluster: one group, centered on the square like the title, so
         the controls sit on the title's line and not above it. The only
         control that costs anything is a button. -->
    <div :class="[ROW_COLUMN_INLINE, 'shrink-0 coarse:[&_button]:w-11 coarse:[&_button]:h-11']">
    <!-- Resample hides at rest because it costs money — but when the amber
         advisory says a resample is the ANSWER (stale input, or mask
         coverage the samples never painted), the answer must be visible. -->
    <Tooltip
      v-if="isGenerative"
      :text="debtAdvisory
        ? 'Re-run through the edited mask'
        : 'Re-run with the current input'"
    >
      <IconButton
        :class="advisory
          ? 'text-amber-400/90 hover:text-amber-300'
          : 'opacity-0 group-hover:opacity-100 focus-visible:opacity-100 coarse:opacity-100'"
        :disabled="resampling"
        @click.stop="emit('resample')"
      >
        <ArrowPathIcon class="w-4 h-4" :class="resampling && 'animate-spin'" />
      </IconButton>
    </Tooltip>

    <!-- The eye stays visible at rest, unlike its neighbours: whether a step
         is on is state you read, not an action you go looking for. -->
    <Tooltip :text="op.enabled ? 'Hide this edit' : 'Show this edit'">
      <IconButton
        :aria-label="op.enabled ? 'Hide this edit' : 'Show this edit'"
        @click.stop="emit('toggle', !op.enabled)"
        @mouseenter="emit('intentHover', true)"
        @mouseleave="emit('intentHover', false)"
      >
        <EyeIcon v-if="op.enabled" class="w-4 h-4" />
        <EyeSlashIcon v-else class="w-4 h-4 text-content-tertiary" />
      </IconButton>
    </Tooltip>

    <Tooltip text="Remove this edit">
      <IconButton
        variant="danger"
        aria-label="Remove this edit"
        @click.stop="emit('remove')"
      >
        <TrashIcon class="w-4 h-4" />
      </IconButton>
    </Tooltip>
    </div>
  </div>
</template>
