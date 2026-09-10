<script setup lang="ts">
/**
 * Place vector annotations: pen, arrows, shapes, text, redaction.
 *
 * Annotate is a container op with parametric physics — the shapes ARE the
 * params, so re-rendering at any size is free and re-entering the step is
 * lossless.
 *
 * The gestures and the renderer are the snapshot editor's, copied into
 * `imageEditor/ported/`: the arrow that smooths as you drag it, neon glow and
 * gradient paints, canvas-native text editing with a real caret, hit testing,
 * resize handles and rotation. That composable reaches the outside world only
 * through getState / updateState / pushHistory, which is exactly the seam the
 * op stack needs — the state it asks for is the op's payload, and pushHistory
 * is a journal entry.
 *
 * This component is the adapter between those two and nothing else.
 */
import { ref, computed, watch, onMounted, onBeforeUnmount, nextTick } from 'vue'
import { useAnnotation } from '../ported/useAnnotation'
import type { AnnotationState } from '../ported/useAnnotation'
import { renderShapes, drawSelectionHandles, getShapeBounds, getShapeCenter } from '../ported/shapes'
import { rotatedBounds } from '../ported/annotationSelection'
import type { Shape, AnnotateTool, Paint } from '../ported/shapeTypes'
import type { Color, ViewTransform } from '../ported/geometry'
import { textStyleAnnotationState } from '../stack/textStyles'
import type { TextStyleId } from '../stack/textStyles'
import { overlayBackingSize } from '../stack/viewportRaster'

const props = withDefaults(defineProps<{
  source: HTMLCanvasElement | null
  /** The op's shapes. Owned by the stack; this component proposes changes. */
  shapes: Shape[]
  displayWidth: number
  displayHeight: number
  /** Fitted-view size used for the backing store; deliberately excludes zoom. */
  renderWidth?: number
  renderHeight?: number
  tool?: AnnotateTool
  /** Stroke and fill are paints: a flat color or a gradient. */
  strokeColor?: Paint
  fillColor?: Paint | null
  strokeWidth?: number
  textStyle?: TextStyleId
  /** Universal shape effect for NEW shapes — the toolbar's None/Neon. */
  shapeEffect?: 'none' | 'neon'
  /** Initial opacity for NEW shapes, 0-1. */
  opacity?: number
}>(), {
  tool: 'arrow',
  renderWidth: 0,
  renderHeight: 0,
  strokeColor: () => ({ r: 255, g: 255, b: 255, a: 1 }),
  fillColor: null,
  // Pixels, not normalized: the renderer converts positions and sizes out of
  // 0-1 space but assigns strokeWidth to lineWidth directly. A normalized value
  // here draws a sub-pixel line that looks like nothing rendered at all.
  strokeWidth: 8,
  textStyle: 'pill',
  shapeEffect: 'none',
  opacity: 1,
})

const emit = defineEmits<{
  /** The whole shape list after a gesture — shapes move and die, not just appear. */
  change: [Shape[]]
  /** A gesture finished and is worth an undo step. */
  commit: [string]
  /** Selection changed, so the inspector can follow it. */
  select: [string | null]
}>()

const overlay = ref<HTMLCanvasElement | null>(null)

// -- the state the ported composable reads and writes -----------------------

const selectedShapeId = ref<string | null>(null)
const selectedShapeIds = ref<string[]>([])

/**
 * The live shape list.
 *
 * Props cannot serve here. Vue pushes props during the parent's next render,
 * so within one gesture handler `props.shapes` still holds the pre-gesture
 * list — and the ported code reads its own state back inside a single tick.
 * Creating a text box does exactly that: it appends the shape and immediately
 * looks it up to start editing, which silently found nothing and left the box
 * empty and uneditable. The list is therefore owned here and mirrored out.
 */
const shapes = ref<Shape[]>([])
watch(() => props.shapes, incoming => {
  // Only adopt a list this component did not just produce, so a stale prop
  // arriving a tick late cannot roll a gesture back.
  if (incoming !== shapes.value) shapes.value = incoming
  const live = new Set(incoming.map(shape => shape.id))
  const selected = selectedShapeIds.value.filter(id => live.has(id))
  if (selected.length !== selectedShapeIds.value.length) {
    selectedShapeIds.value = selected
    if (selectedShapeId.value && !live.has(selectedShapeId.value)) {
      selectedShapeId.value = selected.at(-1) ?? null
      emit('select', selectedShapeId.value)
    }
  }
}, { immediate: true })

