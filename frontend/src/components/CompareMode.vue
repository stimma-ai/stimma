<template>
  <Teleport to="body">
    <div
      ref="overlay"
      class="fixed inset-0 bg-black flex z-[9999]"
      @keydown="handleKeyDown"
      tabindex="0"
    >
      <!-- Left Info Panel -->
      <SlideshowInfoPanel
        v-if="showInfoPanel && leftItem"
        :current-item="leftItem"
        title="Left Image"
        class="!order-none w-[320px] max-w-[25vw] !border-l-0 border-r border-edge-subtle"
        @delete="handleAction('delete', leftItem)"
        @restore="handleAction('restore', leftItem)"
        @permanent-delete="handleAction('permanent-delete', leftItem)"
        @find-similar="handleAction('find-similar', leftItem)"
        @download="handleAction('download', leftItem)"
        @download-original="handleAction('download-original', leftItem)"
        @add-to-board="handleAction('add-to-board', leftItem)"
        @filter-by-tag="(tagId) => handleAction('filter-by-tag', leftItem, tagId)"
        @filter-by-keyword="(keyword) => handleAction('filter-by-keyword', leftItem, keyword)"
        @navigate-to-board="(boardId) => handleAction('navigate-to-board', leftItem, boardId)"
        @navigate-to-source-media="(mediaId) => handleAction('navigate-to-source-media', leftItem, mediaId)"
        @compare-with-source="(sourceId) => handleAction('compare-with-source', leftItem, sourceId)"
        @view-in-tool="(step) => handleAction('view-in-tool', leftItem, step)"
        @jump-to-chat="(chatId) => handleAction('jump-to-chat', leftItem, chatId)"
        @toggle-marker="(markerId) => handleAction('toggle-marker', leftItem, markerId)"
        @tags-saved="handleAction('tags-saved', leftItem)"
        @menu-sent="close"
      />

      <!-- Main comparison area -->
      <div
        ref="comparisonArea"
        class="flex-1 relative overflow-hidden"
      >
        <!-- Loading state -->
        <div v-if="loading" class="absolute inset-0 flex items-center justify-center">
          <div class="text-content-tertiary">Loading images...</div>
        </div>

        <!-- Error state -->
        <div v-else-if="error" class="absolute inset-0 flex items-center justify-center">
          <div class="text-red-500">{{ error }}</div>
        </div>

        <!-- Comparison view -->
        <div
          v-else-if="leftItem && rightItem"
          ref="mediaContainerRef"
          class="w-full h-full relative select-none overflow-hidden"
          :class="zoomScale > 1 ? 'cursor-grab' : ''"
          @wheel.prevent="handleWheel"
          @mousedown="handleMouseDown"
          @dblclick="handleDoubleClick"
        >
          <!-- Transformed container for images and slider -->
          <div
            class="absolute inset-0"
            :style="transformStyle"
          >
            <!-- Right image (base layer - full visibility) -->
            <div class="absolute inset-0 flex items-center justify-center bg-black">
              <img
                :src="rightImageUrl"
                :alt="rightItem?.vlm_caption || 'Right image'"
                class="w-full h-full object-contain"
                style="image-orientation: from-image"
                draggable="false"
                @load="handleRightImageLoad"
              />
            </div>

            <!-- Left image (overlay with clip-path) -->
            <div
              class="absolute inset-0 flex items-center justify-center bg-black"
              :style="{ clipPath: `inset(0 ${100 - sliderPosition}% 0 0)` }"
            >
              <img
                :src="leftImageUrl"
                :alt="leftItem?.vlm_caption || 'Left image'"
                class="w-full h-full object-contain"
                style="image-orientation: from-image"
                draggable="false"
                @load="handleLeftImageLoad"
              />
            </div>

            <!-- Slider handle (inside transformed container so it moves with zoom/pan) -->
            <div
              class="absolute top-0 bottom-0 w-1 cursor-ew-resize z-10"
              :style="{ left: `calc(${sliderPosition}% - 2px)` }"
            >
              <!-- Vertical line -->
              <div class="absolute inset-0 bg-white/80 shadow-lg"></div>

              <!-- Handle circle -->
              <div
                class="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-10 h-10 rounded-full bg-white shadow-xl flex items-center justify-center cursor-ew-resize"
                :style="{ transform: `translate(-50%, -50%) scale(${1/zoomScale})` }"
              >
                <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" class="w-5 h-5 text-gray-600">
                  <path fill-rule="evenodd" d="M15.97 2.47a.75.75 0 0 1 1.06 0l4.5 4.5a.75.75 0 0 1 0 1.06l-4.5 4.5a.75.75 0 1 1-1.06-1.06l3.22-3.22H7.5a.75.75 0 0 1 0-1.5h11.69l-3.22-3.22a.75.75 0 0 1 0-1.06Zm-7.94 9a.75.75 0 0 1 0 1.06l-3.22 3.22H16.5a.75.75 0 0 1 0 1.5H4.81l3.22 3.22a.75.75 0 1 1-1.06 1.06l-4.5-4.5a.75.75 0 0 1 0-1.06l4.5-4.5a.75.75 0 0 1 1.06 0Z" clip-rule="evenodd" />
                </svg>
              </div>
            </div>
          </div>
        </div>

        <!-- Toolbar (top right of comparison area) -->
        <div class="absolute top-4 right-4 flex items-center gap-2 z-20">
          <!-- Swap button -->
          <button
            @click="swapImages"
            class="w-10 h-10 rounded-full bg-black/70 text-white flex items-center justify-center hover:bg-black/50 transition-colors"
            title="Swap images (S)"
          >
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-5 h-5">
              <path fill-rule="evenodd" d="M13.2 2.24a.75.75 0 0 0 .04 1.06l2.1 1.95H6.75a.75.75 0 0 0 0 1.5h8.59l-2.1 1.95a.75.75 0 1 0 1.02 1.1l3.5-3.25a.75.75 0 0 0 0-1.1l-3.5-3.25a.75.75 0 0 0-1.06.04Zm-6.4 8a.75.75 0 0 0-1.06-.04l-3.5 3.25a.75.75 0 0 0 0 1.1l3.5 3.25a.75.75 0 1 0 1.02-1.1l-2.1-1.95h8.59a.75.75 0 0 0 0-1.5H4.66l2.1-1.95a.75.75 0 0 0 .04-1.06Z" clip-rule="evenodd" />
            </svg>
          </button>

          <!-- Info panel toggle -->
          <button
            @click="showInfoPanel = !showInfoPanel"
            :class="[
              'w-10 h-10 rounded-full flex items-center justify-center transition-colors',
              showInfoPanel ? 'bg-blue-500 text-white' : 'bg-black/70 text-white hover:bg-black/50'
            ]"
            title="Toggle info panels (I)"
          >
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-5 h-5">
              <path fill-rule="evenodd" d="M18 10a8 8 0 1 1-16 0 8 8 0 0 1 16 0Zm-7-4a1 1 0 1 1-2 0 1 1 0 0 1 2 0ZM9 9a.75.75 0 0 0 0 1.5h.253a.25.25 0 0 1 .244.304l-.459 2.066A1.75 1.75 0 0 0 10.747 15H11a.75.75 0 0 0 0-1.5h-.253a.25.25 0 0 1-.244-.304l.459-2.066A1.75 1.75 0 0 0 9.253 9H9Z" clip-rule="evenodd" />
            </svg>
          </button>

          <!-- Close button -->
          <button
            @click="close"
            class="w-10 h-10 rounded-full bg-black/70 text-white flex items-center justify-center hover:bg-black/50 transition-colors"
            title="Close (Escape)"
          >
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-5 h-5">
              <path d="M6.28 5.22a.75.75 0 0 0-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 1 0 1.06 1.06L10 11.06l3.72 3.72a.75.75 0 1 0 1.06-1.06L11.06 10l3.72-3.72a.75.75 0 0 0-1.06-1.06L10 8.94 6.28 5.22Z" />
            </svg>
          </button>
        </div>
      </div>

      <!-- Right Info Panel -->
      <SlideshowInfoPanel
        v-if="showInfoPanel && rightItem"
        :current-item="rightItem"
        title="Right Image"
        class="w-[320px] max-w-[25vw]"
        @delete="handleAction('delete', rightItem)"
        @restore="handleAction('restore', rightItem)"
        @permanent-delete="handleAction('permanent-delete', rightItem)"
        @find-similar="handleAction('find-similar', rightItem)"
        @download="handleAction('download', rightItem)"
        @download-original="handleAction('download-original', rightItem)"
        @add-to-board="handleAction('add-to-board', rightItem)"
        @filter-by-tag="(tagId) => handleAction('filter-by-tag', rightItem, tagId)"
        @filter-by-keyword="(keyword) => handleAction('filter-by-keyword', rightItem, keyword)"
        @navigate-to-board="(boardId) => handleAction('navigate-to-board', rightItem, boardId)"
        @navigate-to-source-media="(mediaId) => handleAction('navigate-to-source-media', rightItem, mediaId)"
        @compare-with-source="(sourceId) => handleAction('compare-with-source', rightItem, sourceId)"
        @view-in-tool="(step) => handleAction('view-in-tool', rightItem, step)"
        @jump-to-chat="(chatId) => handleAction('jump-to-chat', rightItem, chatId)"
        @toggle-marker="(markerId) => handleAction('toggle-marker', rightItem, markerId)"
        @tags-saved="handleAction('tags-saved', rightItem)"
        @menu-sent="close"
      />
    </div>
  </Teleport>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, watch, nextTick } from 'vue'
