<script setup lang="ts">
/**
 * Paint strokes into a raster layer.
 *
 * The pixel work is the snapshot editor's, copied into `imageEditor/ported/`:
 * paint, clone stamp, spot heal, patch, dodge and burn with proper shadow /
 * midtone / highlight targeting, sponge, blur and sharpen. Reimplementing it
 * produced a radial-gradient stamp and a brightness multiply pretending to be
 * dodge — this component is now only the gesture surface and the bridge to the
 * op stack.
 *
 * A layer IS a step: several Paint rows are several layers, each at its own
 * stack position, re-enterable by double-clicking the row. Strokes are never
 * rows.
 *
 * Engines that READ the composite below (heal, clone, dodge, burn, sponge,
 * blur, sharpen) bake what was underneath, which is why their layers carry an
 * advisory hash like a generative patch.
 */
import { ref, computed, onMounted, onBeforeUnmount, watch } from 'vue'
import { useRasterPaintLayer } from '../ported/useRasterPaintLayer'
import { getSelectionBounds } from '../ported/selection'
import { tabletInputFor } from '../../composables/useTabletInput'
import type { BrushSettings, Point } from '../ported/geometry'
import type { GradientPaint } from '../ported/shapeTypes'
import type { PaintGradientType } from '../stack/paintEngineSettings'
import { constrainedGradientEnd } from '../stack/rasterGradient'
import { applyAdjust } from '../stack/opExecutors'
import { retouchBrushAdjustmentParams } from '../stack/retouchBrushAdjustment'
import { BrushStrokeRuntime, repairActivePenPressureDropouts } from '../brush/brushRuntime'
import { brushPreset } from '../brush/brushPresets'
import type { BrushInputSample, BrushPresetDefinition } from '../brush/types'
import { fittedBrushScale, zoomedBrushSize } from '../stack/viewportRaster'
import { penTipContactLost } from '../stack/tabletButtons'

interface RasterGestureMetadata {
  tool: string
  source?: Point
  target?: Point
}

/** Engines whose output depends on the pixels below them. */
const PIXEL_READING = new Set([
  'clone', 'heal', 'patch', 'dodge', 'burn', 'sponge', 'blur', 'sharpen',
])

const props = withDefaults(defineProps<{
  /** The composite below — what pixel-reading engines sample. */
  source: HTMLCanvasElement | null
  /** Existing layer content when re-entering a Paint step. */
  initialLayer?: HTMLCanvasElement | null
  /** Restrict strokes to the active selection. */
  selectionMask?: HTMLCanvasElement | null
  /**
   * Paint accumulates gestures into one raster layer. Retouch disables this so
   * every completed gesture is emitted as one independent child region.
   */
  accumulate?: boolean
  displayWidth: number
  displayHeight: number
  viewZoom?: number
  engineId?: string
  brush?: BrushSettings
  color?: { r: number; g: number; b: number; a?: number }
  gradient?: GradientPaint
  gradientType?: PaintGradientType
  gradientReverse?: boolean
  /** Dodge/burn strength and range. */
  exposure?: number
  range?: 'shadows' | 'midtones' | 'highlights'
  /** Sponge / blur / sharpen strength. */
  strength?: number
  /** Sponge direction: saturate, or pull color out. */
  saturate?: boolean
}>(), {
  engineId: 'paint',
  viewZoom: 1,
  accumulate: true,
  exposure: 10,
  range: 'midtones',
  strength: 20,
  saturate: true,
  gradientType: 'linear',
  gradientReverse: false,
})

const emit = defineEmits<{
  /**
   * A stroke finished: an immutable layer snapshot, whether pixels below were
   * read, and the local revision that snapshot represents.
   */
  stroke: [HTMLCanvasElement, boolean, number, RasterGestureMetadata]
  /** A patch landed: the selection it consumed should clear. */
  patchApplied: []
}>()

