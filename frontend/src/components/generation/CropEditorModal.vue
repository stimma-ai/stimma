<template>
  <Teleport to="body">
    <!-- Backdrop -->
    <div v-if="modelValue" class="fixed inset-0 z-[10001] flex items-center justify-center bg-black/60 p-6">
      <!-- Modal card -->
      <div class="flex flex-col w-full h-full max-w-[1400px] max-h-[900px] bg-surface rounded-xl border border-edge-subtle shadow-2xl overflow-hidden">
        <!-- Header -->
        <div class="flex items-center justify-between px-4 py-2 border-b border-edge-subtle flex-shrink-0">
          <h3 class="text-sm font-medium text-content">Crop Input Image</h3>
          <button
            @click="cancel"
            class="p-1 rounded text-content-muted hover:text-content-secondary hover:bg-overlay-subtle transition-colors"
          >
            <svg class="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        <!-- Crop surface -->
        <div ref="containerRef" class="flex-1 min-h-0 relative bg-base overflow-hidden">
          <canvas
            ref="canvasRef"
            class="absolute inset-0 touch-none"
            :style="{ cursor: cursorStyle }"
            @pointerdown="onPointerDown"
            @pointermove="onPointerMove"
            @pointerup="onPointerUp"
            @pointercancel="onPointerUp"
          />
          <div v-if="!imageLoaded" class="absolute inset-0 flex items-center justify-center">
            <div class="w-6 h-6 border-2 border-edge border-t-blue-500 rounded-full animate-spin"></div>
          </div>
        </div>

        <!-- Footer: aspect presets + rotation · readout · actions -->
        <div class="flex flex-col gap-2 px-4 py-2.5 border-t border-edge-subtle flex-shrink-0">
          <div class="flex items-center gap-3 flex-wrap">
            <div class="flex items-center gap-1 flex-wrap">
              <button
                v-for="opt in aspectRatios"
                :key="opt.label"
                @click="selectAspect(opt.value)"
                :class="[
                  'px-2 py-1 rounded text-[11px] font-medium border transition-colors',
                  selectedAspect === opt.value
                    ? 'bg-blue-500/15 border-blue-500/50 text-blue-400'
                    : 'border-white/10 text-content-muted bg-white/[0.05] hover:bg-white/[0.08]'
                ]"
              >{{ opt.label }}</button>
            </div>
            <!-- Rotation slider (straighten) -->
            <div class="flex items-center gap-2 flex-1 min-w-[200px] max-w-[360px] ml-auto">
              <span class="text-[11px] text-content-muted">Rotation</span>
              <input
                type="range" min="-45" max="45" step="0.1"
                :value="rotationDeg"
                @input="onRotationSlider(parseFloat(($event.target as HTMLInputElement).value))"
                @dblclick="onRotationSlider(0)"
                class="flex-1 h-1 accent-blue-500 cursor-pointer"
              />
              <button
                @click="onRotationSlider(0)"
                class="text-[11px] text-blue-400 tabular-nums w-12 text-right hover:text-blue-300"
                title="Reset rotation"
              >{{ rotationDeg.toFixed(1) }}°</button>
            </div>
          </div>
          <div class="flex items-center gap-3">
            <span class="text-[11px] text-content-muted tabular-nums">{{ cropPixelWidth }} × {{ cropPixelHeight }}</span>
            <div class="flex items-center gap-2 ml-auto">
              <button
                @click="resetCrop"
                class="px-3 py-1.5 rounded-lg text-xs font-medium bg-surface-raised hover:bg-surface-hover text-content-secondary transition-colors"
              >Reset</button>
              <button
                @click="cancel"
                class="px-3 py-1.5 rounded-lg text-xs font-medium bg-surface-raised hover:bg-surface-hover text-content transition-colors"
              >Cancel</button>
              <button
                @click="apply"
                class="px-3 py-1.5 rounded-lg text-xs font-medium bg-blue-600 hover:bg-blue-500 text-white transition-colors"
              >Apply</button>
            </div>
          </div>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
