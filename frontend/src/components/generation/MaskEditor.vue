<template>
  <div :class="modalMode ? 'flex flex-col h-full' : 'space-y-2 mb-6 overflow-x-hidden'" data-drop-zone="mask-editor">
    <!-- Label row (hidden in modal mode) -->
    <div v-if="!modalMode">
      <label class="text-xs font-medium text-content-muted uppercase tracking-wide">Source Image</label>
    </div>

    <!-- Toolbar (always visible, disabled when no image) -->
    <div :class="['flex items-center gap-2 h-8 flex-shrink-0', modalMode ? 'mb-4' : '']">
      <!-- Undo/Redo buttons -->
      <div class="flex h-full bg-surface rounded">
        <button
          @click="undo"
          :disabled="!hasImage || undoStack.length === 0"
          :class="[
            'h-full px-2 rounded-l transition-colors flex items-center',
            hasImage && undoStack.length > 0
              ? 'text-content-muted hover:text-content-secondary'
              : 'text-content-muted cursor-not-allowed'
          ]"
          title="Undo"
        >
          <PaintToolIcon name="undo" />
        </button>
        <button
          @click="redo"
          :disabled="!hasImage || redoStack.length === 0"
          :class="[
            'h-full px-2 rounded-r transition-colors flex items-center',
            hasImage && redoStack.length > 0
              ? 'text-content-muted hover:text-content-secondary'
              : 'text-content-muted cursor-not-allowed'
          ]"
          title="Redo"
        >
          <PaintToolIcon name="redo" />
        </button>
      </div>

      <!-- Divider -->
      <div class="w-px h-full bg-surface-raised"></div>

      <!-- Paint/Erase toggle -->
      <div class="flex h-full bg-surface rounded">
        <button
          @click="paintMode = 'paint'"
          :disabled="!hasImage"
          :class="[
            'h-full px-2 rounded-l transition-colors flex items-center',
            !hasImage ? 'text-content-muted cursor-not-allowed' :
            paintMode === 'paint' ? 'bg-blue-500/20 text-blue-500' : 'text-content-muted hover:text-content-secondary'
          ]"
          title="Paint mask (areas to inpaint)"
        >
          <PaintToolIcon name="brush" />
        </button>
        <button
          @click="paintMode = 'erase'"
          :disabled="!hasImage"
          :class="[
            'h-full px-2 rounded-r transition-colors flex items-center',
            !hasImage ? 'text-content-muted cursor-not-allowed' :
            paintMode === 'erase' ? 'bg-blue-500/20 text-blue-500' : 'text-content-muted hover:text-content-secondary'
          ]"
          title="Erase mask"
        >
          <PaintToolIcon name="eraser" />
        </button>
      </div>

      <!-- Brush size slider -->
      <div class="flex items-center gap-2 max-w-48 h-full">
        <span :class="['text-xs tabular-nums w-10', hasImage ? 'text-content-muted' : 'text-content-muted']">{{ brushSize }}px</span>
        <input v-no-autocorrect
          type="range"
          v-model.number="brushSize"
          min="5"
          max="250"
          step="1"
          :disabled="!hasImage"
          :class="['flex-1 slider', hasImage ? 'cursor-pointer' : 'cursor-not-allowed opacity-50']"
        />
      </div>

      <!-- Flexible spacer -->
      <div class="flex-1"></div>

      <!-- Contract mask button (separate) -->
      <button
        @click="contractMask(expandContractPercent)"
        :disabled="!hasImage || !hasMask()"
        :class="[
          'h-full px-2 rounded bg-surface transition-colors flex items-center',
          hasImage && hasMask() ? 'text-content-muted hover:text-content-secondary' : 'text-content-muted cursor-not-allowed'
        ]"
        :title="`Contract mask by ${expandContractPercent}%`"
      >
        <!-- Marquee with minus -->
        <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
          <rect x="4" y="4" width="16" height="16" rx="1" stroke-dasharray="3 2" />
          <path stroke-linecap="round" d="M9 12h6" />
        </svg>
      </button>

      <!-- Expand mask button (separate) -->
      <button
        @click="expandMask(expandContractPercent)"
        :disabled="!hasImage || !hasMask()"
        :class="[
          'h-full px-2 rounded bg-surface transition-colors flex items-center',
          hasImage && hasMask() ? 'text-content-muted hover:text-content-secondary' : 'text-content-muted cursor-not-allowed'
        ]"
        :title="`Expand mask by ${expandContractPercent}%`"
      >
        <!-- Marquee with plus -->
        <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
          <rect x="4" y="4" width="16" height="16" rx="1" stroke-dasharray="3 2" />
          <path stroke-linecap="round" d="M12 9v6M9 12h6" />
        </svg>
      </button>

      <!-- Percentage dropdown -->
      <select
        v-model.number="expandContractPercent"
        :disabled="!hasImage || !hasMask()"
        :class="[
          'h-full bg-surface border border-surface-raised rounded px-2 text-xs focus:outline-none focus:border-blue-500/50',
          hasImage && hasMask() ? 'text-content-secondary' : 'text-content-muted cursor-not-allowed opacity-50'
        ]"
      >
        <option :value="5">5%</option>
        <option :value="10">10%</option>
        <option :value="15">15%</option>
        <option :value="20">20%</option>
        <option :value="25">25%</option>
        <option :value="30">30%</option>
        <option :value="40">40%</option>
        <option :value="50">50%</option>
        <option :value="75">75%</option>
        <option :value="100">100%</option>
      </select>

      <!-- Divider -->
      <div class="w-px h-full bg-surface-raised"></div>

      <!-- Invert mask button -->
      <button
        @click="invertMask"
        :disabled="!hasImage"
        :class="[
          'h-full px-3 rounded bg-surface transition-colors text-xs',
          hasImage ? 'text-content-muted hover:text-content-secondary' : 'text-content-muted cursor-not-allowed'
        ]"
        title="Invert mask"
      >
        Invert
      </button>

      <!-- Clear mask button -->
      <button
        @click="clearMask"
        :disabled="!hasImage"
        :class="[
          'h-full px-3 rounded bg-surface transition-colors text-xs',
          hasImage ? 'text-content-muted hover:text-content-secondary' : 'text-content-muted cursor-not-allowed'
        ]"
        title="Clear mask"
      >
        Clear
      </button>

      <!-- Divider and expand button (only in inline mode) -->
      <template v-if="!modalMode">
        <div class="w-px h-full bg-surface-raised"></div>

        <!-- Expand to modal button -->
        <button
          @click="openExpandedModal"
          :disabled="!hasImage"
          :class="[
            'h-full px-2 rounded bg-surface transition-colors',
            hasImage ? 'text-content-muted hover:text-content-secondary' : 'text-content-muted cursor-not-allowed'
          ]"
          title="Edit in large view"
        >
          <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" d="M3.75 3.75v4.5m0-4.5h4.5m-4.5 0L9 9M3.75 20.25v-4.5m0 4.5h4.5m-4.5 0L9 15M20.25 3.75h-4.5m4.5 0v4.5m0-4.5L15 9m5.25 11.25h-4.5m4.5 0v-4.5m0 4.5L15 15" />
          </svg>
        </button>
      </template>
    </div>

    <!-- Canvas container OR dropzone -->
    <div :class="modalMode ? 'flex justify-center items-center flex-1 min-h-0' : 'flex justify-center'">
      <div v-if="hasImage" class="relative flex-shrink" :class="modalMode ? 'h-full w-full flex items-center justify-center' : ''">
        <div
          ref="canvasContainer"
          class="relative bg-surface-overlay border border-surface-raised rounded-lg overflow-hidden cursor-crosshair flex-shrink"
          :class="[
            { 'border-blue-500 border-2': isDragging },
            modalMode ? 'max-w-full max-h-full' : ''
          ]"
          :style="modalMode
            ? { aspectRatio: aspectRatio, height: '100%', maxHeight: '100%' }
            : { width: `${computedWidth}px`, height: `${editorHeight}px`, minWidth: '100px', minHeight: '100px' }"
          @mousedown="startPainting"
          @mousemove="paint"
          @mouseup="stopPainting"
          @mouseleave="handleMouseLeave"
          @dragover.prevent.stop="onDragOver"
          @dragleave.stop="onDragLeave"
          @drop.prevent.stop="onDropReplace"
        >
          <!-- Source image -->
          <img
            ref="sourceImg"
            :src="sourceImageUrl"
            class="absolute inset-0 w-full h-full object-contain pointer-events-none"
            @load="onImageLoad"
          />
          <!-- Mask canvas (overlay) - shows red where masked -->
          <canvas
            ref="maskCanvas"
            class="absolute inset-0 w-full h-full object-contain pointer-events-none"
            :style="{ opacity: 0.5 }"
          />
          <!-- Brush preview -->
          <div
            v-if="showBrushPreview"
            class="absolute rounded-full border-2 pointer-events-none"
            :class="paintMode === 'paint' ? 'border-red-400/70' : 'border-green-400/70'"
            :style="{
              width: `${brushPreviewSize}px`,
              height: `${brushPreviewSize}px`,
              left: `${brushPreviewX - brushPreviewSize / 2}px`,
              top: `${brushPreviewY - brushPreviewSize / 2}px`
            }"
          />
        </div>
        <!-- Resize handle (only in inline mode) -->
        <div
          v-if="!modalMode"
          class="absolute bottom-0 right-0 w-6 h-6 cursor-se-resize flex items-center justify-center group"
          @mousedown.stop="startResize"
        >
          <svg class="w-3 h-3 text-content-muted group-hover:text-content-muted transition-colors" viewBox="0 0 10 10" fill="currentColor">
            <path d="M9 1v8H1" stroke="currentColor" stroke-width="1.5" fill="none" stroke-linecap="round"/>
          </svg>
        </div>
      </div>

      <!-- Empty state well (when no image) - simple square -->
      <div
        v-else
        @click="openFilePicker"
        @dragover.prevent.stop="onDragOver"
        @dragleave.stop="onDragLeave"
        @drop.prevent.stop="onDrop"
        :class="[
          'w-64 h-64 bg-surface-overlay border rounded-lg cursor-pointer flex flex-col items-center justify-center gap-2 transition-colors',
          isDragging ? 'border-blue-500 border-2' : 'border-surface-raised hover:border-edge'
        ]"
      >
        <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-8 h-8 text-content-muted">
          <path stroke-linecap="round" stroke-linejoin="round" d="M2.25 15.75l5.159-5.159a2.25 2.25 0 013.182 0l5.159 5.159m-1.5-1.5l1.409-1.409a2.25 2.25 0 013.182 0l2.909 2.909m-18 3.75h16.5a1.5 1.5 0 001.5-1.5V6a1.5 1.5 0 00-1.5-1.5H3.75A1.5 1.5 0 002.25 6v12a1.5 1.5 0 001.5 1.5zm10.5-11.25h.008v.008h-.008V8.25zm.375 0a.375.375 0 11-.75 0 .375.375 0 01.75 0z" />
        </svg>
        <span class="text-sm text-content-muted">{{ isDragging ? 'Drop image here' : 'Click or drop image' }}</span>
      </div>
    </div>

    <!-- Loading indicator -->
    <div v-if="isUploading" class="flex items-center gap-2 text-sm text-content-muted">
      <div class="w-4 h-4 border-2 border-edge border-t-blue-500 rounded-full animate-spin"></div>
      <span>Uploading...</span>
    </div>

    <!-- Hidden file input -->
    <input v-no-autocorrect
      ref="fileInput"
      type="file"
      accept="image/jpeg,image/png,image/webp"
      class="hidden"
      @change="handleFileSelect"
    >
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, onMounted, nextTick } from 'vue'
import axios from 'axios'
import { getCurrentProfileId } from '../../composables/useProfile'
import { getCachedPin } from '../../composables/usePinLock'
import { useMediaApi } from '../../composables/useMediaApi'
import { getApiBase } from '../../apiConfig'
import { makeProfileKey } from '../../utils/storageKeys'
import type { MaskFormat } from '../../composables/useToolSchemaFeatures'
import PaintToolIcon from './PaintToolIcon.vue'

