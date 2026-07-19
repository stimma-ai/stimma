<template>
  <div class="h-full flex flex-col">
    <!-- Empty only when there's truly nothing to show: a job whose chain is
         running is hidden from `jobs` (the chain bar represents it), so the
         bar must keep the grid alive or the whole strip blinks out. -->
    <div v-if="jobs.length === 0 && activeChainRuns.length === 0 && waitingSlotCount === 0" class="text-center py-12 px-4 text-content-muted">
      <p>{{ emptyMessage }}</p>
    </div>
    <div v-else class="flex flex-col gap-0.5">
      <!-- In-flight progress: slim landscape bars docked at the top of the
           results area — one per job/batch/chain, stacked newest-first so
           finishing work flows into the completed list below. -->
      <div v-if="activeDisplayItems.length > 0 || waitingSlotCount > 0" class="flex flex-col gap-0.5">
        <template v-for="item in activeDisplayItems" :key="item.key">
          <!-- Active individual job (queued/processing/enhancing) -->
          <PipelineProgressBar
            v-if="item.type === 'active-job'"
            v-bind="jobModel(item.job)"
            :compact="compactOverlays"
            @cancel="$emit('cancel-job', item.job.id)"
          />
          <!-- Active batch (in progress) — determinate fraction -->
          <PipelineProgressBar
            v-else-if="item.type === 'active-batch'"
            v-bind="batchModel(item.batch)"
            :compact="compactOverlays"
            @cancel="$emit('cancel-and-dismiss-batch', item.batch.batch_id)"
          />
          <!-- Running/paused post-processing chain: same segmented pipeline,
               generation shown as the first (done) stage for continuity. -->
          <PipelineProgressBar
            v-else-if="item.type === 'chain-run'"
            v-bind="chainModel(item.run)"
            :compact="compactOverlays"
            @retry="$emit('retry-chain', item.run.id)"
            @dismiss="$emit('dismiss-chain', item.run.id)"
            @cancel="$emit('dismiss-chain', item.run.id)"
          />
          <!-- Active media-batch: standard progress strip, plus finished
               results appearing below as they complete. -->
          <div v-else-if="item.type === 'media-batch-active'" class="flex flex-col gap-0.5">
            <PipelineProgressBar
              v-bind="mediaBatchModel(item.batch)"
              :compact="compactOverlays"
              @cancel="$emit('cancel-and-dismiss-batch', item.batch.batch_id)"
            />
            <BatchGroup
              v-if="batchResultCells(item.batch).length > 0"
              :cells="batchResultCells(item.batch)"
              :total="item.batch.total"
              :completed-count="batchCompletedCount(item.batch)"
              :failed-count="batchFailedCount(item.batch)"
              :complete="false"
              :is-video="isVideo"
              :is-audio="isAudio"
              :image-mode="imageMode"
              :markers="markers"
              :media-markers="mediaMarkers"
              :media-hashes="mediaHashes"
              :media-has-alpha="mediaHasAlpha"
              :media-generation-times="mediaGenerationTimes"
              :media-data="mediaData"
              :current-media-id="currentMediaId"
              :compact-overlays="compactOverlays"
              :thumbnail-size="thumbnailSize"
              @job-click="$emit('job-click', $event)"
              @toggle-marker="$emit('toggle-marker', $event)"
              @show-job-info="$emit('show-job-info', $event)"
              @media-load-error="$emit('media-load-error', $event)"
              @retry-job="$emit('retry-job', $event)"
              @dismiss-job="$emit('dismiss-job', $event)"
              @menu="onBatchMenu($event, item.batch)"
            />
          </div>
        </template>
        <!-- Unfilled generation slots (forever mode): the strip reads as a
             stable set of `slotCount` lanes, so slots this instance hasn't
             been granted yet (backend saturated, or the next submit is still
             in flight) show as waiting lanes instead of vanishing. -->
        <PipelineProgressBar
          v-for="i in waitingSlotCount"
          :key="`waiting-slot-${i}`"
          :name="toolDisplayName || 'Generation'"
          status="queued"
          label="Waiting for slot…"
          :segments="[{ status: 'pending' }]"
          :show-cancel="false"
          :compact="compactOverlays"
          class="opacity-50"
        />
      </div>

      <!-- Completed/failed items -->
      <template v-for="item in completedDisplayItems" :key="item.key">

        <!-- Completed batch output set - set tile -->
        <template v-if="item.type === 'completed-batch'">
          <div class="grid grid-cols-1">
            <div
              class="group relative aspect-square rounded-media overflow-hidden cursor-pointer bg-matte"
              @click="$emit('job-click', { status: 'completed', result_media_id: item.batch.output_set_id, is_set: true, set_data: item.batch.output_set_data })"
            >
              <MediaImage
                v-if="item.batch.output_set_hash"
                :file-hash="item.batch.output_set_hash"
                :media-id="item.batch.output_set_id"
                :asset-id="item.batch.result_asset_id"
                :thumbnail-size="thumbnailSize"
                alt="Batch output set"
                container-class="w-full h-full"
              />
              <div v-if="item.batch.expires_at && formatRemainingTime(item.batch.expires_at)" class="absolute top-2 left-2 z-chrome rounded bg-black/55 px-1.5 py-1 backdrop-blur-sm">
                <span class="text-[11px] font-mono font-semibold leading-none text-amber-400">{{ formatRemainingTime(item.batch.expires_at) }}</span>
              </div>
              <!-- Set badge overlay (upper right, matching browser) -->
              <div class="absolute top-2 right-2 z-chrome bg-black/55 backdrop-blur-sm rounded px-1.5 py-1 flex items-center gap-1">
                <svg class="w-4 h-4 flex-shrink-0 text-amber-400" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M6.429 9.75L2.25 12l4.179 2.25m0-4.5l5.571 3 5.571-3m-11.142 0L2.25 7.5 12 2.25l9.75 5.25-4.179 2.25m0 0L21.75 12l-4.179 2.25m0 0l4.179 2.25L12 21.75 2.25 16.5l4.179-2.25m11.142 0l-5.571 3-5.571-3" />
                </svg>
                <span class="text-[11px] font-mono font-semibold text-white leading-none">{{ item.batch.output_set_member_count || item.batch.completed }}</span>
              </div>
              <!-- Marker toggle buttons (bottom left) -->
              <div v-if="!compactOverlays && item.batch.output_set_id && markers.length > 0" class="absolute bottom-2 left-2 z-chrome flex gap-0.5">
                <button
                  v-for="marker in markers"
                  :key="marker.id"
                  @click.stop="$emit('toggle-marker', { mediaId: item.batch.output_set_id, assetId: item.batch.result_asset_id, marker })"
                  :class="[
                    'w-7 h-7 rounded backdrop-blur-sm flex items-center justify-center transition-all border-2',
                    hasMarker(item.batch.output_set_id, marker.id)
                      ? 'bg-black/55'
                      : 'bg-black/55 border-transparent hover:bg-black/70 text-white/50 hover:text-white'
                  ]"
                  :style="hasMarker(item.batch.output_set_id, marker.id) ? { borderColor: marker.color, color: marker.color } : {}"
                  :title="hasMarker(item.batch.output_set_id, marker.id) ? `Remove ${marker.name}` : `Add ${marker.name}`"
                >
                  <span class="w-4 h-4 flex items-center justify-center icon-container" v-html="sanitizeSvg(marker.icon_svg)" />
                </button>
              </div>
              <!-- Set title overlay (bottom center, matching browser) -->
              <div
                v-if="item.batch.output_set_title"
                class="absolute bottom-2 left-0 right-0 flex justify-center z-chrome pointer-events-none"
              >
                <div class="bg-black/55 backdrop-blur-sm rounded px-2.5 py-1 truncate max-w-[calc(100%-16px)]">
                  <span class="text-[11px] text-white font-medium">{{ item.batch.output_set_title }}</span>
                </div>
              </div>
            </div>
          </div>
        </template>

        <!-- Completed media-batch (presentation-only) - same grid, all filled -->
        <template v-else-if="item.type === 'media-batch-done'">
          <BatchGroup
            :cells="batchCells(item.batch)"
            :total="item.batch.total"
            :completed-count="batchCompletedCount(item.batch)"
            :failed-count="batchFailedCount(item.batch)"
            :complete="true"
            :is-video="isVideo"
            :is-audio="isAudio"
            :image-mode="imageMode"
            :markers="markers"
            :media-markers="mediaMarkers"
            :media-hashes="mediaHashes"
            :media-has-alpha="mediaHasAlpha"
            :media-generation-times="mediaGenerationTimes"
            :media-data="mediaData"
            :current-media-id="currentMediaId"
            :compact-overlays="compactOverlays"
            :thumbnail-size="thumbnailSize"
            @job-click="$emit('job-click', $event)"
            @toggle-marker="$emit('toggle-marker', $event)"
            @show-job-info="$emit('show-job-info', $event)"
            @media-load-error="$emit('media-load-error', $event)"
            @retry-job="$emit('retry-job', $event)"
            @dismiss-job="$emit('dismiss-job', $event)"
            @menu="onBatchMenu($event, item.batch)"
          />
        </template>

        <!-- Completed individual job - image tile -->
        <template v-else-if="item.type === 'completed-job'">
          <div class="grid grid-cols-1">
            <JobTile
              :job="item.job"
              :is-video="jobIsVideo(item.job)"
              :is-audio="isAudio"
              :image-mode="imageMode"
              :markers="markers"
              :media-markers="mediaMarkers"
              :media-hashes="mediaHashes"
              :media-has-alpha="mediaHasAlpha"
              :media-generation-times="mediaGenerationTimes"
              :media-data="mediaData"
              :current-media-id="currentMediaId"
              :compact-overlays="compactOverlays"
              :thumbnail-size="thumbnailSize"
              @job-click="$emit('job-click', $event)"
              @toggle-marker="$emit('toggle-marker', $event)"
              @show-job-info="$emit('show-job-info', $event)"
              @media-load-error="$emit('media-load-error', $event)"
              @trash-media="$emit('trash-media', $event)"
              @remix-media="$emit('remix-media', $event)"
            />
          </div>
        </template>

        <!-- Failed job — terminal error row (no progress track). Click opens the
             failure details; stacks vertically in the narrow stage strip. -->
        <template v-else-if="item.type === 'failed-job'">
          <FailedJobRow
            :name="toolDisplayName || item.job.model_name || 'Generation'"
            :error="item.job.error"
            :compact="compactOverlays"
            class="cursor-pointer"
            @click="handleJobClick(item.job)"
            @retry="$emit('retry-job', item.job.id)"
            @dismiss="$emit('dismiss-job', item.job.id)"
          />
        </template>

      </template>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { MediaImage, AppImage } from '../media'
