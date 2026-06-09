<template>
  <div class="h-full flex flex-col">
    <div v-if="jobs.length === 0" class="text-center py-12 px-4 text-content-muted">
      <p>{{ emptyMessage }}</p>
    </div>
    <div v-else class="flex flex-col gap-4">
      <!-- In-flight progress: slim landscape bars docked at the top of the
           results area — one per job/batch/chain, stacked newest-first so
           finishing work flows into the completed list below. -->
      <div v-if="activeDisplayItems.length > 0" class="flex flex-col gap-2">
        <template v-for="item in activeDisplayItems" :key="item.key">
          <!-- Active individual job (queued/processing/enhancing) -->
          <GenerationProgressBar
            v-if="item.type === 'active-job'"
            :name="item.job.model_name || 'Generation'"
            :status="item.job.status === 'enhancing' ? 'enhancing' : item.job.status === 'processing' ? 'processing' : 'queued'"
            @cancel="$emit('cancel-job', item.job.id)"
          />
          <!-- Active batch (in progress) -->
          <GenerationProgressBar
            v-else-if="item.type === 'active-batch'"
            :name="`${item.batch.jobs?.[0]?.model_name || 'Batch'} · ${item.batch.completed + item.batch.failed}/${item.batch.total}`"
            :status="item.batch.inProgress > 0 ? 'processing' : 'queued'"
            :progress="item.batch.total ? (item.batch.completed + item.batch.failed) / item.batch.total : null"
            @cancel="$emit('cancel-and-dismiss-batch', item.batch.batch_id)"
          />
          <!-- Running/paused post-processing chain: step dots + Retry on failure -->
          <ChainProgressBar
            v-else-if="item.type === 'chain-run'"
            :run="item.run"
            @retry="$emit('retry-chain', $event)"
            @dismiss="$emit('dismiss-chain', $event)"
          />
        </template>
      </div>

      <!-- Completed/failed items -->
      <template v-for="item in completedDisplayItems" :key="item.key">

        <!-- Completed batch output set - set tile -->
        <template v-if="item.type === 'completed-batch'">
          <div class="grid grid-cols-1 gap-4">
            <div
              class="group relative aspect-square rounded-lg overflow-hidden cursor-pointer hover:scale-105 transition-transform bg-surface"
              @click="$emit('job-click', { status: 'completed', result_media_id: item.batch.output_set_id, is_set: true, set_data: item.batch.output_set_data })"
            >
              <MediaImage
                v-if="item.batch.output_set_hash"
                :file-hash="item.batch.output_set_hash"
                :media-id="item.batch.output_set_id"
                alt="Batch output set"
                container-class="w-full h-full"
              />
              <!-- Set badge overlay (upper right, matching browser) -->
              <div class="absolute top-2 right-2 z-[5] bg-black/60 backdrop-blur-md rounded-md px-1.5 py-1 flex items-center gap-1">
                <svg class="w-4 h-4 flex-shrink-0 text-amber-500" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M6.429 9.75L2.25 12l4.179 2.25m0-4.5l5.571 3 5.571-3m-11.142 0L2.25 7.5 12 2.25l9.75 5.25-4.179 2.25m0 0L21.75 12l-4.179 2.25m0 0l4.179 2.25L12 21.75 2.25 16.5l4.179-2.25m11.142 0l-5.571 3-5.571-3" />
                </svg>
                <span class="text-xs font-semibold text-content leading-none">{{ item.batch.output_set_member_count || item.batch.completed }}</span>
              </div>
              <!-- Marker toggle buttons (bottom left) -->
              <div v-if="item.batch.output_set_id && markers.length > 0" class="absolute bottom-2 left-2 z-[10] flex gap-1">
                <button
                  v-for="marker in markers"
                  :key="marker.id"
                  @click.stop="$emit('toggle-marker', { mediaId: item.batch.output_set_id, marker })"
                  :class="[
                    'w-8 h-8 rounded-lg flex items-center justify-center transition-all border-2',
                    hasMarker(item.batch.output_set_id, marker.id)
                      ? 'bg-black/80'
                      : 'bg-black/40 border-transparent hover:bg-black/60 text-white/50 hover:text-white'
                  ]"
                  :style="hasMarker(item.batch.output_set_id, marker.id) ? { borderColor: marker.color, color: marker.color } : {}"
                  :title="hasMarker(item.batch.output_set_id, marker.id) ? `Remove ${marker.name}` : `Add ${marker.name}`"
                >
                  <span class="w-5 h-5 flex items-center justify-center icon-container" v-html="marker.icon_svg" />
                </button>
              </div>
              <!-- Set title overlay (bottom center, matching browser) -->
              <div
                v-if="item.batch.output_set_title"
                class="absolute bottom-2 left-0 right-0 flex justify-center z-[5] pointer-events-none"
              >
                <div class="bg-black/60 backdrop-blur-md rounded-full px-2.5 py-1 truncate max-w-[calc(100%-16px)]">
                  <span class="text-xs font-medium text-content">{{ item.batch.output_set_title }}</span>
                </div>
              </div>
            </div>
          </div>
        </template>

        <!-- Completed individual job - image tile -->
        <template v-else-if="item.type === 'completed-job'">
          <div class="grid grid-cols-1 gap-4">
            <div
              :class="[
                'group relative aspect-square rounded-lg overflow-hidden transition-transform cursor-pointer hover:scale-105',
                imageMode === 'fit' ? 'bg-surface-raised' : '',
                currentMediaId != null && item.job.result_media_id === currentMediaId
                  ? 'ring-2 ring-blue-500 ring-offset-2 ring-offset-surface-overlay'
                  : ''
              ]"
              @click="handleJobClick(item.job)"
            >
              <!-- Video display -->
              <video
                v-if="isVideo && getMediaHash(item.job.result_media_id)"
                :src="getMediaUrl(getMediaHash(item.job.result_media_id))"
                :class="['w-full h-full', imageMode === 'fit' ? 'object-contain' : 'object-cover']"
                loop
                muted
                playsinline
                draggable="true"
                @dragstart="onDragStart($event, item.job.result_media_id)"
                @dragend="handleDragEnd"
                @mouseenter="($event.target as HTMLVideoElement).play()"
                @mouseleave="($event.target as HTMLVideoElement).pause(); ($event.target as HTMLVideoElement).currentTime = 0"
                @error="$emit('media-load-error', item.job.result_media_id)"
                @contextmenu.prevent="handleVideoContextMenu($event, item.job.result_media_id)"
              />
              <!-- Image display -->
              <MediaImage
                v-else-if="!isVideo && item.job.result_media_id"
                :media-id="item.job.result_media_id"
                :thumbnail="imageMode !== 'fit'"
                :thumbnail-size="256"
                :alt="`Generated image ${item.job.id}`"
                :contain="imageMode === 'fit'"
                container-class="w-full h-full"
                @error="$emit('media-load-error', item.job.result_media_id)"
              />
              <div v-else-if="item.job.result_media_id" class="w-full h-full flex items-center justify-center bg-surface">
                <div class="w-8 h-8 border-2 border-edge border-t-blue-500 rounded-full animate-spin"></div>
              </div>
              <!-- Auto-delete time remaining badge (upper left) -->
              <div v-if="item.job.auto_delete_at && formatRemainingTime(item.job.auto_delete_at) && formatRemainingTime(item.job.auto_delete_at) !== '0m'" class="absolute top-2 left-2 z-[5] bg-black/60 backdrop-blur-md rounded-md px-1.5 py-1 flex items-center gap-1">
                <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" fill="currentColor" class="w-3 h-3 text-[#FFC107]">
                  <path fill-rule="evenodd" d="M5 3.25V4H2.75a.75.75 0 0 0 0 1.5h.3l.815 8.15A1.5 1.5 0 0 0 5.357 15h5.285a1.5 1.5 0 0 0 1.493-1.35l.815-8.15h.3a.75.75 0 0 0 0-1.5H11v-.75A2.25 2.25 0 0 0 8.75 1h-1.5A2.25 2.25 0 0 0 5 3.25Zm2.25-.75a.75.75 0 0 0-.75.75V4h3v-.75a.75.75 0 0 0-.75-.75h-1.5ZM6.05 6a.75.75 0 0 1 .787.713l.275 5.5a.75.75 0 0 1-1.498.075l-.275-5.5A.75.75 0 0 1 6.05 6Zm3.9 0a.75.75 0 0 1 .712.787l-.275 5.5a.75.75 0 0 1-1.498-.075l.275-5.5a.75.75 0 0 1 .786-.711Z" clip-rule="evenodd" />
                </svg>
                <span class="text-xs font-semibold text-[#FFC107] leading-none whitespace-nowrap">{{ formatRemainingTime(item.job.auto_delete_at) }}</span>
              </div>
              <!-- Combined gen-time + info (upper right): shows the time, click opens
                   generation details. Falls back to an info icon when no time is
                   recorded. -->
              <button
                @click.stop="$emit('show-job-info', item.job)"
                class="absolute top-2 right-2 z-[10] h-7 flex items-center justify-center gap-1 px-2 bg-black/80 backdrop-blur-md hover:bg-blue-500/80 rounded text-xs font-bold text-white transition-colors shadow-[0_2px_8px_rgba(0,0,0,0.5)]"
                title="Generation details"
              >
                <span v-if="getGenerationTime(item.job)">{{ getGenerationTime(item.job) }}s</span>
                <svg v-else xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-3.5 h-3.5">
                  <path fill-rule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7-4a1 1 0 11-2 0 1 1 0 012 0zM9 9a.75.75 0 000 1.5h.253a.25.25 0 01.244.304l-.459 2.066A1.75 1.75 0 0010.747 15H11a.75.75 0 000-1.5h-.253a.25.25 0 01-.244-.304l.459-2.066A1.75 1.75 0 009.253 9H9z" clip-rule="evenodd" />
                </svg>
              </button>
              <!-- Marker toggle buttons (bottom left) -->
              <div v-if="item.job.result_media_id && markers.length > 0" class="absolute bottom-2 left-2 z-[10] flex gap-1">
                <button
                  v-for="marker in markers"
                  :key="marker.id"
                  @click.stop="$emit('toggle-marker', { mediaId: item.job.result_media_id, marker })"
                  :class="[
                    'w-8 h-8 rounded-lg flex items-center justify-center transition-all border-2',
                    hasMarker(item.job.result_media_id, marker.id)
                      ? 'bg-black/80'
                      : 'bg-black/40 border-transparent hover:bg-black/60 text-white/50 hover:text-white'
                  ]"
                  :style="hasMarker(item.job.result_media_id, marker.id) ? { borderColor: marker.color, color: marker.color } : {}"
                  :title="hasMarker(item.job.result_media_id, marker.id) ? `Remove ${marker.name}` : `Add ${marker.name}`"
                >
                  <span class="w-5 h-5 flex items-center justify-center icon-container" v-html="marker.icon_svg" />
                </button>
              </div>
              <div class="absolute bottom-0 left-0 right-0 p-4 bg-gradient-to-t from-black/80 to-transparent opacity-0 hover:opacity-100 transition-opacity pointer-events-none">
                <div class="text-xs text-white line-clamp-2">{{ getJobPrompt(item.job) }}</div>
              </div>
            </div>
          </div>
        </template>

        <!-- Failed job -->
        <template v-else-if="item.type === 'failed-job'">
          <div class="grid grid-cols-1 gap-4">
            <div
              class="group relative aspect-square rounded-lg overflow-hidden transition-transform cursor-pointer hover:scale-105"
              @click="handleJobClick(item.job)"
            >
              <div class="w-full h-full flex flex-col items-center justify-center p-4 bg-red-500/10 border border-red-500/30">
                <!-- Top right buttons: Retry and Dismiss -->
                <div class="absolute top-2 right-2 flex gap-1 z-10">
                  <button
                    @click.stop="$emit('retry-job', item.job.id)"
                    class="w-6 h-6 flex items-center justify-center bg-blue-500/20 hover:bg-blue-500/40 border border-blue-500/50 rounded text-blue-500 hover:text-white transition-colors"
                    title="Retry"
                  >
                    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-3.5 h-3.5">
                      <path fill-rule="evenodd" d="M15.312 11.424a5.5 5.5 0 01-9.201 2.466l-.312-.311h2.433a.75.75 0 000-1.5H3.989a.75.75 0 00-.75.75v4.242a.75.75 0 001.5 0v-2.43l.31.31a7 7 0 0011.712-3.138.75.75 0 00-1.449-.39zm1.23-3.723a.75.75 0 00.219-.53V2.929a.75.75 0 00-1.5 0v2.43l-.31-.31A7 7 0 003.239 8.188a.75.75 0 101.448.389A5.5 5.5 0 0113.89 6.11l.311.31h-2.432a.75.75 0 000 1.5h4.243a.75.75 0 00.53-.219z" clip-rule="evenodd" />
                    </svg>
                  </button>
                  <button
                    @click.stop="$emit('dismiss-job', item.job.id)"
                    class="w-6 h-6 flex items-center justify-center bg-red-500/20 hover:bg-red-500/40 border border-red-500/50 rounded text-red-500 hover:text-white text-sm transition-colors"
                    title="Dismiss"
                  >
                    ×
                  </button>
                </div>
                <div class="text-red-500 text-2xl mb-2">✕</div>
                <div class="text-xs text-red-500 font-semibold uppercase">Failed</div>
                <div class="text-xs text-red-500/70 mt-2 text-center line-clamp-2">Click for details</div>
              </div>
            </div>
          </div>
        </template>

      </template>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { formatRemainingTime } from '../../utils/timeFormat'
