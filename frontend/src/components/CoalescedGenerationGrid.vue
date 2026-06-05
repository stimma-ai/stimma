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

    <!-- Reference images with prompt (for editing/i2v) - upscale has no prompt -->
    <div v-if="referenceImages.length > 0" class="mb-3">
      <!-- Prompt above for task types that use prompts (not upscale) -->
      <div v-if="parsedGridMeta.taskType !== 'upscale-image' && promptGroups[0]?.text" class="text-sm text-content-secondary whitespace-pre-wrap break-words mb-2">
        {{ promptGroups[0].text }}
      </div>
      <!-- Reference images in a row -->
      <div class="flex flex-wrap gap-3">
        <MediaImage
          v-for="refImg in referenceImages"
          :key="refImg.id"
          :media-id="refImg.id"
          :thumbnail="false"
          :contain="true"
          container-class="w-32 h-32 rounded-lg border border-edge cursor-pointer hover:border-edge transition-colors"
          @click="openReferenceSlideshow(refImg.id)"
        />
      </div>
    </div>

    <!-- Prompts only (when no reference images) - always show if we have jobs -->
    <div v-else-if="promptGroups.length > 0" class="mb-3">
      <!-- Multiple prompts: group results with their prompts -->
      <div v-if="promptGroups.length > 1" class="space-y-4">
        <div v-for="(group, groupIndex) in promptGroups" :key="groupIndex">
          <div class="text-sm text-content-secondary whitespace-pre-wrap break-words mb-2">
            {{ group.text }}
          </div>
          <div class="grid gap-2" :class="getGridClassForCount(group.jobs.length)">
            <GenerationTile
              v-for="job in group.jobs"
              :key="job.id"
              :status="job.status"
              :media-id="job.media_id"
              :is-video="job.task_type === 'image-to-video'"
              :auto-delete-at="job.auto_delete_at"
              :generation-time="job.generation_time"
              :markers="markers"
              :active-marker-ids="getActiveMarkerIds(job.media_id)"
              :size="getTileSizeForCount(group.jobs.length)"
              @view-image="$emit('view-image', job.media_id, getGlobalIndex(job.id))"
              @show-info="$emit('show-info', job)"
              @show-error="$emit('show-error', job)"
              @retry="retryJob(job.id)"
              @cancel="cancelJob(job.id)"
              @image-error="handleImageError(job.id)"
              @toggle-marker="(marker) => $emit('toggle-marker', { mediaId: job.media_id, marker })"
            />
          </div>
        </div>
      </div>
      <!-- Single prompt: show prompt then grid -->
      <div v-else>
        <div v-if="promptGroups[0]?.text" class="text-sm text-content-secondary whitespace-pre-wrap break-words mb-3">
          {{ promptGroups[0].text }}
        </div>
        <div class="grid gap-2" :class="gridClass">
          <GenerationTile
            v-for="(job, index) in allJobs"
            :key="job.id"
            :status="job.status"
            :media-id="job.media_id"
            :is-video="job.task_type === 'image-to-video'"
            :auto-delete-at="job.auto_delete_at"
            :generation-time="job.generation_time"
            :markers="markers"
            :active-marker-ids="getActiveMarkerIds(job.media_id)"
            :size="tileSize"
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
    </div>

    <!-- Has reference images: flat grid below -->
    <div v-if="referenceImages.length > 0" class="grid gap-2" :class="gridClass">
      <GenerationTile
        v-for="(job, index) in allJobs"
        :key="job.id"
        :status="job.status"
        :media-id="job.media_id"
        :is-video="job.task_type === 'image-to-video'"
        :auto-delete-at="job.auto_delete_at"
        :generation-time="job.generation_time"
        :markers="markers"
        :active-marker-ids="getActiveMarkerIds(job.media_id)"
        :size="tileSize"
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
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import GenerationTile from './generation/GenerationTile.vue'
import { MediaImage } from './media'
import { getCurrentProfileId } from '../composables/useProfile'