const overlay = ref<HTMLCanvasElement | null>(null)
/** The complete layer that is snapshotted and persisted after each stroke. */
const layer = useRasterPaintLayer()
/** Only the stroke currently under the pointer; never contains older strokes. */
const liveStroke = useRasterPaintLayer()

const cursor = ref<{ x: number; y: number } | null>(null)
/**
 * Completed strokes that persistence has not handed to the composite yet.
 *
 * The overlay draws these deltas plus `liveStroke`, never the cumulative layer:
 * once a revision lands in the stack, removing its delta cannot reveal or
 * double-composite older strokes.
 */
let pendingPreviews: Array<{
  revision: number
  canvas: HTMLCanvasElement
  /** An erase delta: drawn as a translucent wash, not as pixels that landed. */
  wash?: boolean
}> = []
/** Frozen visual input for the current stroke, including any pending previews. */
let strokeSource: HTMLCanvasElement | null = null
/** Exact parametric result sampled by adjustment brushes during this stroke. */
let strokeAdjustedSource: HTMLCanvasElement | null = null
/** First destination point, retained for source/destination repair feedback. */
let strokeStart: Point | null = null
/** The editable guide while a Gradient gesture is under the pointer. */
let gradientGesture: { start: Point; end: Point } | null = null
/** Where clone samples from, set by alt-click and kept across strokes. */
const cloneAnchor = ref<Point | null>(null)
let drawing = false
let activePointerId: number | null = null
/** Phase-2 sample→dab runtime, used by color paint and erase. */
let brushRuntime: BrushStrokeRuntime | null = null
/**
 * Monotonic ownership token for the overlay.
 *
 * Stroke persistence is asynchronous. A completed older render must not clear
 * a newer stroke that has already taken the overlay back.
 */
let layerRevision = 0
/** The entry snapshot is seed data, not something to restore after each render. */
let loadedInitialLayer: HTMLCanvasElement | null = null

/**
 * The patch drag in flight: grab inside the selection, drag to the donor
 * area. While it lasts, the overlay previews the donor pixels flowing into
 * the selection — the pixels that will actually land, not an outline.
 */
let patchDrag: {
  start: Point
  current: Point
  bounds: { x: number; y: number; width: number; height: number }
  /** Scratch canvas for the masked donor preview, allocated once per drag. */
  preview: HTMLCanvasElement
} | null = null
/** Prevent overlapping edits while the gradient-domain solve runs off-thread. */
const patchPending = ref(false)

function pointInMask(point: Point): boolean {
  const mask = props.selectionMask
  if (!mask) return false
  const x = Math.floor(point.x)
  const y = Math.floor(point.y)
  if (x < 0 || y < 0 || x >= mask.width || y >= mask.height) return false
  const ctx = mask.getContext('2d', { willReadFrequently: true })!
  return ctx.getImageData(x, y, 1, 1).data[3] > 0
}

const brushSettings = computed<BrushSettings>(() => props.brush ?? {
  size: 26, hardness: 60, opacity: 100, flow: 100, spacing: 25,
})
const cursorTip = computed(() => {
  const preset = props.brush?.presetId
    ? brushPreset(props.brush.presetId, props.engineId === 'erase')
    : null
  return preset?.tip ?? { kind: 'ellipse' as const, aspect: 1, rotation: 0 }
})
const scale = computed(() =>
  props.source ? props.source.width / Math.max(1, props.displayWidth) : 1
)
const brushScale = computed(() =>
  props.source
    ? fittedBrushScale(props.source.width, props.displayWidth, props.viewZoom)
    : 1
)
const cursorBrushSize = computed(() =>
  zoomedBrushSize(brushSettings.value.size, props.viewZoom)
)

function pointFrom(event: PointerEvent): Point {
  const rect = overlay.value!.getBoundingClientRect()
  return {
    x: (event.clientX - rect.left) * scale.value,
    y: (event.clientY - rect.top) * scale.value,
  }
}