import { MediaImage, AppImage } from '../media'
import GenerationProgressBar from './postprocessing/GenerationProgressBar.vue'
import ChainProgressBar from './postprocessing/ChainProgressBar.vue'
import { useMediaApi } from '../../composables/useMediaApi'
import { useMediaContextMenu } from '../../composables/useMediaContextMenu'
import { createDragPreview, handleDragEnd } from '../../composables/useDragPreview'

const { getMediaFileUrl, getThumbnailUrl } = useMediaApi()
const contextMenu = useMediaContextMenu()

// Helper to build profile-aware media URLs using db_guid
function getMediaUrl(hash: string) {
  return getMediaFileUrl(hash)
}

function getThumbUrl(hash: string, size = 256) {
  return getThumbnailUrl(hash, size)
}

interface Job {
  id: number
  status: string
  result_media_id?: number
  auto_delete_at?: string
  parameters?: string
  error?: string
  created_at?: string
  completed_at?: string
}

interface Marker {
  id: number
  name: string
  color: string
  icon_svg: string
}

interface BatchInfo {
  batch_id: string
  total: number
  completed: number
  failed: number
  inProgress: number
  output_set_id?: number
  output_set_hash?: string
  output_set_title?: string
  output_set_member_count?: number
  output_set_data?: any
  status?: string
  jobs: Job[]
}