import PipelineProgressBar from './postprocessing/PipelineProgressBar.vue'
import FailedJobRow from './FailedJobRow.vue'
import JobTile from './JobTile.vue'
import BatchGroup from './BatchGroup.vue'
import { useMediaApi } from '../../composables/useMediaApi'
import { useMediaContextMenu } from '../../composables/useMediaContextMenu'
import { createDragPreview, handleDragEnd } from '../../composables/useDragPreview'
import { sanitizeSvg } from '../../utils/sanitizeHtml'
import { isVideo as isVideoMedia } from '../../utils/mediaTypes'
import { useExpirationClock } from '../../composables/useExpirationClock'

const { getMediaFileUrl, getThumbnailUrl } = useMediaApi()
const { formatRemainingTime } = useExpirationClock()
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
  model_name?: string
  result_media_id?: number
  result_asset_id?: number
  expires_at?: string
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
  result_asset_id?: number
  expires_at?: string
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
  mediaHasAlpha?: Record<number, boolean>
  mediaMarkers?: Record<number, Marker[]>
  mediaGenerationTimes?: Record<number, number>
  // Full media records by id (file_format etc.) — a completed job's tile type
  // follows its ACTUAL media, not the tool (an i2v post-processing chain turns
  // an image job's result into a video).
  mediaData?: Record<number, any>
  batchJobs?: Record<string, BatchInfo>
  // In-flight/paused post-processing chains (rendered as progress bars; a
  // completed chain has no presence of its own — the base job's tile becomes
  // the final image)
  activeChainRuns?: ChainRun[]
  imageMode?: 'cover' | 'fit'
  emptyMessage?: string
  isVideo?: boolean
  isAudio?: boolean
  // Media id of the item currently focused/shown elsewhere (e.g. the Stage hero).
  // Its tile gets a blue ring so the user can see what they're looking at.
  currentMediaId?: number | null
  // Human-readable name of the tool whose jobs this grid shows. Jobs only carry
  // the raw model/tool id, so the owning view supplies the display name.
  toolDisplayName?: string
  compactOverlays?: boolean
  thumbnailSize?: number
  // Forever-mode concurrency for this instance, or null when not in forever
  // mode. When set, the active strip renders as that many stable lanes:
  // unoccupied ones show as "Waiting for slot…" placeholders.
  slotCount?: number | null
}