/**
 * Brush size is a display measurement; the layer works in image pixels.
 *
 * Rounded, not just scaled: heal allocates an ImageData of exactly this many
 * pixels and then indexes it as `(y * size + x) * 4`. A fractional size makes
 * every one of those indices miss, and the engine silently writes nothing.
 */
function scaledBrush(): BrushSettings {
  return {
    ...brushSettings.value,
    size: Math.max(1, Math.round(brushSettings.value.size * brushScale.value)),
  }
}

/** At zero pressure a dab shrinks to this fraction, never to nothing. */
const PRESSURE_MIN_SIZE = 0.15

/**
 * The brush for one dab batch under the given stylus pressure. Null pressure
 * means a mouse stroke: the settings apply untouched, exactly as before.
 * Pressure is applied per pointer sample, not per stroke — that is what makes
 * a stroke swell and fade along its path.
 */
function pressuredBrush(pressure: number | null): BrushSettings {
  const brush = scaledBrush()
  if (pressure == null) return brush
  if (brush.pressureSize) {
    brush.size = Math.max(1, Math.round(
      brush.size * (PRESSURE_MIN_SIZE + (1 - PRESSURE_MIN_SIZE) * pressure),
    ))
  }
  if (brush.pressureOpacity) {
    brush.flow = brush.flow * pressure
  }
  return brush
}

/** Old saved settings have no preset id; retain their exact round-brush behavior. */
function legacyPreset(brush: BrushSettings, eraser: boolean): BrushPresetDefinition {
  return {
    ...brushPreset(undefined, eraser),
    id: eraser ? 'stimma.legacy.eraser' : 'stimma.legacy.paint',
    base: {
      size: brush.size,
      hardness: brush.hardness,
      opacity: brush.opacity,
      flow: brush.flow,
      spacing: brush.spacing,
    },
    dynamics: [],
    stabilization: { mode: 'raw' },
  }
}

function inputSample(event: PointerEvent): BrushInputSample {
  const point = pointFrom(event)
  const tablet = tabletInputFor(event)
  return {
    ...point,
    time: event.timeStamp,
    pressure: tablet?.pressure ?? 1,
    tiltX: tablet?.tiltX ?? 0,
    tiltY: tablet?.tiltY ?? 0,
    rotation: tablet?.rotation ?? 0,
    tangentialPressure: tablet?.tangentialPressure ?? 0,
    pointer: tablet ? 'pen' : 'mouse',
    eraser: tablet?.eraser ?? false,
    velocity: 0,
    direction: 0,
    distance: 0,
  }
}

function beginBrushRuntime() {
  const settings = scaledBrush()
  const eraser = props.engineId === 'erase'
  const preset = settings.presetId
    ? brushPreset(settings.presetId, eraser)
    : legacyPreset(settings, eraser)
  brushRuntime = new BrushStrokeRuntime(
    settings,
    preset,
    undefined,
    preset.previewSeed ^ layerRevision,
  )
}

function applyResolvedDabs(dabs: ReturnType<BrushStrokeRuntime['push']>) {
  const color = props.engineId === 'erase'
    ? { r: 255, g: 255, b: 255, a: 1 }
    : props.color ?? { r: 0, g: 0, b: 0, a: 1 }
  for (const dab of dabs) {
    liveStroke.applyPaintDab(
      { x: dab.x, y: dab.y },
      {
        ...scaledBrush(),
        size: dab.size,
        hardness: dab.hardness,
        opacity: dab.opacity,
        flow: dab.flow,
        aspect: dab.aspect,
        rotation: dab.rotation,
        tipAssetId: dab.tipAssetId,
      },
      color,
    )
  }
  if (dabs.length) drawOverlay()
}

let lastActivePenPressure: number | null = null

function pushBrushSamples(events: PointerEvent[]) {
  if (!brushRuntime) return
  const input = events.map(inputSample)
  const repaired = repairActivePenPressureDropouts(input, lastActivePenPressure)
  lastActivePenPressure = repaired.lastPressure
  for (const sample of repaired.samples) {
    applyResolvedDabs(brushRuntime.push(sample))
  }
}

