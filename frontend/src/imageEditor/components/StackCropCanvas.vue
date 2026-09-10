<script setup lang="ts">
/**
 * Crop, on the image as it stands BELOW the crop step.
 *
 * The rectangle sits still and the image moves behind it. That is the
 * convention every photo tool follows, and it is the only arrangement where
 * the gestures read: tilt the frame and the horizon visibly levels, flip and
 * you see the flip immediately rather than discovering it after leaving the
 * mode. Moving the crop moves the picture under a fixed window, which is what
 * choosing a crop actually feels like.
 *
 * The point of showing the uncropped image is that a crop is not destructive
 * here: the region outside it is dimmed rather than gone, so widening the crop
 * later reveals real pixels instead of edge-clamped ones. The step's input is
 * what is drawn; the crop rectangle is the bright window over it.
 *
 * The overlay and the gesture maths are the snapshot editor's, copied into
 * `imageEditor/ported/` — the even-odd dim, the dashed border, the rule of
 * thirds that follows the rotation, the corner handles, and the rotation
 * lollipop hanging perpendicular to the bottom edge. The aspect-locked corner
 * drag projects onto the aspect diagonal, which is the difference between a
 * crop that tracks the pointer and one that snaps between axes.
 */
import { ref, computed, watch, onMounted, onBeforeUnmount, nextTick } from 'vue'
import { useCropInteraction } from '../ported/useCropInteraction'
import type { CropRect } from '../ported/useCropInteraction'
import { drawCropOverlay } from '../ported/cropOverlay'
import type { ViewTransform } from '../ported/geometry'
import { pinchCrop, type CropPinchFrame } from '../ported/cropPinch'

const props = defineProps<{
  /** The composite BELOW the crop step — the uncropped image. */
  source: HTMLCanvasElement | null
  crop: CropRect
  /** Mirrors and quarter turns, so they are visible while cropping. */
  flipX?: boolean
  flipY?: boolean
  rotation?: number
  rotation90?: number
  /** The viewport the image is fitted into. */
  viewWidth: number
  viewHeight: number
}>()

const emit = defineEmits<{
  change: [CropRect]
  /** A drag ended: one undo step. */
  commit: []
}>()

const canvas = ref<HTMLCanvasElement | null>(null)
// Once pinched, retain the preview magnification so the frame stays stationary.
const pinchZoom = ref<number | null>(null)

/** Clearance for corner handles and the rotation lollipop, in canvas pixels. */
const HANDLE_MARGIN = 44

const imageSize = computed(() =>
  props.source ? { width: props.source.width, height: props.source.height } : null
)
const canvasSize = computed(() => ({ width: props.viewWidth, height: props.viewHeight }))

/**
 * Start fitted to the viewport; a pinch retains its preview magnification.
 */
const viewTransform = computed<ViewTransform>(() => {
  const size = imageSize.value
  if (!size || !props.viewWidth || !props.viewHeight) {
    return { zoom: 1, panX: 0, panY: 0, rotation: 0 }
  }
  // Leave room around the image for the handles and the rotation lollipop.
  // Fitting edge-to-edge puts the lollipop off-canvas the moment the crop
  // reaches the bottom of the frame, which is its starting state.
  const margin = HANDLE_MARGIN * 2
  // Straightening swings the image's corners out, so the fit is taken against
  // the rotated extent — otherwise tilting clips the picture against the
  // viewport and the dimmed surround runs out of pixels.
  const angle = Math.abs(props.crop.rotation ?? 0)
  const spanW = size.width * Math.cos(angle) + size.height * Math.sin(angle)
  const spanH = size.width * Math.sin(angle) + size.height * Math.cos(angle)
  const zoom = Math.min(
    (props.viewWidth - margin) / spanW,
    (props.viewHeight - margin) / spanH,
    1
  )
  return { zoom: pinchZoom.value ?? zoom, panX: 0, panY: 0, rotation: 0 }
})

const crop = useCropInteraction(
  canvas,
  viewTransform,
  imageSize,
  canvasSize,
  () => props.crop,
  next => emit('change', next),
  () => emit('commit'),
  true
)