const props = withDefaults(defineProps<Props>(), {
  markers: () => [],
  mediaHashes: () => ({}),
  mediaHasAlpha: () => ({}),
  mediaMarkers: () => ({}),
  mediaGenerationTimes: () => ({}),
  mediaData: () => ({}),
  batchJobs: () => ({}),
  activeChainRuns: () => [],
  imageMode: 'cover',
  emptyMessage: 'No jobs yet',
  isVideo: false,
  isAudio: false,
  currentMediaId: null,
  toolDisplayName: '',
  compactOverlays: false,
  thumbnailSize: 256,
  slotCount: null,
})

const emit = defineEmits<{
  (e: 'job-click', job: Job): void
  (e: 'toggle-marker', data: { mediaId: number, assetId?: number, marker: Marker }): void
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
  (e: 'trash-media', data: { mediaId: number, assetId?: number }): void
  (e: 'remix-media', mediaId: number): void
}>()


// A post-processing chain can transition a job's result media type (an image
// job whose chain ends in an i2v step points at a VIDEO). Type each tile from
// its actual media record when loaded; fall back to the tool's output type.
// Rendering a video through the image path fires media-load-error, which
// silently drops the job from the strip.
function jobIsVideo(job: Job): boolean {
  const media = job.result_media_id ? props.mediaData[job.result_media_id] : null
  if (media?.file_format) return isVideoMedia(media)
  return props.isVideo
}

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