function prepareStroke() {
  const source = props.source
  if (!source) return

  liveStroke.clearLayer()
  liveStroke.startStroke()

  const working = document.createElement('canvas')
  working.width = source.width
  working.height = source.height
  const ctx = working.getContext('2d')!
  ctx.drawImage(source, 0, 0)
  for (const pending of pendingPreviews) {
    // An erase delta is an alpha mask wearing white pixels; drawing it here
    // would feed the wash to sampling engines as real content.
    if (pending.wash) continue
    ctx.drawImage(pending.canvas, 0, 0)
  }
  strokeSource = working
  const adjustment = retouchBrushAdjustmentParams(props.engineId, {
    exposure: props.exposure,
    range: props.range,
    strength: props.strength,
    saturate: props.saturate,
  })
  strokeAdjustedSource = adjustment
    ? applyAdjust(working, working.width, working.height, adjustment)
    : null
}

function stamp(point: Point, pressure: number | null = null) {
  const source = strokeSource ?? props.source
  if (!source) return
  const brush = pressuredBrush(pressure)

  switch (props.engineId) {
    case 'clone':
      liveStroke.applyCloneStamp(source, point, brush)
      break
    case 'heal':
      liveStroke.applySpotHeal(source, point, brush)
      break
    case 'dodge':
    case 'burn':
    case 'sponge':
    case 'blur':
    case 'sharpen':
      if (strokeAdjustedSource) {
        liveStroke.applyAdjustedSourceBrush(strokeAdjustedSource, point, brush)
      }
      break
    // Fill is flat and selection-scoped: the selection tools own finding a
    // region; a click lays the color into it (or the whole layer without one).
    case 'fill':
      liveStroke.applyFlatFill(props.color ?? { r: 0, g: 0, b: 0, a: 1 })
      break
    // The stroke's ALPHA is the erase strength; the white is never shown at
    // full strength — the overlay draws erase deltas as a translucent wash,
    // and the commit consumes only the alpha (destination-out on the layer).
    case 'erase':
      liveStroke.applyPaintBrush(point, brush, { r: 255, g: 255, b: 255, a: 1 })
      break
    default:
      liveStroke.applyPaintBrush(point, brush, props.color ?? { r: 0, g: 0, b: 0, a: 1 })
  }
  drawOverlay()
}

const DEFAULT_GRADIENT: GradientPaint = {
  type: 'gradient',
  colors: [
    { r: 0, g: 0, b: 0, a: 1 },
    { r: 255, g: 255, b: 255, a: 1 },
  ],
  direction: 'horizontal',
}

/** Re-render the one live Gradient gesture; unlike a brush, moves replace it. */
function updateGradient(point: Point, constrain: boolean, preview = true): boolean {
  if (!gradientGesture) return false
  const end = constrainedGradientEnd(gradientGesture.start, point, constrain)
  gradientGesture.end = end
  liveStroke.clearLayer()
  liveStroke.applyGradientFill(
    props.gradient ?? DEFAULT_GRADIENT,
    gradientGesture.start,
    end,
    props.gradientType,
    props.gradientReverse,
    preview,
  )
  drawOverlay()
  return Math.hypot(end.x - gradientGesture.start.x, end.y - gradientGesture.start.y) >= 0.5
}

function finishStroke(
  readsPixels: boolean,
  metadata: RasterGestureMetadata = { tool: props.engineId },
): boolean {
  liveStroke.endStroke()
  const preview = liveStroke.toSnapshot()
  if (!preview) return false

  // Paint merges the delta into its persistent layer. Retouch emits the delta
  // itself, making one gesture one independently editable region.
  const layerCtx = layer.layerCtx.value
  if (props.accumulate && layerCtx) {
    if (props.engineId === 'erase') {
      layerCtx.save()
      layerCtx.globalCompositeOperation = 'destination-out'
      layerCtx.drawImage(preview, 0, 0)
      layerCtx.restore()
    } else {
      layerCtx.drawImage(preview, 0, 0)
    }
  }
  pendingPreviews.push({
    revision: layerRevision,
    canvas: preview,
    wash: props.engineId === 'erase',
  })

  const snapshot = props.accumulate ? layer.toSnapshot() : preview
  liveStroke.clearLayer()
  strokeSource = null
  strokeAdjustedSource = null
  drawOverlay()
  if (snapshot) emit('stroke', snapshot, readsPixels, layerRevision, metadata)
  strokeStart = null
  return !!snapshot
}