const API_BASE = '/api'
const { getMediaItem, getMediaFileUrl } = useMediaApi()

interface ImageInfo {
  path: string
  filename?: string
  hash?: string
  mediaId?: number
  width?: number
  height?: number
}

interface Props {
  image?: ImageInfo | null
  modelValue?: string | null  // Mask data URL
  modalMode?: boolean  // When true, expands to fill container, hides expand button
  maskFormat?: MaskFormat  // Output format: 'alpha' (default), 'white-black', or 'black-white'
}

const props = withDefaults(defineProps<Props>(), {
  modalMode: false,
  maskFormat: 'alpha'
})

const emit = defineEmits<{
  (e: 'update:modelValue', value: string | null): void
  (e: 'update:image', value: ImageInfo | null): void
  (e: 'expand'): void
}>()

// Refs
const canvasContainer = ref<HTMLDivElement | null>(null)
const maskCanvas = ref<HTMLCanvasElement | null>(null)
const sourceImg = ref<HTMLImageElement | null>(null)
const fileInput = ref<HTMLInputElement | null>(null)

// State
const paintMode = ref<'paint' | 'erase'>('paint')
// Profile-scoped storage keys for mask editor settings
function getBrushSizeKey() {
  return makeProfileKey('mask_editor', 'brush_size')
}
function getExpandContractKey() {
  return makeProfileKey('mask_editor', 'expand_percent')
}
function getEditorHeightKey() {
  return makeProfileKey('mask_editor', 'editor_height')
}
const brushSize = ref(parseInt(localStorage.getItem(getBrushSizeKey()) || '80', 10))
const isPainting = ref(false)
const imageWidth = ref(512)
const imageHeight = ref(512)
const showBrushPreview = ref(false)
const brushPreviewX = ref(0)
const brushPreviewY = ref(0)
const lastX = ref(0)
const lastY = ref(0)
const isDragging = ref(false)
const isUploading = ref(false)
const canvasReady = ref(false)
const pendingMaskToLoad = ref<string | null>(null)
const undoStack = ref<ImageData[]>([])
const redoStack = ref<ImageData[]>([])
const MAX_UNDO_STATES = 50
const expandContractPercent = ref(parseInt(localStorage.getItem(getExpandContractKey()) || '15', 10))
const editorHeight = ref(parseInt(localStorage.getItem(getEditorHeightKey()) || '400', 10))
const isResizing = ref(false)
const resizeStartY = ref(0)
const resizeStartHeight = ref(0)
const MIN_EDITOR_HEIGHT = 200
const MAX_EDITOR_HEIGHT = 1200