// Modal crop editor for input-image prep. The surface mirrors the image
// editor's crop plugin (dark mask, dashed blue border, thirds guides, white
// corner handles, rotation lollipop) but edits a normalized left/top-anchored
// rect — plus an optional rect rotation in clockwise degrees — that the backend
// prep pipeline applies AFTER flip/rotate and BEFORE scale.
import { ref, computed, watch, onMounted, onUnmounted, nextTick } from 'vue'

export interface CropRect {
  x: number        // left, 0-1 of the flipped image
  y: number        // top, 0-1
  width: number    // 0-1
  height: number   // 0-1
  rotation?: number // rect rotation in clockwise degrees (straighten), 0 when absent
}

interface FlipState {
  horizontal?: boolean
  vertical?: boolean
  rotation?: number  // 0 | 90 | 180 | 270, clockwise
}

interface Props {
  modelValue: boolean
  imageUrl: string | null
  // Natural (pre-flip) pixel dimensions; used for the pixel readout before load.
  imageWidth?: number
  imageHeight?: number
  flip?: FlipState | null
  crop?: CropRect | null
}

const props = defineProps<Props>()

const emit = defineEmits<{
  (e: 'update:modelValue', value: boolean): void
  (e: 'apply', crop: CropRect | null): void
}>()

// ── Aspect presets (same list/order as the image editor's crop plugin) ──
const aspectRatios: Array<{ label: string; value: number | null }> = [
  { label: 'Free', value: null },
  { label: 'Original', value: -1 },
  { label: '16:9', value: 16 / 9 },
  { label: '3:2', value: 3 / 2 },
  { label: '4:3', value: 4 / 3 },
  { label: '1:1', value: 1 },
  { label: '3:4', value: 3 / 4 },
  { label: '2:3', value: 2 / 3 },
  { label: '9:16', value: 9 / 16 },
]
const selectedAspect = ref<number | null>(null)

const MIN_SCREEN_PX = 12  // minimum crop extent per axis while dragging

const containerRef = ref<HTMLElement | null>(null)
const canvasRef = ref<HTMLCanvasElement | null>(null)

const imageEl = ref<HTMLImageElement | null>(null)
const imageLoaded = ref(false)

const crop = ref<Omit<CropRect, 'rotation'>>({ x: 0, y: 0, width: 1, height: 1 })
const rotationDeg = ref(0)

// ── Flipped-image dimensions (what the crop rect is relative to) ──
const flipRotation = computed(() => (((props.flip?.rotation ?? 0) % 360) + 360) % 360)
const naturalDims = computed(() => ({
  w: imageEl.value?.naturalWidth || props.imageWidth || 1,
  h: imageEl.value?.naturalHeight || props.imageHeight || 1,
}))
const flippedDims = computed(() => {
  const { w, h } = naturalDims.value
  return flipRotation.value === 90 || flipRotation.value === 270 ? { w: h, h: w } : { w, h }
})

const cropPixelWidth = computed(() => Math.max(1, Math.round(crop.value.width * flippedDims.value.w)))
const cropPixelHeight = computed(() => Math.max(1, Math.round(crop.value.height * flippedDims.value.h)))

// ── View transform: fit the flipped image in the container with padding ──
const containerSize = ref({ w: 0, h: 0 })
const VIEW_PAD = 44  // room for the rotation lollipop below the rect

const view = computed(() => {
  const { w: cw, h: ch } = containerSize.value
  const { w: fw, h: fh } = flippedDims.value
  if (!cw || !ch || !fw || !fh) return { zoom: 1, left: 0, top: 0 }
  const zoom = Math.min((cw - VIEW_PAD * 2) / fw, (ch - VIEW_PAD * 2) / fh)
  return {
    zoom,
    left: (cw - fw * zoom) / 2,
    top: (ch - fh * zoom) / 2,
  }
})