function drawOverlay() {
  const canvas = overlay.value
  if (!canvas) return
  const ctx = canvas.getContext('2d')!
  ctx.clearRect(0, 0, canvas.width, canvas.height)
  for (const pending of pendingPreviews) {
    if (pending.wash) {
      ctx.save()
      ctx.globalAlpha = 0.35
      ctx.drawImage(pending.canvas, 0, 0)
      ctx.restore()
    } else {
      ctx.drawImage(pending.canvas, 0, 0)
    }
  }
  if (drawing && liveStroke.layerCanvas.value) {
    if (props.engineId === 'erase') {
      ctx.save()
      ctx.globalAlpha = 0.35
      ctx.drawImage(liveStroke.layerCanvas.value, 0, 0)
      ctx.restore()
    } else {
      ctx.drawImage(liveStroke.layerCanvas.value, 0, 0)
    }
  }

  // The authored line stays visible for the duration of the drag. Its handles
  // explain which end owns the first and last colors without covering them.
  if (drawing && gradientGesture) {
    const { start, end } = gradientGesture
    const width = Math.max(1, scale.value)
    ctx.save()
    ctx.lineCap = 'round'
    ctx.lineWidth = width * 3
    ctx.strokeStyle = 'rgba(0,0,0,0.65)'
    ctx.beginPath()
    ctx.moveTo(start.x, start.y)
    ctx.lineTo(end.x, end.y)
    ctx.stroke()
    ctx.lineWidth = width
    ctx.strokeStyle = 'rgba(255,255,255,0.95)'
    ctx.stroke()
    for (const point of [start, end]) {
      ctx.beginPath()
      ctx.arc(point.x, point.y, width * 4, 0, Math.PI * 2)
      ctx.fillStyle = 'rgba(15,15,15,0.9)'
      ctx.fill()
      ctx.lineWidth = width
      ctx.strokeStyle = 'rgba(255,255,255,0.95)'
      ctx.stroke()
    }
    ctx.restore()
  }

  // Patch drag: preview the donor pixels IN the destination — what will land,
  // not an outline of it — plus a dashed box over the donor area itself.
  if (patchDrag && strokeSource && props.selectionMask) {
    const { start, current, bounds, preview } = patchDrag
    const dx = current.x - start.x
    const dy = current.y - start.y

    const previewCtx = preview.getContext('2d')!
    previewCtx.clearRect(0, 0, preview.width, preview.height)
    previewCtx.drawImage(strokeSource, -dx, -dy)
    previewCtx.globalCompositeOperation = 'destination-in'
    previewCtx.drawImage(props.selectionMask, 0, 0)
    previewCtx.globalCompositeOperation = 'source-over'
    ctx.drawImage(preview, 0, 0)

    ctx.save()
    ctx.strokeStyle = 'rgba(255,255,255,0.8)'
    ctx.lineWidth = Math.max(1, scale.value)
    ctx.setLineDash([5 * scale.value, 4 * scale.value])
    ctx.strokeRect(bounds.x + dx, bounds.y + dy, bounds.width, bounds.height)
    ctx.restore()
  }
}

/** End the live stroke and hand it to the stack, keeping every dab drawn. */
function commitActiveStroke() {
  if (brushRuntime) applyResolvedDabs(brushRuntime.finish())
  brushRuntime = null
  drawing = false
  finishStroke(PIXEL_READING.has(props.engineId), {
    tool: props.engineId,
    ...(props.engineId === 'clone' && cloneAnchor.value && strokeStart
      ? { source: cloneAnchor.value, target: strokeStart }
      : {}),
  })
}