/**
 * Publish the finished local edit to the document.
 *
 * Pointer moves and text keystrokes deliberately stay inside this adapter:
 * the overlay already owns and paints the live shape list, while publishing
 * every intermediate value makes the persistent stack, journal, autosave and
 * compositor all do work that cannot improve the live preview. Mouseup (or
 * ending a text session) is the transaction boundary.
 */
function commitChanges(action: string) {
  emit('change', shapes.value)
  emit('commit', action)
}

/**
 * Text presets, which the old editor expressed as raw style fields. The
 * mapping lives in textStyles.ts because the inspector needs the same one —
 * a preset spans four properties, so two hand-written copies drift.
 */
const textPreset = computed(() =>
  textStyleAnnotationState(props.textStyle, props.strokeColor)
)

function getState(): AnnotationState {
  return {
    activeTool: props.tool,
    annotations: shapes.value,
    selectedShapeId: selectedShapeId.value,
    selectedShapeIds: selectedShapeIds.value,
    annotateStrokeColor: props.strokeColor,
    annotateFillColor: props.fillColor,
    annotateStrokeWidth: props.strokeWidth,
    annotateOpacity: props.opacity,
    annotateShapeEffect: props.shapeEffect,
    annotateGlowIntensity: 70,
    annotateTextFontFamily: 'Inter, system-ui, sans-serif',
    annotateTextAlign: 'center',
    annotateRedactBlockSize: 16,
    ...textPreset.value,
  }
}

/**
 * `quiet` keeps a change local to the overlay.
 *
 * The overlay paints from this list, so a quiet change is fully live on screen
 * — it is only the DOCUMENT that has not been told. Option-drag needs that: one
 * shape is one step in the stack, so publishing the copy while the key is still
 * down would mint and destroy a step on every press. Selection is never quiet;
 * only the shapes are.
 */
function updateState(partial: Partial<AnnotationState>, options?: { quiet?: boolean }) {
  if ('selectedShapeIds' in partial) {
    selectedShapeIds.value = [...(partial.selectedShapeIds ?? [])]
    selectedShapeId.value = partial.selectedShapeId
      ?? selectedShapeIds.value.at(-1)
      ?? null
    emit('select', selectedShapeId.value)
  } else if ('selectedShapeId' in partial) {
    selectedShapeId.value = partial.selectedShapeId ?? null
    selectedShapeIds.value = selectedShapeId.value ? [selectedShapeId.value] : []
    emit('select', selectedShapeId.value)
  }
  if (partial.annotations) {
    shapes.value = partial.annotations
    if (!options?.quiet) emit('change', partial.annotations)
  }
  // activeTool and the style fields are props here: the toolbar owns them, and
  // the composable only ever reads them back through getState.
}

// -- geometry ---------------------------------------------------------------

const imageSize = computed(() =>
  props.source ? { width: props.source.width, height: props.source.height } : null
)
const canvasSize = computed(() => ({ width: props.displayWidth, height: props.displayHeight }))

/**
 * Interaction happens in CSS pixels — the composable measures the element with
 * getBoundingClientRect — so the view zoom is the fit scale. Rendering is a
 * separate space: the backing store is image-sized and the renderer works in
 * image pixels, which is also the space the shapes are stored in.
 */
const viewTransform = computed<ViewTransform>(() => ({
  zoom: imageSize.value ? props.displayWidth / imageSize.value.width : 1,
  panX: 0,
  panY: 0,
  rotation: 0,
}))

const annotation = useAnnotation(
  overlay,
  viewTransform,
  imageSize,
  canvasSize,
  getState,
  updateState,
  commitChanges
)

/**
 * Whether the canvas currently owns a caret.
 *
 * `isEditingTextOnCanvas` is a plain function, so the host and the painter both
 * need something they can watch rather than call — a text session has to hide
 * the handles and the floating strip, and both of those are reactive reads.
 */
