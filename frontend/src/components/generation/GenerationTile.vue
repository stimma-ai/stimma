<template>
  <div
    class="relative bg-base rounded-lg overflow-hidden group"
    :class="[
      sizeClass,
      (status === 'completed' || status === 'failed') ? 'cursor-pointer' : ''
    ]"
  >
    <!-- Spinner while loading -->
    <div v-if="status === 'loading'" class="absolute inset-0 flex items-center justify-center">
      <div class="animate-spin rounded-full h-10 w-10 border-2 border-edge border-t-blue-500"></div>
      <!-- Cancel button on hover -->
      <button
        v-if="showCancel"
        @click.stop="$emit('cancel')"
        class="absolute top-1 right-1 p-1 bg-black/60 hover:bg-red-500/80 rounded opacity-0 group-hover:opacity-100 transition-opacity"
        title="Cancel"
      >
        <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor" class="w-4 h-4 text-white/70 hover:text-red-400">
          <path stroke-linecap="round" stroke-linejoin="round" d="M6 18 18 6M6 6l12 12" />
        </svg>
      </button>
      <!-- Info button on hover (for pending jobs) -->
      <button
        @click.stop="$emit('show-info')"
        class="absolute bottom-1 right-1 p-1 bg-black/60 hover:bg-black/80 rounded opacity-0 group-hover:opacity-100 transition-opacity"
        title="View details"
      >
        <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-4 h-4 text-white/70">
          <path stroke-linecap="round" stroke-linejoin="round" d="m11.25 11.25.041-.02a.75.75 0 0 1 1.063.852l-.708 2.836a.75.75 0 0 0 1.063.853l.041-.021M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Zm-9-3.75h.008v.008H12V8.25Z" />
        </svg>
      </button>
    </div>

    <!-- Completed image/video (or trashed - still viewable) -->
    <template v-else-if="(status === 'completed' || status === 'trashed') && mediaId">
      <!-- Video -->
      <video
        v-if="isVideo"
        :src="getMediaFileUrl(mediaId)"
        class="w-full h-full object-contain cursor-pointer hover:opacity-90 transition-opacity"
        @click="$emit('view-image')"
        @error="$emit('image-error')"
        draggable="true"
        @dragstart="onDragStart"
        @dragend="handleDragEnd"
        muted
        loop
        autoplay
        playsinline
      />
      <!-- Image -->
      <MediaImage
        v-else
        :media-id="mediaId"
        :thumbnail="false"
        :contain="true"
        container-class="w-full h-full cursor-pointer hover:opacity-90 transition-opacity"
        @click="$emit('view-image')"
        @error="$emit('image-error')"
      />
      <!-- Trashed badge (upper left) - red trash icon -->
      <div v-if="status === 'trashed'" class="absolute top-1 left-1 z-[5] bg-black/60 backdrop-blur-md rounded px-1 py-0.5 flex items-center gap-1">
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" fill="currentColor" class="w-3 h-3 text-red-500">
          <path fill-rule="evenodd" d="M5 3.25V4H2.75a.75.75 0 0 0 0 1.5h.3l.815 8.15A1.5 1.5 0 0 0 5.357 15h5.285a1.5 1.5 0 0 0 1.493-1.35l.815-8.15h.3a.75.75 0 0 0 0-1.5H11v-.75A2.25 2.25 0 0 0 8.75 1h-1.5A2.25 2.25 0 0 0 5 3.25Zm2.25-.75a.75.75 0 0 0-.75.75V4h3v-.75a.75.75 0 0 0-.75-.75h-1.5ZM6.05 6a.75.75 0 0 1 .787.713l.275 5.5a.75.75 0 0 1-1.498.075l-.275-5.5A.75.75 0 0 1 6.05 6Zm3.9 0a.75.75 0 0 1 .712.787l-.275 5.5a.75.75 0 0 1-1.498-.075l.275-5.5a.75.75 0 0 1 .786-.711Z" clip-rule="evenodd" />
        </svg>
      </div>
      <!-- Auto-delete time remaining badge (upper left, only if not trashed) -->
      <div v-else-if="autoDeleteAt && formattedRemainingTime" class="absolute top-1 left-1 z-[5] bg-black/60 backdrop-blur-md rounded px-1 py-0.5 flex items-center gap-1">
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" fill="currentColor" class="w-2.5 h-2.5 text-[#FFC107]">
          <path fill-rule="evenodd" d="M5 3.25V4H2.75a.75.75 0 0 0 0 1.5h.3l.815 8.15A1.5 1.5 0 0 0 5.357 15h5.285a1.5 1.5 0 0 0 1.493-1.35l.815-8.15h.3a.75.75 0 0 0 0-1.5H11v-.75A2.25 2.25 0 0 0 8.75 1h-1.5A2.25 2.25 0 0 0 5 3.25Zm2.25-.75a.75.75 0 0 0-.75.75V4h3v-.75a.75.75 0 0 0-.75-.75h-1.5ZM6.05 6a.75.75 0 0 1 .787.713l.275 5.5a.75.75 0 0 1-1.498.075l-.275-5.5A.75.75 0 0 1 6.05 6Zm3.9 0a.75.75 0 0 1 .712.787l-.275 5.5a.75.75 0 0 1-1.498-.075l.275-5.5a.75.75 0 0 1 .786-.711Z" clip-rule="evenodd" />
        </svg>
        <span class="text-[10px] font-semibold text-[#FFC107] leading-none whitespace-nowrap">{{ formattedRemainingTime }}</span>
      </div>
      <!-- Generation time badge (upper right) -->
      <div v-if="generationTime" class="absolute top-1 right-1 z-[5] bg-black/80 backdrop-blur-md rounded px-1.5 py-0.5 text-[10px] font-bold text-white shadow-[0_2px_8px_rgba(0,0,0,0.5)]">
        {{ generationTime }}s
      </div>
      <!-- Marker toggle buttons (bottom left) - hide for trashed items -->
      <div v-if="markers.length > 0 && status !== 'trashed'" class="absolute bottom-1 left-1 z-[10] flex gap-1">
        <button
          v-for="marker in markers"
          :key="marker.id"
          @click.stop="$emit('toggle-marker', marker)"
          :class="[
            'w-6 h-6 rounded flex items-center justify-center transition-all border-2',
            hasMarker(marker.id)
              ? 'bg-black/80'
              : 'bg-black/40 border-transparent hover:bg-black/60 text-white/50 hover:text-white'
          ]"
          :style="hasMarker(marker.id) ? { borderColor: marker.color, color: marker.color } : {}"
          :title="hasMarker(marker.id) ? `Remove ${marker.name}` : `Add ${marker.name}`"
        >
          <span class="w-4 h-4 flex items-center justify-center icon-container" v-html="marker.icon_svg" />
        </button>
      </div>
      <!-- Info button on hover -->
      <button
        @click.stop="$emit('show-info')"
        class="absolute bottom-1 right-1 p-1.5 bg-black/60 hover:bg-black/80 rounded opacity-0 group-hover:opacity-100 transition-opacity"
        title="View details"
      >
        <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-4 h-4 text-white/70">
          <path stroke-linecap="round" stroke-linejoin="round" d="m11.25 11.25.041-.02a.75.75 0 0 1 1.063.852l-.708 2.836a.75.75 0 0 0 1.063.853l.041-.021M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Zm-9-3.75h.008v.008H12V8.25Z" />
        </svg>
      </button>
    </template>

    <!-- Deleted state (truly gone, unrecoverable) - gray trash placeholder -->
    <div
      v-else-if="status === 'deleted'"
      class="absolute inset-0 flex items-center justify-center bg-surface"
    >
      <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1" stroke="currentColor" class="w-10 h-10 text-content-muted">
        <path stroke-linecap="round" stroke-linejoin="round" d="m14.74 9-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 0 1-2.244 2.077H8.084a2.25 2.25 0 0 1-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 0 0-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 0 1 3.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 0 0-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 0 0-7.5 0" />
      </svg>
    </div>

    <!-- Failed state -->
    <div
      v-else-if="status === 'failed' || status === 'cancelled'"
      class="absolute inset-0 flex items-center justify-center bg-red-500/10"
    >
      <div class="text-center">
        <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-8 h-8 text-red-500 mx-auto mb-1">
          <path stroke-linecap="round" stroke-linejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126ZM12 15.75h.007v.008H12v-.008Z" />
        </svg>
        <div class="text-xs text-red-500 mb-1">{{ status === 'cancelled' ? 'Cancelled' : 'Failed' }}</div>
        <button
          @click.stop="$emit('retry')"
          class="px-2 py-1 text-xs bg-surface-raised hover:bg-surface-hover text-content rounded transition-colors"
        >
          Retry
        </button>
      </div>
      <!-- Info button on hover -->
      <button
        @click.stop="$emit('show-error')"
        class="absolute bottom-1 right-1 p-1.5 bg-black/60 hover:bg-black/80 rounded opacity-0 group-hover:opacity-100 transition-opacity"
        title="View error details"
      >
        <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-4 h-4 text-white/70">
          <path stroke-linecap="round" stroke-linejoin="round" d="m11.25 11.25.041-.02a.75.75 0 0 1 1.063.852l-.708 2.836a.75.75 0 0 0 1.063.853l.041-.021M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Zm-9-3.75h.008v.008H12V8.25Z" />
        </svg>
      </button>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { MediaImage } from '../media'