import { useMediaApi } from '../composables/useMediaApi'
import SlideshowInfoPanel from './SlideshowInfoPanel.vue'

const props = defineProps({
  leftItem: {
    type: Object,
    default: null
  },
  rightItem: {
    type: Object,
    default: null
  },
  loading: {
    type: Boolean,
    default: false
  },
  error: {
    type: String,
    default: null
  },
  initialSliderPosition: {
    type: Number,
    default: 50
  }
})

const emit = defineEmits([
  'close',
  'swap',
  'update:slider-position',
  'action'  // Emit actions with { action, item, payload }
])

const { getMediaFileUrl } = useMediaApi()

// Refs
const overlay = ref(null)
const comparisonArea = ref(null)
const mediaContainerRef = ref(null)

// State
const showInfoPanel = ref(true)
const sliderPosition = ref(props.initialSliderPosition)
const isDraggingSlider = ref(false)
const isPanning = ref(false)
const leftImageLoaded = ref(false)
const rightImageLoaded = ref(false)

// Zoom and pan state
const zoomScale = ref(1)
const panX = ref(0)
const panY = ref(0)
const panStart = ref({ x: 0, y: 0 })
const lastPan = ref({ x: 0, y: 0 })

const MIN_ZOOM = 1
const MAX_ZOOM = 10

