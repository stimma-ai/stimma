<template>
  <div class="flex h-full">
    <!-- Canvas area (left, fills available space) -->
    <div
      class="flex-1 relative overflow-hidden flex items-center justify-center bg-[#111113]"
      ref="canvasContainer"
      @pointermove="onContainerPointerMove"
      @pointerleave="showBrushCursor = false"
    >
      <canvas ref="sourceCanvas" class="absolute" style="pointer-events: none;" />
      <canvas
        ref="paintCanvas"
        class="absolute"
        :style="{ cursor: activeTool === 'eyedropper' ? 'crosshair' : 'none' }"
        @pointerdown="onPointerDown"
        @pointermove="onPointerMove"
        @pointerup="onPointerUp"
        @pointerleave="onPointerLeave"
      />
      <!-- Brush cursor overlay -->
      <div
        v-if="showBrushCursor && activeTool !== 'eyedropper'"
        class="absolute rounded-full border-2 pointer-events-none"
        :class="activeTool === 'brush' ? 'border-white/60' : 'border-red-400/60'"
        :style="{
          width: `${brushCursorSize}px`,
          height: `${brushCursorSize}px`,
          left: `${cursorX - brushCursorSize / 2}px`,
          top: `${cursorY - brushCursorSize / 2}px`
        }"
      />
    </div>

    <!-- Right sidebar -->
    <div class="w-[230px] flex-shrink-0 border-l border-edge-subtle flex flex-col">
      <!-- Tools section -->
      <div class="px-3 py-3 border-b border-edge-subtle">
        <h4 class="text-[10px] font-bold uppercase tracking-wider text-content-tertiary mb-2">Tools</h4>
        <div class="flex items-center gap-1">
          <button
            @click="activeTool = 'brush'"
            :class="[
              'w-8 h-8 rounded-md flex items-center justify-center transition-colors',
              activeTool === 'brush' ? 'bg-blue-500 text-white' : 'text-content hover:bg-black/10 dark:hover:bg-white/10'
            ]"
            title="Brush"
          >
            <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" d="M9.53 16.122a3 3 0 00-5.78 1.128 2.25 2.25 0 01-2.4 2.245 4.5 4.5 0 008.4-2.245c0-.399-.078-.78-.22-1.128zm0 0a15.998 15.998 0 003.388-1.62m-5.043-.025a15.994 15.994 0 011.622-3.395m3.42 3.42a15.995 15.995 0 004.764-4.648l3.876-5.814a1.151 1.151 0 00-1.597-1.597L14.146 6.32a15.996 15.996 0 00-4.649 4.763m3.42 3.42a6.776 6.776 0 00-3.42-3.42" />
            </svg>
          </button>
          <button
            @click="activeTool = 'eyedropper'"
            :class="[
              'w-8 h-8 rounded-md flex items-center justify-center transition-colors',
              activeTool === 'eyedropper' ? 'bg-blue-500 text-white' : 'text-content hover:bg-black/10 dark:hover:bg-white/10'
            ]"
            title="Eyedropper (sample color)"
          >
            <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" d="M15 11.25l1.5-1.5a2.121 2.121 0 013 3L18 14.25M15 11.25l-7.5 7.5V21h2.25l7.5-7.5M15 11.25L18 14.25M3.75 21h1.5" />
            </svg>
          </button>
          <button
            @click="activeTool = 'eraser'"
            :class="[
              'w-8 h-8 rounded-md flex items-center justify-center transition-colors',
              activeTool === 'eraser' ? 'bg-blue-500 text-white' : 'text-content hover:bg-black/10 dark:hover:bg-white/10'
            ]"
            title="Eraser"
          >
            <svg class="w-4 h-4" viewBox="0 0 16 16" fill="currentColor">
              <path d="M8.086 2.207a2 2 0 0 1 2.828 0l3.879 3.879a2 2 0 0 1 0 2.828l-5.5 5.5A2 2 0 0 1 7.879 15H5.12a2 2 0 0 1-1.414-.586l-2.5-2.5a2 2 0 0 1 0-2.828zm2.121.707a1 1 0 0 0-1.414 0L4.16 7.547l5.293 5.293 4.633-4.633a1 1 0 0 0 0-1.414zM8.746 13.547 3.453 8.254 1.914 9.793a1 1 0 0 0 0 1.414l2.5 2.5a1 1 0 0 0 .707.293H7.88a1 1 0 0 0 .707-.293z"/>
            </svg>
          </button>
          <button
            @click="clearPaintLayer"
            class="w-8 h-8 rounded-md flex items-center justify-center transition-colors text-content hover:text-red-500 hover:bg-red-500/10"
            title="Clear all paint"
          >
            <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" d="m14.74 9-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 0 1-2.244 2.077H8.084a2.25 2.25 0 0 1-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 0 0-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 0 1 3.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 0 0-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 0 0-7.5 0" />
            </svg>
          </button>
          <div class="flex-1" />
          <button
            @click="undo"
            :disabled="undoCount === 0"
            :class="[
              'w-8 h-8 rounded-md flex items-center justify-center transition-colors',
              undoCount > 0
                ? 'text-content hover:bg-black/10 dark:hover:bg-white/10'
                : 'text-black/20 dark:text-white/20 cursor-not-allowed'
            ]"
            title="Undo"
          >
            <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" d="M9 15L3 9m0 0l6-6M3 9h12a6 6 0 010 12h-3" />
            </svg>
          </button>
          <button
            @click="redo"
            :disabled="redoCount === 0"
            :class="[
              'w-8 h-8 rounded-md flex items-center justify-center transition-colors',
              redoCount > 0
                ? 'text-content hover:bg-black/10 dark:hover:bg-white/10'
                : 'text-black/20 dark:text-white/20 cursor-not-allowed'
            ]"
            title="Redo"
          >
            <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" d="M15 15l6-6m0 0l-6-6m6 6H9a6 6 0 000 12h3" />
            </svg>
          </button>
        </div>
      </div>

      <!-- Color section -->
      <div class="px-3 py-3 border-b border-edge-subtle">
        <h4 class="text-[10px] font-bold uppercase tracking-wider text-content-tertiary mb-2">Color</h4>
        <div class="grid grid-cols-8 gap-1">
          <button
            v-for="color in presetColors"
            :key="color"
            @click="activeColor = color"
            class="w-6 h-6 rounded border-2 transition-transform hover:scale-110 flex-shrink-0"
            :class="activeColor === color ? 'border-blue-500 scale-110 ring-1 ring-blue-500' : 'border-black/15 dark:border-white/15'"
            :style="{ backgroundColor: color }"
            :title="color"
          />
        </div>
      </div>

      <!-- Brush section -->
      <div class="px-3 py-3 border-b border-edge-subtle">
        <h4 class="text-[10px] font-bold uppercase tracking-wider text-content-tertiary mb-2">Brush</h4>
        <div class="flex items-center gap-1.5">
          <span class="text-[11px] text-content-muted w-10">Size</span>
          <input
            type="range"
            v-model.number="brushSize"
            min="2"
            max="200"
            step="1"
            class="flex-1 slider cursor-pointer"
          />
          <span class="text-[11px] tabular-nums text-content-muted w-6 text-right">{{ brushSize }}</span>
        </div>
      </div>

      <!-- Spacer + Done button at bottom -->
      <div class="flex-1" />
      <div class="px-3 py-3">
        <button
          @click="$emit('done')"
          class="w-full py-2 rounded-md bg-blue-500 hover:bg-blue-600 text-white text-xs font-semibold transition-colors"
        >
          Done
        </button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, onMounted, onUnmounted, nextTick } from 'vue'