// ── Screen-space geometry (uniform zoom, so screen aspect == pixel aspect) ──
interface ScreenRect { cx: number; cy: number; w: number; h: number }

function theta(): number {
  return (rotationDeg.value * Math.PI) / 180
}

function screenRect(): ScreenRect {
  const { zoom, left, top } = view.value
  const { w: fw, h: fh } = flippedDims.value
  const c = crop.value
  return {
    cx: left + (c.x + c.width / 2) * fw * zoom,
    cy: top + (c.y + c.height / 2) * fh * zoom,
    w: c.width * fw * zoom,
    h: c.height * fh * zoom,
  }
}

function commitScreenRect(r: ScreenRect) {
  const { zoom, left, top } = view.value
  const { w: fw, h: fh } = flippedDims.value
  const width = r.w / (fw * zoom)
  const height = r.h / (fh * zoom)
  crop.value = {
    x: (r.cx - left) / (fw * zoom) - width / 2,
    y: (r.cy - top) / (fh * zoom) - height / 2,
    width,
    height,
  }
}

// Rotate a point by t (clockwise on screen) around a center.
function rotatePt(px: number, py: number, cx: number, cy: number, t: number) {
  const cos = Math.cos(t)
  const sin = Math.sin(t)
  const dx = px - cx
  const dy = py - cy
  return { x: cx + dx * cos - dy * sin, y: cy + dx * sin + dy * cos }
}

// Rotated corners: nw, ne, se, sw
function cornerPoints(r: ScreenRect, t: number): Array<{ x: number; y: number }> {
  return [
    rotatePt(r.cx - r.w / 2, r.cy - r.h / 2, r.cx, r.cy, t),
    rotatePt(r.cx + r.w / 2, r.cy - r.h / 2, r.cx, r.cy, t),
    rotatePt(r.cx + r.w / 2, r.cy + r.h / 2, r.cx, r.cy, t),
    rotatePt(r.cx - r.w / 2, r.cy + r.h / 2, r.cx, r.cy, t),
  ]
}

const ROTATE_HANDLE_DISTANCE = 30
const ROTATE_HANDLE_RADIUS = 7

// Rotation lollipop: below the bottom edge, perpendicular to it.
function rotateHandlePoint(r: ScreenRect, t: number): { x: number; y: number; stemX: number; stemY: number } {
  const bottomCenter = rotatePt(r.cx, r.cy + r.h / 2, r.cx, r.cy, t)
  const dirX = bottomCenter.x - r.cx
  const dirY = bottomCenter.y - r.cy
  const len = Math.hypot(dirX, dirY) || 1
  return {
    x: bottomCenter.x + (dirX / len) * ROTATE_HANDLE_DISTANCE,
    y: bottomCenter.y + (dirY / len) * ROTATE_HANDLE_DISTANCE,
    stemX: bottomCenter.x,
    stemY: bottomCenter.y,
  }
}

