<template>
  <div class="media-display bg-surface rounded-lg p-3">
    <!-- Header with title (always show if present) -->
    <div v-if="displayData.title" class="mb-3">
      <span class="text-sm text-content-secondary font-medium">
        {{ displayData.title }}
      </span>
      <span v-if="!allComplete" class="text-sm text-content-tertiary ml-2">
        {{ statusText }}
      </span>
    </div>

    <!-- Rows: output-only batches use a bounded responsive gallery, everything else keeps the existing layouts -->
    <div :class="rowsContainerClass">
      <MediaDisplayRow
        v-for="row in visibleRows"
        :key="row.id"
        :row="row"
        :compact="shouldUseCompactLayout"
        :library-mode="isLibraryMode"
        @view-image="(mediaId) => $emit('view-image', mediaId)"
        @retry="retryRow"
        @cancel="cancelRow"
        @show-job-info="(jobId) => $emit('show-job-info', jobId)"
      />
    </div>

    <!-- Show more button when there are hidden rows -->
    <div v-if="hasMoreRows" class="mt-3 flex justify-center">
      <button
        @click="showMore"
        class="text-xs px-4 py-1.5 bg-surface-raised hover:bg-surface-hover text-content-secondary rounded transition-colors"
      >
        Show more
      </button>
    </div>

    <!-- Footer: retry button and actions slot -->
    <div class="mt-3 flex items-center justify-between">
      <!-- Retry all failed button (left side) -->
      <div>
        <button
          v-if="failedCount > 1"
          @click="retryAllFailed"
          class="text-xs px-3 py-1.5 bg-surface-raised hover:bg-surface-hover text-content-secondary rounded transition-colors"
        >
          Retry All Failed ({{ failedCount }})
        </button>
      </div>
      <!-- Actions slot (right side) -->
      <slot name="actions"></slot>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import MediaDisplayRow from './MediaDisplayRow.vue'
import { getCurrentProfileId } from '../../composables/useProfile'

const props = defineProps({
  displayData: {
    type: Object,
    required: true
    // Expected shape:
    // {
    //   rows: MediaDisplayRow[],
    //   title?: string,
    //   status: "pending" | "generating" | "complete" | "partial" | "failed"
    // }
  },
  chatItemId: {
    type: Number,
    default: null
  }
})

const emit = defineEmits(['view-image', 'update', 'show-job-info'])

// Local state for rows (allows updating status)
const localRows = ref([])
const pollInterval = ref(null)

// Compact mode state (default: true for trimmer default appearance)
const isCompact = ref(true)

const DEFAULT_ITEMS_PER_LOAD = 18
const GALLERY_ITEMS_PER_LOAD = 9
const visibleCount = ref(DEFAULT_ITEMS_PER_LOAD)

// Initialize local rows from props
watch(() => props.displayData.rows, (newRows) => {
  localRows.value = JSON.parse(JSON.stringify(newRows || []))
}, { immediate: true, deep: true })

// Computed status - use localRows but fall back to props for initial render
const rows = computed(() => localRows.value.length > 0 ? localRows.value : (props.displayData.rows || []))
const generatingCount = computed(() =>
  rows.value.filter(r => r.output?.status === 'generating' || r.output?.status === 'pending').length
)
const failedCount = computed(() =>
  rows.value.filter(r => r.output?.status === 'failed').length
)
const allComplete = computed(() =>
  rows.value.length > 0 &&
  rows.value.every(r => ['complete', 'failed', 'cancelled', 'trashed'].includes(r.output?.status))
)
const allOutputOnly = computed(() =>
  rows.value.length > 0 &&
  rows.value.every(r => r.input?.type === 'output_only')
)
// True if any row has expandable content (prompt, refs, input image)
const hasExpandableRows = computed(() =>
  rows.value.some(r => r.input?.type !== 'output_only')
)
// Library mode uses smaller thumbnails by default
const isLibraryMode = computed(() =>
  props.displayData.mode === 'library'
)
// Use compact layout when all output_only OR when user has compact mode enabled
const shouldUseCompactLayout = computed(() =>
  allOutputOnly.value || isCompact.value
)
const isOutputGallery = computed(() =>
  allOutputOnly.value && rows.value.length > 1
)
const itemsPerLoad = computed(() =>
  isOutputGallery.value ? GALLERY_ITEMS_PER_LOAD : DEFAULT_ITEMS_PER_LOAD
)
const rowsContainerClass = computed(() => {
  if (isOutputGallery.value) {
    return 'grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3'
  }
  return shouldUseCompactLayout.value ? 'flex flex-wrap gap-2' : 'space-y-3'
})

// Pagination computed properties
const visibleRows = computed(() => localRows.value.slice(0, visibleCount.value))
const hasMoreRows = computed(() => localRows.value.length > visibleCount.value)

function showMore() {
  visibleCount.value += itemsPerLoad.value
}