interface ChainRun {
  id: number
  job_id: number
  base_media_id: number
  chain: any[]
  step_index: number
  step_count: number
  step_results: Array<{ status: string; media_id?: number; error?: string }>
  status: string
  last_good_media_id?: number
  final_media_id?: number
  error?: string
  updated_at?: string
}

interface Props {
  jobs: Job[]
  markers?: Marker[]
  mediaHashes?: Record<number, string>
  mediaMarkers?: Record<number, Marker[]>
  mediaGenerationTimes?: Record<number, number>
  batchJobs?: Record<string, BatchInfo>
  // Post-processing chains: in-flight/paused (bars) + completed (result tiles)
  activeChainRuns?: ChainRun[]
  completedChainRuns?: ChainRun[]
  imageMode?: 'cover' | 'fit'
  emptyMessage?: string
  isVideo?: boolean
  // Media id of the item currently focused/shown elsewhere (e.g. the Stage hero).
  // Its tile gets a blue ring so the user can see what they're looking at.
  currentMediaId?: number | null
}

const props = withDefaults(defineProps<Props>(), {
  markers: () => [],
  mediaHashes: () => ({}),
  mediaMarkers: () => ({}),
  mediaGenerationTimes: () => ({}),
  batchJobs: () => ({}),
  activeChainRuns: () => [],
  completedChainRuns: () => [],
  imageMode: 'cover',
  emptyMessage: 'No jobs yet',
  isVideo: false,
  currentMediaId: null
})

