<script setup lang="ts">
/**
 * The selection overlay: marching ants whenever a selection exists, and the
 * gesture surface while a selection tool is armed.
 *
 * Mounted for the whole life of the display box, not per mode — the selection
 * is workspace state that cuts across every family, so its rendering cannot
 * belong to any one of them. The model itself (`useSelection`) is owned by the
 * HOST and passed in: this component draws and gestures, nothing more, so the
 * selection survives anything that unmounts the overlay (the crop viewport
 * replaces the display box entirely).
 *
 * When no tool is armed the overlay is pointer-transparent: the open family's
 * canvas underneath keeps the pointer, and the ants simply march above it.
 * Arming a tool takes the pointer without touching the family's session.
 *
 * A selection is not a step. It is a value the next gesture consumes: an
 * inpaint mask, a paint clip, an adjustment's region. Always by copy, never
 * live-linked, so an op ends up referencing only its own payload.
 */
import { ref, computed, onMounted, onBeforeUnmount, watch } from 'vue'
import type { useSelection } from '../ported/useSelection'
import { useMagneticLasso } from '../ported/useMagneticLasso'
import type { Point, SelectionMode } from '../ported/geometry'
import type { SelectToolId } from '../stack/toolFamilies'
import {
  DEFAULT_LINEAR_SOFTNESS,
  DEFAULT_RADIAL_FEATHER,
  MIN_GRADIENT_EXTENT,
  gradientMaskCanvas,
  isDegenerate,
  linearMaskFromDrag,
  radialMaskFromDrag,
  shouldShowGradientChrome,
} from '../stack/regionMask'
import {
  fillRectSelection,
  fillEllipseSelection,
  fillLassoSelection,
  featherSelection,
} from '../ported/selection'
import { applySelectionBrushSegment } from '../stack/selectionBrush'
import { combineFromModifiers } from '../stack/selectionLifecycle'
import type { GradientMask } from '../stack/types'
import { fittedBrushScale, overlayBackingSize, zoomedBrushSize } from '../stack/viewportRaster'

const props = withDefaults(defineProps<{
  source: HTMLCanvasElement | null
  displayWidth: number
  displayHeight: number
  /** Fitted-view size used for the backing store; deliberately excludes zoom. */
  renderWidth?: number
  renderHeight?: number
  viewZoom?: number
  /** The host-owned selection model; this component never creates its own. */
  model: ReturnType<typeof useSelection>
  /** The armed tool, or null when the overlay is display-only. */
  armed?: SelectToolId | null
  combine?: SelectionMode
  featherPx?: number
  /** Magic wand color-and-opacity threshold, 0-100. */
  tolerance?: number
  /** Fully opaque extent within the wand threshold, 0-100. */
  wandSpread?: number
  /** Wand mask growth (positive) or shrinkage (negative), in source pixels. */
  wandGrowPx?: number
  /** Smooth hard wand boundaries when feathering is zero. */
  wandAntialias?: boolean
  /** Selection brush diameter in fitted-view pixels, like the paint brush. */
  brushSize?: number
  /** Visual chrome only; the selection model remains intact while hidden. */
  visible?: boolean
  /** An objectPick is being segmented; the cursor says so. */
  busy?: boolean
  /**
   * The selected region's gradient, in source pixels. Present means its
   * handles are on the canvas and draggable — a ramp that cannot be re-dragged
   * after you have seen the grade is not the feature.
   */
  gradient?: GradientMask | null
  /** True when the selected Adjust region owns the rendered result. */
  gradientOwnsResult?: boolean
  /** A gradient falloff slider is being adjusted; show its coverage wash. */
  gradientPreviewing?: boolean
  /** Falloff a newly dragged ramp starts with, from the island's slider. */
  gradientSoftness?: number
  gradientFeather?: number
}>(), {
  armed: null,
  renderWidth: 0,
  renderHeight: 0,
  viewZoom: 1,
  combine: 'new',
  featherPx: 0,
  tolerance: 8,
  wandSpread: 100,
  wandGrowPx: 0,
  wandAntialias: true,
  brushSize: 80,
  visible: true,
  gradient: null,
  gradientOwnsResult: false,
  gradientPreviewing: false,
  gradientSoftness: DEFAULT_LINEAR_SOFTNESS,
  gradientFeather: DEFAULT_RADIAL_FEATHER,
})

