<template>
  <div class="generation-grid bg-surface rounded-lg p-3 w-full">
    <!-- Header -->
    <div class="flex items-center justify-between mb-3">
      <div class="flex items-center gap-2">
        <!-- Status text - only while generating -->
        <span v-if="!allComplete" class="text-sm text-content-tertiary">Generating</span>
        <!-- Tool name pill - always show -->
        <span
          v-if="toolName"
          class="px-2 py-0.5 rounded text-xs font-medium bg-emerald-500/20 border border-emerald-500/50 text-emerald-500"
        >
          {{ toolName }}
        </span>
      </div>
      <div v-if="!allComplete" class="flex items-center gap-3">
        <div class="text-xs text-content-muted">
          {{ completedCount }}/{{ totalCount }} complete
        </div>
        <!-- Cancel all button -->
        <button
          v-if="loadingCount > 0"
          @click="cancelAllPending"
          class="text-xs px-2 py-1 bg-surface-raised hover:bg-red-500/15 text-content-tertiary hover:text-red-500 rounded transition-colors"
          title="Cancel all pending"
        >
          Cancel All
        </button>
      </div>
    </div>

    <!-- Grid of images -->
    <div class="grid gap-2" :class="gridClass">
      <GenerationTile
        v-for="(job, index) in jobs"
        :key="job.id"
        :status="job.status"
        :media-id="job.media_id"
        :auto-delete-at="job.auto_delete_at"
        :generation-time="job.generation_time"
        :markers="markers"
        :active-marker-ids="getActiveMarkerIds(job.media_id)"
        :size="tileSize"
        :is-video="job.task_type === 'image-to-video'"
        @view-image="$emit('view-image', job.media_id, index)"
        @show-info="$emit('show-info', job)"
        @show-error="$emit('show-error', job)"
        @retry="retryJob(job.id)"
        @cancel="cancelJob(job.id)"
        @image-error="handleImageError(job.id)"
        @toggle-marker="(marker) => $emit('toggle-marker', { mediaId: job.media_id, marker })"
      />
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import GenerationTile from './generation/GenerationTile.vue'
import { getCurrentProfileId } from '../composables/useProfile'

const props = defineProps({
  gridLayout: {
    type: [String, Object],
    required: true
  },
  markers: {
    type: Array,
    default: () => []
  },
  mediaMarkers: {
    type: Object,
    default: () => ({})
  }
})

const emit = defineEmits(['view-image', 'show-info', 'show-error', 'toggle-marker'])

const jobs = ref([])
const pollInterval = ref(null)

// Parse grid data safely - handle both string and object
let grid_data = {}
try {
  if (typeof props.gridLayout === 'string') {
    grid_data = props.gridLayout ? JSON.parse(props.gridLayout) : {}
  } else if (typeof props.gridLayout === 'object' && props.gridLayout !== null) {
    grid_data = props.gridLayout
  }
} catch (e) {
  console.error('Failed to parse grid layout:', e)
  grid_data = {
    job_ids: [],
    prompt: 'Error loading generation data',
    seeds: [],
    total_count: 0
  }
}

// Initialize jobs array with loading status
onMounted(() => {
  const jobIds = Array.isArray(grid_data.job_ids) ? grid_data.job_ids : []
  jobs.value = jobIds.map(id => ({
    id,
    status: 'loading',
    media_id: null
  }))

  // Start polling for job status
  startPolling()
})

onUnmounted(() => {
  if (pollInterval.value) {
    clearInterval(pollInterval.value)
  }
})

const totalCount = computed(() => grid_data.total_count || jobs.value.length)
const completedCount = computed(() => jobs.value.filter(j => j.status === 'completed').length)
const loadingCount = computed(() => jobs.value.filter(j => j.status === 'loading').length)
const allComplete = computed(() => jobs.value.length > 0 && jobs.value.every(j => j.status !== 'loading'))
const toolName = computed(() => grid_data.tool_name || null)

// Expose completed media IDs for parent component
const completedMediaIds = computed(() =>
  jobs.value.filter(j => j.status === 'completed' && j.media_id).map(j => j.media_id)
)
defineExpose({ completedMediaIds })