function onPointerDown(event: PointerEvent) {
  if (!props.source || patchPending.value) return

  // Only the pen tip (or left button) draws. A pen's barrel buttons arrive as
  // middle/right presses on the SAME pointer, so without this they read as the
  // start of another stroke and prepareStroke() would wipe the live one — a
  // bumped button silently discarded everything drawn before it.
  //
  // Bumping a barrel button mid-stroke instead ends the stroke and keeps the
  // pixels, matching Photoshop. That is also what makes the front button's
  // middle-drag pan usable: the stroke closes, then the canvas moves.
  if (event.button !== 0) {
    if (drawing) {
      releasePointer(event.pointerId)
      activePointerId = null
      commitActiveStroke()
    }
    return
  }

  const point = pointFrom(event)

  // Patch is a drag of the selection, not a stroke. No selection or a grab
  // outside it does nothing — the selection tools own making one.
  if (props.engineId === 'patch') {
    const mask = props.selectionMask
    if (!mask || !pointInMask(point)) return
    const maskCtx = mask.getContext('2d', { willReadFrequently: true })!
    const bounds = getSelectionBounds(maskCtx)
    if (!bounds) return
    const preview = document.createElement('canvas')
    preview.width = props.source.width
    preview.height = props.source.height
    layerRevision += 1
    prepareStroke()
    activePointerId = event.pointerId
    overlay.value?.setPointerCapture(event.pointerId)
    patchDrag = { start: point, current: point, bounds, preview }
    drawOverlay()
    return
  }

  // Alt-click sets the clone source, the way it works everywhere else. The
  // OFFSET is only known once painting starts, so the anchor is held here and
  // resolved against the first destination point of the stroke.
  if (props.engineId === 'clone' && event.altKey) {
    cloneAnchor.value = point
    return
  }
  if (props.engineId === 'clone' && !cloneAnchor.value) return
  layerRevision += 1
  prepareStroke()
  strokeStart = point
  if (props.engineId === 'clone') {
    liveStroke.setCloneSource(strokeSource ?? props.source, cloneAnchor.value, point)
  }

  activePointerId = event.pointerId
  overlay.value?.setPointerCapture(event.pointerId)
  drawing = true
  lastActivePenPressure = null
  if (props.engineId === 'gradient') {
    gradientGesture = { start: point, end: point }
    drawOverlay()
    return
  }
  if (props.engineId === 'paint' || props.engineId === 'erase') {
    beginBrushRuntime()
    pushBrushSamples([event])
  } else {
    stamp(point, tabletInputFor(event)?.pressure ?? null)
  }
}

function onPointerMove(event: PointerEvent) {
  if (activePointerId !== null && event.pointerId !== activePointerId) return
  const rect = overlay.value?.getBoundingClientRect()
  if (rect) cursor.value = { x: event.clientX - rect.left, y: event.clientY - rect.top }
  // A few Wacom/Chromium combinations can transition straight from contact to
  // hover without routing pointerup back through the captured canvas. Do not
  // feed those pressure-zero hover samples into the active brush runtime.
  if (drawing && penTipContactLost(event)) {
    releasePointer(event.pointerId)
    activePointerId = null
    if (props.engineId === 'gradient') {
      updateGradient(pointFrom(event), event.shiftKey)
    }
    commitActiveStroke()
    gradientGesture = null
    return
  }
  if (patchDrag) {
    patchDrag.current = pointFrom(event)
    drawOverlay()
    return
  }
  // Fill is a click operation: one click, one flat fill of the selection or
  // layer. Dragging adds nothing to that.
  if (drawing && props.engineId === 'gradient') {
    updateGradient(pointFrom(event), event.shiftKey)
  } else if (drawing && props.engineId !== 'fill') {
    // Chromium throttles pointermove to the frame rate and parks the full-rate
    // samples in getCoalescedEvents; WKWebView may not have the method.
    const coalesced = typeof event.getCoalescedEvents === 'function'
      ? event.getCoalescedEvents()
      : []
    const samples = coalesced.length ? coalesced : [event]
    if (props.engineId === 'paint' || props.engineId === 'erase') {
      pushBrushSamples(samples)
    } else {
      for (const sample of samples) {
        stamp(pointFrom(sample), tabletInputFor(sample)?.pressure ?? null)
      }
    }
  }
}