const emit = defineEmits<{
  /**
   * The gesture that is ABOUT to publish, as its own coverage — emitted
   * immediately before the `change` it belongs to, so the host can keep the
   * selection as a composition of editable ingredients instead of only the
   * flattened bitmap. Gradient gestures use the `gradient` event (geometry
   * beats a raster); AI masks land through applyMask, which the host owns.
   */
  gestureCapture: [{
    coverage: HTMLCanvasElement
    tool: SelectToolId
    /** The mode the gesture actually combined with — the island's, or the
     *  held-modifier override sampled at gesture start. */
    combine: SelectionMode
  }]
  change: [HTMLCanvasElement | null]
  /** Object tool click, in source pixels; the host runs segmentation and
   *  lands the result through applyMask with the given combine mode. */
  objectPick: [{ x: number; y: number; combine: SelectionMode }]
  /**
   * A NEW ramp, dragged out with a gradient tool armed, in source pixels.
   *
   * Emitted ONCE, on release. While the pointer is down the ramp is a local
   * draft drawn straight to the overlay: persisting each move would re-render
   * the composite at full resolution per mouse event, and the guides — a few
   * lines and dots — would queue up behind seconds of pixel work.
   */
  gradient: [mask: GradientMask, combine: SelectionMode]
  /**
   * An EXISTING ramp re-aimed by its handles, also once on release.
   * Deliberately a different event: dragging a handle must edit the region it
   * belongs to, while dragging out a fresh ramp must make a new one, and one
   * event for both cannot tell them apart.
   */
  gradientEdit: [mask: GradientMask]
}>()

const overlay = ref<HTMLCanvasElement | null>(null)
const selection = props.model
const magnetic = useMagneticLasso()

let drawing = false
/**
 * The one-shot combine override for the CURRENT gesture, from the modifiers
 * held when it started (Shift add, Option subtract, both intersect). Never
 * touches the island's persistent mode; cleared when the gesture ends.
 */
let gestureCombine: SelectionMode | null = null
/** A magnetic lasso spans several clicks; only its FIRST anchor samples. */
let magneticStarted = false

function effectiveCombine(): SelectionMode {
  return gestureCombine ?? props.combine
}
let lastBrushPoint: Point | null = null
/** This gesture's brush path, for live feedback until the ants take over. */
let brushGesture: Point[] = []
/** Opaque intermediate prevents translucent feedback from accumulating where a path overlaps itself. */
let brushFeedback: HTMLCanvasElement | null = null
const cursor = ref<{ x: number; y: number } | null>(null)
let antsTimer: ReturnType<typeof setInterval> | null = null

/** The gradient being dragged out right now, before it is anything persistent. */
const draftGradient = ref<GradientMask | null>(null)
let gradientStart: Point | null = null
/** Which handle of an existing gradient the pointer owns. */
type HandleId = 'lin1' | 'lin2' | 'radc' | 'radx' | 'rady'
let handleDrag: HandleId | null = null
/** A saved gradient's geometry while its handle is being dragged. */
const handleDraft = ref<GradientMask | null>(null)

/**
 * The gradient the canvas should be drawing. A live draft outranks the saved
 * one so the guides track the pointer at pointer speed, with no document write
 * and no render in the loop.
 */
const shownGradient = computed<GradientMask | null>(
  () => draftGradient.value ?? handleDraft.value ?? props.gradient
)

/** Workspace selection chrome is tool-scoped; adjustment chrome is step-owned. */
const gradientChromeVisible = computed(() => {
  const mask = shownGradient.value
  return !!mask && props.visible
    && shouldShowGradientChrome(mask, props.armed, props.gradientOwnsResult)
})

const scale = computed(() =>
  props.source ? props.source.width / Math.max(1, props.displayWidth) : 1
)
const brushScale = computed(() =>
  props.source
    ? fittedBrushScale(props.source.width, props.displayWidth, props.viewZoom)
    : 1
)
const cursorBrushSize = computed(() => zoomedBrushSize(props.brushSize, props.viewZoom))

function pointFrom(event: PointerEvent): Point {
  const rect = overlay.value!.getBoundingClientRect()
  return {
    x: (event.clientX - rect.left) * scale.value,
    y: (event.clientY - rect.top) * scale.value,
  }
}

/**
 * Feather is skipped for brush gestures: the brush tip carries its own soft
 * edge, and a brush stroke publishes per gesture — re-feathering the whole
 * mask on each one would accumulate blur.
 */
function publish(applyFeather = true) {
  if (applyFeather && props.featherPx > 0) selection.feather(props.featherPx)
  selection.updateMarchingAnts()
  draw()
  emit('change', selection.hasSelection() ? selection.getSelectionMask() : null)
}

/**
 * Rasterise the gesture that just finished, ALONE, and hand it up before the
 * flattened selection publishes. `fill` draws the gesture's coverage into an
 * empty source-sized alpha canvas; feather matches what publish() will do to
 * the combined mask, so the ingredient reads like its combination.
 */
function captureGesture(
  fill: (ctx: CanvasRenderingContext2D) => void,
  applyFeather = true,
) {
  if (!props.source || !props.armed) return
  const canvas = document.createElement('canvas')
  canvas.width = props.source.width
  canvas.height = props.source.height
  const ctx = canvas.getContext('2d', { willReadFrequently: true })!
  fill(ctx)
  if (applyFeather && props.featherPx > 0) featherSelection(ctx, props.featherPx)
  emit('gestureCapture', {
    coverage: canvas,
    tool: props.armed,
    combine: effectiveCombine(),
  })
}

/**
 * Replay this drag's brush path into a gesture-only coverage canvas — the
 * same per-segment compact regions the live stroke used, because the segment
 * shader scans whatever region it is given.
 */
