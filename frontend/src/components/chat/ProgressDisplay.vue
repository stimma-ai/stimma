<template>
  <div class="progress-display bg-surface rounded-lg p-3 min-w-[280px]">
    <!-- Header: title + counter -->
    <div class="flex items-baseline justify-between gap-4 mb-2">
      <span v-if="displayData.title" class="text-sm text-content-secondary font-medium truncate">
        {{ displayData.title }}
      </span>
      <span class="text-xs text-content-tertiary tabular-nums whitespace-nowrap flex-shrink-0">
        {{ displayData.current }} / {{ displayData.total }}
      </span>
    </div>

    <!-- Progress bar -->
    <ProgressBar :value="progressPercent" :hue="barColorClass" />

    <!-- Status text for non-normal states -->
    <div v-if="displayData.status === 'cancelled'" class="mt-1.5">
      <span class="text-xs text-amber-400">Cancelled</span>
    </div>
    <div v-else-if="displayData.status === 'timed_out'" class="mt-1.5">
      <span class="text-xs text-amber-400">Timed out</span>
    </div>
    <div v-else-if="displayData.status === 'error'" class="mt-1.5">
      <span class="text-xs text-red-400">Failed</span>
    </div>

    <!-- Thumbnail grid (hidden when empty) -->
    <div
      v-if="displayData.previews && displayData.previews.length > 0"
      class="mt-3"
    >
      <div
        ref="gridRef"
        class="flex flex-wrap gap-1.5 overflow-hidden transition-[max-height] duration-200"
        :style="{ maxHeight: expanded ? 'none' : '102px' }"
      >
        <div
          v-for="mediaId in displayData.previews"
          :key="mediaId"
          class="w-12 h-12 flex-shrink-0 rounded-md overflow-hidden cursor-pointer hover:ring-2 hover:ring-accent/50 transition-all"
          @click="$emit('view-image', mediaId)"
        >
          <MediaImage
            :media-id="mediaId"
            container-class="w-full h-full"
            img-class="w-full h-full object-cover"
            loading="lazy"
          />
        </div>
      </div>
      <button
        v-if="hasOverflow"
        class="mt-1.5 text-xs text-content-tertiary hover:text-content-secondary transition-colors"
        @click="expanded = !expanded"
      >
        {{ expanded ? 'Show less' : `Show all ${displayData.previews.length}` }}
      </button>
    </div>
  </div>
</template>

<script setup>
import { computed, ref, onMounted, watch, nextTick } from 'vue'
import { MediaImage } from '../media'
import ProgressBar from '../ui/ProgressBar.vue'
import { dotClass } from '../../utils/statusColors'

const props = defineProps({
  displayData: {
    type: Object,
    required: true
    // Expected shape:
    // {
    //   title?: string,
    //   status: "in_progress" | "completed" | "cancelled" | "timed_out" | "error",
    //   current: number,
    //   total: number,
    //   previews: number[]  // media_id ints
    // }
  }
})

defineEmits(['view-image'])

const expanded = ref(false)
const gridRef = ref(null)
const hasOverflow = ref(false)

const progressPercent = computed(() => {
  if (!props.displayData.total) return 0
  return Math.round((props.displayData.current / props.displayData.total) * 100)
})

// Status → bucket per STANDARDS.md §1.9 (statusColors.ts is the single
// source of truth): cancelled/timed_out are non-fatal trouble (warning),
// completed is terminal success (done), error is terminal failure (failed),
// everything else (in_progress) is running.
const statusBucket = computed(() => {
  switch (props.displayData.status) {
    case 'completed': return 'done'
    case 'cancelled':
    case 'timed_out': return 'warning'
    case 'error': return 'failed'
    default: return 'running'
  }
})

const barColorClass = computed(() => dotClass(statusBucket.value))

function checkOverflow() {
  if (!gridRef.value) return
  // scrollHeight > 102px (2 rows) means there are hidden items
  hasOverflow.value = gridRef.value.scrollHeight > 102
}

onMounted(() => nextTick(checkOverflow))

watch(() => props.displayData.previews?.length, () => nextTick(checkOverflow))
</script>
