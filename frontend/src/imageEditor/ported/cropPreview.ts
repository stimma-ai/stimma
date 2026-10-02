import type { CropRect } from './useCropInteraction.ts'
import { sourceOffset, type CropPinchFrame } from './cropPinch.ts'

export function cropPreviewSize(width: number, height: number, rotation90 = 0) {
  return rotation90 % 2 !== 0 ? { width: height, height: width } : { width, height }
}

/** Express the source crop in the stationary frame's screen axes. */
export function previewCrop(frame: CropPinchFrame, rotation90: number): CropRect {
  const size = cropPreviewSize(frame.width, frame.height, rotation90)
  const angle = -(frame.crop.rotation ?? 0)
  const px = (frame.crop.x - 0.5) * frame.width
  const py = (frame.crop.y - 0.5) * frame.height
  const x = (Math.cos(angle) * px - Math.sin(angle) * py) * (frame.flipX ? -1 : 1)
  const y = (Math.sin(angle) * px + Math.cos(angle) * py) * (frame.flipY ? -1 : 1)
  const c = Math.cos(frame.rotation), s = Math.sin(frame.rotation)
  const swapped = rotation90 % 2 !== 0
  return {
    ...frame.crop,
    x: 0.5 + (c * x - s * y) / size.width,
    y: 0.5 + (s * x + c * y) / size.height,
    width: swapped ? frame.crop.height : frame.crop.width,
    height: swapped ? frame.crop.width : frame.crop.height,
    aspectRatio: swapped && frame.crop.aspectRatio ? 1 / frame.crop.aspectRatio : frame.crop.aspectRatio,
  }
}

export function sourceCrop(crop: CropRect, frame: CropPinchFrame, rotation90: number): CropRect {
  const size = cropPreviewSize(frame.width, frame.height, rotation90)
  const offset = sourceOffset({ x: (crop.x - 0.5) * size.width, y: (crop.y - 0.5) * size.height }, { ...frame, zoom: 1 })
  const swapped = rotation90 % 2 !== 0
  return {
    ...crop,
    x: 0.5 + offset.x / frame.width,
    y: 0.5 + offset.y / frame.height,
    width: swapped ? crop.height : crop.width,
    height: swapped ? crop.width : crop.height,
    aspectRatio: frame.crop.aspectRatio,
  }
}