function captureBrushGesture(points: Point[]) {
  if (!props.source || !points.length) return
  const radius = (props.brushSize * brushScale.value) / 2
  captureGesture(ctx => {
    let from: Point | null = null
    for (const to of points) {
      const start = from ?? to
      const minX = Math.max(0, Math.floor(Math.min(start.x, to.x) - radius))
      const minY = Math.max(0, Math.floor(Math.min(start.y, to.y) - radius))
      const maxX = Math.min(ctx.canvas.width, Math.ceil(Math.max(start.x, to.x) + radius))
      const maxY = Math.min(ctx.canvas.height, Math.ceil(Math.max(start.y, to.y) + radius))
      const width = maxX - minX
      const height = maxY - minY
      if (width > 0 && height > 0) {
        const region = ctx.getImageData(minX, minY, width, height)
        applySelectionBrushSegment(
          region.data,
          width,
          height,
          from ? { x: from.x - minX, y: from.y - minY } : null,
          { x: to.x - minX, y: to.y - minY },
          radius,
          0.6,
          'add',
        )
        ctx.putImageData(region, minX, minY)
      }
      from = to
    }
  }, false)
}

// -- gestures ---------------------------------------------------------------

function onPointerDown(event: PointerEvent) {
  if (!props.source || !props.armed) return
  // A pen's barrel buttons press the same pointer the gesture is using. Left
  // unguarded they restart the selection mid-drag, throwing away the lasso or
  // marquee in progress.
  if (event.button !== 0) return
  const point = pointFrom(event)
  // Photoshop's grammar: the modifiers held at the PRESS pick the combine
  // mode for this one gesture. Shift during the drag still constrains.
  const override = combineFromModifiers(event.shiftKey, event.altKey)

  // Object select is a click, not a drag: hand the point to the host and let
  // the async mask land through applyMask when segmentation returns.
  if (props.armed === 'object') {
    emit('objectPick', {
      x: point.x,
      y: point.y,
      combine: override ?? props.combine,
    })
    return
  }

  // A gradient is dragged out: press where the effect is strongest, release
  // where it has died away entirely.
  if (props.armed === 'linear' || props.armed === 'radial') {
    drawing = true
    gestureCombine = override
    overlay.value?.setPointerCapture(event.pointerId)
    gradientStart = point
    draftGradient.value = gradientFrom(point, point)
    draw()
    return
  }

  drawing = true
  overlay.value?.setPointerCapture(event.pointerId)

  if (props.armed === 'wand') {
    const combine = override ?? props.combine
    const ctx = props.source.getContext('2d', { willReadFrequently: true })
    if (ctx) {
      const gesture = selection.magicWandSelect(ctx, point, {
        threshold: props.tolerance,
        spread: props.wandSpread,
        growPx: props.wandGrowPx,
        featherPx: props.featherPx,
        antialias: props.wandAntialias,
      }, combine)
      // The wand's refined mask is already the gesture alone; no re-feather.
      if (gesture) emit('gestureCapture', { coverage: gesture, tool: 'wand', combine })
    }
    drawing = false
    // The wand refines its temporary mask before combining it. Publishing
    // must not feather the accumulated selection a second time.
    publish(false)
    return
  }
  if (props.armed === 'brush') {
    gestureCombine = override
    // `New` replaces per GESTURE, so the first stroke starts over and further
    // strokes of the same drag extend it — matching how every brush works.
    if (effectiveCombine() === 'new') selection.clearSelection()
    lastBrushPoint = null
    brushGesture = []
    brushTo(point)
    return
  }
  if (props.armed === 'magnetic') {
    // The live-wire traces edges from a gradient map of the image, so it has to
    // be initialised against whatever the step is being drawn over.
    if (!magnetic.isReady()) magnetic.initialize(props.source)
    // The whole multi-click lasso is one gesture; its first anchor's
    // modifiers pick the mode.
    if (!magneticStarted) {
      magneticStarted = true
      gestureCombine = override
    }
    // placeAnchor returns true when the click closed the loop on the first
    // anchor, which is the gesture that finishes a magnetic lasso.
    if (magnetic.placeAnchor(point)) closeMagnetic()
    draw()
    startAnts()
    return
  }
  gestureCombine = override
  if (props.armed === 'rect') selection.startRectSelection(point)
  else if (props.armed === 'ellipse') selection.startEllipseSelection(point)
  else selection.startLassoSelection(point)
  startAnts()
}

