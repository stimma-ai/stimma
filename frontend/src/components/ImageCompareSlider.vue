<template>
  <!-- A before/after wipe: the right image is the full base layer, the left
       image is clipped to the slider. Both fill the same box, so the divider
       reveals the same pixel location on either side. Corner labels stay pinned
       while the images zoom and pan beneath them. -->
  <div
    ref="root"
    class="absolute inset-0 overflow-hidden select-none bg-matte rounded-media"
    :class="zoomScale > 1 ? 'cursor-grab' : 'cursor-ew-resize'"
    tabindex="0"
    @wheel.prevent="handleWheel"
    @mousedown="handleMouseDown"
    @dblclick="handleDoubleClick"
    @keydown="handleKeyDown"
  >
    <!-- Zoom/pan layer: everything geometric moves together. -->
    <div class="absolute inset-0" :style="transformStyle">
      <!-- Right image (full base layer) -->
      <div class="absolute inset-0 flex items-center justify-center">
        <img
          :src="rightSrc"
          class="w-full h-full object-contain"
          style="image-orientation: from-image"
          draggable="false"
        />
      </div>

      <!-- Left image (overlay clipped by the slider) -->
      <div
        class="absolute inset-0 flex items-center justify-center"
        :style="{ clipPath: `inset(0 ${100 - sliderPosition}% 0 0)` }"
      >
        <img
          :src="leftSrc"
          class="w-full h-full object-contain"
          style="image-orientation: from-image"
          draggable="false"
        />
      </div>

      <!-- Slider handle (inside the transform so it tracks zoom/pan; the circle
           counter-scales so it keeps a constant on-screen size) -->
      <div
        class="absolute top-0 bottom-0 w-1 cursor-ew-resize z-10"
        :style="{ left: `calc(${sliderPosition}% - 2px)` }"
      >
        <div class="absolute inset-0 bg-white/80 shadow-lg"></div>
        <div
          class="absolute top-1/2 left-1/2 w-10 h-10 rounded-full bg-white shadow-xl flex items-center justify-center"
          :style="{ transform: `translate(-50%, -50%) scale(${1 / zoomScale})` }"
        >
          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" class="w-icon-nav h-icon-nav text-gray-600">
            <path fill-rule="evenodd" d="M15.97 2.47a.75.75 0 0 1 1.06 0l4.5 4.5a.75.75 0 0 1 0 1.06l-4.5 4.5a.75.75 0 1 1-1.06-1.06l3.22-3.22H7.5a.75.75 0 0 1 0-1.5h11.69l-3.22-3.22a.75.75 0 0 1 0-1.06Zm-7.94 9a.75.75 0 0 1 0 1.06l-3.22 3.22H16.5a.75.75 0 0 1 0 1.5H4.81l3.22 3.22a.75.75 0 1 1-1.06 1.06l-4.5-4.5a.75.75 0 0 1 0-1.06l4.5-4.5a.75.75 0 0 1 1.06 0Z" clip-rule="evenodd" />
          </svg>
        </div>
      </div>
    </div>

    <!-- Corner labels: pinned to the box, not the zoom/pan layer. -->
    <div
      v-if="leftLabel"
      class="absolute top-3 left-3 px-2 py-1 rounded bg-black/60 text-white text-xs font-medium pointer-events-none z-20"
    >
      {{ leftLabel }}
    </div>
    <div
      v-if="rightLabel"
      class="absolute top-3 right-3 px-2 py-1 rounded bg-black/60 text-white text-xs font-medium pointer-events-none z-20"
    >
      {{ rightLabel }}
    </div>
  </div>
</template>

<script setup>
/**
 * A standalone before/after comparison slider. Given two image URLs sized to the
 * same box, it wipes between them with a draggable divider, matching the
 * slideshow's CompareMode interaction (drag / arrows to move the divider, wheel
 * to zoom, drag to pan when zoomed, double-click to toggle zoom, Esc to close).
 *
 * Unlike CompareMode it carries no media-info panels and no swap/close chrome —
 * the host owns those. It only compares two sources and reports Escape.
 */
import { ref, computed, onMounted, onUnmounted, nextTick } from 'vue'