import { getCurrentProfileId } from '../../composables/useProfile'
import { getCachedPin } from '../../composables/usePinLock'
import { useMediaApi } from '../../composables/useMediaApi'
import { getApiBase } from '../../apiConfig'

const { getMediaFileUrl } = useMediaApi()

interface ImageInfo {
  path: string
  hash?: string
  mediaId?: number
  width?: number
  height?: number
}

interface Props {
  image: ImageInfo | null
  paintLayerDataUrl: string | null
}

const props = defineProps<Props>()

const emit = defineEmits<{
  (e: 'update:paintLayerDataUrl', value: string | null): void
  (e: 'done'): void
}>()

// Preset colors
// Bold 16-color palette (2 rows of 8)
const presetColors = [
  '#000000', '#ffffff', '#ff0000', '#00ff00',
  '#0000ff', '#ffff00', '#ff00ff', '#00ffff',
  '#808080', '#c0c0c0', '#800000', '#008000',
  '#000080', '#808000', '#800080', '#008080',
]

// Refs
const canvasContainer = ref<HTMLDivElement | null>(null)
const sourceCanvas = ref<HTMLCanvasElement | null>(null)
const paintCanvas = ref<HTMLCanvasElement | null>(null)

// State
const activeTool = ref<'brush' | 'eyedropper' | 'eraser'>('brush')
const activeColor = ref('#ff0000')
const brushSize = ref(32)
const brushOpacity = ref(100)
const isPainting = ref(false)
const lastX = ref(0)
const lastY = ref(0)
const showBrushCursor = ref(false)
const cursorX = ref(0)
const cursorY = ref(0)
const imageWidth = ref(512)
const imageHeight = ref(512)
const canvasReady = ref(false)
const pendingPaintLayer = ref<string | null>(null)