function onPointerMove(event: PointerEvent) {
  const rect = overlay.value?.getBoundingClientRect()
  if (rect && props.armed === 'brush') {
    cursor.value = { x: event.clientX - rect.left, y: event.clientY - rect.top }
  }
  if (!drawing || !props.source || !props.armed) return
  const point = pointFrom(event)
  if (props.armed === 'linear' || props.armed === 'radial') {
    if (!gradientStart) return
    // Draw only. Nothing is persisted and nothing is rendered until release.
    draftGradient.value = gradientFrom(gradientStart, point)
    draw()
    return
  }
  if (props.armed === 'brush') brushTo(point)
  else if (props.armed === 'magnetic') magnetic.updatePreview(point)
  else if (props.armed === 'rect') selection.updateRectSelection(point, effectiveCombine(), event.shiftKey)
  else if (props.armed === 'ellipse') selection.updateEllipseSelection(point, effectiveCombine(), event.shiftKey)
  else selection.continueLassoSelection(point)
  if (props.armed !== 'brush') draw()
}

function onPointerUp(event: PointerEvent) {
  // A barrel-button release is not the end of the drag; the tip is still down.
  if (event.button !== 0) return
  if (!drawing || !props.armed) return
  const point = pointFrom(event)
  overlay.value?.releasePointerCapture(event.pointerId)

  // A magnetic lasso closes on its own anchors, not on pointer-up.
  if (props.armed === 'magnetic') { draw(); return }
  if (props.armed === 'linear' || props.armed === 'radial') {
    drawing = false
    const mask = gradientStart ? gradientFrom(gradientStart, point) : null
    gradientStart = null
    draftGradient.value = null
    // A tap, or a ramp too short to read as one, is a miss rather than an
    // invisible region: nothing was persisted during the drag, so leaving the
    // selection exactly as it was is all it takes.
    if (!mask || !gradientWorthKeeping(mask)) {
      gestureCombine = null
      draw()
      return
    }
    commitGradient(mask)
    return
  }
  drawing = false
  if (props.armed === 'brush') {
    captureBrushGesture(brushGesture)
    lastBrushPoint = null
    brushGesture = []
    gestureCombine = null
    publish(false)
    return
  }
  if (props.armed === 'rect') {
    const shape = selection.finishRectSelection(point, effectiveCombine(), event.shiftKey)
    if (shape) {
      captureGesture(ctx =>
        fillRectSelection(ctx, shape.x, shape.y, shape.width, shape.height, 'new'))
    }
  } else if (props.armed === 'ellipse') {
    const shape = selection.finishEllipseSelection(point, effectiveCombine(), event.shiftKey)
    if (shape) {
      captureGesture(ctx => fillEllipseSelection(
        ctx, shape.centerX, shape.centerY, shape.radiusX, shape.radiusY, 'new'))
    }
  } else {
    const path = selection.finishLassoSelection(effectiveCombine())
    if (path) captureGesture(ctx => fillLassoSelection(ctx, path, 'new'))
  }
  gestureCombine = null
  stopAnts()
  publish()
}

// -- gradients --------------------------------------------------------------

function gradientFrom(from: Point, to: Point): GradientMask {
  return props.armed === 'radial'
    ? radialMaskFromDrag(from, to, { feather: props.gradientFeather })
    : linearMaskFromDrag(from, to, props.gradientSoftness)
}

/** How big the gradient is on the shorter axis, for the too-small check. */
function gradientExtent(mask: GradientMask): number {
  return mask.kind === 'linear'
    ? Math.hypot(mask.x2 - mask.x1, mask.y2 - mask.y1)
    : Math.min(mask.rx, mask.ry)
}

function gradientWorthKeeping(mask: GradientMask): boolean {
  return !isDegenerate(mask) && gradientExtent(mask) >= MIN_GRADIENT_EXTENT * scale.value
}

/**
 * A gradient lands in TWO places, and both matter.
 *
 * The selection buffer gets a rasterised copy, so every existing consumer —
 * Repaint, Remove, inpaint, a paint clip — takes a soft ramp without knowing
 * gradients exist. The host separately gets the geometry, which is what a
 * masked-adjustment region persists so its handles stay live.
 */
function commitGradient(mask: GradientMask) {
  const combine = effectiveCombine()
  if (props.source) {
    selection.applyMaskCanvas(
      gradientMaskCanvas(mask, props.source.width, props.source.height),
      combine,
    )
  }
  emit('gradient', mask, combine)
  gestureCombine = null
  // The ramp IS the edge treatment; feathering it again only blurs a blur.
  publish(false)
}

function gradientHandles(mask: GradientMask): Array<{ id: HandleId; x: number; y: number }> {
  if (mask.kind === 'linear') {
    return [
      { id: 'lin1', x: mask.x1, y: mask.y1 },
      { id: 'lin2', x: mask.x2, y: mask.y2 },
    ]
  }
  return [
    { id: 'radc', x: mask.cx, y: mask.cy },
    { id: 'radx', x: mask.cx + mask.rx, y: mask.cy },
    { id: 'rady', x: mask.cx, y: mask.cy + mask.ry },
  ]
}

/** Handle positions in DISPLAY pixels, for the DOM grab targets. */
const handlePoints = computed(() => {
  const mask = shownGradient.value
  if (!mask || !gradientChromeVisible.value) return []
  return gradientHandles(mask).map(handle => ({
    id: handle.id,
    left: handle.x / scale.value,
    top: handle.y / scale.value,
    // Only the ellipse's centre moves the whole mask. A linear ramp has no
    // centre — dragging either end re-aims it — so neither end claims to.
    move: handle.id === 'radc',
  }))
})