// Transform style for zoom/pan
const transformStyle = computed(() => ({
  transform: `translate(${panX.value}px, ${panY.value}px) scale(${zoomScale.value})`,
  transformOrigin: 'center center'
}))

// Compute image URLs
const leftImageUrl = computed(() => {
  if (!props.leftItem) return ''
  return getMediaFileUrl(props.leftItem.file_hash)
})

const rightImageUrl = computed(() => {
  if (!props.rightItem) return ''
  return getMediaFileUrl(props.rightItem.file_hash)
})

// Image load handlers
function handleLeftImageLoad() {
  leftImageLoaded.value = true
}

function handleRightImageLoad() {
  rightImageLoaded.value = true
}

// Reset zoom
function resetZoom() {
  zoomScale.value = 1
  panX.value = 0
  panY.value = 0
}

// Clamp pan to keep image in view
function clampPan() {
  if (zoomScale.value <= 1) {
    panX.value = 0
    panY.value = 0
    return
  }

  const container = mediaContainerRef.value
  if (!container) return

  const rect = container.getBoundingClientRect()
  const maxPanX = (rect.width * (zoomScale.value - 1)) / 2
  const maxPanY = (rect.height * (zoomScale.value - 1)) / 2

  panX.value = Math.max(-maxPanX, Math.min(maxPanX, panX.value))
  panY.value = Math.max(-maxPanY, Math.min(maxPanY, panY.value))
}

// Zoom with mousewheel
function handleWheel(event) {
  const delta = event.deltaY > 0 ? -0.1 : 0.1
  const newScale = Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, zoomScale.value + delta * zoomScale.value))

  if (newScale !== zoomScale.value) {
    const container = mediaContainerRef.value
    const rect = container.getBoundingClientRect()
    const cursorX = event.clientX - rect.left - rect.width / 2
    const cursorY = event.clientY - rect.top - rect.height / 2

    const scaleFactor = newScale / zoomScale.value
    panX.value = cursorX - (cursorX - panX.value) * scaleFactor
    panY.value = cursorY - (cursorY - panY.value) * scaleFactor

    zoomScale.value = newScale
    clampPan()
  }
}