// Computed
const hasImage = computed(() => !!props.image?.path)
const aspectRatio = computed(() => `${imageWidth.value} / ${imageHeight.value}`)

// Computed width for non-modal mode (avoids CSS aspect-ratio browser compatibility issues)
// Cap at screen width to prevent horizontal overflow on landscape images
const computedWidth = computed(() => {
  if (imageHeight.value === 0) return editorHeight.value
  const width = Math.round(editorHeight.value * (imageWidth.value / imageHeight.value))
  const maxWidth = typeof window !== 'undefined' ? window.innerWidth - 80 : 1200
  return Math.max(100, Math.min(width, maxWidth))
})

const sourceImageUrl = computed(() => {
  if (!props.image) return ''
  // If image has a hash property, it's from the media library
  if (props.image.hash) {
    return getMediaFileUrl(props.image.hash)
  }
  // If it's an absolute file path, use the file endpoint
  if (props.image.path?.startsWith('/')) {
    const profileId = getCurrentProfileId()
    const pin = getCachedPin(profileId)
    let url = `${getApiBase()}/generate/reference-file?path=${encodeURIComponent(props.image.path)}&profile=${encodeURIComponent(profileId)}`
    if (pin) url += `&pin=${encodeURIComponent(pin)}`
    return url
  }
  // Otherwise assume path is a hash
  return getMediaFileUrl(props.image.path)
})

// Scale brush size based on canvas display size vs actual size
// Note: We use imageWidth (reactive) instead of maskCanvas.value.width (not reactive)
// to ensure the computed recomputes when the canvas dimensions change
const brushPreviewSize = computed(() => {
  if (!canvasContainer.value || imageWidth.value === 0) return brushSize.value
  const displayWidth = canvasContainer.value.clientWidth
  return (brushSize.value * displayWidth) / imageWidth.value
})

// Persist brush size to localStorage
watch(brushSize, (newSize) => {
  localStorage.setItem(getBrushSizeKey(), String(newSize))
})

watch(expandContractPercent, (newPercent) => {
  localStorage.setItem(getExpandContractKey(), String(newPercent))
})

watch(editorHeight, (newHeight) => {
  localStorage.setItem(getEditorHeightKey(), String(newHeight))
})

// Watch for modelValue changes and redraw mask (needed for restoring from localStorage on reload)
watch(() => props.modelValue, (newMask) => {
  if (newMask) {
    if (canvasReady.value) {
      loadMaskToCanvas(newMask)
    } else {
      pendingMaskToLoad.value = newMask
    }
  }
})