function releasePointer(pointerId: number) {
  const canvas = overlay.value
  if (canvas?.hasPointerCapture(pointerId)) canvas.releasePointerCapture(pointerId)
}

async function onPointerUp(event: PointerEvent) {
  // Releasing a barrel button is not the end of the gesture: the pen tip is
  // still down. Landing a patch here would apply it mid-drag.
  if (event.button !== 0) return
  if (activePointerId === null || event.pointerId !== activePointerId) return
  releasePointer(event.pointerId)
  activePointerId = null

  if (patchDrag) {
    // The final pointer position is authoritative. A coalesced or lost move
    // must not make the patch land at the last preview frame instead.
    patchDrag.current = pointFrom(event)
    const { start, current, bounds } = patchDrag
    const offset = { x: current.x - start.x, y: current.y - start.y }
    patchDrag = null
    try {
      // A couple of pixels is a click, not a drag — applying it would sample
      // the selection onto itself.
      if (strokeSource && Math.hypot(offset.x, offset.y) > 2) {
        patchPending.value = true
        try {
          await liveStroke.applyPatchTool(strokeSource, offset, bounds)
          finishStroke(true, {
            tool: 'patch',
            source: {
              x: bounds.x + bounds.width / 2 + offset.x,
              y: bounds.y + bounds.height / 2 + offset.y,
            },
            target: {
              x: bounds.x + bounds.width / 2,
              y: bounds.y + bounds.height / 2,
            },
          })
          // The patch consumed the selection; ants over fixed pixels would lie.
          emit('patchApplied')
        } finally {
          patchPending.value = false
        }
      } else {
        liveStroke.endStroke()
        liveStroke.clearLayer()
        strokeSource = null
        strokeAdjustedSource = null
      }
    } finally {
      // Never strand the donor preview if reconstruction throws.
      drawOverlay()
    }
    return
  }

  if (!drawing) return
  if (props.engineId === 'gradient') {
    // The release position is authoritative even when the final move was
    // coalesced. A click is not a gradient and must not create an empty layer.
    if (!updateGradient(pointFrom(event), event.shiftKey, false)) {
      drawing = false
      gradientGesture = null
      liveStroke.endStroke()
      liveStroke.clearLayer()
      strokeSource = null
      strokeAdjustedSource = null
      strokeStart = null
      drawOverlay()
      return
    }
  } else if (props.engineId === 'paint' || props.engineId === 'erase') {
    // Release is authoritative when pointer capture dropped the last move.
    pushBrushSamples([event])
  }
  commitActiveStroke()
  gradientGesture = null
}

/**
 * Pointer capture is not a completion guarantee: WebKit can drop it when the
 * pointer crosses another overlay or leaves the element. The snapshot editor's
 * working gesture path listened on window for this reason. These fallbacks only
 * act when the event was not already retargeted to the captured canvas.
 */
function onWindowPointerMove(event: PointerEvent) {
  if (event.target !== overlay.value && activePointerId === event.pointerId) {
    onPointerMove(event)
  }
}

function onWindowPointerUp(event: PointerEvent) {
  if (event.target !== overlay.value && activePointerId === event.pointerId) {
    void onPointerUp(event)
  }
}

function onPointerCancel(event: PointerEvent) {
  if (activePointerId !== event.pointerId) return
  releasePointer(event.pointerId)
  activePointerId = null
  drawing = false
  brushRuntime = null
  patchDrag = null
  gradientGesture = null
  liveStroke.endStroke()
  liveStroke.clearLayer()
  strokeSource = null
  strokeAdjustedSource = null
  strokeStart = null
  drawOverlay()
}

