<template>
  <div class="space-y-2">
    <!-- Kept tiles + empty placeholders strip. Mirrors the slot row that
         hitl.approve produces, so awaiting and completed select equations
         read with the same visual rhythm as approve in the timeline. The
         giant grid lives in the sheet, not here. -->
    <div class="flex items-center gap-2 flex-wrap">
      <div
        v-for="i in count"
        :key="i"
        class="w-16 h-16 sm:w-20 sm:h-20 rounded-md overflow-hidden flex-shrink-0"
        :class="
          keptTiles[i - 1]
            ? 'border border-blue-500/50 ring-1 ring-blue-500/30'
            : 'border border-dashed border-edge-subtle bg-overlay-subtle/30'
        "
      >
        <RecipeMediaTile
          v-if="keptTiles[i - 1] && keptTiles[i - 1]!.mediaId != null"
          :media-id="keptTiles[i - 1]!.mediaId!"
          :thumbnail="true"
          :thumbnail-size="128"
          container-class="w-full h-full"
          img-class="w-full h-full object-cover"
        />
        <img
          v-else-if="keptTiles[i - 1] && keptTiles[i - 1]!.mediaUrl"
          :src="keptTiles[i - 1]!.mediaUrl!"
          :alt="keptTiles[i - 1]!.label"
          class="w-full h-full object-cover"
          referrerpolicy="no-referrer"
          loading="lazy"
        />
        <span
          v-else-if="keptTiles[i - 1]"
          class="w-full h-full flex items-center justify-center text-[10px] text-content-muted px-1 text-center"
        >{{ keptTiles[i - 1]!.label }}</span>
        <span
          v-else
          class="w-full h-full flex items-center justify-center text-[10px] text-content-muted/60"
        >{{ i }}</span>
      </div>

      <button
        type="button"
        class="ml-auto px-2.5 py-1.5 text-[11.5px] font-medium rounded bg-blue-500 hover:bg-blue-600 text-white transition-colors disabled:opacity-50"
        :disabled="poolSize === 0"
        @click="openSheet"
      >
        {{ browseLabel }}
      </button>
    </div>

    <!-- Status / progress line -->
    <div class="flex items-center justify-between gap-2 text-[11px] text-content-tertiary">
      <span>{{ statusLine }}</span>
      <button
        v-if="hasDraft && !sheetShown"
        type="button"
        class="px-2 py-0.5 rounded bg-overlay-subtle border border-edge-subtle text-content-muted hover:text-content hover:bg-overlay-hover"
        @click="resetDraft"
      >Reset</button>
    </div>

    <HitlBrowseSheet
      :show="sheetShown"
      :candidates="candidates"
      :count="count"
      :initial-selection="draftValues"
      :instructions="instructions"
      :title="sheetTitle"
      :confirm-label="confirmLabel"
      @cancel="sheetShown = false"
      @confirm="onSheetConfirm"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import HitlBrowseSheet from './HitlBrowseSheet.vue'
import RecipeMediaTile from './RecipeMediaTile.vue'
import {
  normalizeCandidate,
  valuesEquivalent,
  type NormalizedCandidate,
} from '../../utils/hitlCandidates'

interface Props {
  // Full candidate pool (raw values from task.payload.candidates or trace).
  candidates: any[]
  count: number
  // Pre-existing selection (e.g. completed equation's result). Empty for
  // a fresh awaiting task.
  initialSelection?: any[]
  instructions?: string
  // Wording mode: 'task' for awaiting tasks (primary CTA), 'reselect' for
  // re-opening a completed equation (de-emphasized re-edit).
  mode?: 'task' | 'reselect'
}
const props = withDefaults(defineProps<Props>(), {
  initialSelection: () => [],
  instructions: '',
  mode: 'task',
})

const emit = defineEmits<{
  // Caller wires this to resolve-task (task mode) or reselectEquation
  // (re-select mode). Resolution shape matches hitl.select output: scalar
  // when count===1, array otherwise.
  (e: 'resolve', resolution: any): void
}>()

const sheetShown = ref(false)
// Draft tracks unsaved changes after a sheet confirm. In task mode this is
// effectively the resolution (we emit on sheet confirm). In reselect mode
// the parent decides whether to apply optimistically; we keep the draft
// visible until parent updates initialSelection.
const draftValues = ref<any[]>([...props.initialSelection])

const poolSize = computed(() => props.candidates.length)

const keptTiles = computed<(NormalizedCandidate | null)[]>(() => {
  const tiles: (NormalizedCandidate | null)[] = []
  for (let i = 0; i < props.count; i++) {
    const value = draftValues.value[i]
    tiles.push(value !== undefined ? normalizeCandidate(value, i) : null)
  }
  return tiles
})

const hasDraft = computed(
  () => !valuesEquivalent(draftValues.value, props.initialSelection),
)

const browseLabel = computed(() => {
  if (poolSize.value === 0) return 'No candidates'
  if (draftValues.value.length === 0) return `Browse pool (${poolSize.value}) →`
  return `Change picks →`
})

const statusLine = computed(() => {
  if (poolSize.value === 0) return 'Waiting for candidates…'
  const picked = draftValues.value.length
  if (picked === 0) return `Pick ${props.count} of ${poolSize.value}`
  if (props.count === 1) return picked > 0 ? '1 picked' : 'No selection'
  return `${picked} of ${props.count} picked`
})

const sheetTitle = computed(() =>
  props.count === 1 ? 'Pick one' : `Pick ${props.count}`,
)

const confirmLabel = computed(() => (props.mode === 'reselect' ? 'Apply' : 'Done'))

function openSheet() {
  sheetShown.value = true
}

function onSheetConfirm(resolution: any) {
  sheetShown.value = false
  // Mirror the hitl.select output shape: scalar at count===1, array otherwise.
  if (props.count === 1) {
    draftValues.value = resolution == null ? [] : [resolution]
  } else {
    draftValues.value = Array.isArray(resolution) ? [...resolution] : []
  }
  emit('resolve', resolution)
}

function resetDraft() {
  draftValues.value = [...props.initialSelection]
}

// Re-sync draft when the parent's initialSelection changes (e.g. a successful
// reselect updates the equation's result, parent passes the new result back).
watch(() => props.initialSelection, (next) => {
  if (!valuesEquivalent(draftValues.value, next)) {
    draftValues.value = [...next]
  }
}, { deep: true })
</script>