// ── Rendering (visuals match the editor's drawCropOverlay) ──
function render() {
  const canvas = canvasRef.value
  const container = containerRef.value
  if (!canvas || !container) return

  const { w: cw, h: ch } = containerSize.value
  if (!cw || !ch) return

  const dpr = window.devicePixelRatio || 1
  if (canvas.width !== Math.round(cw * dpr) || canvas.height !== Math.round(ch * dpr)) {
    canvas.width = Math.round(cw * dpr)
    canvas.height = Math.round(ch * dpr)
    canvas.style.width = `${cw}px`
    canvas.style.height = `${ch}px`
  }

  const ctx = canvas.getContext('2d')
  if (!ctx) return
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
  ctx.clearRect(0, 0, cw, ch)

  const img = imageEl.value
  if (!img || !imageLoaded.value) return

  const { zoom, left, top } = view.value
  const { w: fw, h: fh } = flippedDims.value
  const { w: nw, h: nh } = naturalDims.value

  // Draw the image with flip-first-then-rotate (mirrors the backend pipeline).
  ctx.save()
  ctx.translate(left + (fw * zoom) / 2, top + (fh * zoom) / 2)
  ctx.rotate((flipRotation.value * Math.PI) / 180)
  ctx.scale(props.flip?.horizontal ? -1 : 1, props.flip?.vertical ? -1 : 1)
  ctx.drawImage(img, (-nw * zoom) / 2, (-nh * zoom) / 2, nw * zoom, nh * zoom)
  ctx.restore()

  const r = screenRect()
  const t = theta()
  const corners = cornerPoints(r, t)

  // Mask outside the (possibly rotated) crop rect
  ctx.save()
  ctx.fillStyle = 'rgba(0, 0, 0, 0.5)'
  ctx.beginPath()
  ctx.rect(0, 0, cw, ch)
  ctx.moveTo(corners[0].x, corners[0].y)
  ctx.lineTo(corners[3].x, corners[3].y)
  ctx.lineTo(corners[2].x, corners[2].y)
  ctx.lineTo(corners[1].x, corners[1].y)
  ctx.closePath()
  ctx.fill('evenodd')
  ctx.restore()

  // Dashed blue crop border
  ctx.strokeStyle = '#3b82f6'
  ctx.lineWidth = 2
  ctx.setLineDash([6, 4])
  ctx.beginPath()
  ctx.moveTo(corners[0].x, corners[0].y)
  ctx.lineTo(corners[1].x, corners[1].y)
  ctx.lineTo(corners[2].x, corners[2].y)
  ctx.lineTo(corners[3].x, corners[3].y)
  ctx.closePath()
  ctx.stroke()
  ctx.setLineDash([])

  // Rule-of-thirds guides (lerped along the rotated edges)
  const lerp = (p1: { x: number; y: number }, p2: { x: number; y: number }, f: number) => ({
    x: p1.x + (p2.x - p1.x) * f,
    y: p1.y + (p2.y - p1.y) * f,
  })
  ctx.strokeStyle = 'rgba(255, 255, 255, 0.5)'
  ctx.lineWidth = 1
  ctx.beginPath()
  for (const f of [1 / 3, 2 / 3]) {
    const gt = lerp(corners[0], corners[1], f)
    const gb = lerp(corners[3], corners[2], f)
    ctx.moveTo(gt.x, gt.y)
    ctx.lineTo(gb.x, gb.y)
    const gl = lerp(corners[0], corners[3], f)
    const gr = lerp(corners[1], corners[2], f)
    ctx.moveTo(gl.x, gl.y)
    ctx.lineTo(gr.x, gr.y)
  }
  ctx.stroke()

  // Center cross (rotates with the rect)
  const cos = Math.cos(t)
  const sin = Math.sin(t)
  ctx.beginPath()
  ctx.moveTo(r.cx - 8 * cos, r.cy - 8 * sin)
  ctx.lineTo(r.cx + 8 * cos, r.cy + 8 * sin)
  ctx.moveTo(r.cx + 8 * sin, r.cy - 8 * cos)
  ctx.lineTo(r.cx - 8 * sin, r.cy + 8 * cos)
  ctx.stroke()

  // Rotation lollipop: dashed stem + white circle below the bottom edge
  const rh = rotateHandlePoint(r, t)
  ctx.strokeStyle = '#3b82f6'
  ctx.lineWidth = 2
  ctx.setLineDash([4, 3])
  ctx.beginPath()
  ctx.moveTo(rh.stemX, rh.stemY)
  ctx.lineTo(rh.x, rh.y)
  ctx.stroke()
  ctx.setLineDash([])
  ctx.fillStyle = '#ffffff'
  ctx.beginPath()
  ctx.arc(rh.x, rh.y, ROTATE_HANDLE_RADIUS, 0, Math.PI * 2)
  ctx.fill()
  ctx.stroke()

  // Corner handles: white circles with blue stroke
  ctx.fillStyle = '#ffffff'
  ctx.strokeStyle = '#3b82f6'
  ctx.lineWidth = 2
  for (const corner of corners) {
    ctx.beginPath()
    ctx.arc(corner.x, corner.y, 7, 0, Math.PI * 2)
    ctx.fill()
    ctx.stroke()
  }
}