// ── Media-batch (presentation-only) grouping ───────────────────────────────
// A media-batch runs a tool once per item; results stay individual library
// assets and we present them as ONE mini-grid that fills in as items complete.
// Post-processing is part of an item: a member whose chain is still running is
// "in progress" — the batch is not done until every member (incl. its chain) is.

function jobParams(job: Job): any {
  if (!job.parameters) return null
  try { return JSON.parse(job.parameters) } catch { return null }
}

function isPresentationBatch(batch: BatchInfo): boolean {
  for (const j of batch.jobs || []) {
    const p = jobParams(j)
    if (p && p._batch_presentation_only) return true
  }
  return false
}

// job_id -> active (running/paused) post-processing chain run
const activeChainByJobId = computed(() => {
  const m = new Map<number, ChainRun>()
  for (const r of props.activeChainRuns || []) {
    if (r.job_id != null) m.set(r.job_id, r)
  }
  return m
})

const mediaBatches = computed(() => Object.values(props.batchJobs).filter(isPresentationBatch))
const mediaBatchIds = computed(() => new Set(mediaBatches.value.map(b => b.batch_id)))
// Job ids belonging to media batches (so their chain bars aren't shown standalone).
const mediaBatchJobIds = computed(() => {
  const ids = new Set<number>()
  for (const b of mediaBatches.value) for (const j of b.jobs || []) ids.add(j.id)
  return ids
})

type BatchCellState = 'pending' | 'postprocessing' | 'done' | 'failed'
interface BatchCell { key: string; state: BatchCellState; job: Job; mediaId?: number }

// Cells for a media-batch mini-grid, ordered by submission (≈ batch index).
function batchCells(batch: BatchInfo): BatchCell[] {
  const jobs = [...(batch.jobs || [])].sort((a, b) => a.id - b.id)
  return jobs.map(job => {
    if (job.status === 'failed' || job.status === 'cancelled') {
      return { key: `j${job.id}`, state: 'failed', job }
    }
    if (job.status === 'completed') {
      const chain = activeChainByJobId.value.get(job.id)
      if (chain) {
        // Post-processing still running — part of this item, not done yet.
        return { key: `j${job.id}`, state: 'postprocessing', job, mediaId: chain.last_good_media_id || job.result_media_id }
      }
      return { key: `j${job.id}`, state: 'done', job, mediaId: job.result_media_id }
    }
    return { key: `j${job.id}`, state: 'pending', job }
  })
}

