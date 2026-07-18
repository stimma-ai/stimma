<template>
  <div class="flex h-full">
    <!-- Canvas area (left, fills available space) -->
    <div
      class="flex-1 relative overflow-hidden flex items-center justify-center bg-matte"
      ref="canvasContainer"
      @pointermove="onContainerPointerMove"
      @pointerleave="showBrushCursor = false"
      @wheel="onWheel"
    >
      <!-- Zoom/pan wrapper: scales+translates both canvases together. getBoundingClientRect()
           on the canvases below already reflects this transform, so pointer coordinate
           mapping in getCanvasCoords() needs no changes for zoom/pan to work. -->
      <div
        class="absolute"
        :style="{
          width: `${displayWidth}px`,
          height: `${displayHeight}px`,
          transform: `translate(${panX}px, ${panY}px) scale(${zoomLevel})`,
        }"
      >
        <canvas
          ref="sourceCanvas"
          class="absolute inset-0 w-full h-full"
          :style="{ pointerEvents: 'none' }"
        />
        <canvas
          ref="paintCanvas"
          class="absolute inset-0 w-full h-full"
          :style="{ cursor: cursorStyle }"
          @pointerdown="onPointerDown"
          @pointermove="onPointerMove"
          @pointerup="onPointerUp"
          @pointerleave="onPointerLeave"
        />
      </div>
      <!-- Brush cursor overlay -->
      <div
        v-if="showBrushCursor && activeTool !== 'eyedropper' && !spacePressed"
        class="absolute rounded-full border-2 pointer-events-none"
        :class="activeTool === 'brush' ? 'border-white/60' : 'border-red-400/60'"
        :style="{
          width: `${brushCursorSize}px`,
          height: `${brushCursorSize}px`,
          left: `${cursorX - brushCursorSize / 2}px`,
          top: `${cursorY - brushCursorSize / 2}px`
        }"
      />
      <!-- Zoom controls -->
      <div class="absolute bottom-2 left-2 flex items-center gap-0.5 bg-black/55 backdrop-blur-sm rounded-md px-1 py-1">
        <button
          @click="zoomOut"
          :disabled="zoomLevel <= ZOOM_MIN"
          class="w-6 h-6 rounded-md flex items-center justify-center text-white/80 hover:text-white hover:bg-white/10 disabled:opacity-30 disabled:hover:bg-transparent transition-colors"
          title="Zoom out"
        >
          <PaintToolIcon name="zoomOut" />
        </button>
        <span class="text-[10px] tabular-nums text-white/80 w-9 text-center select-none">{{ Math.round(zoomLevel * 100) }}%</span>
        <button
          @click="zoomIn"
          :disabled="zoomLevel >= ZOOM_MAX"
          class="w-6 h-6 rounded-md flex items-center justify-center text-white/80 hover:text-white hover:bg-white/10 disabled:opacity-30 disabled:hover:bg-transparent transition-colors"
          title="Zoom in"
        >
          <PaintToolIcon name="zoomIn" />
        </button>
      </div>
    </div>

    <!-- Right sidebar -->
    <div class="w-[230px] flex-shrink-0 border-l border-edge-subtle flex flex-col">
      <!-- Tools section -->
      <div class="px-3 py-3 border-b border-edge-subtle">
        <h4 class="text-xs font-semibold text-content-secondary mb-2">Tools</h4>
        <div class="flex items-center gap-1">
          <button
            @click="activeTool = 'brush'"
            :class="[
              'w-8 h-8 rounded-md flex items-center justify-center transition-colors',
              activeTool === 'brush' ? 'bg-accent text-white' : 'text-content hover:bg-overlay-subtle'
            ]"
            title="Brush"
          >
            <PaintToolIcon name="brush" />
          </button>
          <button
            @click="activeTool = 'eyedropper'"
            :class="[
              'w-8 h-8 rounded-md flex items-center justify-center transition-colors',
              activeTool === 'eyedropper' ? 'bg-accent text-white' : 'text-content hover:bg-overlay-subtle'
            ]"
            title="Eyedropper (sample color from image)"
          >
            <PaintToolIcon name="eyedropper" />
          </button>
          <button
            @click="activeTool = 'eraser'"
            :class="[
              'w-8 h-8 rounded-md flex items-center justify-center transition-colors',
              activeTool === 'eraser' ? 'bg-accent text-white' : 'text-content hover:bg-overlay-subtle'
            ]"
            title="Eraser"
          >
            <PaintToolIcon name="eraser" />
          </button>
          <button
            @click="clearPaintLayer"
            class="w-8 h-8 rounded-md flex items-center justify-center transition-colors text-content hover:text-red-500 hover:bg-red-500/10"
            title="Clear all paint"
          >
            <PaintToolIcon name="trash" />
          </button>
          <div class="flex-1" />
          <button
            @click="undo"
            :disabled="undoCount === 0"
            :class="[
              'w-8 h-8 rounded-md flex items-center justify-center transition-colors',
              undoCount > 0
                ? 'text-content hover:bg-overlay-subtle'
                : 'text-content-muted opacity-40 cursor-not-allowed'
            ]"
            title="Undo"
          >
            <PaintToolIcon name="undo" />
          </button>
          <button
            @click="redo"
            :disabled="redoCount === 0"
            :class="[
              'w-8 h-8 rounded-md flex items-center justify-center transition-colors',
              redoCount > 0
                ? 'text-content hover:bg-overlay-subtle'
                : 'text-content-muted opacity-40 cursor-not-allowed'
            ]"
            title="Redo"
          >
            <PaintToolIcon name="redo" />
          </button>
        </div>
      </div>

      <!-- Color section -->
      <div class="px-3 py-3 border-b border-edge-subtle">
        <h4 class="text-xs font-semibold text-content-secondary mb-2">Color</h4>
        <!-- Current color -->
        <div class="flex items-center gap-2 mb-2.5">
          <div
            class="w-8 h-8 rounded-md border-2 flex-shrink-0"
            :class="isCustomColor ? 'border-accent ring-1 ring-accent' : 'border-edge-subtle'"
            :style="{ backgroundColor: activeColor }"
            title="Current color"
          />
          <span class="text-[11px] font-mono uppercase text-content-secondary tracking-wide">{{ activeColor }}</span>
        </div>
        <div class="grid grid-cols-8 gap-1">
          <button
            v-for="color in presetColors"
            :key="color"
            @click="activeColor = color"
            class="w-6 h-6 rounded border-2 flex-shrink-0"
            :class="activeColor === color ? 'border-accent ring-1 ring-accent' : 'border-edge-subtle'"
            :style="{ backgroundColor: color }"
            :title="color"
          />
        </div>
      </div>

      <!-- Brush section -->
      <div class="px-3 py-3 border-b border-edge-subtle">
        <h4 class="text-xs font-semibold text-content-secondary mb-2">Brush</h4>
        <div class="flex items-center gap-1.5 mb-2">
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
        <div class="flex items-center gap-1.5">
          <span class="text-[11px] text-content-muted w-10">Hardness</span>
          <input
            type="range"
            v-model.number="brushHardness"
            min="0"
            max="100"
            step="1"
            class="flex-1 slider cursor-pointer"
            title="Lower hardness feathers the brush edge"
          />
          <span class="text-[11px] tabular-nums text-content-muted w-6 text-right">{{ brushHardness }}</span>
        </div>
      </div>

      <!-- Spacer + Done button at bottom -->
      <div class="flex-1" />
      <div class="px-3 py-3">
        <button
          @click="$emit('done')"
          class="w-full py-2 rounded-md bg-accent hover:bg-accent/90 text-white text-xs font-semibold transition-colors"
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
import PaintToolIcon from './PaintToolIcon.vue'

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
const brushHardness = ref(100)
const isPainting = ref(false)
const isSampling = ref(false)
const lastX = ref(0)
const lastY = ref(0)
const showBrushCursor = ref(false)
const cursorX = ref(0)
const cursorY = ref(0)
const imageWidth = ref(512)
const imageHeight = ref(512)
const canvasReady = ref(false)
const pendingPaintLayer = ref<string | null>(null)