watch(itemsPerLoad, (newValue) => {
  visibleCount.value = newValue
}, { immediate: true })

const statusText = computed(() => {
  if (generatingCount.value > 0) return 'Generating...'
  if (failedCount.value > 0) return 'Some failed'
  return ''
})

// Expose computed for parent
defineExpose({
  completedMediaIds: computed(() =>
    localRows.value
      .filter(r => (r.output?.status === 'complete' || r.output?.status === 'trashed') && r.output?.media_id)
      .map(r => r.output.media_id)
  )
})

// Poll for job status updates
onMounted(() => {
  startPolling()
})

onUnmounted(() => {
  if (pollInterval.value) {
    clearInterval(pollInterval.value)
  }
})

function startPolling() {
  // Check if there are any jobs to poll
  const hasGeneratingJobs = localRows.value.some(
    r => r.output?.job_id && ['pending', 'generating'].includes(r.output?.status)
  )

  if (!hasGeneratingJobs) return

  // Poll immediately
  pollJobs()

  // Then poll every 1.5 seconds
  pollInterval.value = setInterval(() => {
    const stillGenerating = localRows.value.some(
      r => ['pending', 'generating'].includes(r.output?.status)
    )
    if (!stillGenerating) {
      clearInterval(pollInterval.value)
      pollInterval.value = null
    } else {
      pollJobs()
    }
  }, 1500)
}

async function pollJobs() {
  const jobIds = localRows.value
    .filter(r => r.output?.job_id && ['pending', 'generating'].includes(r.output?.status))
    .map(r => r.output.job_id)

  if (jobIds.length === 0) return

  try {
    const response = await fetch(`/api/generate/jobs/status?ids=${jobIds.join(',')}`, {
      headers: { 'X-Profile-ID': getCurrentProfileId() }
    })

    if (!response.ok) return

    const statuses = await response.json()
    let hasUpdates = false

    statuses.forEach(status => {
      const row = localRows.value.find(r => r.output?.job_id === status.id)
      if (row) {
        if (status.status === 'completed' && status.result_media_id) {
          // Check if media was trashed
          if (status.media_trashed) {
            row.output.status = 'trashed'
          } else {
            row.output.status = 'complete'
          }
          row.output.media_id = status.result_media_id
          row.output.auto_delete_at = status.auto_delete_at
          row.output.file_format = status.file_format
          hasUpdates = true
        } else if (status.status === 'failed') {
          row.output.status = 'failed'
          row.output.error = status.error
          hasUpdates = true
        } else if (status.status === 'cancelled') {
          row.output.status = 'cancelled'
          hasUpdates = true
        }
        // Update progress if available
        if (status.progress !== undefined) {
          row.output.progress = status.progress
        }
      }
    })

    // Persist updates to database so ChatImageStrip and slideshow work
    if (hasUpdates && props.chatItemId) {
      await persistRowUpdates()
    }
  } catch (error) {
    console.error('Error polling job status:', error)
  }
}

async function persistRowUpdates() {
  // Update the ChatItem's metadata with current row state
  try {
    const displayData = {
      rows: localRows.value,
      title: props.displayData.title,
      status: allComplete.value ? 'complete' : 'generating',
    }
    await fetch(`/api/chats/items/${props.chatItemId}/metadata`, {
      method: 'PATCH',
      headers: {
        'Content-Type': 'application/json',
        'X-Profile-ID': getCurrentProfileId()
      },
      body: JSON.stringify({ display_data: displayData })
    })
    // Emit update so parent can refresh
    emit('update')
  } catch (error) {
    console.error('Error persisting row updates:', error)
  }
}

async function cancelRow(rowId) {
  const row = localRows.value.find(r => r.id === rowId)
  if (!row?.output?.job_id) return

  try {
    const response = await fetch(`/api/generate/jobs/${row.output.job_id}`, {
      method: 'DELETE',
      headers: { 'X-Profile-ID': getCurrentProfileId() }
    })

    if (response.ok) {
      row.output.status = 'cancelled'
    }
  } catch (error) {
    console.error('Error cancelling job:', error)
  }
}

async function retryRow(rowId) {
  const row = localRows.value.find(r => r.id === rowId)
  if (!row?.output?.job_id) return

  try {
    const response = await fetch(`/api/generate/jobs/${row.output.job_id}/retry`, {
      method: 'POST',
      headers: { 'X-Profile-ID': getCurrentProfileId() }
    })

    if (response.ok) {
      row.output.status = 'generating'
      row.output.error = null
      row.output.media_id = null

      // Restart polling if not running
      if (!pollInterval.value) {
        startPolling()
      }
    }
  } catch (error) {
    console.error('Error retrying job:', error)
  }
}

async function retryAllFailed() {
  const failedRows = localRows.value.filter(r => r.output?.status === 'failed')
  await Promise.all(failedRows.map(r => retryRow(r.id)))
}
</script>

<style scoped>
/* No percentage constraints - size determined by content */
</style>
