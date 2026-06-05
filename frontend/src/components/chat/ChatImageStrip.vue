<template>
  <div class="chat-image-strip flex bg-base border-t border-edge">
    <!-- Scrollable strip (horizontal) -->
    <div
      ref="stripContainer"
      class="flex-1 overflow-x-auto overflow-y-hidden p-1.5 flex items-center"
      @scroll="handleScroll"
    >
      <!-- Images (horizontal row) -->
      <div class="flex gap-1.5">
        <template v-for="mediaId in mediaIds" :key="mediaId">
          <!-- Trashed media - show trash icon placeholder -->
          <div
            v-if="isTrashed(mediaId)"
            class="strip-thumbnail flex-shrink-0 rounded bg-surface flex items-center justify-center"
          >
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-5 h-5 text-[#FFC107]">
              <path fill-rule="evenodd" d="M8.75 1A2.75 2.75 0 006 3.75v.443c-.795.077-1.584.176-2.365.298a.75.75 0 10.23 1.482l.149-.022.841 10.518A2.75 2.75 0 007.596 19h4.807a2.75 2.75 0 002.742-2.53l.841-10.52.149.023a.75.75 0 00.23-1.482A41.03 41.03 0 0014 4.193V3.75A2.75 2.75 0 0011.25 1h-2.5zM10 4c.84 0 1.673.025 2.5.075V3.75c0-.69-.56-1.25-1.25-1.25h-2.5c-.69 0-1.25.56-1.25 1.25v.325C8.327 4.025 9.16 4 10 4zM8.58 7.72a.75.75 0 00-1.5.06l.3 7.5a.75.75 0 101.5-.06l-.3-7.5zm4.34.06a.75.75 0 10-1.5-.06l-.3 7.5a.75.75 0 101.5.06l.3-7.5z" clip-rule="evenodd" />
            </svg>
          </div>
          <!-- Active media - show image thumbnail -->
          <MediaImage
            v-else
            :media-id="mediaId"
            :thumbnail="true"
            :thumbnail-size="96"
            container-class="strip-thumbnail flex-shrink-0 rounded cursor-pointer hover:ring-2 hover:ring-blue-500 transition-all"
            @click="openSlideshow(mediaId)"
            @dragstart="onDragStart($event, mediaId)"
          />
        </template>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, watch, nextTick, onMounted, computed } from 'vue'
import { MediaImage } from '../media'
import { useMediaState } from '../../composables/useMediaState'

const props = defineProps({
  mediaIds: {
    type: Array,
    required: true
  }
})

// Track trashed state for media items
const { mediaState, init: initMediaState, loadStateForMedia } = useMediaState()

// Check if a media item is trashed
function isTrashed(mediaId) {
  const state = mediaState.value[mediaId]
  return state?.deleted_at != null
}

const emit = defineEmits(['open-slideshow', 'drag-media'])

const stripContainer = ref(null)
const userHasScrolled = ref(false)
const isAtBottom = ref(true)

function handleScroll() {
  if (!stripContainer.value) return

  const { scrollLeft, scrollWidth, clientWidth } = stripContainer.value
  const threshold = 50

  isAtBottom.value = scrollLeft + clientWidth >= scrollWidth - threshold

  if (!isAtBottom.value) {
    userHasScrolled.value = true
  }
}

function scrollToEnd() {
  if (stripContainer.value) {
    stripContainer.value.scrollLeft = stripContainer.value.scrollWidth
  }
}

// Watch for new images and auto-scroll if user hasn't scrolled up
watch(() => props.mediaIds.length, async (newLen, oldLen) => {
  if (newLen > oldLen) {
    await nextTick()
    if (!userHasScrolled.value || isAtBottom.value) {
      scrollToEnd()
      userHasScrolled.value = false
    }
  }
})

function openSlideshow(mediaId) {
  emit('open-slideshow', mediaId)
}

function onDragStart(event, mediaId) {
  // MediaImage already sets the drag data, but we still emit the event
  emit('drag-media', mediaId)
}

onMounted(async () => {
  initMediaState()
  // Load state for all media items
  if (props.mediaIds.length > 0) {
    await loadStateForMedia(props.mediaIds)
  }
  nextTick(() => {
    scrollToEnd()
  })
})

// Load state for new media items when they're added
watch(() => props.mediaIds, async (newIds, oldIds) => {
  const oldSet = new Set(oldIds || [])
  const newMediaIds = newIds.filter(id => !oldSet.has(id))
  if (newMediaIds.length > 0) {
    await loadStateForMedia(newMediaIds)
  }
}, { deep: true })
</script>

<style scoped>
.chat-image-strip {
  height: 76px; /* 66px tile + padding */
}

.strip-thumbnail {
  width: 66px;
  height: 66px;
  transition: transform 0.15s ease;
}

.strip-thumbnail:hover {
  transform: scale(1.05);
}

/* Custom scrollbar (horizontal) */
.chat-image-strip ::-webkit-scrollbar {
  -webkit-appearance: none;
  height: 4px;
}

.chat-image-strip ::-webkit-scrollbar-track {
  background: transparent;
}

.chat-image-strip ::-webkit-scrollbar-thumb {
  background: var(--color-scrollbar-thumb);
  border-radius: 2px;
}

.chat-image-strip ::-webkit-scrollbar-thumb:hover {
  background: var(--color-scrollbar-thumb-hover);
}
</style>