const emit = defineEmits<{
  (e: 'job-click', job: Job): void
  (e: 'toggle-marker', data: { mediaId: number, marker: Marker }): void
  (e: 'dismiss-job', jobId: number): void
  (e: 'retry-job', jobId: number): void
  (e: 'cancel-job', jobId: number): void
  (e: 'cancel-and-dismiss-batch', batchId: string): void
  (e: 'dismiss-batch', batchId: string): void
  (e: 'clear-queue'): void
  (e: 'show-job-info', job: Job): void
  (e: 'media-load-error', mediaId: number): void
  (e: 'retry-chain', chainRunId: number): void
  (e: 'dismiss-chain', chainRunId: number): void
}>()


// Get all batch job IDs for filtering
const batchJobIds = computed(() => {
  const ids = new Set<number>()
  for (const batch of Object.values(props.batchJobs)) {
    for (const job of batch.jobs || []) {
      ids.add(job.id)
    }
  }
  return ids
})

// Computed job lists - exclude batch jobs from individual display
const activeJobs = computed(() =>
  props.jobs.filter(j =>
    ['enhancing', 'queued', 'assigned', 'processing'].includes(j.status) &&
    !batchJobIds.value.has(j.id)
  )
)

const processingJobs = computed(() =>
  props.jobs.filter(j => j.status === 'processing')
)