import { useMediaApi } from '../../composables/useMediaApi'
import { formatRemainingTime } from '../../utils/timeFormat'
import { createDragPreview, handleDragEnd } from '../../composables/useDragPreview'

const { getMediaFileUrl, getThumbnailUrl } = useMediaApi()

const props = defineProps({
  status: {
    type: String,
    required: true // 'loading', 'completed', 'failed', 'cancelled', 'trashed', 'deleted'
  },
  mediaId: {
    type: Number,
    default: null
  },
  isVideo: {
    type: Boolean,
    default: false
  },
  autoDeleteAt: {
    type: String,
    default: null
  },
  generationTime: {
    type: Number,
    default: null
  },
  markers: {
    type: Array,
    default: () => []
  },
  activeMarkerIds: {
    type: Array,
    default: () => []
  },
  showCancel: {
    type: Boolean,
    default: true
  },
  size: {
    type: String,
    default: 'medium' // 'small', 'medium', 'large'
  }
})

defineEmits(['view-image', 'show-info', 'show-error', 'cancel', 'image-error', 'toggle-marker', 'retry'])

const formattedRemainingTime = computed(() => {
  if (!props.autoDeleteAt) return null
  const result = formatRemainingTime(props.autoDeleteAt)
  // Don't show if already expired
  if (result === '0m') return null
  return result
})

const sizeClass = computed(() => {
  switch (props.size) {
    case 'small':
      return 'aspect-square'
    case 'large':
      return 'aspect-square w-full max-w-xs'
    default:
      return 'aspect-square'
  }
})

function hasMarker(markerId) {
  return props.activeMarkerIds.includes(markerId)
}

function onDragStart(event) {
  if (props.mediaId) {
    // Create a smaller drag preview
    const thumbnailUrl = getThumbnailUrl(props.mediaId, 128)
    createDragPreview(event, thumbnailUrl, props.mediaId)
  }
}
</script>