const props = defineProps({
  leftSrc: { type: String, required: true },
  rightSrc: { type: String, required: true },
  leftLabel: { type: String, default: '' },
  rightLabel: { type: String, default: '' },
  initialSliderPosition: { type: Number, default: 50 },
})

const emit = defineEmits(['close', 'update:slider-position'])

const root = ref(null)

const sliderPosition = ref(props.initialSliderPosition)
const isDraggingSlider = ref(false)
const isPanning = ref(false)

const zoomScale = ref(1)
const panX = ref(0)
const panY = ref(0)
const panStart = ref({ x: 0, y: 0 })
const lastPan = ref({ x: 0, y: 0 })

const MIN_ZOOM = 1
const MAX_ZOOM = 10

const transformStyle = computed(() => ({
  transform: `translate(${panX.value}px, ${panY.value}px) scale(${zoomScale.value})`,
  transformOrigin: 'center center',
}))

function resetZoom() {
  zoomScale.value = 1
  panX.value = 0
  panY.value = 0
}

function clampPan() {
  if (zoomScale.value <= 1) {
    panX.value = 0
    panY.value = 0
    return
  }
  const el = root.value
  if (!el) return
  const rect = el.getBoundingClientRect()
  const maxPanX = (rect.width * (zoomScale.value - 1)) / 2
  const maxPanY = (rect.height * (zoomScale.value - 1)) / 2
  panX.value = Math.max(-maxPanX, Math.min(maxPanX, panX.value))
  panY.value = Math.max(-maxPanY, Math.min(maxPanY, panY.value))
}

function handleWheel(event) {
  const delta = event.deltaY > 0 ? -0.1 : 0.1
  const newScale = Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, zoomScale.value + delta * zoomScale.value))
  if (newScale === zoomScale.value) return

  const rect = root.value.getBoundingClientRect()
  const cursorX = event.clientX - rect.left - rect.width / 2
  const cursorY = event.clientY - rect.top - rect.height / 2
  const scaleFactor = newScale / zoomScale.value
  panX.value = cursorX - (cursorX - panX.value) * scaleFactor
  panY.value = cursorY - (cursorY - panY.value) * scaleFactor
  zoomScale.value = newScale
  clampPan()
}

function handleDoubleClick(event) {
  if (event.target.closest('.cursor-ew-resize')) return
  if (zoomScale.value > 1) {
    resetZoom()
    return
  }
  const rect = root.value.getBoundingClientRect()
  const clickX = event.clientX - rect.left - rect.width / 2
  const clickY = event.clientY - rect.top - rect.height / 2
  zoomScale.value = 2
  panX.value = -clickX
  panY.value = -clickY
  clampPan()
}

function handleMouseDown(e) {
  e.preventDefault()
  if (e.target.closest('.cursor-ew-resize')) {
    isDraggingSlider.value = true
    updateSliderFromEvent(e)
  } else if (zoomScale.value > 1) {
    isPanning.value = true
    panStart.value = { x: e.clientX, y: e.clientY }
    lastPan.value = { x: panX.value, y: panY.value }
  } else {
    // At 1x, clicking anywhere moves the divider.
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
    panX.value = lastPan.value.x + (e.clientX - panStart.value.x)
    panY.value = lastPan.value.y + (e.clientY - panStart.value.y)
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
  const rect = root.value?.getBoundingClientRect()
  if (!rect) return
  // Undo the zoom/pan transform so the divider follows the cursor at any zoom.
  const centerX = rect.width / 2
  const mouseX = e.clientX - rect.left
  const transformedX = (mouseX - centerX - panX.value) / zoomScale.value + centerX
  const percentage = (transformedX / rect.width) * 100
  sliderPosition.value = Math.max(0, Math.min(100, percentage))
  emit('update:slider-position', sliderPosition.value)
}

function handleKeyDown(e) {
  switch (e.key) {
    case 'Escape':
      e.stopPropagation()
      emit('close')
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

onMounted(() => {
  nextTick(() => root.value?.focus())
})

onUnmounted(() => {
  document.removeEventListener('mousemove', handleDocumentMouseMove)
  document.removeEventListener('mouseup', handleDocumentMouseUp)
})
</script>