const enhancingJobs = computed(() =>
  props.jobs.filter(j => j.status === 'enhancing')
)

const queuedJobs = computed(() =>
  props.jobs.filter(j => ['queued', 'assigned'].includes(j.status))
)

// Enhancing first (LLM working), then processing, then queued
const sortedActiveJobs = computed(() => [
  ...enhancingJobs.value,
  ...processingJobs.value,
  ...queuedJobs.value
])

// Active batches (still in progress)
const activeBatches = computed(() => {
  return Object.values(props.batchJobs).filter(batch => {
    // Only show batches that are still in progress (not yet complete)
    return batch.inProgress > 0 || (batch.completed + batch.failed) < batch.total
  })
})

// Completed batches (show output set tile)
const completedBatches = computed(() => {
  return Object.values(props.batchJobs).filter(batch => {
    // Show batches that are fully complete and have an output set with loaded hash
    return (batch.completed + batch.failed) >= batch.total &&
           batch.output_set_id &&
           batch.output_set_hash
  })
})

const displayedJobs = computed(() =>
  props.jobs.filter(j =>
    (j.status === 'completed' || j.status === 'failed') &&
    !batchJobIds.value.has(j.id)  // Exclude batch jobs
  )
)

// Unified display items - all jobs and batches sorted by timestamp
// Active items (processing/queued) come first, then completed/failed sorted by time
const unifiedDisplayItems = computed(() => {
  const items: Array<{
    key: string
    type: 'active-job' | 'active-batch' | 'chain-run' | 'completed-batch' | 'completed-job' | 'failed-job'
    timestamp: Date
    job?: Job
    batch?: BatchInfo
    run?: ChainRun
  }> = []

  // Add active individual jobs (not in batches)
  for (const job of activeJobs.value) {
    items.push({
      key: `job-${job.id}`,
      type: 'active-job',
      timestamp: new Date(job.created_at || Date.now()),
      job
    })
  }

  // Add active batches
  for (const batch of activeBatches.value) {
    // Use earliest job's created_at as batch timestamp
    const earliestJob = batch.jobs?.sort((a, b) =>
      new Date(a.created_at).getTime() - new Date(b.created_at).getTime()
    )[0]
    items.push({
      key: `batch-active-${batch.batch_id}`,
      type: 'active-batch',
      timestamp: new Date(earliestJob?.created_at || Date.now()),
      batch
    })
  }

  // Add running/paused post-processing chains — sorted into the active flow
  // by start time so the stack reads newest-at-top like the job bars.
  for (const run of props.activeChainRuns) {
    items.push({
      key: `chain-${run.id}`,
      type: 'chain-run',
      timestamp: new Date((run as any).created_at || Date.now()),
      run
    })
  }

  // Add completed batches
  for (const batch of completedBatches.value) {
    // Use latest job's completed_at as batch timestamp
    const latestJob = batch.jobs?.filter(j => j.completed_at).sort((a, b) =>
      new Date(b.completed_at).getTime() - new Date(a.completed_at).getTime()
    )[0]
    items.push({
      key: `batch-completed-${batch.batch_id}`,
      type: 'completed-batch',
      timestamp: new Date(latestJob?.completed_at || Date.now()),
      batch
    })
  }

  // Add completed and failed individual jobs (not in batches)
  for (const job of displayedJobs.value) {
    items.push({
      key: `job-${job.id}`,
      type: job.status === 'failed' ? 'failed-job' : 'completed-job',
      timestamp: new Date(job.completed_at || job.created_at || Date.now()),
      job
    })
  }

  // Completed post-processing chains: the final image gets a result tile
  // (chain-step jobs themselves are filtered out of this page's job list).
  for (const run of props.completedChainRuns) {
    if (!run.final_media_id) continue
    items.push({
      key: `chain-final-${run.id}`,
      type: 'completed-job',
      timestamp: new Date(run.updated_at || Date.now()),
      job: {
        id: -run.id, // synthetic id; never collides with real job ids
        status: 'completed',
        result_media_id: run.final_media_id,
        completed_at: run.updated_at,
      }
    })
  }

  // Sort: active items first (by created_at desc), then completed/failed (by completed_at desc)
  const isActiveType = (t: string) => t === 'active-job' || t === 'active-batch' || t === 'chain-run'
  return items.sort((a, b) => {
    const aIsActive = isActiveType(a.type)
    const bIsActive = isActiveType(b.type)

    // Active items always come first
    if (aIsActive && !bIsActive) return -1
    if (!aIsActive && bIsActive) return 1

    // Within same category, sort by timestamp (most recent first)
    return b.timestamp.getTime() - a.timestamp.getTime()
  })
})