// Display dimensions (how big the canvases appear on screen at zoom 1)
const displayWidth = ref(0)
const displayHeight = ref(0)

// Zoom/pan
const ZOOM_MIN = 1
const ZOOM_MAX = 4
const ZOOM_STEP = 0.25
const zoomLevel = ref(1)
const panX = ref(0)
const panY = ref(0)
const spacePressed = ref(false)
const isPanning = ref(false)
const panStartClientX = ref(0)
const panStartClientY = ref(0)
const panOriginX = ref(0)
const panOriginY = ref(0)

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
  return (brushSize.value * displayWidth.value * zoomLevel.value) / imageWidth.value
})

const cursorStyle = computed(() => {
  if (spacePressed.value) return isPanning.value ? 'grabbing' : 'grab'
  return activeTool.value === 'eyedropper' ? 'crosshair' : 'none'
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

// Update the base (zoom=1) display size to fit the container while maintaining aspect ratio
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
  clampPan()
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

// Get canvas coordinates from pointer event. getBoundingClientRect() reflects
// the on-screen box AFTER the zoom/pan CSS transform, so this needs no zoom-aware math.
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
//
// Hardness is implemented as an alpha falloff via a radial gradient rather
// than ctx.filter's blur() — canvas 2D `filter` support is flaky in Tauri's
// WKWebView, and a slider that silently does nothing is worse than not
// having it. Radial gradients are basic Canvas 2D and work everywhere.
// Since a single stamp's gradient can't be dragged into a line via
// ctx.stroke() (a gradient fillStyle is anchored to fixed coordinates, not
// the path), soft strokes are built by stamping overlapping dabs along the
// pointer path instead of stroke+endpoint-circle.
function brushFillStyle(ctx: CanvasRenderingContext2D, x: number, y: number): string | CanvasGradient {
  if (activeTool.value === 'eraser') {
    if (brushHardness.value >= 100) return 'rgba(0,0,0,1)'
    const gradient = ctx.createRadialGradient(x, y, (brushSize.value / 2) * (brushHardness.value / 100), x, y, brushSize.value / 2)
    gradient.addColorStop(0, 'rgba(0,0,0,1)')
    gradient.addColorStop(1, 'rgba(0,0,0,0)')
    return gradient
  }

  if (brushHardness.value >= 100) return activeColor.value

  const [r, g, b] = hexToRgb(activeColor.value)
  const gradient = ctx.createRadialGradient(x, y, (brushSize.value / 2) * (brushHardness.value / 100), x, y, brushSize.value / 2)
  gradient.addColorStop(0, `rgba(${r}, ${g}, ${b}, 1)`)
  gradient.addColorStop(1, `rgba(${r}, ${g}, ${b}, 0)`)
  return gradient
}

function stampBrush(ctx: CanvasRenderingContext2D, x: number, y: number) {
  ctx.fillStyle = brushFillStyle(ctx, x, y)
  ctx.beginPath()
  ctx.arc(x, y, brushSize.value / 2, 0, Math.PI * 2)
  ctx.fill()
}

function stampBrushLine(ctx: CanvasRenderingContext2D, fromX: number, fromY: number, toX: number, toY: number) {
  const dist = Math.hypot(toX - fromX, toY - fromY)
  const spacing = Math.max(1, brushSize.value * 0.15)
  const steps = Math.max(1, Math.ceil(dist / spacing))
  for (let i = 1; i <= steps; i++) {
    const t = i / steps
    stampBrush(ctx, fromX + (toX - fromX) * t, fromY + (toY - fromY) * t)
  }
}

function setupBrushContext(ctx: CanvasRenderingContext2D) {
  ctx.globalCompositeOperation = activeTool.value === 'eraser' ? 'destination-out' : 'source-over'
  ctx.globalAlpha = 1
}

function clearPaintLayer() {
  if (!paintCanvas.value) return
  const ctx = paintCanvas.value.getContext('2d')
  if (!ctx) return
  saveToUndoStack()
  ctx.clearRect(0, 0, paintCanvas.value.width, paintCanvas.value.height)
  emitPaintLayer()
}

function hexToRgb(hex: string): [number, number, number] {
  const n = parseInt(hex.replace('#', ''), 16)
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255]
}

function sampleColor(event: PointerEvent) {
  if (!sourceCanvas.value) return
  const coords = getCanvasCoords(event)
  if (!coords) return

  const ctx = sourceCanvas.value.getContext('2d')
  if (!ctx) return

  // Clamp to canvas bounds: while dragging with the pointer captured, coords
  // can land outside [0, width) x [0, height) and getImageData throws on that.
  const x = Math.min(Math.max(Math.round(coords.x), 0), sourceCanvas.value.width - 1)
  const y = Math.min(Math.max(Math.round(coords.y), 0), sourceCanvas.value.height - 1)

  const pixel = ctx.getImageData(x, y, 1, 1).data
  const r = pixel[0].toString(16).padStart(2, '0')
  const g = pixel[1].toString(16).padStart(2, '0')
  const b = pixel[2].toString(16).padStart(2, '0')
  activeColor.value = `#${r}${g}${b}`
}

// Zoom/pan
function setZoom(next: number) {
  zoomLevel.value = Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, next))
  if (zoomLevel.value === ZOOM_MIN) {
    panX.value = 0
    panY.value = 0
  } else {
    clampPan()
  }
}