function moveGradientHandle(id: HandleId, point: Point): GradientMask | null {
  const mask = props.gradient
  if (!mask) return null
  if (mask.kind === 'linear') {
    return id === 'lin1'
      ? { ...mask, x1: point.x, y1: point.y }
      : { ...mask, x2: point.x, y2: point.y }
  }
  if (id === 'radc') return { ...mask, cx: point.x, cy: point.y }
  if (id === 'radx') return { ...mask, rx: Math.max(1, Math.abs(point.x - mask.cx)) }
  return { ...mask, ry: Math.max(1, Math.abs(point.y - mask.cy)) }
}

function onHandleDown(id: HandleId, event: PointerEvent) {
  if (!props.gradient) return
  event.stopPropagation()
  event.preventDefault()
  handleDrag = id
  ;(event.target as HTMLElement).setPointerCapture(event.pointerId)
}

function onHandleMove(event: PointerEvent) {
  if (!handleDrag || !props.source) return
  // Same rule as creation: move the guides, touch no pixels.
  const next = moveGradientHandle(handleDrag, pointFromClient(event))
  if (!next) return
  handleDraft.value = next
  draw()
}

function onHandleUp(event: PointerEvent) {
  if (!handleDrag) return
  const next = moveGradientHandle(handleDrag, pointFromClient(event)) ?? handleDraft.value
  handleDrag = null
  handleDraft.value = null
  if (!next || isDegenerate(next)) { draw(); return }
  emit('gradientEdit', next)
}

/** Handle drags land on a DOM node, so the overlay rect is the shared frame. */
function pointFromClient(event: PointerEvent): Point {
  const rect = overlay.value!.getBoundingClientRect()
  return {
    x: (event.clientX - rect.left) * scale.value,
    y: (event.clientY - rect.top) * scale.value,
  }
}

function brushTo(point: Point) {
  const radius = (props.brushSize * brushScale.value) / 2
  selection.brushStroke(lastBrushPoint, point, radius, effectiveCombine())
  lastBrushPoint = point
  brushGesture.push(point)
  draw()
}

/** Double-click, or clicking the first anchor, closes a magnetic lasso. */
function onDoubleClick() {
  if (props.armed === 'magnetic') closeMagnetic()
}

function closeMagnetic() {
  const path = magnetic.closeSelection()
  if (path.length > 2) {
    const committed = selection.createMagneticLassoSelection(path, effectiveCombine())
    if (committed) captureGesture(ctx => fillLassoSelection(ctx, committed, 'new'))
  }
  magnetic.cancel()
  magneticStarted = false
  gestureCombine = null
  drawing = false
  stopAnts()
  publish()
}

// -- painting ---------------------------------------------------------------

