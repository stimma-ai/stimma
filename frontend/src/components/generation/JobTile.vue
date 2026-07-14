<template>
  <div
    :class="[
      'group relative aspect-square rounded-lg overflow-hidden transition-transform cursor-pointer hover:scale-105',
      imageMode === 'fit' ? 'bg-surface-raised' : '',
      currentMediaId != null && job.result_media_id === currentMediaId
        ? 'ring-2 ring-blue-500 ring-offset-2 ring-offset-surface-overlay'
        : ''
    ]"
    @click="handleJobClick"
  >
    <!-- Video display: a static poster (the video's first-frame thumbnail) is
         shown by default; the real <video> is mounted only while the tile is
         hovered and torn down again on leave. Mounting a live <video> for every
         completed tile exhausts WebKit's media-element/decoder pool — the symptom
         is blank/flickering tiles that only paint on hover. Posters are cheap
         images, so offscreen previews hold no decoder. Mirrors VirtualMediaGrid. -->
    <div
      v-if="isVideo && getMediaHash(job.result_media_id)"
      class="absolute inset-0"
      draggable="true"
      @mouseenter="activateVideo"
      @mouseleave="releaseVideo"
      @dragstart="onDragStart($event, job.result_media_id)"
      @dragend="handleDragEnd"
      @contextmenu.prevent="handleVideoContextMenu($event, job.result_media_id)"
    >
      <AppImage
        :src="getThumbnailUrl(getMediaHash(job.result_media_id), thumbnailSize, imageMode === 'fit' ? { mode: 'fit' } : {})"
        :alt="`Generated video ${job.id}`"
        :contain="imageMode === 'fit'"
        :has-alpha="false"
        container-class="w-full h-full"
        retry-on-error
      />
      <video
        v-if="videoActive"
        ref="videoEl"
        :class="['absolute inset-0 w-full h-full', imageMode === 'fit' ? 'object-contain' : 'object-cover']"
        muted
        playsinline
        preload="none"
        @error="$emit('media-load-error', job.result_media_id)"
      />
    </div>
    <!-- Image display. Fit mode shows the original full-resolution file — this is
         the user's review surface and must be sharp. Crop mode uses a bounded
         thumbnail for cover-cropped tiles. Unlike videos, images can render the
         original directly in fit mode, so they do. -->
    <MediaImage
      v-else-if="!isVideo && job.result_media_id"
      :media-id="job.result_media_id"
      :is-audio="isAudio"
      :thumbnail="imageMode !== 'fit'"
      :thumbnail-size="thumbnailSize"
      :alt="`Generated image ${job.id}`"
      :contain="imageMode === 'fit'"
      :has-alpha="mediaHasAlpha[job.result_media_id]"
      container-class="w-full h-full"
      @error="$emit('media-load-error', job.result_media_id)"
    />
    <div v-else-if="job.result_media_id" class="w-full h-full flex items-center justify-center bg-surface">
      <div class="w-8 h-8 border-2 border-edge border-t-blue-500 rounded-full animate-spin"></div>
    </div>
    <!-- Auto-delete time remaining badge (upper left) -->
    <div v-if="!compactOverlays && job.expires_at && formatRemainingTime(job.expires_at)" class="absolute top-2 left-2 z-[5] bg-black/60 backdrop-blur-md rounded-md px-1.5 py-1 flex items-center gap-1">
      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" fill="currentColor" class="w-3 h-3 text-[#FFC107]">
        <path fill-rule="evenodd" d="M5 3.25V4H2.75a.75.75 0 0 0 0 1.5h.3l.815 8.15A1.5 1.5 0 0 0 5.357 15h5.285a1.5 1.5 0 0 0 1.493-1.35l.815-8.15h.3a.75.75 0 0 0 0-1.5H11v-.75A2.25 2.25 0 0 0 8.75 1h-1.5A2.25 2.25 0 0 0 5 3.25Zm2.25-.75a.75.75 0 0 0-.75.75V4h3v-.75a.75.75 0 0 0-.75-.75h-1.5ZM6.05 6a.75.75 0 0 1 .787.713l.275 5.5a.75.75 0 0 1-1.498.075l-.275-5.5A.75.75 0 0 1 6.05 6Zm3.9 0a.75.75 0 0 1 .712.787l-.275 5.5a.75.75 0 0 1-1.498-.075l.275-5.5a.75.75 0 0 1 .786-.711Z" clip-rule="evenodd" />
      </svg>
      <span class="text-xs font-semibold text-[#FFC107] leading-none whitespace-nowrap">{{ formatRemainingTime(job.expires_at) }}</span>
    </div>
    <!-- Gen-time + info (upper right): click opens generation details -->
    <button
      v-if="!compactOverlays"
      @click.stop="$emit('show-job-info', job)"
      class="absolute top-2 right-2 z-[10] h-7 flex items-center justify-center gap-1 px-2 bg-black/80 backdrop-blur-md hover:bg-blue-500/80 rounded text-xs font-bold text-white transition-colors shadow-[0_2px_8px_rgba(0,0,0,0.5)]"
      title="Generation details"
    >
      <span v-if="getGenerationTime(job)">{{ getGenerationTime(job) }}s</span>
      <svg v-else xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-3.5 h-3.5">
        <path fill-rule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7-4a1 1 0 11-2 0 1 1 0 012 0zM9 9a.75.75 0 000 1.5h.253a.25.25 0 01.244.304l-.459 2.066A1.75 1.75 0 0010.747 15H11a.75.75 0 000-1.5h-.253a.25.25 0 01-.244-.304l.459-2.066A1.75 1.75 0 009.253 9H9z" clip-rule="evenodd" />
      </svg>
    </button>
    <!-- Marker toggle buttons (bottom left) -->
    <div v-if="!compactOverlays && job.result_media_id && markers.length > 0" class="absolute bottom-2 left-2 z-[10] flex gap-0.5">
      <button
        v-for="marker in markers"
        :key="marker.id"
        @click.stop="$emit('toggle-marker', { mediaId: job.result_media_id, marker })"
        :class="[
          'w-7 h-7 rounded-md flex items-center justify-center transition-all border-2',
          hasMarker(job.result_media_id, marker.id)
            ? 'bg-black/80'
            : 'bg-black/40 border-transparent hover:bg-black/60 text-white/50 hover:text-white'
        ]"
        :style="hasMarker(job.result_media_id, marker.id) ? { borderColor: marker.color, color: marker.color } : {}"
        :title="hasMarker(job.result_media_id, marker.id) ? `Remove ${marker.name}` : `Add ${marker.name}`"
      >
        <span class="w-4 h-4 flex items-center justify-center icon-container" v-html="sanitizeSvg(marker.icon_svg)" />
      </button>
    </div>
    <!-- Trash + remix actions (bottom right) -->
    <div v-if="!compactOverlays && job.result_media_id" class="absolute bottom-2 right-2 z-[10] flex gap-0.5">
      <button
        @click.stop="$emit('remix-media', job.result_media_id)"
        class="w-7 h-7 rounded-md flex items-center justify-center bg-black/40 hover:bg-blue-500/80 text-white/50 hover:text-white transition-all"
        title="Remix: load this image's settings"
      >
        <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor" class="w-4 h-4">
          <path stroke-linecap="round" stroke-linejoin="round" d="M19.5 12c0-1.232-.046-2.453-.138-3.662a4.006 4.006 0 0 0-3.7-3.7 48.678 48.678 0 0 0-7.324 0 4.006 4.006 0 0 0-3.7 3.7c-.017.22-.032.441-.046.662M19.5 12l3-3m-3 3-3-3m-12 3c0 1.232.046 2.453.138 3.662a4.006 4.006 0 0 0 3.7 3.7 48.656 48.656 0 0 0 7.324 0 4.006 4.006 0 0 0 3.7-3.7c.017-.22.032-.441.046-.662M4.5 12l3 3m-3-3-3 3" />
        </svg>
      </button>
      <button
        @click.stop="$emit('trash-media', job.result_media_id)"
        class="w-7 h-7 rounded-md flex items-center justify-center bg-black/40 hover:bg-red-500/80 text-white/50 hover:text-white transition-all"
        title="Move to Trash"
      >
        <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor" class="w-4 h-4">
          <path stroke-linecap="round" stroke-linejoin="round" d="m14.74 9-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 0 1-2.244 2.077H8.084a2.25 2.25 0 0 1-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 0 0-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 0 1 3.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 0 0-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 0 0-7.5 0" />
        </svg>
      </button>
    </div>
    <div class="absolute bottom-0 left-0 right-0 p-4 bg-gradient-to-t from-black/80 to-transparent opacity-0 hover:opacity-100 transition-opacity pointer-events-none">
      <div class="text-xs text-white line-clamp-2">{{ getJobPrompt(job) }}</div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, nextTick, onBeforeUnmount } from 'vue'