const props = defineProps({
  gridItems: {
    type: Array,
    required: true
  },
  generationGridRefs: {
    type: Object,
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

const emit = defineEmits(['view-image', 'show-info', 'show-error', 'toggle-marker', 'view-reference-image'])

const allJobs = ref([])
const pollInterval = ref(null)

// Store parsed prompt groups from grid data
const parsedPromptGroups = ref([])

// Store parsed grid metadata for reference images
const parsedGridMeta = ref({
  taskType: null,
  inputImageIds: [],
  inputImageId: null,  // Single input image (for upscale)
  startImageId: null,
  endImageId: null,
  resolutionLabel: null,  // e.g., "2x" or "1080p" for upscale
  profileId: null,  // Profile that owns the input media
  toolName: null  // Tool used for this generation
})

// Parse all grid items and collect job IDs
function parseGridItems() {
  const jobs = []
  const promptGroupsData = []
  let meta = {
    taskType: null,
    inputImageIds: [],
    inputImageId: null,
    startImageId: null,
    endImageId: null,
    resolutionLabel: null,
    profileId: null,
    toolName: null
  }

  for (const gridItem of props.gridItems) {
    let gridData = {}
    try {
      if (typeof gridItem.grid_layout === 'string') {
        gridData = gridItem.grid_layout ? JSON.parse(gridItem.grid_layout) : {}
      } else if (typeof gridItem.grid_layout === 'object' && gridItem.grid_layout !== null) {
        gridData = gridItem.grid_layout
      }
    } catch (e) {
      console.error('Failed to parse grid layout:', e)
      continue
    }

    // Extract task type and reference images
    if (gridData.task_type) {
      meta.taskType = gridData.task_type
    }
    if (Array.isArray(gridData.input_image_ids)) {
      meta.inputImageIds = gridData.input_image_ids
    }
    if (gridData.input_image_id) {
      meta.inputImageId = gridData.input_image_id
    }
    if (gridData.start_image_id) {
      meta.startImageId = gridData.start_image_id
    }
    if (gridData.end_image_id) {
      meta.endImageId = gridData.end_image_id
    }
    if (gridData.resolution_label) {
      meta.resolutionLabel = gridData.resolution_label
    }
    if (gridData.profile_id) {
      meta.profileId = gridData.profile_id
    }
    if (gridData.tool_name) {
      meta.toolName = gridData.tool_name
    }

    // Check for new prompts array format
    if (Array.isArray(gridData.prompts)) {
      for (const promptGroup of gridData.prompts) {
        const groupJobIds = Array.isArray(promptGroup.job_ids) ? promptGroup.job_ids : []
        promptGroupsData.push({
          text: promptGroup.text || '',
          jobIds: groupJobIds
        })
        for (const id of groupJobIds) {
          jobs.push({
            id,
            status: 'loading',
            media_id: null,
            gridItemId: gridItem.id,
            promptText: promptGroup.text
          })
        }
      }
    } else {
      // Legacy format: flat job_ids array
      const jobIds = Array.isArray(gridData.job_ids) ? gridData.job_ids : []
      const promptText = gridData.prompt || ''
      if (jobIds.length > 0) {
        promptGroupsData.push({
          text: promptText,
          jobIds: jobIds
        })
      }
      for (const id of jobIds) {
        jobs.push({
          id,
          status: 'loading',
          media_id: null,
          gridItemId: gridItem.id,
          promptText: promptText
        })
      }
    }
  }

  parsedPromptGroups.value = promptGroupsData
  parsedGridMeta.value = meta
  return jobs
}

// Initialize jobs array
onMounted(() => {
  allJobs.value = parseGridItems()
  startPolling()
})

onUnmounted(() => {
  if (pollInterval.value) {
    clearInterval(pollInterval.value)
  }
})

// Watch for changes to gridItems (new grids being added)
watch(() => props.gridItems, () => {
  // Merge new jobs while preserving existing status
  const newJobs = parseGridItems()
  const existingJobIds = new Set(allJobs.value.map(j => j.id))

  for (const newJob of newJobs) {
    if (!existingJobIds.has(newJob.id)) {
      allJobs.value.push(newJob)
    }
  }

  // Restart polling if we have loading jobs
  if (allJobs.value.some(j => j.status === 'loading') && !pollInterval.value) {
    startPolling()
  }
}, { deep: true })

const totalCount = computed(() => allJobs.value.length)
const completedCount = computed(() => allJobs.value.filter(j => j.status === 'completed').length)
const loadingCount = computed(() => allJobs.value.filter(j => j.status === 'loading').length)
const allComplete = computed(() => allJobs.value.length > 0 && allJobs.value.every(j => j.status !== 'loading'))
const toolName = computed(() => parsedGridMeta.value.toolName)

// Computed prompt groups with their jobs
const promptGroups = computed(() => {
  return parsedPromptGroups.value.map(group => ({
    text: group.text,
    jobs: group.jobIds.map(id => allJobs.value.find(j => j.id === id)).filter(Boolean)
  }))
})

// Computed reference images based on task type
const referenceImages = computed(() => {
  const meta = parsedGridMeta.value
  const images = []

  if (meta.taskType === 'image-to-image' && meta.inputImageIds.length > 0) {
    // Image editing: show input images
    meta.inputImageIds.forEach((id, idx) => {
      images.push({
        id,
        label: meta.inputImageIds.length > 1 ? `Input ${idx + 1}` : 'Input'
      })
    })
  } else if (meta.taskType === 'image-to-video') {
    // I2V: show start frame and optionally end frame
    if (meta.startImageId) {
      images.push({
        id: meta.startImageId,
        label: meta.endImageId ? 'Start frame' : 'Source'
      })
    }
    if (meta.endImageId) {
      images.push({
        id: meta.endImageId,
        label: 'End frame'
      })
    }
  } else if (meta.taskType === 'upscale-image' && meta.inputImageId) {
    // Upscaling: show the source image being upscaled
    images.push({
      id: meta.inputImageId,
      label: 'Source'
    })
  }

  return images
})

// Get global index for a job (for slideshow navigation)
function getGlobalIndex(jobId) {
  return allJobs.value.findIndex(j => j.id === jobId)
}

// Open slideshow for a reference image (single image view)
function openReferenceSlideshow(mediaId) {
  emit('view-reference-image', mediaId)
}

// Get grid class for a specific count
function getGridClassForCount(count) {
  if (count === 1) return 'grid-cols-1 max-w-xs'
  if (count === 2) return 'grid-cols-2 max-w-md'
  if (count <= 4) return 'grid-cols-2 sm:grid-cols-4 max-w-xl'
  if (count <= 6) return 'grid-cols-3 max-w-xl'
  return 'grid-cols-3 sm:grid-cols-4 max-w-2xl'
}

// Get tile size for a specific count
function getTileSizeForCount(count) {
  if (count === 1) return 'large'
  return 'medium'
}

// Expose viewable media IDs for parent component (completed + trashed for slideshow)
const completedMediaIds = computed(() =>
  allJobs.value.filter(j => (j.status === 'completed' || j.status === 'trashed') && j.media_id).map(j => j.media_id)
)
// Non-trashed media IDs for marker loading (skip trashed to avoid 404s)
const liveMediaIds = computed(() =>
  allJobs.value.filter(j => j.status === 'completed' && j.media_id).map(j => j.media_id)
)
defineExpose({ completedMediaIds, liveMediaIds })

// Update parent's generationGridRefs with our media IDs
watch([completedMediaIds, liveMediaIds], ([completed, live]) => {
  // Register each grid item's media for the parent
  for (const gridItem of props.gridItems) {
    props.generationGridRefs[gridItem.id] = { completedMediaIds: completed, liveMediaIds: live }
  }
}, { immediate: true })

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
    const allDone = allJobs.value.every(j => j.status !== 'loading')
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
  const loadingJobs = allJobs.value.filter(j => j.status === 'loading')
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
      const job = allJobs.value.find(j => j.id === status.id)
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
          // Check if media was deleted or trashed
          if (status.media_deleted) {
            // Media record is completely gone (hard deleted)
            job.status = 'deleted'
          } else if (status.media_trashed) {
            // Media is in trash (soft deleted, still viewable)
            job.status = 'trashed'
            job.media_id = status.result_media_id
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

// Handle image load errors - could be trashed or truly deleted
// Default to 'trashed' which shows badge but keeps image visible if it loads
function handleImageError(jobId) {
  const job = allJobs.value.find(j => j.id === jobId)
  if (job) {
    // Only mark as trashed if we don't already know the state from backend
    // The polling will set the correct state based on media_deleted/media_trashed
    if (job.status === 'completed') {
      job.status = 'trashed'
    }
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
      const job = allJobs.value.find(j => j.id === jobId)
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
  const loadingJobs = allJobs.value.filter(j => j.status === 'loading')
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
      const job = allJobs.value.find(j => j.id === jobId)
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