// Watch for image changes
// Only clear mask when ACTUALLY changing from one image to another (not on initial load)
watch(() => props.image?.path, (newPath, oldPath) => {
  canvasReady.value = false

  // Clear undo/redo stacks when image changes
  undoStack.value = []
  redoStack.value = []

  // Don't clear mask when going from null to a path (that's initial load, not a change)
  // Only clear when changing from one valid path to another valid path
  if (oldPath && newPath && oldPath !== newPath) {
    pendingMaskToLoad.value = null
    if (maskCanvas.value) {
      const ctx = maskCanvas.value.getContext('2d')
      if (ctx) {
        ctx.clearRect(0, 0, maskCanvas.value.width, maskCanvas.value.height)
      }
    }
    emit('update:modelValue', null)
  }
})

function loadMaskToCanvas(maskDataUrl: string) {
  if (!maskCanvas.value) return
  const canvas = maskCanvas.value
  const ctx = canvas.getContext('2d')
  if (!ctx) return

  const img = new Image()
  img.onload = () => {
    // Convert from output format back to display format
    const tempCanvas = document.createElement('canvas')
    tempCanvas.width = canvas.width
    tempCanvas.height = canvas.height
    const tempCtx = tempCanvas.getContext('2d')
    if (!tempCtx) return

    tempCtx.drawImage(img, 0, 0)
    const imageData = tempCtx.getImageData(0, 0, canvas.width, canvas.height)
    const data = imageData.data
    const format = props.maskFormat || 'alpha'

    console.log('[MaskEditor] loadMaskToCanvas format:', format)

    // Clear existing mask first
    ctx.clearRect(0, 0, canvas.width, canvas.height)

    // Convert from output format to display format (red pixels)
    for (let i = 0; i < data.length; i += 4) {
      const r = data[i]
      const g = data[i + 1]
      const b = data[i + 2]
      const a = data[i + 3]

      // Determine if this pixel is an inpaint area based on format
      let isInpaintArea = false
      if (format === 'alpha') {
        isInpaintArea = a < 128
      } else if (format === 'white-black') {
        isInpaintArea = r > 128 && g > 128 && b > 128
      } else if (format === 'black-white') {
        isInpaintArea = r < 128 && g < 128 && b < 128
      }

      if (isInpaintArea) {
        ctx.fillStyle = 'rgba(255, 0, 0, 1)'
        const pixelIndex = i / 4
        const x = pixelIndex % canvas.width
        const y = Math.floor(pixelIndex / canvas.width)
        ctx.fillRect(x, y, 1, 1)
      }
    }
  }
  img.src = maskDataUrl
}

function onImageLoad() {
  if (!sourceImg.value) return
  imageWidth.value = sourceImg.value.naturalWidth
  imageHeight.value = sourceImg.value.naturalHeight
  initCanvas()
}

function initCanvas() {
  if (!maskCanvas.value) return

  const canvas = maskCanvas.value
  canvas.width = imageWidth.value
  canvas.height = imageHeight.value
  const ctx = canvas.getContext('2d')
  if (!ctx) return

  ctx.clearRect(0, 0, canvas.width, canvas.height)
  canvasReady.value = true

  // Check for pending mask first (from watcher), then props.modelValue
  const maskToLoad = pendingMaskToLoad.value || props.modelValue
  if (maskToLoad) {
    loadMaskToCanvas(maskToLoad)
    pendingMaskToLoad.value = null
  }
}

function getCanvasCoords(event: MouseEvent): { x: number; y: number } | null {
  if (!maskCanvas.value || !canvasContainer.value) return null

  const rect = canvasContainer.value.getBoundingClientRect()
  const scaleX = maskCanvas.value.width / rect.width
  const scaleY = maskCanvas.value.height / rect.height

  return {
    x: (event.clientX - rect.left) * scaleX,
    y: (event.clientY - rect.top) * scaleY
  }
}

function saveToUndoStack() {
  if (!maskCanvas.value) return
  const ctx = maskCanvas.value.getContext('2d')
  if (!ctx) return

  const imageData = ctx.getImageData(0, 0, maskCanvas.value.width, maskCanvas.value.height)
  undoStack.value.push(imageData)

  // Limit stack size
  if (undoStack.value.length > MAX_UNDO_STATES) {
    undoStack.value.shift()
  }

  // Clear redo stack on new action
  redoStack.value = []
}

function undo() {
  if (undoStack.value.length === 0 || !maskCanvas.value) return
  const ctx = maskCanvas.value.getContext('2d')
  if (!ctx) return

  // Save current state to redo stack
  const currentState = ctx.getImageData(0, 0, maskCanvas.value.width, maskCanvas.value.height)
  redoStack.value.push(currentState)

  // Restore previous state
  const previousState = undoStack.value.pop()!
  ctx.putImageData(previousState, 0, 0)
  emitMask()
}

function redo() {
  if (redoStack.value.length === 0 || !maskCanvas.value) return
  const ctx = maskCanvas.value.getContext('2d')
  if (!ctx) return

  // Save current state to undo stack
  const currentState = ctx.getImageData(0, 0, maskCanvas.value.width, maskCanvas.value.height)
  undoStack.value.push(currentState)

  // Restore next state
  const nextState = redoStack.value.pop()!
  ctx.putImageData(nextState, 0, 0)
  emitMask()
}

function startPainting(event: MouseEvent) {
  const coords = getCanvasCoords(event)
  if (!coords) return

  // Save state before painting
  saveToUndoStack()

  isPainting.value = true
  lastX.value = coords.x
  lastY.value = coords.y

  // Draw a single point
  drawCircle(coords.x, coords.y)
}

function paint(event: MouseEvent) {
  // Update brush preview position
  if (canvasContainer.value) {
    const rect = canvasContainer.value.getBoundingClientRect()
    brushPreviewX.value = event.clientX - rect.left
    brushPreviewY.value = event.clientY - rect.top
    showBrushPreview.value = true
  }

  if (!isPainting.value) return

  const coords = getCanvasCoords(event)
  if (!coords) return

  // Draw line from last position to current
  drawLine(lastX.value, lastY.value, coords.x, coords.y)
  lastX.value = coords.x
  lastY.value = coords.y
}