function draw() {
  const canvas = overlay.value
  if (!canvas || !props.source) return
  const ctx = canvas.getContext('2d')!
  // The overlay is display chrome, not the authoritative selection mask. Its
  // backing store is viewport-sized (see resizeOverlay), while every geometry
  // value remains in source pixels. Map source space onto the smaller backing
  // store so a 24 MP photo does not make every ants tick, tool switch, and
  // gradient pointer move repaint 24 million invisible pixels.
  ctx.setTransform(1, 0, 0, 1, 0, 0)
  ctx.clearRect(0, 0, canvas.width, canvas.height)
  if (!props.visible) return
  ctx.setTransform(
    canvas.width / Math.max(1, props.source.width), 0,
    0, canvas.height / Math.max(1, props.source.height), 0, 0,
  )

  drawGradientDragPreview(ctx)

  // Live feedback for a brush gesture: rasterize the path opaquely first, then
  // apply one translucent wash. Stroking with the translucent color directly
  // makes self-overlaps visibly darker even though they are one selection.
  if (drawing && props.armed === 'brush' && brushGesture.length) {
    if (!brushFeedback) brushFeedback = document.createElement('canvas')
    if (brushFeedback.width !== canvas.width) brushFeedback.width = canvas.width
    if (brushFeedback.height !== canvas.height) brushFeedback.height = canvas.height
    const feedbackCtx = brushFeedback.getContext('2d')!
    feedbackCtx.clearRect(0, 0, brushFeedback.width, brushFeedback.height)
    feedbackCtx.save()
    feedbackCtx.setTransform(
      brushFeedback.width / Math.max(1, props.source.width), 0,
      0, brushFeedback.height / Math.max(1, props.source.height), 0, 0,
    )
    feedbackCtx.strokeStyle = '#fff'
    feedbackCtx.lineWidth = props.brushSize * brushScale.value
    feedbackCtx.lineCap = 'round'
    feedbackCtx.lineJoin = 'round'
    feedbackCtx.beginPath()
    feedbackCtx.moveTo(brushGesture[0].x, brushGesture[0].y)
    // A tap has one point; the lineTo-self plus round caps makes it a dot.
    if (brushGesture.length === 1) {
      feedbackCtx.lineTo(brushGesture[0].x, brushGesture[0].y)
    }
    for (const point of brushGesture.slice(1)) feedbackCtx.lineTo(point.x, point.y)
    feedbackCtx.stroke()
    feedbackCtx.globalCompositeOperation = 'source-in'
    feedbackCtx.fillStyle = effectiveCombine() === 'subtract'
      ? 'rgba(0,0,0,0.3)' : 'rgba(255,255,255,0.3)'
    feedbackCtx.fillRect(0, 0, props.source.width, props.source.height)
    feedbackCtx.restore()
    ctx.save()
    ctx.setTransform(1, 0, 0, 1, 0, 0)
    ctx.drawImage(brushFeedback, 0, 0)
    ctx.restore()
  }

  ctx.save()
  ctx.lineWidth = Math.max(1, scale.value)

  // A parametric gradient keeps its guides and handles instead of degrading
  // to the outline of its raster fallback. Ordinary selections keep ants.
  if (!shownGradient.value) {
    for (const path of selection.marchingAntsPaths.value) {
      if (path.length < 2) continue
      ctx.beginPath()
      ctx.moveTo(path[0].x, path[0].y)
      for (const point of path.slice(1)) ctx.lineTo(point.x, point.y)
      ctx.closePath()
      ctx.strokeStyle = '#000'
      ctx.setLineDash([])
      ctx.stroke()
      ctx.strokeStyle = '#fff'
      ctx.setLineDash([5 * scale.value, 5 * scale.value])
      ctx.lineDashOffset = -selection.antsOffset.value
      ctx.stroke()
    }
  }

  // The gesture in progress.
  ctx.setLineDash([4 * scale.value, 3 * scale.value])
  ctx.strokeStyle = '#fff'
  if (props.armed === 'magnetic') {
    const preview = magnetic.getAllPoints()
    if (preview.length > 1) {
      ctx.beginPath()
      ctx.moveTo(preview[0].x, preview[0].y)
      for (const point of preview.slice(1)) ctx.lineTo(point.x, point.y)
      ctx.stroke()
    }
  } else if (drawing) {
    const points = selection.drawingPoints.value
    const start = selection.drawingStartPoint.value
    const current = selection.drawingCurrentPoint.value
    if ((props.armed === 'rect') && start && current) {
      ctx.strokeRect(
        Math.min(start.x, current.x), Math.min(start.y, current.y),
        Math.abs(current.x - start.x), Math.abs(current.y - start.y)
      )
    } else if (props.armed === 'ellipse' && start && current) {
      ctx.beginPath()
      ctx.ellipse(
        (start.x + current.x) / 2, (start.y + current.y) / 2,
        Math.abs(current.x - start.x) / 2, Math.abs(current.y - start.y) / 2,
        0, 0, Math.PI * 2
      )
      ctx.stroke()
    } else if (points.length > 1) {
      ctx.beginPath()
      ctx.moveTo(points[0].x, points[0].y)
      for (const point of points.slice(1)) ctx.lineTo(point.x, point.y)
      ctx.stroke()
    }
  }
  ctx.restore()

  drawGradientGuides(ctx)
}

/**
 * A gradient has no ants to march: its whole point is that there is no edge.
 * The guides ARE the boundary readout — where full strength ends and where the
 * ramp has died — so they are drawn in the accent rather than as a dashed
 * selection, and they stop at the frame the way the image does.
 */
function drawGradientGuides(ctx: CanvasRenderingContext2D) {
  const mask = shownGradient.value
  if (!mask || !props.visible || !props.source) return
  const sourceWidth = props.source.width
  const sourceHeight = props.source.height
  const line = Math.max(1, scale.value)
  const interactive = gradientChromeVisible.value

  ctx.save()
  ctx.beginPath()
  ctx.rect(0, 0, sourceWidth, sourceHeight)
  ctx.clip()
  // Teal accent. Canvas takes no design tokens, so this matches --accent the
  // way the ants above match plain white.
  ctx.strokeStyle = '#2dd4bf'
  // A workspace selection remains legible after Paint takes the pointer, but
  // quieter chrome plus no handles makes it clear that the pixels underneath
  // are not being edited parametrically.
  ctx.globalAlpha = interactive ? 1 : 0.48
  ctx.lineWidth = line

  if (mask.kind === 'linear') {
    const dx = mask.x2 - mask.x1
    const dy = mask.y2 - mask.y1
    const length = Math.hypot(dx, dy) || 1
    // Perpendicular, long enough to cross any frame at any angle.
    const span = (sourceWidth + sourceHeight) * 1.5
    const px = (-dy / length) * span
    const py = (dx / length) * span
    const rail = (x: number, y: number, dashed: boolean) => {
      ctx.setLineDash(dashed ? [7 * line, 5 * line] : [])
      ctx.beginPath()
      ctx.moveTo(x + px, y + py)
      ctx.lineTo(x - px, y - py)
      ctx.stroke()
    }
    // Solid where the effect is at full strength, dashed where it has ended.
    rail(mask.x1, mask.y1, false)
    rail(mask.x2, mask.y2, true)
    ctx.setLineDash([])
    ctx.globalAlpha = interactive ? 0.55 : 0.28
    ctx.beginPath()
    ctx.moveTo(mask.x1, mask.y1)
    ctx.lineTo(mask.x2, mask.y2)
    ctx.stroke()
  } else {
    ctx.setLineDash([7 * line, 5 * line])
    ctx.beginPath()
    ctx.ellipse(mask.cx, mask.cy, mask.rx, mask.ry, 0, 0, Math.PI * 2)
    ctx.stroke()
    // The inner ring is where the feather starts, so the falloff is legible.
    const inner = 1 - Math.max(0.02, Math.min(1, mask.feather / 100))
    ctx.setLineDash([])
    ctx.globalAlpha = interactive ? 0.45 : 0.24
    ctx.beginPath()
    ctx.ellipse(mask.cx, mask.cy, mask.rx * inner, mask.ry * inner, 0, 0, Math.PI * 2)
    ctx.stroke()
  }
  ctx.restore()
}