// ── Interaction: corners resize, inside moves, lollipop rotates ──
type Handle = 'nw' | 'ne' | 'se' | 'sw' | 'move' | 'rotate'
const HANDLE_HIT_RADIUS = 14
const CORNER_NAMES: Array<'nw' | 'ne' | 'se' | 'sw'> = ['nw', 'ne', 'se', 'sw']
// Direction of each corner from the rect center in local (unrotated) space.
const CORNER_SIGNS: Record<'nw' | 'ne' | 'se' | 'sw', { x: number; y: number }> = {
  nw: { x: -1, y: -1 }, ne: { x: 1, y: -1 }, se: { x: 1, y: 1 }, sw: { x: -1, y: 1 },
}

const activeHandle = ref<Handle | null>(null)
const hoverHandle = ref<Handle | null>(null)
let dragStart = {
  px: 0, py: 0,
  rect: { cx: 0, cy: 0, w: 0, h: 0 } as ScreenRect,
}

const cursorStyle = computed(() => {
  const h = activeHandle.value || hoverHandle.value
  switch (h) {
    case 'nw': case 'se': return 'nwse-resize'
    case 'ne': case 'sw': return 'nesw-resize'
    case 'move': return activeHandle.value ? 'grabbing' : 'grab'
    case 'rotate': return activeHandle.value ? 'grabbing' : 'crosshair'
    default: return 'default'
  }
})

function canvasPoint(e: PointerEvent): { x: number; y: number } {
  const rect = canvasRef.value!.getBoundingClientRect()
  return { x: e.clientX - rect.left, y: e.clientY - rect.top }
}

function hitTest(p: { x: number; y: number }): Handle | null {
  const r = screenRect()
  const t = theta()
  const pts = cornerPoints(r, t)
  for (let i = 0; i < 4; i++) {
    if (Math.hypot(p.x - pts[i].x, p.y - pts[i].y) <= HANDLE_HIT_RADIUS) return CORNER_NAMES[i]
  }
  const rh = rotateHandlePoint(r, t)
  if (Math.hypot(p.x - rh.x, p.y - rh.y) <= HANDLE_HIT_RADIUS) return 'rotate'
  // Inside test in the rect's local frame
  const local = rotatePt(p.x, p.y, r.cx, r.cy, -t)
  if (Math.abs(local.x - r.cx) <= r.w / 2 && Math.abs(local.y - r.cy) <= r.h / 2) return 'move'
  return null
}

function onPointerDown(e: PointerEvent) {
  if (!imageLoaded.value) return
  const p = canvasPoint(e)
  const handle = hitTest(p)
  if (!handle) return
  activeHandle.value = handle
  dragStart = { px: p.x, py: p.y, rect: screenRect() }
  ;(e.target as HTMLElement).setPointerCapture(e.pointerId)
}

function onPointerMove(e: PointerEvent) {
  const p = canvasPoint(e)
  if (!activeHandle.value) {
    hoverHandle.value = imageLoaded.value ? hitTest(p) : null
    return
  }

  if (activeHandle.value === 'move') {
    moveTo(p)
  } else if (activeHandle.value === 'rotate') {
    rotateTo(p)
  } else {
    resizeFromCorner(activeHandle.value, p)
  }
  render()
}

function onPointerUp(e: PointerEvent) {
  if (activeHandle.value) {
    ;(e.target as HTMLElement).releasePointerCapture?.(e.pointerId)
    activeHandle.value = null
  }
}

function clamp(v: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, v))
}