function zoomIn() {
  setZoom(zoomLevel.value + ZOOM_STEP)
}

function zoomOut() {
  setZoom(zoomLevel.value - ZOOM_STEP)
}

function clampPan() {
  if (!canvasContainer.value) return
  const rect = canvasContainer.value.getBoundingClientRect()
  const scaledW = displayWidth.value * zoomLevel.value
  const scaledH = displayHeight.value * zoomLevel.value
  const maxX = Math.max(0, (scaledW - rect.width) / 2)
  const maxY = Math.max(0, (scaledH - rect.height) / 2)
  panX.value = Math.min(maxX, Math.max(-maxX, panX.value))
  panY.value = Math.min(maxY, Math.max(-maxY, panY.value))
}

function onWheel(event: WheelEvent) {
  event.preventDefault()
  adjustBrushSize(event.deltaY < 0 ? 1 : -1)
}

function adjustBrushSize(direction: number) {
  const step = Math.max(1, Math.round(brushSize.value * 0.1))
  brushSize.value = Math.min(200, Math.max(2, brushSize.value + direction * step))
}

function handleKeyDown(e: KeyboardEvent) {
  if (e.key === '[') {
    adjustBrushSize(-1)
    e.preventDefault()
  } else if (e.key === ']') {
    adjustBrushSize(1)
    e.preventDefault()
  } else if (e.code === 'Space' && !spacePressed.value) {
    spacePressed.value = true
    e.preventDefault()
  }
}