function stopPainting() {
  if (isPainting.value) {
    isPainting.value = false
    // Only emit mask when stroke is complete
    emitMask()
  }
}

function handleMouseLeave() {
  stopPainting()
  showBrushPreview.value = false
}

function drawCircle(x: number, y: number) {
  if (!maskCanvas.value) return
  const ctx = maskCanvas.value.getContext('2d')
  if (!ctx) return

  if (paintMode.value === 'paint') {
    ctx.globalCompositeOperation = 'source-over'
    ctx.fillStyle = 'rgba(255, 0, 0, 1)'
  } else {
    ctx.globalCompositeOperation = 'destination-out'
    ctx.fillStyle = 'rgba(0, 0, 0, 1)'
  }

  ctx.beginPath()
  ctx.arc(x, y, brushSize.value / 2, 0, Math.PI * 2)
  ctx.fill()

  ctx.globalCompositeOperation = 'source-over'
}

function drawLine(x1: number, y1: number, x2: number, y2: number) {
  if (!maskCanvas.value) return
  const ctx = maskCanvas.value.getContext('2d')
  if (!ctx) return

  if (paintMode.value === 'paint') {
    ctx.globalCompositeOperation = 'source-over'
    ctx.strokeStyle = 'rgba(255, 0, 0, 1)'
  } else {
    ctx.globalCompositeOperation = 'destination-out'
    ctx.strokeStyle = 'rgba(0, 0, 0, 1)'
  }

  ctx.lineWidth = brushSize.value
  ctx.lineCap = 'round'
  ctx.lineJoin = 'round'

  ctx.beginPath()
  ctx.moveTo(x1, y1)
  ctx.lineTo(x2, y2)
  ctx.stroke()

  ctx.globalCompositeOperation = 'source-over'
}

function clearMask() {
  if (!maskCanvas.value) return
  const ctx = maskCanvas.value.getContext('2d')
  if (!ctx) return

  // Save to undo stack before clearing
  saveToUndoStack()

  ctx.clearRect(0, 0, maskCanvas.value.width, maskCanvas.value.height)
  emitMask()
}

function emitMask() {
  if (!maskCanvas.value) {
    emit('update:modelValue', null)
    return
  }

  const canvas = maskCanvas.value
  const ctx = canvas.getContext('2d')
  if (!ctx) return

  // Check if mask is empty (all transparent)
  const imageData = ctx.getImageData(0, 0, canvas.width, canvas.height)
  const data = imageData.data
  let hasPaint = false
  for (let i = 0; i < data.length; i += 4) {
    if (data[i + 3] > 0) {
      hasPaint = true
      break
    }
  }

  if (!hasPaint) {
    emit('update:modelValue', null)
    return
  }

  // Create output based on maskFormat prop
  const outputCanvas = document.createElement('canvas')
  outputCanvas.width = canvas.width
  outputCanvas.height = canvas.height
  const outCtx = outputCanvas.getContext('2d')
  if (!outCtx) return

  const outputData = outCtx.createImageData(canvas.width, canvas.height)
  const format = props.maskFormat || 'alpha'
  console.log('[MaskEditor] emitMask format:', format)

  for (let i = 0; i < data.length; i += 4) {
    const r = data[i]
    const a = data[i + 3]
    const isInpaintArea = r > 128 && a > 128

    if (format === 'alpha') {
      // Alpha format: inpaint=transparent, preserve=opaque black
      if (isInpaintArea) {
        outputData.data[i] = 255
        outputData.data[i + 1] = 255
        outputData.data[i + 2] = 255
        outputData.data[i + 3] = 0
      } else {
        outputData.data[i] = 0
        outputData.data[i + 1] = 0
        outputData.data[i + 2] = 0
        outputData.data[i + 3] = 255
      }
    } else if (format === 'white-black') {
      // White-black format: inpaint=white opaque, preserve=black opaque
      if (isInpaintArea) {
        outputData.data[i] = 255
        outputData.data[i + 1] = 255
        outputData.data[i + 2] = 255
        outputData.data[i + 3] = 255
      } else {
        outputData.data[i] = 0
        outputData.data[i + 1] = 0
        outputData.data[i + 2] = 0
        outputData.data[i + 3] = 255
      }
    } else if (format === 'black-white') {
      // Black-white format: inpaint=black opaque, preserve=white opaque
      if (isInpaintArea) {
        outputData.data[i] = 0
        outputData.data[i + 1] = 0
        outputData.data[i + 2] = 0
        outputData.data[i + 3] = 255
      } else {
        outputData.data[i] = 255
        outputData.data[i + 1] = 255
        outputData.data[i + 2] = 255
        outputData.data[i + 3] = 255
      }
    }
  }

  outCtx.putImageData(outputData, 0, 0)

  const dataUrl = outputCanvas.toDataURL('image/png')
  emit('update:modelValue', dataUrl)
}

// Image upload handling
function openFilePicker() {
  fileInput.value?.click()
}

function onDragOver() {
  isDragging.value = true
}

function onDragLeave() {
  isDragging.value = false
}

async function onDrop(event: DragEvent) {
  isDragging.value = false
  console.log('[MaskEditor] onDrop called', event.dataTransfer?.types)

  // Check for media ID from generation queue drag
  const mediaId = event.dataTransfer?.getData('application/x-media-id')
  console.log('[MaskEditor] mediaId from drag:', mediaId)
  if (mediaId) {
    await addFromMediaId(parseInt(mediaId))
    return
  }

  // Fall back to file handling
  const files = event.dataTransfer?.files
  if (!files || files.length === 0) return

  const file = Array.from(files).find(f => f.type.startsWith('image/'))
  if (!file) return

  await uploadFile(file)
}

