import type { CropRect } from './useCropInteraction.ts'

type Point = { x: number; y: number }
export type CropPinchFrame = {
  crop: CropRect
  zoom: number
  width: number
  height: number
  rotation: number
  flipX: boolean
  flipY: boolean
}

/** Screen offset back into source pixels, matching the crop preview transform. */
function sourceOffset(point: Point, frame: CropPinchFrame): Point {
  const c = Math.cos(frame.rotation), s = Math.sin(frame.rotation)
  const x = (c * point.x + s * point.y) * (frame.flipX ? -1 : 1)
  const y = (-s * point.x + c * point.y) * (frame.flipY ? -1 : 1)
  const angle = frame.crop.rotation ?? 0
  return {
    x: (Math.cos(angle) * x - Math.sin(angle) * y) / frame.zoom,
    y: (Math.sin(angle) * x + Math.cos(angle) * y) / frame.zoom,
  }
}

/** Pinch the image beneath a stationary crop frame, anchored between the fingers. */
export function pinchCrop(frame: CropPinchFrame, start: [Point, Point], next: [Point, Point]) {
  const distance = (p: [Point, Point]) => Math.hypot(p[1].x - p[0].x, p[1].y - p[0].y)
  const midpoint = (p: [Point, Point]) => ({ x: (p[0].x + p[1].x) / 2, y: (p[0].y + p[1].y) / 2 })
  const angle = (p: [Point, Point]) => Math.atan2(p[1].y - p[0].y, p[1].x - p[0].x)
  const scale = Math.max(0.05, Math.min(20, distance(next) / Math.max(1, distance(start))))
  const delta = Math.atan2(Math.sin(angle(next) - angle(start)), Math.cos(angle(next) - angle(start)))
  const parity = frame.flipX !== frame.flipY ? -1 : 1
  const crop = {
    ...frame.crop,
    width: frame.crop.width / scale,
    height: frame.crop.height / scale,
    rotation: Math.max(-Math.PI / 4, Math.min(Math.PI / 4, (frame.crop.rotation ?? 0) - delta * parity)),
  }
  const zoom = frame.zoom * scale
  const anchor = sourceOffset(midpoint(start), frame)
  const moved = sourceOffset(midpoint(next), { ...frame, crop, zoom })
  crop.x += (anchor.x - moved.x) / frame.width
  crop.y += (anchor.y - moved.y) / frame.height
  return { crop, zoom }
}