/**
 * Preview coverage while geometry or falloff is moving. Once the gesture is
 * released, the wash drops away and the guides become the selection readout;
 * after Paint takes the pointer those guides remain, without editable handles.
 * Native canvas gradients keep pointer-move feedback cheap at display resolution.
 */
function drawGradientDragPreview(ctx: CanvasRenderingContext2D) {
  const mask = shownGradient.value
  if (!mask || !props.source) return

  // Geometry previews are tool-local: a persisted adjustment already renders
  // its result, and inactive tools do not paint a workspace wash. A falloff
  // slider is explicit, though, and needs the same coverage readout even when
  // it lives in the selected region's inspector and no gradient tool is armed.
  const geometryMoving = !!draftGradient.value || !!handleDraft.value
  const showGeometry = geometryMoving
    && !props.gradientOwnsResult
    && props.armed === mask.kind
  if (!showGeometry && !props.gradientPreviewing) return

  const colorAt = (coverage: number) =>
    `rgba(45, 212, 191, ${Math.max(0, Math.min(1, coverage)) * 0.22})`

  ctx.save()
  if (mask.kind === 'linear') {
    if (Math.hypot(mask.x2 - mask.x1, mask.y2 - mask.y1) < 1) {
      ctx.restore()
      return
    }
    const gradient = ctx.createLinearGradient(mask.x1, mask.y1, mask.x2, mask.y2)
    const ease = Math.max(0, Math.min(1, mask.softness / 100))
    // Sample the eased ramp into native color stops. Canvas interpolates the
    // short gaps on the GPU instead of rasterising the whole mask in JS.
    for (let step = 0; step <= 12; step++) {
      const t = step / 12
      const smooth = t * t * (3 - 2 * t)
      const ramp = smooth * ease + t * (1 - ease)
      gradient.addColorStop(t, colorAt(1 - ramp))
    }
    ctx.fillStyle = gradient
    ctx.fillRect(0, 0, props.source.width, props.source.height)
  } else {
    if (mask.rx < 1 || mask.ry < 1) {
      ctx.restore()
      return
    }
    const gradient = ctx.createRadialGradient(0, 0, 0, 0, 0, 1)
    const feather = Math.max(0.02, Math.min(1, mask.feather / 100))
    const inner = 1 - feather
    for (let step = 0; step <= 12; step++) {
      const distance = step / 12
      const t = Math.max(0, Math.min(1, (distance - inner) / feather))
      const inside = 1 - t * t * (3 - 2 * t)
      gradient.addColorStop(distance, colorAt(mask.invert ? 1 - inside : inside))
    }
    ctx.translate(mask.cx, mask.cy)
    ctx.scale(mask.rx, mask.ry)
    ctx.fillStyle = gradient
    ctx.fillRect(
      -mask.cx / mask.rx,
      -mask.cy / mask.ry,
      props.source.width / mask.rx,
      props.source.height / mask.ry,
    )
  }
  ctx.restore()
}

function startAnts() {
  if (antsTimer) return
  antsTimer = setInterval(() => {
    selection.antsOffset.value = (selection.antsOffset.value + 1) % 10
    draw()
  }, 90)
}
function stopAnts() {
  if (antsTimer) { clearInterval(antsTimer); antsTimer = null }
}

function clear() {
  selection.clearSelection()
  magnetic.cancel()
  magneticStarted = false
  gestureCombine = null
  publish()
}

/** Invert and feather are selection-wide verbs the options bar offers. */
function invert() {
  selection.invert()
  publish(false)
}

/** Grow/contract the live workspace mask, then publish it like any gesture. */
function morph(deltaPx: number) {
  selection.morph(deltaPx)
  publish(false)
}

/**
 * Land an externally produced mask (AI select) as this gesture's selection,
 * through the same combine-and-publish path a drawn gesture takes.
 */