async function onDropReplace(event: DragEvent) {
  isDragging.value = false
  console.log('[MaskEditor] onDropReplace called', event.dataTransfer?.types)

  // Check for media ID from generation queue drag
  const mediaId = event.dataTransfer?.getData('application/x-media-id')
  console.log('[MaskEditor] mediaId from drag:', mediaId)
  if (mediaId) {
    // Clear the mask first
    emit('update:modelValue', null)
    pendingMaskToLoad.value = null
    await addFromMediaId(parseInt(mediaId))
    return
  }

  // Fall back to file handling
  const files = event.dataTransfer?.files
  if (!files || files.length === 0) return

  const file = Array.from(files).find(f => f.type.startsWith('image/'))
  if (!file) return

  // Clear the mask first
  emit('update:modelValue', null)
  pendingMaskToLoad.value = null

  await uploadFile(file)
}

async function addFromMediaId(mediaId: number) {
  isUploading.value = true
  try {
    const mediaItem = await getMediaItem(mediaId)

    // Copy the media to reference directory (same as "send to tool")
    let path = mediaItem.file_path
    let filename = mediaItem.file_path?.split('/').pop() || `image.${mediaItem.file_format}`

    try {
      const response = await axios.post(
        `${API_BASE}/generate/copy-to-reference?source_path=${encodeURIComponent(mediaItem.file_path)}`
      )
      path = response.data.path
      filename = response.data.filename
    } catch (err) {
      console.error('Error copying media to reference:', err)
    }

    const newImage: ImageInfo = {
      path,
      filename,
      hash: mediaItem.file_hash,
      mediaId: mediaItem.id,
      width: mediaItem.width,
      height: mediaItem.height,
    }

    emit('update:image', newImage)
  } catch (error) {
    console.error('Failed to add image from media library:', error)
  } finally {
    isUploading.value = false
  }
}

async function uploadFile(file: File) {
  isUploading.value = true
  try {
    const formData = new FormData()
    formData.append('file', file)

    const response = await axios.post(`${API_BASE}/generate/upload-reference`, formData, {
      headers: {
        'Content-Type': 'multipart/form-data'
      }
    })

    const newImage: ImageInfo = {
      path: response.data.path,
      filename: response.data.filename,
      hash: response.data.file_hash,
      mediaId: response.data.media_id,
      width: response.data.width,
      height: response.data.height,
    }

    emit('update:image', newImage)
  } catch (error) {
    console.error('Failed to upload image:', error)
  } finally {
    isUploading.value = false
  }
}

async function handleFileSelect(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]

  if (!file) return

  input.value = ''
  await uploadFile(file)
}

function removeImage() {
  emit('update:image', null)
  emit('update:modelValue', null)
}

// Resize handling
function startResize(event: MouseEvent) {
  event.preventDefault()
  isResizing.value = true
  resizeStartY.value = event.clientY
  resizeStartHeight.value = editorHeight.value

  document.addEventListener('mousemove', handleResize)
  document.addEventListener('mouseup', stopResize)
}

function handleResize(event: MouseEvent) {
  if (!isResizing.value) return

  const deltaY = event.clientY - resizeStartY.value
  const newHeight = Math.min(MAX_EDITOR_HEIGHT, Math.max(MIN_EDITOR_HEIGHT, resizeStartHeight.value + deltaY))
  editorHeight.value = newHeight
}

function stopResize() {
  isResizing.value = false
  document.removeEventListener('mousemove', handleResize)
  document.removeEventListener('mouseup', stopResize)
}

function openExpandedModal() {
  emit('expand')
}

// Initialize canvas when mounted
onMounted(() => {
  nextTick(() => {
    if (sourceImg.value && sourceImg.value.complete && sourceImg.value.naturalWidth > 0) {
      onImageLoad()
    }
  })
})

/**
 * Apply a mask from an external source (e.g., SAM3 segmentation).
 * @param dataUrl - The mask as a data URL (RGBA PNG where alpha=0 means inpaint area)
 * @param operation - 'replace' clears and sets new mask, 'add' unions with existing mask
 */
async function applyMaskFromDataUrl(dataUrl: string, operation: 'replace' | 'add' = 'replace'): Promise<void> {
  if (!maskCanvas.value || !canvasReady.value) return

  const canvas = maskCanvas.value
  const ctx = canvas.getContext('2d')
  if (!ctx) return

  return new Promise((resolve) => {
    const img = new Image()
    img.onload = () => {
      if (operation === 'replace') {
        // Clear and draw new mask
        ctx.clearRect(0, 0, canvas.width, canvas.height)
      }

      // Draw the new mask onto canvas
      // The incoming mask has alpha=0 for inpaint areas
      // We need to convert to red pixels for display
      const tempCanvas = document.createElement('canvas')
      tempCanvas.width = canvas.width
      tempCanvas.height = canvas.height
      const tempCtx = tempCanvas.getContext('2d')
      if (!tempCtx) {
        resolve()
        return
      }

      tempCtx.drawImage(img, 0, 0, canvas.width, canvas.height)
      const imageData = tempCtx.getImageData(0, 0, canvas.width, canvas.height)
      const data = imageData.data

      // Convert: where alpha=0 (inpaint area), draw red on display canvas
      for (let i = 0; i < data.length; i += 4) {
        const a = data[i + 3]
        if (a < 128) {
          // This is an inpaint area - draw red
          const pixelIndex = i / 4
          const x = pixelIndex % canvas.width
          const y = Math.floor(pixelIndex / canvas.width)

          if (operation === 'add') {
            // For add operation, use source-over to union
            ctx.globalCompositeOperation = 'source-over'
          }
          ctx.fillStyle = 'rgba(255, 0, 0, 1)'
          ctx.fillRect(x, y, 1, 1)
        }
      }

      ctx.globalCompositeOperation = 'source-over'
      emitMask()
      resolve()
    }
    img.onerror = () => resolve()
    img.src = dataUrl
  })
}

