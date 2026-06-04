<template>
  <div class="flex-1 overflow-y-auto overflow-x-hidden p-4 media-grid-container" ref="container" @scroll="handleScroll">
    <div class="grid grid-cols-[repeat(auto-fill,minmax(200px,1fr))] gap-4">
      <div
        v-for="(item, index) in items"
        :key="item.id"
        class="media-item relative aspect-square bg-surface-raised rounded-lg overflow-hidden cursor-pointer"
        @click="emit('item-click', index)"
        @mouseenter="handleMouseEnter($event, item)"
        @mouseleave="handleMouseLeave($event, item)"
      >
        <AppImage
          v-if="!isVideo(item)"
          :src="getThumbnailUrl(item.file_hash)"
          :alt="item.vlm_caption || 'Media item'"
          :contain="item.file_format === 'stimmalayout'"
          container-class="w-full h-full"
        />
        <video
          v-else
          :ref="el => setVideoRef(item.id, el)"
          :poster="getThumbnailUrl(item.file_hash)"
          class="w-full h-full object-cover bg-surface"
          muted
          loop
          playsinline
        >
          <source :src="getMediaFileUrl(item.file_hash)" type="video/mp4">
        </video>
        <!-- Media type badge -->
        <div class="absolute top-2 right-2 z-[5] bg-black/60 backdrop-blur-md rounded-md p-1 flex items-center justify-center">
          <!-- Video icon (Heroicons play) -->
          <svg v-if="isVideo(item)" class="w-4 h-4 flex-shrink-0 text-green-500" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" d="M5.25 5.653c0-.856.917-1.398 1.667-.986l11.54 6.348a1.125 1.125 0 010 1.971l-11.54 6.347a1.125 1.125 0 01-1.667-.985V5.653z" />
          </svg>
          <!-- Image icon (Heroicons photo) -->
          <svg v-else class="w-4 h-4 flex-shrink-0 text-blue-500" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" d="M2.25 15.75l5.159-5.159a2.25 2.25 0 013.182 0l5.159 5.159m-1.5-1.5l1.409-1.409a2.25 2.25 0 013.182 0l2.909 2.909m-18 3.75h16.5a1.5 1.5 0 001.5-1.5V6a1.5 1.5 0 00-1.5-1.5H3.75A1.5 1.5 0 002.25 6v12a1.5 1.5 0 001.5 1.5zm10.5-11.25h.008v.008h-.008V8.25zm.375 0a.375.375 0 11-.75 0 .375.375 0 01.75 0z" />
          </svg>
        </div>
        <!-- Similarity score badge -->
        <div v-if="item.similarity_score !== null && item.similarity_score !== undefined" class="absolute top-2 left-2 z-[5] bg-black/80 backdrop-blur-md border border-edge rounded px-2 py-1 text-xs font-bold text-content shadow-[0_2px_8px_rgba(0,0,0,0.5)]">
          {{ formatSimilarity(item.similarity_score) }}
        </div>
        <!-- Marker badges -->
        <div v-if="item.markers && item.markers.length > 0" class="absolute bottom-2 right-2 z-[5] flex gap-1">
          <div
            v-for="marker in item.markers"
            :key="marker.id"
            class="w-6 h-6 bg-black/60 backdrop-blur-md rounded flex items-center justify-center"
            :title="marker.name"
          >
            <span class="w-4 h-4 flex items-center justify-center icon-container" :style="{ color: marker.color }" v-html="marker.icon_svg" />
          </div>
        </div>
        <div class="media-overlay absolute bottom-0 left-0 right-0 bg-gradient-to-t from-black/80 to-transparent p-2 opacity-0">
          <div v-if="item.has_clip_embedding" class="mt-2 flex justify-center">
            <button
              @click.stop="emit('item-find-similar', item.id)"
              class="bg-green-500/30 border border-green-500 text-content py-2 px-3 rounded text-xs font-semibold cursor-pointer flex items-center gap-1 transition-all hover:bg-green-500/50 hover:-translate-y-0.5"
              title="Find visually similar images"
            >
              <MagnifyingGlassCircleIcon class="w-4 h-4" />
              Find Similar
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- Loading indicator -->
    <div v-if="loading" class="flex justify-center p-8">
      <div class="spinner w-8 h-8 border-[3px] border-edge border-t-white rounded-full"></div>
    </div>

    <!-- Empty state -->
    <div v-if="!loading && items.length === 0" class="text-center py-16 px-8 text-content-muted">
      <p>No media items found</p>
      <p class="text-sm mt-2">Try adjusting your filters</p>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { MagnifyingGlassCircleIcon } from '@heroicons/vue/24/solid'
import { AppImage } from './media'
import { useMediaApi } from '../composables/useMediaApi'

const props = defineProps({
  items: Array,
  loading: Boolean
})

const emit = defineEmits(['load-more', 'item-click', 'item-find-similar'])

const { getThumbnailUrl, getMediaFileUrl } = useMediaApi()
const container = ref(null)
const videoRefs = ref(new Map())

function handleScroll() {
  if (!container.value) return

  // Don't trigger if already loading (prevents infinite loop)
  if (props.loading) return

  const { scrollTop, scrollHeight, clientHeight } = container.value
  const scrollPercentage = (scrollTop + clientHeight) / scrollHeight

  // Load more when 80% scrolled
  if (scrollPercentage > 0.8) {
    emit('load-more')
  }
}

function formatResolution(item) {
  return `${item.width}×${item.height}`
}

function formatDuration(seconds) {
  const mins = Math.floor(seconds / 60)
  const secs = Math.floor(seconds % 60)
  return `${mins}:${secs.toString().padStart(2, '0')}`
}

function isVideo(item) {
  const videoFormats = ['mp4', 'webm', 'mov', 'avi', 'mkv', 'ogg']
  return videoFormats.includes(item.file_format.toLowerCase())
}

function formatSimilarity(score) {
  return `${(score * 100).toFixed(1)}%`
}

function setVideoRef(itemId, el) {
  if (el) {
    videoRefs.value.set(itemId, el)
  } else {
    videoRefs.value.delete(itemId)
  }
}

function handleMouseEnter(event, item) {
  if (isVideo(item)) {
    const video = videoRefs.value.get(item.id)
    if (video) {
      video.currentTime = 0
      video.play().catch(err => {
        console.warn('Video autoplay failed:', err)
      })
    }
  }
}

function handleMouseLeave(event, item) {
  if (isVideo(item)) {
    const video = videoRefs.value.get(item.id)
    if (video) {
      video.pause()
      video.currentTime = 0
    }
  }
}
</script>

<style scoped>
.media-item {
  transition: transform 0.2s, box-shadow 0.2s;
}

.media-item:hover {
  transform: scale(1.05);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.5);
  z-index: 10;
}

.media-overlay {
  transition: opacity 0.2s;
}

.media-item:hover .media-overlay {
  opacity: 1;
}

.spinner {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

/* Scrollbar styling */
.media-grid-container::-webkit-scrollbar {
  -webkit-appearance: none;
  width: 24px;
}

.media-grid-container::-webkit-scrollbar-track {
  background: var(--color-surface-overlay);
  border-left: 1px solid var(--color-border);
}

.media-grid-container::-webkit-scrollbar-thumb {
  background: var(--color-scrollbar-thumb);
  border-radius: 12px;
  border: 4px solid var(--color-surface-overlay);
}

.media-grid-container::-webkit-scrollbar-thumb:hover {
  background: var(--color-scrollbar-thumb-hover);
}
</style>