function handleKeyUp(e: KeyboardEvent) {
  if (e.code === 'Space') {
    spacePressed.value = false
  }
}

// Pointer events
function onPointerDown(event: PointerEvent) {
  if (!paintCanvas.value) return

  if (spacePressed.value && zoomLevel.value > ZOOM_MIN) {
    isPanning.value = true
    panStartClientX.value = event.clientX
    panStartClientY.value = event.clientY
    panOriginX.value = panX.value
    panOriginY.value = panY.value
    paintCanvas.value.setPointerCapture(event.pointerId)
    return
  }

  if (activeTool.value === 'eyedropper') {
    isSampling.value = true
    sampleColor(event)
    paintCanvas.value.setPointerCapture(event.pointerId)
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
  stampBrush(ctx, coords.x, coords.y)

  // Capture pointer for smooth drawing
  paintCanvas.value.setPointerCapture(event.pointerId)
}

function onPointerMove(event: PointerEvent) {
  if (isPanning.value) {
    panX.value = panOriginX.value + (event.clientX - panStartClientX.value)
    panY.value = panOriginY.value + (event.clientY - panStartClientY.value)
    clampPan()
    return
  }

  if (isSampling.value) {
    sampleColor(event)
    return
  }

  if (!isPainting.value || !paintCanvas.value) return

  const coords = getCanvasCoords(event)
  if (!coords) return

  const ctx = paintCanvas.value.getContext('2d')
  if (!ctx) return

  setupBrushContext(ctx)

  // Stamp dabs along the path from the last position to fill any gap
  stampBrushLine(ctx, lastX.value, lastY.value, coords.x, coords.y)

  lastX.value = coords.x
  lastY.value = coords.y
}

function onPointerUp(_event: PointerEvent) {
  if (isPanning.value) {
    isPanning.value = false
    return
  }

  if (isSampling.value) {
    isSampling.value = false
    return
  }

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
  if (activeTool.value === 'eyedropper' || spacePressed.value) {
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
  zoomLevel.value = 1; panX.value = 0; panY.value = 0
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
    zoomLevel.value = 1; panX.value = 0; panY.value = 0
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

  window.addEventListener('keydown', handleKeyDown)
  window.addEventListener('keyup', handleKeyUp)

  nextTick(() => loadSourceImage())
})

onUnmounted(() => {
  if (resizeObserver) {
    resizeObserver.disconnect()
    resizeObserver = null
  }
  window.removeEventListener('keydown', handleKeyDown)
  window.removeEventListener('keyup', handleKeyUp)
})
</script>

<style scoped>
/* .slider: the two brush sliders (Size, Hardness) reference this class but no
   definition existed anywhere in scope, so they rendered as unstyled native
   range inputs. Standard thumb spec (matches MaskEditor.vue), accent thumb. */
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
  @apply bg-accent;
  cursor: pointer;
  transition: background 0.2s;
}

.slider::-webkit-slider-thumb:hover {
  @apply bg-accent/90;
}

.slider::-moz-range-thumb {
  width: 12px;
  height: 12px;
  border-radius: 50%;
  @apply bg-accent;
  cursor: pointer;
  border: none;
  transition: background 0.2s;
}

.slider::-moz-range-thumb:hover {
  @apply bg-accent/90;
}

.slider::-moz-range-track {
  background: var(--color-surface-raised);
  border-radius: 2px;
  height: 4px;
}
</style>
