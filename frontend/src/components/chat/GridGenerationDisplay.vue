<template>
  <div class="grid-generation-display bg-surface rounded-lg p-4">
    <!-- Header with title -->
    <div class="flex items-center gap-3 mb-2">
      <!-- Grid icon -->
      <div class="w-8 h-8 rounded bg-blue-500/20 flex items-center justify-center flex-shrink-0">
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-4 h-4 text-blue-500">
          <path fill-rule="evenodd" d="M4.25 2A2.25 2.25 0 002 4.25v2.5A2.25 2.25 0 004.25 9h2.5A2.25 2.25 0 009 6.75v-2.5A2.25 2.25 0 006.75 2h-2.5zm0 9A2.25 2.25 0 002 13.25v2.5A2.25 2.25 0 004.25 18h2.5A2.25 2.25 0 009 15.75v-2.5A2.25 2.25 0 006.75 11h-2.5zm9-9A2.25 2.25 0 0011 4.25v2.5A2.25 2.25 0 0013.25 9h2.5A2.25 2.25 0 0018 6.75v-2.5A2.25 2.25 0 0015.75 2h-2.5zm0 9A2.25 2.25 0 0011 13.25v2.5A2.25 2.25 0 0013.25 18h2.5A2.25 2.25 0 0018 15.75v-2.5A2.25 2.25 0 0015.75 11h-2.5z" clip-rule="evenodd" />
        </svg>
      </div>

      <div class="flex-1 min-w-0">
        <div class="flex items-center gap-2">
          <span class="text-sm font-medium text-content">{{ displayData.title || 'Comparison Grid' }}</span>
          <span class="text-xs text-content-muted">{{ displayData.rows }}×{{ displayData.cols }} grid</span>
        </div>
      </div>
    </div>

    <!-- Description -->
    <p v-if="displayData.description" class="text-sm text-content-tertiary mb-3 ml-11">
      {{ displayData.description }}
    </p>

    <!-- Axes summary -->
    <div class="text-xs text-content-muted mb-3 ml-11 space-y-1">
      <div v-if="displayData.row_labels?.length">
        <span class="text-content-tertiary">{{ formatAxisName(displayData.row_axis_name) }}:</span>
        {{ displayData.row_labels.join(' vs ') }}
      </div>
      <div v-if="displayData.col_labels?.length">
        <span class="text-content-tertiary">{{ formatAxisName(displayData.col_axis_name) }}:</span>
        {{ displayData.col_labels.join(', ') }}
      </div>
    </div>

    <!-- Progress (during generation) -->
    <div v-if="displayData.status === 'generating'" class="ml-11">
      <div class="flex items-center justify-between text-xs text-content-tertiary mb-1.5">
        <span>Generating {{ displayData.total_cells }} images...</span>
        <span>{{ displayData.completed_cells }} / {{ displayData.total_cells }}</span>
      </div>
      <div class="h-2 bg-surface-raised rounded-full overflow-hidden">
        <div
          class="h-full bg-blue-500 transition-all duration-300"
          :style="{ width: `${progressPercent}%` }"
        ></div>
      </div>
    </div>

    <!-- Complete: show link to view grid -->
    <div v-else-if="displayData.status === 'complete'" class="ml-11">
      <button
        v-if="displayData.grid_media_id"
        @click="$emit('view-grid', displayData.grid_media_id)"
        class="inline-flex items-center gap-2 px-3 py-1.5 bg-blue-500/20 hover:bg-blue-500/30 text-blue-500 text-sm rounded-lg transition-colors"
      >
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-4 h-4">
          <path fill-rule="evenodd" d="M4.25 2A2.25 2.25 0 002 4.25v2.5A2.25 2.25 0 004.25 9h2.5A2.25 2.25 0 009 6.75v-2.5A2.25 2.25 0 006.75 2h-2.5zm0 9A2.25 2.25 0 002 13.25v2.5A2.25 2.25 0 004.25 18h2.5A2.25 2.25 0 009 15.75v-2.5A2.25 2.25 0 006.75 11h-2.5zm9-9A2.25 2.25 0 0011 4.25v2.5A2.25 2.25 0 0013.25 9h2.5A2.25 2.25 0 0018 6.75v-2.5A2.25 2.25 0 0015.75 2h-2.5zm0 9A2.25 2.25 0 0011 13.25v2.5A2.25 2.25 0 0013.25 18h2.5A2.25 2.25 0 0018 15.75v-2.5A2.25 2.25 0 0015.75 11h-2.5z" clip-rule="evenodd" />
        </svg>
        View Grid
      </button>
      <span class="ml-3 text-xs text-content-muted">
        {{ displayData.total_cells }} images generated
      </span>
    </div>

    <!-- Failed -->
    <div v-else-if="displayData.status === 'failed'" class="ml-11">
      <div class="text-sm text-red-500">Generation failed</div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  displayData: {
    type: Object,
    required: true
    // Expected shape:
    // {
    //   grid_id: string,
    //   title: string,
    //   description?: string,
    //   rows: number,
    //   cols: number,
    //   row_labels: string[],
    //   col_labels: string[],
    //   total_cells: number,
    //   completed_cells: number,
    //   status: "generating" | "complete" | "failed",
    //   grid_media_id?: number
    // }
  },
  chatItemId: {
    type: Number,
    default: null
  }
})

defineEmits(['view-image', 'view-grid'])

// Progress percentage
const progressPercent = computed(() => {
  if (!props.displayData.total_cells) return 0
  return Math.round((props.displayData.completed_cells / props.displayData.total_cells) * 100)
})

// Format axis name for display (capitalize, replace underscores)
function formatAxisName(name) {
  if (!name) return 'Variable'
  return name
    .replace(/_/g, ' ')
    .replace(/\b\w/g, c => c.toUpperCase())
}
</script>
