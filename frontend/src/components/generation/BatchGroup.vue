<template>
  <div>
    <!-- Stable batch results header. Progress/count lives in the pipeline strip. -->
    <div v-if="showHeader" class="flex items-center gap-2 px-0.5 py-1.5 border-b border-edge-subtle mb-0.5">
      <svg class="w-4 h-4 flex-shrink-0 text-content-tertiary" viewBox="0 0 20 20" fill="currentColor"><path d="M7 3a1 1 0 000 2h6a1 1 0 100-2H7zM4 7a1 1 0 011-1h10a1 1 0 110 2H5a1 1 0 01-1-1zM2 11a2 2 0 012-2h12a2 2 0 012 2v4a2 2 0 01-2 2H4a2 2 0 01-2-2v-4z" /></svg>
      <span class="text-xs text-content-muted">Batch</span>
      <div class="ml-auto flex items-center gap-1">
        <button
          @click="$emit('menu', $event)"
          class="p-1 rounded hover:bg-overlay-subtle text-content-muted hover:text-content"
          title="Batch actions"
        >
          <svg class="w-4 h-4" viewBox="0 0 20 20" fill="currentColor"><path d="M10 6a2 2 0 110-4 2 2 0 010 4zM10 12a2 2 0 110-4 2 2 0 010 4zM10 18a2 2 0 110-4 2 2 0 010 4z" /></svg>
        </button>
      </div>
    </div>

    <!-- Results grid. Callers pass only cells that should be visible; pending
         batch slots are represented by the progress strip, not placeholders. -->
    <div class="grid grid-cols-2 gap-0.5">
      <template v-for="cell in cells" :key="cell.key">
        <!-- Done: real job tile with all capabilities -->
        <div v-if="cell.state === 'done'" class="relative">
          <JobTile
            :job="cell.job"
            :is-video="jobIsVideo(cell.job)"
            :is-audio="isAudio"
            :image-mode="imageMode"
            :markers="markers"
            :media-markers="mediaMarkers"
            :media-hashes="mediaHashes"
            :media-has-alpha="mediaHasAlpha"
            :media-generation-times="mediaGenerationTimes"
            :current-media-id="currentMediaId"
            :compact-overlays="compactOverlays"
            :thumbnail-size="thumbnailSize"
            @job-click="$emit('job-click', $event)"
            @toggle-marker="$emit('toggle-marker', $event)"
            @show-job-info="$emit('show-job-info', $event)"
            @media-load-error="$emit('media-load-error', $event)"
          />
        </div>

        <!-- Post-processing: completed tile with a post-processing spinner badge -->
        <div v-else-if="cell.state === 'postprocessing'" class="relative">
          <JobTile
            :job="cell.job"
            :is-video="jobIsVideo(cell.job)"
            :is-audio="isAudio"
            :image-mode="imageMode"
            :markers="markers"
            :media-markers="mediaMarkers"
            :media-hashes="mediaHashes"
            :media-has-alpha="mediaHasAlpha"
            :media-generation-times="mediaGenerationTimes"
            :current-media-id="currentMediaId"
            :compact-overlays="compactOverlays"
            :thumbnail-size="thumbnailSize"
            @job-click="$emit('job-click', $event)"
            @toggle-marker="$emit('toggle-marker', $event)"
            @show-job-info="$emit('show-job-info', $event)"
            @media-load-error="$emit('media-load-error', $event)"
          />
          <div class="absolute top-2 left-2 z-[11] flex items-center gap-1 bg-black/70 rounded px-1.5 py-0.5">
            <div class="w-3 h-3 border-2 border-edge-subtle border-t-blue-400 rounded-full animate-spin"></div>
            <span class="text-[9px] text-white/80">post</span>
          </div>
        </div>

        <!-- Failed: error cell with retry / info / dismiss (parity with non-batch) -->
        <div
          v-else-if="cell.state === 'failed'"
          class="group relative aspect-square rounded-media overflow-hidden bg-red-500/10 flex flex-col items-center justify-center gap-2 cursor-pointer"
          @click="$emit('show-job-info', cell.job)"
        >
          <span class="text-red-400 text-lg leading-none">✕</span>
          <div class="flex items-center gap-1.5">
            <button
              @click.stop="$emit('retry-job', cell.job.id)"
              class="text-[11px] px-2 py-0.5 rounded bg-overlay-medium hover:bg-overlay-strong text-content"
            >Retry</button>
            <button
              @click.stop="$emit('dismiss-job', cell.job.id)"
              class="text-[11px] px-2 py-0.5 rounded bg-overlay-medium hover:bg-overlay-strong text-content-muted"
            >Dismiss</button>
          </div>
        </div>

        <!-- Pending (queued / generating) -->
        <div v-else class="relative aspect-square rounded-media overflow-hidden bg-matte flex items-center justify-center">
          <StatusDot bucket="running" pulse />
        </div>
      </template>
    </div>
  </div>
</template>

<script setup lang="ts">
import JobTile from './JobTile.vue'
import StatusDot from '../ui/StatusDot.vue'
import { isVideo as isVideoMedia } from '../../utils/mediaTypes'

interface Job { id: number; status: string; result_media_id?: number; result_asset_id?: number; expires_at?: string; parameters?: string }
interface Marker { id: number; name: string; color: string; icon_svg: string }
interface BatchCell { key: string; state: 'pending' | 'postprocessing' | 'done' | 'failed'; job: Job; mediaId?: number }

const props = withDefaults(defineProps<{
  cells: BatchCell[]
  total: number
  completedCount: number
  failedCount: number
  complete: boolean
  showHeader?: boolean
  isVideo?: boolean
  isAudio?: boolean
  imageMode?: 'cover' | 'fit'
  markers?: Marker[]
  mediaMarkers?: Record<number, Marker[]>
  mediaHashes?: Record<number, string>
  mediaHasAlpha?: Record<number, boolean>
  mediaGenerationTimes?: Record<number, number>
  // Full media records by id — a member's tile type follows its ACTUAL media
  // (an i2v post-processing chain turns an image job's result into a video).
  mediaData?: Record<number, any>
  currentMediaId?: number | null
  compactOverlays?: boolean
  thumbnailSize?: number
}>(), {
  showHeader: true,
  compactOverlays: false,
  thumbnailSize: 256,
})

// Same rule as JobsGrid.jobIsVideo: actual media type when loaded, else the
// tool's output type. A video rendered through the image path fires
// media-load-error, which silently drops the job.
function jobIsVideo(job: Job): boolean {
  const media = job.result_media_id ? props.mediaData?.[job.result_media_id] : null
  if (media?.file_format) return isVideoMedia(media)
  return props.isVideo ?? false
}

defineEmits<{
  (e: 'job-click', job: Job): void
  (e: 'toggle-marker', data: { mediaId: number, assetId?: number, marker: Marker }): void
  (e: 'show-job-info', job: Job): void
  (e: 'media-load-error', mediaId: number): void
  (e: 'retry-job', jobId: number): void
  (e: 'dismiss-job', jobId: number): void
  (e: 'menu', event: MouseEvent): void
}>()
</script>