import { formatRemainingTime } from '../../utils/timeFormat'
import { MediaImage, AppImage } from '../media'
import { useMediaApi } from '../../composables/useMediaApi'
import { useMediaContextMenu } from '../../composables/useMediaContextMenu'
import { createDragPreview, handleDragEnd } from '../../composables/useDragPreview'
import { sanitizeSvg } from '../../utils/sanitizeHtml'
import { MseLoopPlayback } from '../../utils/mseLoopPlayback'

interface Job {
  id: number
  status: string
  result_media_id?: number
  expires_at?: string
  parameters?: string
}
interface Marker { id: number; name: string; color: string; icon_svg: string }

const props = withDefaults(defineProps<{
  job: Job
  isVideo?: boolean
  isAudio?: boolean
  imageMode?: 'cover' | 'fit'
  markers?: Marker[]
  mediaMarkers?: Record<number, Marker[]>
  mediaHashes?: Record<number, string>
  mediaHasAlpha?: Record<number, boolean>
  mediaGenerationTimes?: Record<number, number>
  currentMediaId?: number | null
  compactOverlays?: boolean
  thumbnailSize?: number
}>(), {
  isVideo: false,
  isAudio: false,
  imageMode: 'cover',
  markers: () => [],
  mediaMarkers: () => ({}),
  mediaHashes: () => ({}),
  mediaHasAlpha: () => ({}),
  mediaGenerationTimes: () => ({}),
  currentMediaId: null,
  compactOverlays: false,
  thumbnailSize: 256,
})