const editingText = computed(() =>
  annotation.textEditState.value !== null ||
  annotation.interactionMode.value.type === 'editing-text-canvas'
)

/**
 * A gesture is under way: drawing, moving, resizing, rotating.
 *
 * `pending` is excluded — that is a mouse button held on a shape, which is how
 * an ordinary click starts, and chrome that blinks on every click is worse than
 * chrome that stays. Floating chrome hides for the duration: a move publishes
 * nothing until it ends, so anything positioned from the document would sit at
 * the pose the shape was grabbed at and then jump.
 */
const gestureActive = computed(() => {
  const type = annotation.interactionMode.value.type
  return type !== 'idle' && type !== 'pending'
})

const selectionCount = computed(() => selectedShapeIds.value.length)
const selectedShapes = computed(() =>
  shapes.value.filter(shape => selectedShapeIds.value.includes(shape.id))
)

// -- painting ---------------------------------------------------------------

function draw() {
  const canvas = overlay.value
  const size = imageSize.value
  if (!canvas || !size) return
  const ctx = canvas.getContext('2d')!

  // The shape renderer speaks in source-image pixels. Transform that space
  // into a display-sized backing store instead of rasterizing a multi-megapixel
  // overlay and asking CSS to shrink it after every pointer move.
  ctx.setTransform(canvas.width / size.width, 0, 0, canvas.height / size.height, 0, 0)
  ctx.clearRect(0, 0, size.width, size.height)

  // The source is passed through because redaction samples the pixels it
  // covers rather than painting a flat block over them.
  renderShapes(ctx, shapes.value, size, props.source ?? undefined, annotation.textEditState.value)

  const selected = selectedShapes.value
  if (selected.length === 1 && !editingText.value) {
    const shape = selected[0]
    drawSelectionHandles(
      ctx,
      getShapeBounds(shape, size),
      size,
      shape.rotation,
      getShapeCenter(shape),
      // Handles are drawn in image pixels but read at display size, so they
      // are scaled back down to stay a constant size on screen.
      imageSize.value ? size.width / Math.max(1, props.displayWidth) : 1
    )
  } else if (selected.length > 1 && !editingText.value) {
    drawGroupSelection(ctx, selected, size)
  }

  const marquee = annotation.marqueeBounds.value
  if (marquee) {
    const scale = size.width / Math.max(1, props.displayWidth)
    const selectionColor =
      getComputedStyle(canvas).getPropertyValue('--color-selection').trim()
      || 'rgb(129, 140, 248)'
    ctx.save()
    ctx.strokeStyle = selectionColor
    ctx.fillStyle = selectionColor
    ctx.globalAlpha = 0.12
    ctx.fillRect(
      marquee.x * size.width,
      marquee.y * size.height,
      marquee.width * size.width,
      marquee.height * size.height
    )
    ctx.globalAlpha = 1
    ctx.lineWidth = 1 / scale
    ctx.setLineDash([4 / scale, 3 / scale])
    ctx.strokeRect(
      marquee.x * size.width,
      marquee.y * size.height,
      marquee.width * size.width,
      marquee.height * size.height
    )
    ctx.restore()
  }
}

function drawGroupSelection(
  ctx: CanvasRenderingContext2D,
  selected: Shape[],
  size: { width: number; height: number }
) {
  const scale = size.width / Math.max(1, props.displayWidth)
  const selectionColor =
    getComputedStyle(overlay.value!).getPropertyValue('--color-selection').trim()
    || 'rgb(129, 140, 248)'

  ctx.save()
  ctx.strokeStyle = selectionColor
  ctx.lineWidth = 1 / scale

  // Outline every member in its own rotation so the group reads as a set of
  // objects, not one newly-created rectangle.
  for (const shape of selected) {
    const bounds = getShapeBounds(shape, size)
    const center = getShapeCenter(shape)
    const x = bounds.x * size.width
    const y = bounds.y * size.height
    const width = bounds.width * size.width
    const height = bounds.height * size.height
    ctx.save()
    ctx.translate(center.x * size.width, center.y * size.height)
    ctx.rotate(shape.rotation || 0)
    ctx.translate(-center.x * size.width, -center.y * size.height)
    ctx.strokeRect(x, y, width, height)
    ctx.restore()
  }

  // A dashed union box is the shared drag target and stays axis-aligned.
  const bounds = selected.map(shape => rotatedBounds(
    getShapeBounds(shape, size),
    getShapeCenter(shape),
    shape.rotation || 0,
    size
  ))
  const minX = Math.min(...bounds.map(item => item.x))
  const minY = Math.min(...bounds.map(item => item.y))
  const maxX = Math.max(...bounds.map(item => item.x + item.width))
  const maxY = Math.max(...bounds.map(item => item.y + item.height))
  ctx.lineWidth = 2 / scale
  ctx.setLineDash([6 / scale, 4 / scale])
  ctx.strokeRect(
    minX * size.width,
    minY * size.height,
    (maxX - minX) * size.width,
    (maxY - minY) * size.height
  )
  ctx.restore()
}