// Double click to toggle zoom
function handleDoubleClick(event) {
  // Don't zoom if clicking on slider
  if (event.target.closest('.cursor-ew-resize')) return

  if (zoomScale.value > 1) {
    resetZoom()
  } else {
    // Zoom in to 2x centered on click point
    const container = mediaContainerRef.value
    if (container) {
      const rect = container.getBoundingClientRect()
      const clickX = event.clientX - rect.left - rect.width / 2
      const clickY = event.clientY - rect.top - rect.height / 2

      zoomScale.value = 2
      panX.value = -clickX
      panY.value = -clickY
      clampPan()
    }
  }
}

// Mouse handling
function handleMouseDown(e) {
  // Prevent text selection during drag
  e.preventDefault()

  // Check if clicking on slider handle
  if (e.target.closest('.cursor-ew-resize')) {
    isDraggingSlider.value = true
    updateSliderFromEvent(e)
  } else if (zoomScale.value > 1) {
    // Start panning when zoomed
    isPanning.value = true
    panStart.value = { x: e.clientX, y: e.clientY }
    lastPan.value = { x: panX.value, y: panY.value }
  } else {
    // At 1x zoom, clicking anywhere moves slider
    isDraggingSlider.value = true
    updateSliderFromEvent(e)
  }

  document.addEventListener('mousemove', handleDocumentMouseMove)
  document.addEventListener('mouseup', handleDocumentMouseUp)
}

function handleDocumentMouseMove(e) {
  if (isDraggingSlider.value) {
    updateSliderFromEvent(e)
  } else if (isPanning.value) {
    const dx = e.clientX - panStart.value.x
    const dy = e.clientY - panStart.value.y
    panX.value = lastPan.value.x + dx
    panY.value = lastPan.value.y + dy
    clampPan()
  }
}

function handleDocumentMouseUp() {
  isDraggingSlider.value = false
  isPanning.value = false
  document.removeEventListener('mousemove', handleDocumentMouseMove)
  document.removeEventListener('mouseup', handleDocumentMouseUp)
}

function updateSliderFromEvent(e) {
  const rect = comparisonArea.value?.getBoundingClientRect()
  if (rect) {
    // Convert mouse position to slider position accounting for zoom/pan
    const containerCenterX = rect.width / 2
    const mouseX = e.clientX - rect.left

    // Convert from screen space to transformed space
    const transformedX = (mouseX - containerCenterX - panX.value) / zoomScale.value + containerCenterX
    const percentage = (transformedX / rect.width) * 100

    sliderPosition.value = Math.max(0, Math.min(100, percentage))
    emit('update:slider-position', sliderPosition.value)
  }
}

// Action handler - emit to parent and close
function handleAction(action, item, payload = null) {
  emit('action', { action, item, payload })
  close()
}

// Actions
function close() {
  emit('close')
}

function swapImages() {
  emit('swap')
}

// Keyboard handling
function handleKeyDown(e) {
  switch (e.key) {
    case 'Escape':
      e.stopPropagation() // Prevent bubbling to slideshow
      close()
      break
    case 's':
    case 'S':
      swapImages()
      break
    case 'i':
    case 'I':
      showInfoPanel.value = !showInfoPanel.value
      break
    case 'ArrowLeft':
      sliderPosition.value = Math.max(0, sliderPosition.value - 5)
      emit('update:slider-position', sliderPosition.value)
      break
    case 'ArrowRight':
      sliderPosition.value = Math.min(100, sliderPosition.value + 5)
      emit('update:slider-position', sliderPosition.value)
      break
    case '0':
      resetZoom()
      break
  }
}

// Focus overlay on mount for keyboard events
onMounted(() => {
  nextTick(() => {
    overlay.value?.focus()
  })
})

// Cleanup on unmount
onUnmounted(() => {
  document.removeEventListener('mousemove', handleDocumentMouseMove)
  document.removeEventListener('mouseup', handleDocumentMouseUp)
})

// Watch for external slider position changes
watch(() => props.initialSliderPosition, (newVal) => {
  sliderPosition.value = newVal
})
</script>