// Split display items into active and completed for separate rendering
const ACTIVE_ITEM_TYPES = new Set(['active-job', 'active-batch', 'chain-run'])

const activeDisplayItems = computed(() =>
  unifiedDisplayItems.value.filter(item => ACTIVE_ITEM_TYPES.has(item.type))
)

const completedDisplayItems = computed(() =>
  unifiedDisplayItems.value.filter(item => !ACTIVE_ITEM_TYPES.has(item.type))
)

// Helper functions
function getMediaHash(mediaId: number): string {
  return props.mediaHashes[mediaId] || ''
}

function hasMarker(mediaId: number, markerId: number): boolean {
  const markers = props.mediaMarkers[mediaId] || []
  return markers.some(m => m.id === markerId)
}

function getJobPrompt(job: Job): string {
  try {
    if (!job.parameters) return ''
    const params = JSON.parse(job.parameters)
    return params.prompt || ''
  } catch {
    return ''
  }
}

function getGenerationTime(job: Job): number | null {
  if (!job.result_media_id) return null
  const time = props.mediaGenerationTimes[job.result_media_id]
  return time ? Math.round(time * 10) / 10 : null  // Round to 1 decimal place
}

function handleJobClick(job: Job) {
  if (job.status === 'completed' || job.status === 'failed') {
    emit('job-click', job)
  }
}

function onDragStart(event: DragEvent, mediaId: number | undefined) {
  if (mediaId) {
    // Create a smaller drag preview for videos
    const thumbnailUrl = getThumbnailUrl(mediaId, 128)
    createDragPreview(event, thumbnailUrl, mediaId)
  }
}

function handleVideoContextMenu(event: MouseEvent, mediaId: number | undefined) {
  if (mediaId) {
    contextMenu.show({
      event,
      mediaId,
      fileHash: props.mediaHashes[mediaId]
    })
  }
}
</script>