const gridClass = computed(() => {
  const count = totalCount.value
  if (count === 1) return 'grid-cols-1 max-w-xs'
  if (count === 2) return 'grid-cols-2 max-w-md'
  if (count <= 4) return 'grid-cols-2 sm:grid-cols-4 max-w-xl'
  if (count <= 6) return 'grid-cols-3 max-w-xl'
  return 'grid-cols-3 sm:grid-cols-4 max-w-2xl'
})

const tileSize = computed(() => {
  const count = totalCount.value
  if (count === 1) return 'large'
  return 'medium'
})

function getActiveMarkerIds(mediaId) {
  if (!mediaId || !props.mediaMarkers[mediaId]) return []
  return props.mediaMarkers[mediaId].map(m => m.id)
}

async function startPolling() {
  // Poll immediately
  await pollJobs()

  // Then poll every 1.5 seconds
  pollInterval.value = setInterval(async () => {
    const allDone = jobs.value.every(j => j.status !== 'loading')
    if (allDone) {
      clearInterval(pollInterval.value)
      pollInterval.value = null
    } else {
      await pollJobs()
    }
  }, 1500)
}

async function pollJobs() {
  // Get all loading jobs
  const loadingJobs = jobs.value.filter(j => j.status === 'loading')
  if (loadingJobs.length === 0) return

  try {
    // Fetch status for all jobs in one request
    const jobIds = loadingJobs.map(j => j.id).join(',')
    const response = await fetch(`/api/generate/jobs/status?ids=${jobIds}`, {
      headers: { 'X-Profile-ID': getCurrentProfileId() }
    })

    if (!response.ok) {
      console.error('Failed to fetch job status')
      return
    }

    const statuses = await response.json()

    // Update job statuses
    statuses.forEach(status => {
      const job = jobs.value.find(j => j.id === status.id)
      if (job) {
        // Store full job data for info/error modals
        job.model_name = status.model_name
        job.parameters = status.parameters
        job.error = status.error
        job.created_at = status.created_at
        job.auto_delete_at = status.auto_delete_at
        job.generation_time = status.generation_time
        job.task_type = status.task_type

        if (status.status === 'completed' && status.result_media_id) {
          // Check if media was trashed (from backend join with MediaItem)
          if (status.media_trashed) {
            job.status = 'trashed'
          } else {
            job.status = 'completed'
            job.media_id = status.result_media_id
          }
        } else if (status.status === 'failed') {
          job.status = 'failed'
        } else if (status.status === 'cancelled') {
          job.status = 'cancelled'
        }
        // Still loading if status is queued, assigned, or processing
      }
    })
  } catch (error) {
    console.error('Error polling job status:', error)
  }
}

// Handle image load errors - likely means the media was trashed/deleted
function handleImageError(jobId) {
  const job = jobs.value.find(j => j.id === jobId)
  if (job) {
    job.status = 'trashed'
  }
}

// Cancel a single job
async function cancelJob(jobId) {
  try {
    const response = await fetch(`/api/generate/jobs/${jobId}`, {
      method: 'DELETE',
      headers: { 'X-Profile-ID': getCurrentProfileId() }
    })

    if (response.ok) {
      const job = jobs.value.find(j => j.id === jobId)
      if (job) {
        job.status = 'cancelled'
      }
    } else {
      console.error('Failed to cancel job:', await response.text())
    }
  } catch (error) {
    console.error('Error cancelling job:', error)
  }
}

// Cancel all pending/loading jobs
async function cancelAllPending() {
  const loadingJobs = jobs.value.filter(j => j.status === 'loading')
  await Promise.all(loadingJobs.map(job => cancelJob(job.id)))
}

// Retry a failed job
async function retryJob(jobId) {
  try {
    const response = await fetch(`/api/generate/jobs/${jobId}/retry`, {
      method: 'POST',
      headers: { 'X-Profile-ID': getCurrentProfileId() }
    })

    if (response.ok) {
      // Set job back to loading and restart polling
      const job = jobs.value.find(j => j.id === jobId)
      if (job) {
        job.status = 'loading'
        job.error = null
        job.media_id = null
      }

      // Restart polling if not already running
      if (!pollInterval.value) {
        startPolling()
      }
    } else {
      console.error('Failed to retry job:', await response.text())
    }
  } catch (error) {
    console.error('Error retrying job:', error)
  }
}
</script>

<style scoped>
.generation-grid {
  width: 100%;
}
</style>