/**
 * Check if the mask canvas has any painted areas.
 */
function hasMask(): boolean {
  if (!maskCanvas.value) return false
  const ctx = maskCanvas.value.getContext('2d')
  if (!ctx) return false

  const imageData = ctx.getImageData(0, 0, maskCanvas.value.width, maskCanvas.value.height)
  const data = imageData.data
  for (let i = 0; i < data.length; i += 4) {
    if (data[i + 3] > 0) return true
  }
  return false
}

/**
 * Expand (dilate) the current mask by a percentage.
 * Uses morphological dilation to grow masked regions outward.
 */
function expandMask(percent: number): void {
  if (!maskCanvas.value || !hasMask()) return

  const canvas = maskCanvas.value
  const ctx = canvas.getContext('2d')
  if (!ctx) return

  // Save to undo stack before modifying
  saveToUndoStack()

  // Calculate dilation radius based on image dimensions
  const avgDimension = (canvas.width + canvas.height) / 2
  const radius = Math.max(1, Math.round((percent / 100) * avgDimension * 0.1))

  const imageData = ctx.getImageData(0, 0, canvas.width, canvas.height)
  const data = imageData.data
  const width = canvas.width
  const height = canvas.height

  // Extract alpha channel
  const alpha = new Uint8Array(width * height)
  for (let i = 0; i < alpha.length; i++) {
    alpha[i] = data[i * 4 + 3]
  }

  // Separable dilation - horizontal pass
  const temp = new Uint8Array(width * height)
  for (let y = 0; y < height; y++) {
    const rowOffset = y * width
    for (let x = 0; x < width; x++) {
      let maxVal = 0
      const xStart = Math.max(0, x - radius)
      const xEnd = Math.min(width - 1, x + radius)
      for (let nx = xStart; nx <= xEnd; nx++) {
        if (alpha[rowOffset + nx] > maxVal) maxVal = alpha[rowOffset + nx]
      }
      temp[rowOffset + x] = maxVal
    }
  }

  // Vertical pass - write directly to output
  for (let x = 0; x < width; x++) {
    for (let y = 0; y < height; y++) {
      let maxVal = 0
      const yStart = Math.max(0, y - radius)
      const yEnd = Math.min(height - 1, y + radius)
      for (let ny = yStart; ny <= yEnd; ny++) {
        if (temp[ny * width + x] > maxVal) maxVal = temp[ny * width + x]
      }
      if (maxVal > 0) {
        const i = (y * width + x) * 4
        data[i] = 255
        data[i + 1] = 0
        data[i + 2] = 0
        data[i + 3] = 255
      }
    }
  }

  ctx.putImageData(imageData, 0, 0)
  emitMask()
}

/**
 * Contract (erode) the current mask by a percentage.
 * Uses morphological erosion to shrink masked regions inward.
 */
function contractMask(percent: number = 10): void {
  if (!maskCanvas.value || !hasMask()) return

  const canvas = maskCanvas.value
  const ctx = canvas.getContext('2d')
  if (!ctx) return

  // Save to undo stack before modifying
  saveToUndoStack()

  // Calculate erosion radius based on image dimensions
  const avgDimension = (canvas.width + canvas.height) / 2
  const radius = Math.max(1, Math.round((percent / 100) * avgDimension * 0.1))

  const imageData = ctx.getImageData(0, 0, canvas.width, canvas.height)
  const data = imageData.data
  const width = canvas.width
  const height = canvas.height

  // Extract alpha channel (255 = painted, 0 = not painted)
  const alpha = new Uint8Array(width * height)
  for (let i = 0; i < alpha.length; i++) {
    alpha[i] = data[i * 4 + 3]
  }

  // Separable erosion - horizontal pass (find min in neighborhood)
  const temp = new Uint8Array(width * height)
  for (let y = 0; y < height; y++) {
    const rowOffset = y * width
    for (let x = 0; x < width; x++) {
      let minVal = 255
      const xStart = Math.max(0, x - radius)
      const xEnd = Math.min(width - 1, x + radius)
      for (let nx = xStart; nx <= xEnd; nx++) {
        if (alpha[rowOffset + nx] < minVal) minVal = alpha[rowOffset + nx]
      }
      temp[rowOffset + x] = minVal
    }
  }

  // Vertical pass - write directly to output
  for (let x = 0; x < width; x++) {
    for (let y = 0; y < height; y++) {
      let minVal = 255
      const yStart = Math.max(0, y - radius)
      const yEnd = Math.min(height - 1, y + radius)
      for (let ny = yStart; ny <= yEnd; ny++) {
        if (temp[ny * width + x] < minVal) minVal = temp[ny * width + x]
      }
      const i = (y * width + x) * 4
      if (minVal === 0) {
        // Erode - clear this pixel
        data[i] = 0
        data[i + 1] = 0
        data[i + 2] = 0
        data[i + 3] = 0
      }
    }
  }

  ctx.putImageData(imageData, 0, 0)
  emitMask()
}

/**
 * Invert the current mask (masked areas become unmasked and vice versa).
 */
function invertMask(): void {
  if (!maskCanvas.value) return

  const canvas = maskCanvas.value
  const ctx = canvas.getContext('2d')
  if (!ctx) return

  // Save to undo stack before modifying
  saveToUndoStack()

  const imageData = ctx.getImageData(0, 0, canvas.width, canvas.height)
  const data = imageData.data

  // Invert: where alpha > 0, make it 0; where alpha = 0, make it painted
  for (let i = 0; i < data.length; i += 4) {
    if (data[i + 3] > 128) {
      // Was painted, now clear
      data[i] = 0
      data[i + 1] = 0
      data[i + 2] = 0
      data[i + 3] = 0
    } else {
      // Was clear, now paint red
      data[i] = 255
      data[i + 1] = 0
      data[i + 2] = 0
      data[i + 3] = 255
    }
  }

  ctx.putImageData(imageData, 0, 0)
  emitMask()
}