/** Start a new layer: the next stroke creates the next Paint step. */
function reset() {
  // Invalidate any async hand-off still referring to the previous layer.
  layerRevision += 1
  loadedInitialLayer = null
  pendingPreviews = []
  strokeSource = null
  strokeAdjustedSource = null
  strokeStart = null
  gradientGesture = null
  brushRuntime = null
  liveStroke.clearLayer()
  layer.clearLayer()
  drawOverlay()
}

function resize() {
  const canvas = overlay.value
  if (!canvas || !props.source) return
  canvas.width = props.source.width
  canvas.height = props.source.height
  layer.initLayer({ width: props.source.width, height: props.source.height })
  liveStroke.initLayer({ width: props.source.width, height: props.source.height })
  if (props.initialLayer && props.initialLayer !== loadedInitialLayer) {
    layer.loadFromSnapshot(props.initialLayer)
    loadedInitialLayer = props.initialLayer
  } else if (!props.initialLayer) {
    loadedInitialLayer = null
  }
  drawOverlay()
}

defineExpose({
  reset,
  /**
   * End the live stroke on the host's word.
   *
   * The viewport's middle-drag pan claims that pointerdown in the capture
   * phase and stops it, so this canvas never sees the barrel press that starts
   * a pan. Without being told, the stroke would stay open across the pan and
   * close with a jump in it.
   */
  commitStroke() {
    if (!drawing) return
    if (activePointerId !== null) {
      releasePointer(activePointerId)
      activePointerId = null
    }
    commitActiveStroke()
  },
  /**
   * Remove only the preview revisions the freshly rendered composite now owns.
   * A newer live stroke is a separate canvas, so an older async handoff can
   * never hide it.
   */
  clearDisplay(revision: number) {
    pendingPreviews = pendingPreviews.filter(pending => pending.revision > revision)
    drawOverlay()
  },
})

// Strokes respect the active selection, which is what makes Select → Paint work
// without either side knowing about the other.
watch(() => props.selectionMask, mask => {
  liveStroke.setSelectionMask(mask ? mask.getContext('2d') : null)
}, { immediate: true })

watch(() => props.source, resize)
watch(() => props.initialLayer, resize)
onMounted(() => {
  resize()
  window.addEventListener('pointermove', onWindowPointerMove)
  window.addEventListener('pointerup', onWindowPointerUp)
  window.addEventListener('pointercancel', onPointerCancel)
})
onBeforeUnmount(() => {
  window.removeEventListener('pointermove', onWindowPointerMove)
  window.removeEventListener('pointerup', onWindowPointerUp)
  window.removeEventListener('pointercancel', onPointerCancel)
})
</script>

<template>
  <div class="absolute inset-0">
    <canvas
      ref="overlay"
      class="w-full h-full touch-none"
      :class="patchPending
        ? 'cursor-wait'
        : engineId === 'patch'
        ? (selectionMask ? 'cursor-move' : 'cursor-default')
        : 'cursor-crosshair'"
      :style="{ width: displayWidth + 'px', height: displayHeight + 'px' }"
      @pointerdown="onPointerDown"
      @pointermove="onPointerMove"
      @pointerup="onPointerUp"
      @pointercancel="onPointerCancel"
      @contextmenu.prevent
      @pointerleave="cursor = null"
    />
    <div
      v-if="cursor && brush && !['patch', 'fill', 'gradient'].includes(engineId)"
      class="pointer-events-none absolute rounded-full border border-white/70 mix-blend-difference"
      :style="{
        left: cursor.x - cursorBrushSize / 2 + 'px',
        top: cursor.y - cursorBrushSize * cursorTip.aspect / 2 + 'px',
        width: cursorBrushSize + 'px',
        height: cursorBrushSize * cursorTip.aspect + 'px',
        transform: `rotate(${cursorTip.rotation}deg)`,
      }"
    />
  </div>
</template>