function batchCompletedCount(batch: BatchInfo): number {
  return batchCells(batch).filter(c => c.state === 'done').length
}
function batchFailedCount(batch: BatchInfo): number {
  return batchCells(batch).filter(c => c.state === 'failed').length
}
function batchTerminalCount(batch: BatchInfo): number {
  return batchCompletedCount(batch) + batchFailedCount(batch)
}
function batchResultCells(batch: BatchInfo): BatchCell[] {
  return batchCells(batch).filter(c => c.state === 'done' || c.state === 'failed')
}
function batchIsComplete(batch: BatchInfo): boolean {
  const cells = batchCells(batch)
  // Guard against not-all-jobs-loaded-yet: require the full expected count.
  if (cells.length < (batch.total || cells.length)) return false
  return cells.length > 0 && cells.every(c => c.state === 'done' || c.state === 'failed')
}
function batchMemberMediaIds(batch: BatchInfo): number[] {
  return batchCells(batch).filter(c => c.state === 'done' && c.mediaId).map(c => c.mediaId as number)
}

// Active batches (still in progress) — set-based batches only; media batches
// have their own mini-grid rendering.
const activeBatches = computed(() => {
  return Object.values(props.batchJobs).filter(batch => {
    if (mediaBatchIds.value.has(batch.batch_id)) return false
    return batch.inProgress > 0 || (batch.completed + batch.failed) < batch.total
  })
})