/**
 * Subtract a mask from the existing mask with intelligent region removal.
 * If the incoming mask covers 80%+ of any connected component in the existing mask,
 * the ENTIRE component is removed (greedy). Otherwise, just subtracts pixel-by-pixel.
 *
 * @param dataUrl - The mask as a data URL (RGBA PNG where alpha=0 means areas to unmask)
 */
async function subtractMaskFromDataUrl(dataUrl: string): Promise<void> {
  if (!maskCanvas.value || !canvasReady.value || !hasMask()) return

  const canvas = maskCanvas.value
  const ctx = canvas.getContext('2d')
  if (!ctx) return

  // Save undo state
  saveToUndoStack()

  return new Promise((resolve) => {
    const img = new Image()
    img.onload = () => {
      const width = canvas.width
      const height = canvas.height

      // Get the incoming unmask mask
      const tempCanvas = document.createElement('canvas')
      tempCanvas.width = width
      tempCanvas.height = height
      const tempCtx = tempCanvas.getContext('2d')
      if (!tempCtx) {
        resolve()
        return
      }
      tempCtx.drawImage(img, 0, 0, width, height)
      const unmaskData = tempCtx.getImageData(0, 0, width, height).data

      // Build unmask binary array (true = area to unmask, i.e., alpha < 128)
      const unmaskBinary = new Uint8Array(width * height)
      for (let i = 0; i < unmaskBinary.length; i++) {
        unmaskBinary[i] = unmaskData[i * 4 + 3] < 128 ? 1 : 0
      }

      // Get existing mask
      const existingData = ctx.getImageData(0, 0, width, height)
      const existingPixels = existingData.data

      // Build existing mask binary array (true = masked, i.e., alpha > 128)
      const existingBinary = new Uint8Array(width * height)
      for (let i = 0; i < existingBinary.length; i++) {
        existingBinary[i] = existingPixels[i * 4 + 3] > 128 ? 1 : 0
      }

      // Find connected components in existing mask using flood fill
      const labels = new Int32Array(width * height)
      labels.fill(-1)
      let nextLabel = 0
      const componentPixels: number[][] = []  // componentPixels[label] = [pixelIndex, ...]

      for (let i = 0; i < existingBinary.length; i++) {
        if (existingBinary[i] === 1 && labels[i] === -1) {
          // Start new component
          const label = nextLabel++
          componentPixels[label] = []

          // Flood fill
          const stack = [i]
          while (stack.length > 0) {
            const idx = stack.pop()!
            if (labels[idx] !== -1) continue
            if (existingBinary[idx] !== 1) continue

            labels[idx] = label
            componentPixels[label].push(idx)

            const x = idx % width
            const y = Math.floor(idx / width)

            // 4-connected neighbors
            if (x > 0) stack.push(idx - 1)
            if (x < width - 1) stack.push(idx + 1)
            if (y > 0) stack.push(idx - width)
            if (y < height - 1) stack.push(idx + width)
          }
        }
      }

      // For each component, calculate overlap with unmask region
      const componentsToRemove = new Set<number>()

      for (let label = 0; label < componentPixels.length; label++) {
        const pixels = componentPixels[label]
        if (pixels.length === 0) continue

        let overlapCount = 0
        for (const idx of pixels) {
          if (unmaskBinary[idx] === 1) {
            overlapCount++
          }
        }

        const overlapPercent = overlapCount / pixels.length
        if (overlapPercent >= 0.8) {
          // 80%+ overlap - mark entire component for removal
          componentsToRemove.add(label)
        }
      }

      // Apply the subtraction
      for (let i = 0; i < existingBinary.length; i++) {
        const idx = i * 4

        if (labels[i] !== -1 && componentsToRemove.has(labels[i])) {
          // Remove entire component (greedy)
          existingPixels[idx] = 0
          existingPixels[idx + 1] = 0
          existingPixels[idx + 2] = 0
          existingPixels[idx + 3] = 0
        } else if (unmaskBinary[i] === 1 && existingBinary[i] === 1) {
          // Subtract pixel-by-pixel for non-greedy regions
          existingPixels[idx] = 0
          existingPixels[idx + 1] = 0
          existingPixels[idx + 2] = 0
          existingPixels[idx + 3] = 0
        }
      }

      ctx.putImageData(existingData, 0, 0)
      emitMask()
      resolve()
    }
    img.onerror = () => resolve()
    img.src = dataUrl
  })
}

// Expose methods and state for AI mask assistant
defineExpose({
  applyMaskFromDataUrl,
  subtractMaskFromDataUrl,
  saveToUndoStack,
  clearMask,
  expandMask,
  contractMask,
  invertMask,
  hasMask,
  imageWidth,
  imageHeight,
  expandContractPercent,
})
</script>

<style scoped>
.slider {
  -webkit-appearance: none;
  appearance: none;
  height: 4px;
  background: var(--color-surface-raised);
  border-radius: 2px;
}

.slider::-webkit-slider-thumb {
  -webkit-appearance: none;
  appearance: none;
  width: 12px;
  height: 12px;
  border-radius: 50%;
  @apply bg-blue-500;
  cursor: pointer;
  transition: background 0.2s;
}

.slider::-webkit-slider-thumb:hover {
  @apply bg-blue-600;
}

.slider::-moz-range-thumb {
  width: 12px;
  height: 12px;
  border-radius: 50%;
  @apply bg-blue-500;
  cursor: pointer;
  border: none;
  transition: background 0.2s;
}

.slider::-moz-range-thumb:hover {
  @apply bg-blue-600;
}

.slider::-moz-range-track {
  background: var(--color-surface-raised);
  border-radius: 2px;
  height: 4px;
}
</style>