function resize() {
  const canvas = overlay.value
  const size = imageSize.value
  if (!canvas || !size) return

  // Enough pixels for a crisp interactive overlay, capped so a high-DPI
  // monitor cannot turn a fitted preview back into a source-sized hot path.
  const { width, height } = overlayBackingSize(
    props.renderWidth || props.displayWidth,
    props.renderHeight || props.displayHeight,
    window.devicePixelRatio || 1,
  )
  if (canvas.width !== width) canvas.width = width
  if (canvas.height !== height) canvas.height = height
  draw()
}

defineExpose({
  commitGesture: () => annotation.commitGesture(),
  /** Typing goes to the canvas, so the view must hold its shortcuts. */
  isEditingText: () => annotation.isEditingTextOnCanvas(),
  /** The same fact, watchable: chrome over the canvas hides during a session. */
  editingText,
  gestureActive,
  selectionCount,
  selectedShapes,
  /**
   * Put the caret in a text shape without a double-click. Text editing lives
   * in the composable's interaction model, so it cannot be driven from the
   * document side — only asked for here.
   */
  editText(id: string) {
    annotation.startTextEditing(id)
  },
  /** Delete is a document verb, so the bottom bar can reach it. */
  deleteSelected() {
    annotation.deleteSelectedShapes()
  },
  duplicateSelected() {
    annotation.duplicateSelectedShapes()
  },
  clearSelection() {
    selectedShapeId.value = null
    selectedShapeIds.value = []
    emit('select', null)
  },
  /**
   * Let Object Select begin on the surrounding matte. The composable converts
   * the screen point through this canvas even when it lies outside its rect,
   * so the marquee naturally enters and leaves the image without clamping.
   */
  startMarqueeSelection(event: MouseEvent) {
    annotation.startMarqueeSelection(event)
  },
  consumeCompletedGestureClick() {
    return annotation.consumeCompletedGestureClick()
  },
  /** External selection push (a row click); no emit, or it would echo. */
  setSelected(id: string | null) {
    if (selectedShapeId.value === id) return
    selectedShapeId.value = id
    selectedShapeIds.value = id ? [id] : []
  },
})

watch(
  () => [
    props.source,
    props.displayWidth,
    props.displayHeight,
    props.renderWidth,
    props.renderHeight,
  ] as const,
  resize,
)

let drawFrame: number | null = null
function scheduleDraw() {
  if (drawFrame !== null) return
  drawFrame = requestAnimationFrame(() => {
    drawFrame = null
    draw()
  })
}

watch(
  () => [
    shapes.value,
    selectedShapeId.value,
    selectedShapeIds.value,
    annotation.textEditState.value,
    annotation.marqueeBounds.value,
  ] as const,
  () => nextTick(scheduleDraw),
  { deep: true }
)
// The composable listens on the canvas element, which only exists after mount.
onMounted(() => {
  resize()
  annotation.setupListeners()
})
onBeforeUnmount(() => {
  annotation.cleanupListeners()
  if (drawFrame !== null) cancelAnimationFrame(drawFrame)
})
</script>

<template>
  <div class="absolute inset-0">
    <canvas
      ref="overlay"
      class="touch-none"
      :style="{
        width: displayWidth + 'px',
        height: displayHeight + 'px',
        cursor: annotation.cursorStyle.value,
      }"
    />
  </div>
</template>