// Completed batches (show output set tile) — set-based batches only.
const completedBatches = computed(() => {
  return Object.values(props.batchJobs).filter(batch => {
    if (mediaBatchIds.value.has(batch.batch_id)) return false
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
    type: 'active-job' | 'active-batch' | 'chain-run' | 'completed-batch' | 'media-batch-active' | 'media-batch-done' | 'completed-job' | 'failed-job'
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
  // by start time so the stack reads newest-at-top like the job bars. Chains that
  // belong to a media-batch member are represented INSIDE the batch grid (the
  // item shows a post-processing state), so they're not shown standalone here.
  for (const run of props.activeChainRuns) {
    if (run.job_id != null && mediaBatchJobIds.value.has(run.job_id)) continue
    items.push({
      key: `chain-${run.id}`,
      type: 'chain-run',
      timestamp: new Date((run as any).created_at || Date.now()),
      run
    })
  }

  // Add media-batches (presentation-only) — one mini-grid that fills in. Active
  // until every member (incl. post-processing) is terminal.
  for (const batch of mediaBatches.value) {
    const done = batchIsComplete(batch)
    const earliestJob = [...(batch.jobs || [])].sort((a, b) =>
      new Date(a.created_at || 0).getTime() - new Date(b.created_at || 0).getTime()
    )[0]
    const latestJob = [...(batch.jobs || [])].filter(j => j.completed_at).sort((a, b) =>
      new Date(b.completed_at!).getTime() - new Date(a.completed_at!).getTime()
    )[0]
    items.push({
      key: `media-batch-${batch.batch_id}`,
      type: done ? 'media-batch-done' : 'media-batch-active',
      timestamp: new Date((done ? latestJob?.completed_at : earliestJob?.created_at) || Date.now()),
      batch
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

  // Sort: active items first (by created_at desc), then completed/failed (by completed_at desc)
  const isActiveType = (t: string) => t === 'active-job' || t === 'active-batch' || t === 'chain-run' || t === 'media-batch-active'
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
const ACTIVE_ITEM_TYPES = new Set(['active-job', 'active-batch', 'chain-run', 'media-batch-active'])

const activeDisplayItems = computed(() =>
  unifiedDisplayItems.value.filter(item => ACTIVE_ITEM_TYPES.has(item.type))
)

const completedDisplayItems = computed(() =>
  unifiedDisplayItems.value.filter(item => !ACTIVE_ITEM_TYPES.has(item.type))
)

// Generation slots currently occupied by active items. A post-processing
// chain does NOT hold a slot — the backend frees the generation slot before
// the chain tail runs (that's why chain bars can appear on top of a full set
// of generating lanes).
const waitingSlotCount = computed(() => {
  if (!props.slotCount) return 0
  let used = 0
  for (const item of activeDisplayItems.value) {
    if (item.type === 'active-job') {
      used += 1
    } else if (item.type === 'active-batch' || item.type === 'media-batch-active') {
      // A batch bar stands for all its member jobs; members that are queued/
      // assigned/processing each hold a slot. An in-progress batch with no
      // countable members yet still holds at least one.
      used += Math.max(item.batch?.inProgress || 0, 1)
    }
  }
  return Math.max(0, props.slotCount - used)
})

// --- PipelineProgressBar models ---------------------------------------------
// Each active item (job / batch / chain) is normalised into the same segmented
// pipeline props so generation and post-processing read as one continuous flow.

function jobModel(job: Job) {
  const enhancing = job.status === 'enhancing'
  const processing = job.status === 'processing'
  return {
    name: props.toolDisplayName || job.model_name || 'Generation',
    status: enhancing ? 'enhancing' : processing ? 'processing' : 'queued',
    label: enhancing ? 'Enhancing prompt…' : processing ? 'Generating…' : 'Queued…',
    segments: [{ status: (processing || enhancing ? 'active' : 'pending') as const }],
  }
}

function batchModel(batch: BatchInfo) {
  const done = batch.completed + batch.failed
  return {
    name: props.toolDisplayName || batch.jobs?.[0]?.model_name || 'Batch',
    status: batch.inProgress > 0 ? 'processing' : 'queued',
    label: `${done} of ${batch.total} done`,
    progress: batch.total ? done / batch.total : null,
  }
}

function mediaBatchModel(batch: BatchInfo) {
  const done = batchTerminalCount(batch)
  return {
    name: props.toolDisplayName || batch.jobs?.[0]?.model_name || 'Batch',
    status: batch.inProgress > 0 ? 'processing' : 'queued',
    label: `${done} of ${batch.total} done`,
    progress: batch.total ? done / batch.total : null,
  }
}

function chainStepLabel(step: any): string {
  if (!step) return 'step'
  return step.kind === 'filter' ? (step.filter_id || 'filter') : (step.tool_name || step.tool_id || 'tool')
}

const CHAIN_STATUS_WORD: Record<string, string> = {
  done: 'done', running: 'running', failed: 'failed',
  skipped_incompatible: 'skipped (incompatible input)', queued: 'queued',
}

function chainModel(run: ChainRun) {
  const failed = run.status === 'paused' || run.status === 'failed'
  const results = run.step_results || []
  const chain = run.chain || []

  // Steps skipped as incompatible were no-ops — drop them from the live
  // pipeline (and the "of N" count) entirely; they aren't part of the work
  // that ran, same as a step the user disabled up front.
  const kept = results
    .map((r, i) => ({ r, i }))
    .filter(({ r }) => r.status !== 'skipped_incompatible')

  // Generation is the first, always-done stage; the kept chain steps follow.
  const stepSegments = kept.map(({ r, i }) => ({
    status: (r.status === 'done' ? 'done'
      : r.status === 'running' ? 'active'
      : r.status === 'failed' ? 'failed'
      : 'pending') as 'done' | 'active' | 'pending' | 'failed',
    title: `${chainStepLabel(chain[i])} — ${CHAIN_STATUS_WORD[r.status] || r.status}`,
  }))
  const segments = [{ status: 'done' as const, title: 'Generated' }, ...stepSegments]

  // Locate the step the user should be told about, within the kept steps: the
  // failed one, else the running one, else the latest reached.
  let focusPos = kept.findIndex(({ r }) => r.status === 'failed')
  if (focusPos < 0) focusPos = kept.findIndex(({ r }) => r.status === 'running')
  if (focusPos < 0) focusPos = Math.max(0, kept.filter(({ i }) => i <= run.step_index).length - 1)
  const focusOrigIdx = kept[focusPos]?.i ?? 0

  const total = kept.length + 1                          // +1 for generation
  const position = Math.min(focusPos + 2, total)         // generation is position 1
  const stepName = chainStepLabel(chain[focusOrigIdx])
  const label = failed
    ? `${stepName} failed — step ${position} of ${total}`
    : `${stepName} — step ${position} of ${total}`

  // Single-step chains read better titled by their one tool (matching the
  // generation bars); multi-step chains get the umbrella "Post-processing".
  const name = kept.length > 1
    ? 'Post-processing'
    : (kept.length ? chainStepLabel(chain[kept[0].i]) : 'Post-processing')

  return {
    name,
    label,
    segments,
    thumbMediaId: run.last_good_media_id || run.base_media_id,
    failed,
    showRetry: failed,
  }
}

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

// Group actions over the batch members (add to board, create set, tag, export…).
function onBatchMenu(event: MouseEvent, batch: BatchInfo) {
  const mediaIds = batchMemberMediaIds(batch)
  if (mediaIds.length === 0) return
  contextMenu.show({ event, mediaId: mediaIds[0], mediaIds })
}
</script>
