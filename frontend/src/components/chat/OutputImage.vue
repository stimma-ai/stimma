<template>
  <!-- Output image container: always square with letterboxing (v2) -->
  <div
    class="rounded overflow-hidden flex-shrink-0 relative group"
    :style="containerStyle"
    :class="{
      'bg-base flex items-center justify-center': row.output.status === 'pending' || row.output.status === 'generating',
      'cursor-pointer': (row.output.status === 'complete' || row.output.status === 'trashed') && !isTrashed && !row.output.deleted,
      'bg-red-500/10 flex flex-col items-center justify-center': row.output.status === 'failed' || row.output.status === 'cancelled'
    }"
    @click="handleClick"
  >
    <!-- Generating spinner -->
    <div
      v-if="row.output.status === 'pending' || row.output.status === 'generating'"
      class="relative w-full h-full flex items-center justify-center"
    >
      <div class="animate-spin rounded-full h-10 w-10 border-2 border-edge border-t-blue-500"></div>
      <!-- Progress indicator -->
      <div v-if="row.output.progress" class="absolute bottom-2 left-2 right-2">
        <div class="h-1 bg-surface-raised rounded-full overflow-hidden">
          <div
            class="h-full bg-blue-500 transition-all"
            :style="{ width: `${row.output.progress}%` }"
          ></div>
        </div>
      </div>
      <!-- Cancel button on hover -->
      <button
        @click.stop="$emit('cancel', row.id)"
        class="absolute top-1 right-1 p-1 bg-surface/80 hover:bg-red-500/20 rounded opacity-0 group-hover:opacity-100 transition-opacity"
        title="Cancel"
      >
        <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor" class="w-4 h-4 text-content-tertiary hover:text-red-500">
          <path stroke-linecap="round" stroke-linejoin="round" d="M6 18 18 6M6 6l12 12" />
        </svg>
      </button>
    </div>

    <!-- Permanently Deleted -->
    <template v-if="row.output.deleted">
      <div class="w-full h-full bg-surface flex items-center justify-center">
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-8 h-8 text-content-muted">
          <path fill-rule="evenodd" d="M8.75 1A2.75 2.75 0 006 3.75v.443c-.795.077-1.584.176-2.365.298a.75.75 0 10.23 1.482l.149-.022.841 10.518A2.75 2.75 0 007.596 19h4.807a2.75 2.75 0 002.742-2.53l.841-10.52.149.023a.75.75 0 00.23-1.482A41.03 41.03 0 0014 4.193V3.75A2.75 2.75 0 0011.25 1h-2.5zM10 4c.84 0 1.673.025 2.5.075V3.75c0-.69-.56-1.25-1.25-1.25h-2.5c-.69 0-1.25.56-1.25 1.25v.325C8.327 4.025 9.16 4 10 4zM8.58 7.72a.75.75 0 00-1.5.06l.3 7.5a.75.75 0 101.5-.06l-.3-7.5zm4.34.06a.75.75 0 10-1.5-.06l-.3 7.5a.75.75 0 101.5.06l.3-7.5z" clip-rule="evenodd" />
        </svg>
      </div>
    </template>

    <!-- Complete: workspace file (no media_id, served via workspace URL) -->
    <template v-else-if="row.output.status === 'complete' && row.output.workspace_url && !row.output.media_id">
      <img
        :src="workspaceImageSrc"
        class="w-full h-full object-contain"
        loading="lazy"
      />
    </template>

    <!-- Complete or Trashed (trashed items still viewable) -->
    <template v-else-if="(row.output.status === 'complete' || row.output.status === 'trashed') && row.output.media_id">
      <MediaImage
        :media-id="row.output.media_id"
        :thumbnail="effectiveThumbnail"
        :thumbnail-size="effectiveThumbnail ? 512 : undefined"
        :contain="true"
        container-class="w-full h-full"
      />

      <!-- Media type badge (upper right) - for non-image types -->
      <div v-if="outputMediaType && outputMediaType !== 'image'" class="absolute top-1.5 right-1.5 z-[5]">
        <div class="bg-black/60 backdrop-blur-md rounded px-1.5 py-0.5 flex items-center gap-1">
          <!-- Audio icon (music note) -->
          <svg v-if="outputMediaType === 'audio'" class="w-3.5 h-3.5 flex-shrink-0 text-purple-500" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" d="M9 19V6l12-3v13M9 19c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zm12-3c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2z" />
          </svg>
          <!-- Text icon (document) -->
          <svg v-else-if="outputMediaType === 'text'" class="w-3.5 h-3.5 flex-shrink-0 text-gray-400" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m0 12.75h7.5m-7.5 3H12M10.5 2.25H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z" />
          </svg>
          <!-- Set icon (layers) -->
          <svg v-else-if="outputMediaType === 'set'" class="w-3.5 h-3.5 flex-shrink-0 text-amber-500" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" d="M6.429 9.75L2.25 12l4.179 2.25m0-4.5l5.571 3 5.571-3m-11.142 0L2.25 7.5 12 2.25l9.75 5.25-4.179 2.25m0 0L21.75 12l-4.179 2.25m0 0l4.179 2.25L12 21.75 2.25 16.5l4.179-2.25m11.142 0l-5.571 3-5.571-3" />
          </svg>
          <!-- Grid icon -->
          <svg v-else-if="outputMediaType === 'grid'" class="w-3.5 h-3.5 flex-shrink-0 text-cyan-500" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" d="M3.75 6A2.25 2.25 0 016 3.75h2.25A2.25 2.25 0 0110.5 6v2.25a2.25 2.25 0 01-2.25 2.25H6a2.25 2.25 0 01-2.25-2.25V6zM3.75 15.75A2.25 2.25 0 016 13.5h2.25a2.25 2.25 0 012.25 2.25V18a2.25 2.25 0 01-2.25 2.25H6A2.25 2.25 0 013.75 18v-2.25zM13.5 6a2.25 2.25 0 012.25-2.25H18A2.25 2.25 0 0120.25 6v2.25A2.25 2.25 0 0118 10.5h-2.25a2.25 2.25 0 01-2.25-2.25V6zM13.5 15.75a2.25 2.25 0 012.25-2.25H18a2.25 2.25 0 012.25 2.25V18A2.25 2.25 0 0118 20.25h-2.25A2.25 2.25 0 0113.5 18v-2.25z" />
          </svg>
          <!-- Video icon -->
          <svg v-else-if="outputMediaType === 'video'" class="w-3.5 h-3.5 flex-shrink-0 text-green-500" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" d="M5.25 5.653c0-.856.917-1.398 1.667-.986l11.54 6.348a1.125 1.125 0 010 1.971l-11.54 6.347a1.125 1.125 0 01-1.667-.985V5.653z" />
          </svg>
          <!-- Layout icon (newspaper) -->
          <svg v-else-if="outputMediaType === 'layout'" class="w-3.5 h-3.5 flex-shrink-0 text-emerald-500" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" d="M12 7.5h1.5m-1.5 3h1.5m-7.5 3h7.5m-7.5 3h7.5m3-9h3.375c.621 0 1.125.504 1.125 1.125V18a2.25 2.25 0 0 1-2.25 2.25M16.5 7.5V18a2.25 2.25 0 0 0 2.25 2.25M16.5 7.5V4.875c0-.621-.504-1.125-1.125-1.125H4.125C3.504 3.75 3 4.254 3 4.875V18a2.25 2.25 0 0 0 2.25 2.25h13.5M6 7.5h3v3H6v-3Z" />
          </svg>
        </div>
      </div>

      <!-- Trashed badge (upper left) - yellow trash icon -->
      <div v-if="isTrashed" class="absolute top-1.5 left-1.5 z-[5] bg-black/60 backdrop-blur-md rounded px-1.5 py-0.5 flex items-center gap-1">
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" fill="currentColor" class="w-3.5 h-3.5 text-[#FFC107]">
          <path fill-rule="evenodd" d="M5 3.25V4H2.75a.75.75 0 0 0 0 1.5h.3l.815 8.15A1.5 1.5 0 0 0 5.357 15h5.285a1.5 1.5 0 0 0 1.493-1.35l.815-8.15h.3a.75.75 0 0 0 0-1.5H11v-.75A2.25 2.25 0 0 0 8.75 1h-1.5A2.25 2.25 0 0 0 5 3.25Zm2.25-.75a.75.75 0 0 0-.75.75V4h3v-.75a.75.75 0 0 0-.75-.75h-1.5ZM6.05 6a.75.75 0 0 1 .787.713l.275 5.5a.75.75 0 0 1-1.498.075l-.275-5.5A.75.75 0 0 1 6.05 6Zm3.9 0a.75.75 0 0 1 .712.787l-.275 5.5a.75.75 0 0 1-1.498-.075l.275-5.5a.75.75 0 0 1 .786-.711Z" clip-rule="evenodd" />
        </svg>
      </div>

      <!-- Auto-delete time remaining badge (upper left, only if not trashed) -->
      <div v-else-if="formattedRemainingTime" class="absolute top-1.5 left-1.5 z-[5] bg-black/60 backdrop-blur-md rounded px-1.5 py-0.5 flex items-center gap-1">
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" fill="currentColor" class="w-3 h-3 text-[#FFC107]">
          <path fill-rule="evenodd" d="M5 3.25V4H2.75a.75.75 0 0 0 0 1.5h.3l.815 8.15A1.5 1.5 0 0 0 5.357 15h5.285a1.5 1.5 0 0 0 1.493-1.35l.815-8.15h.3a.75.75 0 0 0 0-1.5H11v-.75A2.25 2.25 0 0 0 8.75 1h-1.5A2.25 2.25 0 0 0 5 3.25Zm2.25-.75a.75.75 0 0 0-.75.75V4h3v-.75a.75.75 0 0 0-.75-.75h-1.5ZM6.05 6a.75.75 0 0 1 .787.713l.275 5.5a.75.75 0 0 1-1.498.075l-.275-5.5A.75.75 0 0 1 6.05 6Zm3.9 0a.75.75 0 0 1 .712.787l-.275 5.5a.75.75 0 0 1-1.498-.075l.275-5.5a.75.75 0 0 1 .786-.711Z" clip-rule="evenodd" />
        </svg>
        <span class="text-[10px] font-semibold text-[#FFC107] leading-none whitespace-nowrap">{{ formattedRemainingTime }}</span>
      </div>

      <!-- Marker toggle buttons (bottom left) -->
      <div v-if="!isTrashed && availableMarkers.length > 0" class="absolute bottom-2 left-2 z-[10] flex gap-0.5">
        <button
          v-for="marker in availableMarkers"
          :key="marker.id"
          @click.stop="toggleMarker(row.output.media_id, marker)"
          :class="[
            'w-7 h-7 rounded-md flex items-center justify-center transition-all border-2',
            hasMarker(row.output.media_id, marker.id)
              ? 'bg-black/80'
              : 'bg-black/40 border-transparent hover:bg-black/60 text-white/50 hover:text-white'
          ]"
          :style="hasMarker(row.output.media_id, marker.id) ? { borderColor: marker.color, color: marker.color } : {}"
          :title="hasMarker(row.output.media_id, marker.id) ? `Remove ${marker.name}` : `Add ${marker.name}`"
        >
          <span class="w-4 h-4 flex items-center justify-center icon-container" v-html="sanitizeSvg(marker.icon_svg)" />
        </button>
      </div>

      <!-- Bottom right controls: info button -->
      <div class="absolute bottom-2 right-2 z-[10] flex gap-1 items-center">
        <!-- Info button (visible on hover) -->
        <button
          v-if="row.output.job_id"
          @click.stop="$emit('show-job-info', row.output.job_id)"
          class="w-6 h-6 flex items-center justify-center bg-black/60 backdrop-blur-md hover:bg-blue-500/80 rounded text-content-secondary hover:text-white transition-all opacity-0 group-hover:opacity-100"
          title="Show generation info"
        >
          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-4 h-4">
            <path fill-rule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7-4a1 1 0 11-2 0 1 1 0 012 0zM9 9a.75.75 0 000 1.5h.253a.25.25 0 01.244.304l-.459 2.066A1.75 1.75 0 0010.747 15H11a.75.75 0 000-1.5h-.253a.25.25 0 01-.244-.304l.459-2.066A1.75 1.75 0 009.253 9H9z" clip-rule="evenodd" />
          </svg>
        </button>
      </div>
    </template>

    <!-- Failed -->
    <template v-else-if="row.output.status === 'failed'">
      <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-6 h-6 text-red-500 mb-1">
        <path stroke-linecap="round" stroke-linejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126ZM12 15.75h.007v.008H12v-.008Z" />
      </svg>
      <div class="text-xs text-red-500 mb-1">Failed</div>
      <div v-if="row.output.error_summary" class="text-[10px] text-red-400 mb-1 px-2 text-center leading-tight line-clamp-3">{{ row.output.error_summary }}</div>
      <details v-if="row.output.error && row.output.error !== row.output.error_summary" class="w-full px-1 mb-1" @click.stop>
        <summary class="text-[10px] cursor-pointer text-red-400/70 hover:text-red-400 select-none text-center">Details</summary>
        <pre class="mt-1 text-[9px] whitespace-pre-wrap break-words font-mono bg-red-500/10 rounded p-1 max-h-20 overflow-y-auto custom-scrollbar text-red-400/80 select-text">{{ row.output.error }}</pre>
      </details>
      <button
        @click.stop="$emit('retry', row.id)"
        class="px-2 py-0.5 text-xs bg-surface-raised hover:bg-surface-hover text-content rounded transition-colors"
      >
        Retry
      </button>
    </template>

    <!-- Cancelled -->
    <template v-else-if="row.output.status === 'cancelled'">
      <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-6 h-6 text-red-500 mb-1">
        <path stroke-linecap="round" stroke-linejoin="round" d="M6 18 18 6M6 6l12 12" />
      </svg>
      <div class="text-xs text-red-500">Cancelled</div>
    </template>
  </div>
</template>

<script setup>
import { computed, onMounted, watch } from 'vue'
import { MediaImage } from '../media'
import { rewriteUrl } from '../../apiConfig'
import { getCurrentProfileId } from '../../composables/useProfile'
import { getCachedPin } from '../../composables/usePinLock'
import { useMarkers } from '../../composables/useMarkers'
import { useMediaState } from '../../composables/useMediaState'
import { useExpirationClock } from '../../composables/useExpirationClock'
import { getMediaType } from '../../utils/mediaTypes'
import { sanitizeSvg } from '../../utils/sanitizeHtml'

const props = defineProps({
  row: {
    type: Object,
    required: true
  },
  size: {
    type: Number,
    default: 240
  },
  // Fill the parent's width (square letterbox preserved via aspect-ratio) instead of a fixed pixel size
  fill: {
    type: Boolean,
    default: false
  },
  useThumbnail: {
    type: Boolean,
    default: true
  }
})

const emit = defineEmits(['view-image', 'retry', 'cancel', 'show-job-info'])
const { formatRemainingTime } = useExpirationClock()

const containerStyle = computed(() =>
  props.fill
    ? { width: '100%', aspectRatio: '1 / 1' }
    : { width: `${props.size}px`, height: `${props.size}px` }
)

const workspaceImageSrc = computed(() => {
  const src = props.row.output.workspace_url
  if (!src) return src

  const profileId = getCurrentProfileId()
  const pin = profileId ? getCachedPin(profileId) : null
  const url = new URL(src, 'http://stimma.local')

  if (profileId && !url.searchParams.has('profile')) {
    url.searchParams.set('profile', profileId)
  }
  if (pin && !url.searchParams.has('pin')) {
    url.searchParams.set('pin', pin)
  }

  const rewritten = `${url.pathname}${url.search}${url.hash}`
  return rewriteUrl(rewritten)
})

// Use shared markers composable
const {
  availableMarkers,
  init: initMarkers,
  loadMarkersForMedia,
  hasMarker,
  toggleMarker
} = useMarkers()

// Use shared media state composable for auto_delete_at and deleted_at
const {
  mediaState,
  init: initMediaState,
  loadStateForMedia
} = useMediaState()

// Initialize on mount
onMounted(async () => {
  initMediaState()
  await initMarkers()
  // Load markers and media state for this media if complete
  const isComplete = props.row.output.status === 'complete' || props.row.output.status === 'trashed'
  if (isComplete && props.row.output.media_id) {
    await Promise.all([
      loadMarkersForMedia([props.row.output.media_id]),
      loadStateForMedia([props.row.output.media_id])
    ])
  }
})

// Load markers and media state when media_id becomes available (e.g., after generation completes)
watch(
  () => props.row.output.media_id,
  async (newMediaId) => {
    const isComplete = props.row.output.status === 'complete' || props.row.output.status === 'trashed'
    if (newMediaId && isComplete) {
      await Promise.all([
        loadMarkersForMedia([newMediaId]),
        loadStateForMedia([newMediaId])
      ])
    }
  }
)

// Get current media state (reactive via shared composable)
const currentMediaState = computed(() => {
  if (!props.row.output.media_id) return null
  return mediaState.value[props.row.output.media_id] || null
})

// Computed for auto-delete time display (from media state or row data)
const formattedRemainingTime = computed(() => {
  // Prefer shared media state, fall back to row data
  const autoDeleteAt = currentMediaState.value
    ? currentMediaState.value.auto_delete_at
    : props.row.output.auto_delete_at
  if (!autoDeleteAt) return null
  const result = formatRemainingTime(autoDeleteAt)
  // Don't show if already expired
  if (result === '0m') return null
  return result
})

// Check if the image is trashed (from media state or row status)
const isTrashed = computed(() => {
  // If we have media state, check deleted_at
  if (currentMediaState.value) {
    return !!currentMediaState.value.deleted_at
  }
  // Fall back to row status
  return props.row.output.status === 'trashed'
})

// Get the media type for badge display
const outputMediaType = computed(() => {
  // Check if we have file_format from media state or row output
  const fileFormat = currentMediaState.value?.file_format || props.row.output.file_format
  if (!fileFormat) return null
  return getMediaType({ file_format: fileFormat })
})

// Force thumbnail mode for composite media (grids, sets) whose raw files are JSON, not images.
// Default to thumbnail until we know the type — safe because chat tiles top out around the
// 512px thumbnail size.
const ATOMIC_IMAGE_TYPES = new Set(['image'])
const effectiveThumbnail = computed(() => {
  if (props.useThumbnail) return true
  // Only use full-res file when we've confirmed it's a regular image
  if (outputMediaType.value && ATOMIC_IMAGE_TYPES.has(outputMediaType.value)) return false
  return true
})

function handleClick() {
  // Don't allow clicking on deleted or trashed images
  if (props.row.output.deleted || isTrashed.value) return
  // Allow clicking on complete images
  if ((props.row.output.status === 'complete' || props.row.output.status === 'trashed') && props.row.output.media_id) {
    emit('view-image', props.row.output.media_id)
  }
}
</script>