const emit = defineEmits<{
  (e: 'job-click', job: Job): void
  (e: 'toggle-marker', data: { mediaId: number, marker: Marker }): void
  (e: 'show-job-info', job: Job): void
  (e: 'media-load-error', mediaId: number): void
  (e: 'trash-media', mediaId: number): void
  (e: 'remix-media', mediaId: number): void
}>()

const { getThumbnailUrl, getMseLoopUrls } = useMediaApi()
const contextMenu = useMediaContextMenu()

function getMediaHash(mediaId?: number): string { return (mediaId && props.mediaHashes[mediaId]) || '' }

// Hover-gated video playback. A live <video> per completed tile would pile up
// against WebKit's media-element/decoder budget, so the real element is mounted
// only while hovered and fully released on leave/unmount — at most one tile ever
// holds a decoding video. The poster (first-frame thumbnail) carries the resting
// state. Debounced so flicking the cursor across the strip allocates nothing.
const videoEl = ref<HTMLVideoElement | null>(null)
const videoActive = ref(false)
let hoverTimer: ReturnType<typeof setTimeout> | null = null
let msePlayback: MseLoopPlayback | null = null

async function activateVideo() {
  if (hoverTimer) clearTimeout(hoverTimer)
  hoverTimer = setTimeout(async () => {
    hoverTimer = null
    const hash = getMediaHash(props.job.result_media_id)
    if (!hash) return
    videoActive.value = true            // mount the <video>
    await nextTick()
    const v = videoEl.value
    if (!v || !videoActive.value) return // left during mount
    msePlayback = new MseLoopPlayback(v, getMseLoopUrls(hash), {
      applyFaceCrop: props.imageMode !== 'fit',
      initialLoops: 3,
      appendLoops: 2,
      bufferAheadLoops: 1,
      retainBehindLoops: 1,
      onError: () => emit('media-load-error', props.job.result_media_id!),
    })
    void msePlayback.start().catch(() => {})
  }, 150)
}

function releaseVideo() {
  if (hoverTimer) { clearTimeout(hoverTimer); hoverTimer = null }
  msePlayback?.destroy()
  msePlayback = null
  videoActive.value = false             // unmount the <video>
}

onBeforeUnmount(releaseVideo)
function hasMarker(mediaId: number, markerId: number): boolean {
  return (props.mediaMarkers[mediaId] || []).some(m => m.id === markerId)
}
function getGenerationTime(job: Job): number | null {
  if (!job.result_media_id) return null
  const time = props.mediaGenerationTimes[job.result_media_id]
  return time ? Math.round(time * 10) / 10 : null
}
function getJobPrompt(job: Job): string {
  try { return job.parameters ? (JSON.parse(job.parameters).prompt || '') : '' } catch { return '' }
}
function handleJobClick() {
  if (props.job.status === 'completed' || props.job.status === 'failed') emit('job-click', props.job)
}
function onDragStart(event: DragEvent, mediaId?: number) {
  if (mediaId) createDragPreview(event, getThumbnailUrl(mediaId, 128), mediaId, undefined, props.isVideo)
}
function handleVideoContextMenu(event: MouseEvent, mediaId?: number) {
  if (mediaId) contextMenu.show({ event, mediaId, fileHash: props.mediaHashes[mediaId] })
}
</script>