// Display dimensions (how big the canvases appear on screen)
const displayWidth = ref(0)
const displayHeight = ref(0)

// Undo/Redo — raw arrays + reactive counter (ImageData can't be Vue-proxied)
let _undoStack: ImageData[] = []
let _redoStack: ImageData[] = []
const undoCount = ref(0)
const redoCount = ref(0)
const MAX_UNDO_STATES = 50

// Computed
const isCustomColor = computed(() => !presetColors.includes(activeColor.value))

const brushCursorSize = computed(() => {
  if (!displayWidth.value || !imageWidth.value) return brushSize.value
  return (brushSize.value * displayWidth.value) / imageWidth.value
})

const sourceImageUrl = computed(() => {
  if (!props.image) return ''
  if (props.image.hash) {
    return getMediaFileUrl(props.image.hash)
  }
  if (props.image.path?.startsWith('/')) {
    const base = getApiBase()
    const profileId = getCurrentProfileId()
    const pin = getCachedPin(profileId)
    let url = `${base}/generate/reference-file?path=${encodeURIComponent(props.image.path)}&profile=${encodeURIComponent(profileId)}`
    if (pin) url += `&pin=${encodeURIComponent(pin)}`
    return url
  }
  return getMediaFileUrl(props.image.path)
})

// Load source image onto source canvas
function loadSourceImage() {
  if (!sourceImageUrl.value || !sourceCanvas.value) return

  const img = new Image()
  img.crossOrigin = 'anonymous'
  img.onload = () => {
    imageWidth.value = img.naturalWidth
    imageHeight.value = img.naturalHeight

    // Set canvas intrinsic size to match image
    sourceCanvas.value!.width = img.naturalWidth
    sourceCanvas.value!.height = img.naturalHeight
    paintCanvas.value!.width = img.naturalWidth
    paintCanvas.value!.height = img.naturalHeight

    // Draw image on source canvas
    const ctx = sourceCanvas.value!.getContext('2d')
    if (ctx) {
      ctx.clearRect(0, 0, img.naturalWidth, img.naturalHeight)
      ctx.drawImage(img, 0, 0)
    }

    // Clear paint canvas
    const paintCtx = paintCanvas.value!.getContext('2d')
    if (paintCtx) {
      paintCtx.clearRect(0, 0, img.naturalWidth, img.naturalHeight)
    }

    canvasReady.value = true
    updateCanvasDisplay()

    // Load pending paint layer
    const toLoad = pendingPaintLayer.value || props.paintLayerDataUrl
    if (toLoad) {
      loadPaintLayer(toLoad)
      pendingPaintLayer.value = null
    }
  }
  img.src = sourceImageUrl.value
}

// Update canvas CSS size to fit container while maintaining aspect ratio
function updateCanvasDisplay() {
  if (!canvasContainer.value || !sourceCanvas.value || !paintCanvas.value) return

  const containerRect = canvasContainer.value.getBoundingClientRect()
  const containerW = containerRect.width
  const containerH = containerRect.height

  if (containerW === 0 || containerH === 0) return

  const imgAspect = imageWidth.value / imageHeight.value
  const containerAspect = containerW / containerH

  let dw: number, dh: number
  if (imgAspect > containerAspect) {
    dw = containerW
    dh = containerW / imgAspect
  } else {
    dh = containerH
    dw = containerH * imgAspect
  }

  displayWidth.value = dw
  displayHeight.value = dh

  const style = `width: ${dw}px; height: ${dh}px;`
  sourceCanvas.value.style.cssText += style
  paintCanvas.value.style.cssText += style
}