function imageScreenBounds() {
  const { zoom, left, top } = view.value
  const { w: fw, h: fh } = flippedDims.value
  return { left, top, right: left + fw * zoom, bottom: top + fh * zoom }
}

function moveTo(p: { x: number; y: number }) {
  const s0 = dragStart.rect
  let cx = s0.cx + (p.x - dragStart.px)
  let cy = s0.cy + (p.y - dragStart.py)
  const b = imageScreenBounds()
  if (rotationDeg.value === 0) {
    // Unrotated: keep the whole rect inside the image (original behavior).
    cx = clamp(cx, b.left + s0.w / 2, Math.max(b.left + s0.w / 2, b.right - s0.w / 2))
    cy = clamp(cy, b.top + s0.h / 2, Math.max(b.top + s0.h / 2, b.bottom - s0.h / 2))
  } else {
    // Rotated rects may overhang (revealed corners fill black); just keep the
    // center on the image so the rect can't be lost off-canvas.
    cx = clamp(cx, b.left, b.right)
    cy = clamp(cy, b.top, b.bottom)
  }
  commitScreenRect({ ...s0, cx, cy })
}

function rotateTo(p: { x: number; y: number }) {
  const s0 = dragStart.rect
  // Handle sits below the rect at +90° when unrotated (screen y-down).
  let deg = (Math.atan2(p.y - s0.cy, p.x - s0.cx) * 180) / Math.PI - 90
  while (deg > 180) deg -= 360
  while (deg < -180) deg += 360
  rotationDeg.value = clamp(Math.round(deg * 10) / 10, -45, 45)
}

function onRotationSlider(deg: number) {
  rotationDeg.value = clamp(Math.round(deg * 10) / 10, -45, 45)
  render()
}

function resizeFromCorner(handle: 'nw' | 'ne' | 'se' | 'sw', p: { x: number; y: number }) {
  const t = theta()
  const cos = Math.cos(t)
  const sin = Math.sin(t)
  const s0 = dragStart.rect
  const sign = CORNER_SIGNS[handle]

  // Anchor is the opposite corner; it stays fixed in world space.
  const anchor = rotatePt(
    s0.cx - sign.x * (s0.w / 2),
    s0.cy - sign.y * (s0.h / 2),
    s0.cx, s0.cy, t,
  )

  // Pointer delta from the anchor, expressed in the rect's local frame.
  const dx = p.x - anchor.x
  const dy = p.y - anchor.y
  const du = dx * cos + dy * sin
  const dv = -dx * sin + dy * cos

  let w = Math.max(MIN_SCREEN_PX, du * sign.x)
  let h = Math.max(MIN_SCREEN_PX, dv * sign.y)

  // Aspect lock (screen aspect == pixel aspect under uniform zoom).
  const aspect = effectivePixelAspect()
  if (aspect != null) {
    if (w / aspect >= h) h = w / aspect
    else w = h * aspect
  }

  // Unrotated: keep the moving corner inside the image (original behavior).
  if (rotationDeg.value === 0) {
    const b = imageScreenBounds()
    const maxW = sign.x > 0 ? b.right - anchor.x : anchor.x - b.left
    const maxH = sign.y > 0 ? b.bottom - anchor.y : anchor.y - b.top
    if (aspect != null) {
      const fit = Math.min(1, maxW / w, maxH / h)
      w *= fit
      h *= fit
    } else {
      w = Math.min(w, maxW)
      h = Math.min(h, maxH)
    }
  }

  // New center: anchor + half the local extent, rotated back to world space.
  const lu = sign.x * (w / 2)
  const lv = sign.y * (h / 2)
  commitScreenRect({
    cx: anchor.x + lu * cos - lv * sin,
    cy: anchor.y + lu * sin + lv * cos,
    w, h,
  })
}