function applyMask(mask: CanvasImageSource, mode: SelectionMode) {
  selection.applyMaskCanvas(mask, mode)
  publish()
}

/** Re-rasterize a live workspace gradient after a handle or slider edit. */
function replaceGradient(mask: GradientMask) {
  if (!props.source) return
  selection.applyMaskCanvas(
    gradientMaskCanvas(mask, props.source.width, props.source.height),
    'new',
  )
  publish(false)
}

function resizeOverlay() {
  const canvas = overlay.value
  if (!canvas) return
  // Match the annotation overlay: crisp at normal/high DPI, but never let a
  // very dense monitor turn display chrome back into a source-sized hot path.
  const { width, height } = overlayBackingSize(
    props.renderWidth || props.displayWidth,
    props.renderHeight || props.displayHeight,
    window.devicePixelRatio || 1,
  )
  if (canvas.width !== width) canvas.width = width
  if (canvas.height !== height) canvas.height = height
}

function resize() {
  if (!props.source) return
  resizeOverlay()
  selection.initSelection({ width: props.source.width, height: props.source.height })
  // The gradient map is per-image; drop it when the composite underneath moves.
  magnetic.invalidate()
  draw()
}

defineExpose({
  clear,
  invert,
  morph,
  applyMask,
  replaceGradient,
  redraw: draw,
  selectionCanvas: () => (selection.hasSelection() ? selection.getSelectionMask() : null),
})

watch(() => props.source, resize)
watch([() => props.displayWidth, () => props.displayHeight], () => {
  resizeOverlay()
  draw()
})
watch([() => props.renderWidth, () => props.renderHeight], () => {
  resizeOverlay()
  draw()
})
watch(() => props.armed, armed => {
  if (!armed) {
    magnetic.cancel()
    drawing = false
    cursor.value = null
  }
  // A tool change ends whatever gesture the modifiers were speaking about.
  magneticStarted = false
  gestureCombine = null
  draftGradient.value = null
  handleDraft.value = null
  gradientStart = null
  draw()
})
// The saved gradient is the host's value; its guides must follow it whether it
// moved by handle, by slider, or by undo.
watch(() => props.gradient, draw, { deep: true })
watch(() => props.gradientOwnsResult, draw)
watch(() => props.gradientPreviewing, draw)
watch(() => props.visible, draw)
// Marching ants animate whenever there IS a selection, not only while drawing.
watch([
  () => selection.marchingAntsPaths.value.length,
  () => props.visible,
  () => !!props.gradient,
], ([length, visible, hasGradient]) => {
  // Gradient selections have stationary guides/coverage instead of ants, so
  // they should not keep an otherwise invisible 11fps animation timer alive.
  if (length && visible && !hasGradient) startAnts()
  else stopAnts()
}, { immediate: true })
onMounted(resize)
onBeforeUnmount(stopAnts)
</script>

<template>
  <div
    class="absolute inset-0"
    :class="armed && visible ? '' : 'pointer-events-none'"
  >
    <canvas
      ref="overlay"
      class="w-full h-full touch-none"
      :class="armed && visible ? (busy ? 'cursor-progress' : 'cursor-crosshair') : ''"
      :style="{ width: displayWidth + 'px', height: displayHeight + 'px' }"
      @pointerdown="onPointerDown"
      @pointermove="onPointerMove"
      @pointerup="onPointerUp"
      @pointerleave="cursor = null"
      @dblclick="onDoubleClick"
    />
    <!--
      Gradient handles. DOM nodes rather than canvas hit-testing so they can be
      grabbed while NO tool is armed — re-dragging a saved ramp must not require
      re-arming its tool — without the overlay swallowing clicks meant for the
      family canvas underneath.
    -->
    <button
      v-for="handle in handlePoints"
      :key="handle.id"
      type="button"
      class="pointer-events-auto absolute rounded-full border-2 transition-colors
             focus-visible:outline-none focus-visible:ring-2 ring-accent/60"
      :class="[
        handle.move
          ? 'bg-accent border-base w-3.5 h-3.5 cursor-move'
          : 'bg-base border-accent w-3 h-3 cursor-grab active:cursor-grabbing',
      ]"
      :style="{
        left: handle.left + 'px',
        top: handle.top + 'px',
        transform: 'translate(-50%, -50%)',
      }"
      :aria-label="handle.move ? 'Move the gradient' : 'Re-aim the gradient'"
      @pointerdown="onHandleDown(handle.id, $event)"
      @pointermove="onHandleMove"
      @pointerup="onHandleUp"
    />
    <!-- Brush outline: the only reliable size feedback while painting. -->
    <div
      v-if="visible && cursor && armed === 'brush'"
      class="pointer-events-none absolute rounded-full border border-white/70 mix-blend-difference"
      :style="{
        left: cursor.x - cursorBrushSize / 2 + 'px',
        top: cursor.y - cursorBrushSize / 2 + 'px',
        width: cursorBrushSize + 'px',
        height: cursorBrushSize + 'px',
      }"
    />
  </div>
</template>