// Load paint layer from data URL
function loadPaintLayer(dataUrl: string) {
  if (!paintCanvas.value) return
  const canvas = paintCanvas.value
  const ctx = canvas.getContext('2d')
  if (!ctx) return

  const img = new Image()
  img.onload = () => {
    ctx.clearRect(0, 0, canvas.width, canvas.height)
    // Scale paint layer to match canvas if dimensions differ
    if (img.naturalWidth !== canvas.width || img.naturalHeight !== canvas.height) {
      ctx.drawImage(img, 0, 0, canvas.width, canvas.height)
    } else {
      ctx.drawImage(img, 0, 0)
    }
  }
  img.src = dataUrl
}

// Get canvas coordinates from pointer event
function getCanvasCoords(event: PointerEvent): { x: number; y: number } | null {
  if (!paintCanvas.value) return null

  const rect = paintCanvas.value.getBoundingClientRect()
  const scaleX = paintCanvas.value.width / rect.width
  const scaleY = paintCanvas.value.height / rect.height

  return {
    x: (event.clientX - rect.left) * scaleX,
    y: (event.clientY - rect.top) * scaleY
  }
}

// Undo/Redo
function saveToUndoStack() {
  if (!paintCanvas.value) return
  const ctx = paintCanvas.value.getContext('2d')
  if (!ctx) return

  const imageData = ctx.getImageData(0, 0, paintCanvas.value.width, paintCanvas.value.height)
  _undoStack.push(imageData)
  if (_undoStack.length > MAX_UNDO_STATES) _undoStack.shift()
  _redoStack = []
  undoCount.value = _undoStack.length
  redoCount.value = 0
}

function undo() {
  if (_undoStack.length === 0 || !paintCanvas.value) return
  const ctx = paintCanvas.value.getContext('2d')
  if (!ctx) return

  const currentState = ctx.getImageData(0, 0, paintCanvas.value.width, paintCanvas.value.height)
  _redoStack.push(currentState)
  const previousState = _undoStack.pop()!
  undoCount.value = _undoStack.length
  redoCount.value = _redoStack.length

  ctx.putImageData(previousState, 0, 0)
  emitPaintLayer()
}

function redo() {
  if (_redoStack.length === 0 || !paintCanvas.value) return
  const ctx = paintCanvas.value.getContext('2d')
  if (!ctx) return

  const currentState = ctx.getImageData(0, 0, paintCanvas.value.width, paintCanvas.value.height)
  _undoStack.push(currentState)
  const nextState = _redoStack.pop()!
  undoCount.value = _undoStack.length
  redoCount.value = _redoStack.length

  ctx.putImageData(nextState, 0, 0)
  emitPaintLayer()
}

// Drawing
function drawCircle(ctx: CanvasRenderingContext2D, x: number, y: number) {
  ctx.beginPath()
  ctx.arc(x, y, brushSize.value / 2, 0, Math.PI * 2)
  ctx.fill()
}

function drawLine(ctx: CanvasRenderingContext2D, fromX: number, fromY: number, toX: number, toY: number) {
  ctx.beginPath()
  ctx.moveTo(fromX, fromY)
  ctx.lineTo(toX, toY)
  ctx.stroke()
}

function setupBrushContext(ctx: CanvasRenderingContext2D) {
  if (activeTool.value === 'eraser') {
    ctx.globalCompositeOperation = 'destination-out'
    ctx.globalAlpha = 1
    ctx.fillStyle = 'rgba(0,0,0,1)'
    ctx.strokeStyle = 'rgba(0,0,0,1)'
  } else {
    ctx.globalCompositeOperation = 'source-over'
    ctx.globalAlpha = 1
    ctx.fillStyle = activeColor.value
    ctx.strokeStyle = activeColor.value
  }
  ctx.lineWidth = brushSize.value
  ctx.lineCap = 'round'
  ctx.lineJoin = 'round'
}

function clearPaintLayer() {
  if (!paintCanvas.value) return
  const ctx = paintCanvas.value.getContext('2d')
  if (!ctx) return
  saveToUndoStack()
  ctx.clearRect(0, 0, paintCanvas.value.width, paintCanvas.value.height)
  emitPaintLayer()
}