function effectivePixelAspect(): number | null {
  if (selectedAspect.value === null) return null
  if (selectedAspect.value === -1) {
    const { w: fw, h: fh } = flippedDims.value
    return fw / fh
  }
  return selectedAspect.value
}

// ── Aspect presets ──
function selectAspect(value: number | null) {
  selectedAspect.value = value
  if (value === null) return
  const pixelAspect = value === -1 ? flippedDims.value.w / flippedDims.value.h : value
  const { w: fw, h: fh } = flippedDims.value
  // Normalized width/height ratio equivalent to the pixel aspect ratio.
  const na = pixelAspect * (fh / fw)

  // Re-fit the current rect to the aspect around its center (shrink one dim).
  const c = crop.value
  let w = c.width
  let h = c.height
  if (w / h > na) w = h * na
  else h = w / na
  let x = c.x + (c.width - w) / 2
  let y = c.y + (c.height - h) / 2
  if (rotationDeg.value === 0) {
    x = clamp(x, 0, 1 - w)
    y = clamp(y, 0, 1 - h)
  }
  crop.value = { x, y, width: w, height: h }
  render()
}

function resetCrop() {
  crop.value = { x: 0, y: 0, width: 1, height: 1 }
  rotationDeg.value = 0
  selectedAspect.value = null
  render()
}

// ── Apply / cancel ──
function isFullFrame(c: { x: number; y: number; width: number; height: number }): boolean {
  return c.x <= 0.0005 && c.y <= 0.0005 && c.width >= 0.999 && c.height >= 0.999
}

function apply() {
  const c = crop.value
  const rot = Math.round(rotationDeg.value * 10) / 10
  if (isFullFrame(c) && rot === 0) {
    emit('apply', null)
  } else {
    emit('apply', {
      x: round4(c.x),
      y: round4(c.y),
      width: round4(c.width),
      height: round4(c.height),
      ...(rot !== 0 ? { rotation: rot } : {}),
    })
  }
  emit('update:modelValue', false)
}

function round4(v: number): number {
  return Math.round(v * 10000) / 10000
}

function cancel() {
  emit('update:modelValue', false)
}

// ── Lifecycle: load image + observe container size while open ──
let resizeObserver: ResizeObserver | null = null

function measureContainer() {
  const el = containerRef.value
  if (!el) return
  containerSize.value = { w: el.clientWidth, h: el.clientHeight }
}

function openSession() {
  const c = props.crop
  crop.value = c
    ? { x: c.x, y: c.y, width: c.width, height: c.height }
    : { x: 0, y: 0, width: 1, height: 1 }
  rotationDeg.value = clamp(c?.rotation ?? 0, -45, 45)
  selectedAspect.value = null
  imageLoaded.value = false
  imageEl.value = null

  if (props.imageUrl) {
    const img = new Image()
    img.onload = () => {
      imageEl.value = img
      imageLoaded.value = true
      render()
    }
    img.src = props.imageUrl
  }

  nextTick(() => {
    measureContainer()
    if (containerRef.value && !resizeObserver) {
      resizeObserver = new ResizeObserver(() => {
        measureContainer()
        render()
      })
      resizeObserver.observe(containerRef.value)
    }
    render()
  })
}

function closeSession() {
  resizeObserver?.disconnect()
  resizeObserver = null
  imageEl.value = null
  imageLoaded.value = false
}

watch(() => props.modelValue, (open) => {
  if (open) openSession()
  else closeSession()
})

watch([containerSize, imageLoaded, rotationDeg], () => render())

function handleKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape' && props.modelValue) cancel()
}

onMounted(() => {
  document.addEventListener('keydown', handleKeydown)
  if (props.modelValue) openSession()
})

onUnmounted(() => {
  document.removeEventListener('keydown', handleKeydown)
  closeSession()
})

// Prevent body scroll when open (same as PaintEditorModal)
watch(() => props.modelValue, (isOpen) => {
  document.body.style.overflow = isOpen ? 'hidden' : ''
})
</script>