function draw() {
  const element = canvas.value
  const size = imageSize.value
  if (!element || !size) return
  const ctx = element.getContext('2d')!
  const { zoom } = viewTransform.value

  // Keep drawing coordinates in CSS pixels, with a device-resolution bitmap.
  ctx.setTransform(element.width / props.viewWidth, 0, 0, element.height / props.viewHeight, 0, 0)
  ctx.clearRect(0, 0, props.viewWidth, props.viewHeight)
  ctx.imageSmoothingEnabled = true
  ctx.imageSmoothingQuality = 'high'

  // The image is placed so the CROP CENTRE lands at the viewport centre and
  // the crop's tilt is taken out of it — the inverse of the transform the
  // executor will apply, which is why what you see here is what you get.
  ctx.save()
  ctx.translate(props.viewWidth / 2, props.viewHeight / 2)
  // Composed in the executor's order — image rotation, then flip, then the
  // crop's own tilt. These do not commute: flipping after the tilt mirrors
  // about the wrong axis, and the preview would disagree with the output.
  ctx.rotate((props.rotation ?? 0) + ((props.rotation90 ?? 0) * Math.PI) / 2)
  if (props.flipX || props.flipY) ctx.scale(props.flipX ? -1 : 1, props.flipY ? -1 : 1)
  ctx.rotate(-(props.crop.rotation ?? 0))
  ctx.scale(zoom, zoom)
  ctx.translate(-props.crop.x * size.width, -props.crop.y * size.height)
  ctx.drawImage(props.source!, 0, 0)
  ctx.restore()

  drawCropOverlay(ctx, props.crop, viewTransform.value, size, canvasSize.value, true)
}

function resize() {
  const element = canvas.value
  if (!element) return
  const ratio = window.devicePixelRatio || 1
  element.width = Math.max(1, Math.round(props.viewWidth * ratio))
  element.height = Math.max(1, Math.round(props.viewHeight * ratio))
  draw()
}

watch(() => [props.viewWidth, props.viewHeight], () => { pinchZoom.value = null; resize() })
watch(() => props.source, resize)
watch(
  () => [props.crop, props.flipX, props.flipY, props.rotation, props.rotation90],
  () => nextTick(draw),
  { deep: true }
)

onMounted(() => {
  resize()
  crop.setupListeners()
})
onBeforeUnmount(() => crop.cleanupListeners())
type TouchPoint = { x: number; y: number }
const touches = new Map<number, TouchPoint>()
let pinch: { frame: CropPinchFrame; points: [TouchPoint, TouchPoint]; ids: [number, number] } | null = null
let finishingPinch = false
function localPoint(event: PointerEvent): TouchPoint {
  const rect = canvas.value!.getBoundingClientRect()
  return {
    x: (event.clientX - rect.left) * props.viewWidth / rect.width - props.viewWidth / 2,
    y: (event.clientY - rect.top) * props.viewHeight / rect.height - props.viewHeight / 2,
  }
}
function consume(event: PointerEvent) { event.preventDefault(); event.stopPropagation() }
function touchDown(event: PointerEvent) {
  if (!canvas.value || !imageSize.value) return
  touches.set(event.pointerId, localPoint(event))
  if (touches.size === 2 && !finishingPinch) {
    crop.commit()
    pinch = {
      frame: {
        crop: { ...props.crop }, zoom: viewTransform.value.zoom,
        width: imageSize.value.width, height: imageSize.value.height,
        rotation: (props.rotation ?? 0) + (props.rotation90 ?? 0) * Math.PI / 2,
        flipX: !!props.flipX, flipY: !!props.flipY,
      },
      points: [...touches.values()] as [TouchPoint, TouchPoint],
      ids: [...touches.keys()] as [number, number],
    }
    for (const id of touches.keys()) canvas.value.setPointerCapture(id)
  }
  if (pinch || finishingPinch) consume(event)
}
function touchMove(event: PointerEvent) {
  if (!touches.has(event.pointerId)) return
  touches.set(event.pointerId, localPoint(event))
  if (pinch) {
    const result = pinchCrop(pinch.frame, pinch.points, pinch.ids.map(id => touches.get(id)!) as [TouchPoint, TouchPoint])
    pinchZoom.value = result.zoom
    emit('change', result.crop)
  }
  if (pinch || finishingPinch) consume(event)
}
function touchUp(event: PointerEvent) {
  touches.delete(event.pointerId)
  if (!pinch && !finishingPinch) return
  consume(event)
  if (pinch && pinch.ids.includes(event.pointerId)) {
    pinch = null
    finishingPinch = true
    emit('commit')
  }
  if (!touches.size) finishingPinch = false
}
defineExpose({ commitGesture: () => crop.commit(), touchDown, touchMove, touchUp })
</script>

<template>
  <canvas
    ref="canvas"
    class="absolute inset-0 touch-none"
    :style="{
      width: viewWidth + 'px',
      height: viewHeight + 'px',
      cursor: crop.cursorStyle.value,
    }"
  />
</template>