function sampleColor(event: PointerEvent) {
  if (!sourceCanvas.value) return
  const coords = getCanvasCoords(event)
  if (!coords) return

  const ctx = sourceCanvas.value.getContext('2d')
  if (!ctx) return

  const pixel = ctx.getImageData(Math.round(coords.x), Math.round(coords.y), 1, 1).data
  const r = pixel[0].toString(16).padStart(2, '0')
  const g = pixel[1].toString(16).padStart(2, '0')
  const b = pixel[2].toString(16).padStart(2, '0')
  activeColor.value = `#${r}${g}${b}`
  // Switch back to brush after sampling
  activeTool.value = 'brush'
}

// Pointer events
function onPointerDown(event: PointerEvent) {
  if (!paintCanvas.value) return

  if (activeTool.value === 'eyedropper') {
    sampleColor(event)
    return
  }

  const coords = getCanvasCoords(event)
  if (!coords) return

  // Save undo state before stroke begins
  saveToUndoStack()

  isPainting.value = true
  lastX.value = coords.x
  lastY.value = coords.y

  const ctx = paintCanvas.value.getContext('2d')
  if (!ctx) return

  setupBrushContext(ctx)
  drawCircle(ctx, coords.x, coords.y)

  // Capture pointer for smooth drawing
  paintCanvas.value.setPointerCapture(event.pointerId)
}

function onPointerMove(event: PointerEvent) {
  if (!isPainting.value || !paintCanvas.value) return

  const coords = getCanvasCoords(event)
  if (!coords) return

  const ctx = paintCanvas.value.getContext('2d')
  if (!ctx) return

  setupBrushContext(ctx)

  // Draw line from last position and circle at current position
  drawLine(ctx, lastX.value, lastY.value, coords.x, coords.y)
  drawCircle(ctx, coords.x, coords.y)

  lastX.value = coords.x
  lastY.value = coords.y
}

function onPointerUp(_event: PointerEvent) {
  if (!isPainting.value) return
  isPainting.value = false

  // Reset composite operation
  if (paintCanvas.value) {
    const ctx = paintCanvas.value.getContext('2d')
    if (ctx) {
      ctx.globalCompositeOperation = 'source-over'
      ctx.globalAlpha = 1
    }
  }

  emitPaintLayer()
}

function onPointerLeave(_event: PointerEvent) {
  showBrushCursor.value = false
}

function onContainerPointerMove(event: PointerEvent) {
  if (activeTool.value === 'eyedropper') {
    showBrushCursor.value = false
    return
  }

  showBrushCursor.value = true
  const rect = canvasContainer.value!.getBoundingClientRect()
  cursorX.value = event.clientX - rect.left
  cursorY.value = event.clientY - rect.top
}

function emitPaintLayer() {
  if (!paintCanvas.value) return
  const dataUrl = paintCanvas.value.toDataURL('image/png')
  emit('update:paintLayerDataUrl', dataUrl)
}

// Watch source image changes
watch(sourceImageUrl, () => {
  canvasReady.value = false
  _undoStack = []; _redoStack = []
  undoCount.value = 0; redoCount.value = 0
  nextTick(() => loadSourceImage())
})

// Watch paint layer data URL changes from outside
watch(() => props.paintLayerDataUrl, (newVal) => {
  if (newVal) {
    if (canvasReady.value) {
      loadPaintLayer(newVal)
    } else {
      pendingPaintLayer.value = newVal
    }
  }
})

// Watch image prop for dimension changes
watch(() => props.image, (newImg, oldImg) => {
  if (newImg?.path !== oldImg?.path) {
    canvasReady.value = false
    _undoStack = []; _redoStack = []
    undoCount.value = 0; redoCount.value = 0
    nextTick(() => loadSourceImage())
  }
})

// Handle resize
let resizeObserver: ResizeObserver | null = null

onMounted(() => {
  if (canvasContainer.value) {
    resizeObserver = new ResizeObserver(() => {
      if (canvasReady.value) {
        updateCanvasDisplay()
      }
    })
    resizeObserver.observe(canvasContainer.value)
  }

  nextTick(() => loadSourceImage())
})

onUnmounted(() => {
  if (resizeObserver) {
    resizeObserver.disconnect()
    resizeObserver = null
  }
})
</script>
