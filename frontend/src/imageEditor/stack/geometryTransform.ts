/**
 * Geometry co-transform.
 *
 * The base image establishes permanent document space. Every spatial payload
 * owns one complete local-payload → document affine; every stack boundary owns
 * a document → stage affine. Rendering composes those two transforms.
 *
 * Crops therefore never rewrite a mask, patch, stroke, selection or vector.
 * Crop something away and un-crop it and the payload returns intact because
 * its document anchor and master pixels never changed.
 */

import { cropPreviewSize } from '../ported/cropPreview.ts'
import type { CropParams } from './opExecutors'
import type { StackDocument } from './types'
import { pickedCandidate } from './types.ts'
import { expandEdgesFromParams, expandedFrame } from './expandGeometry.ts'

/** 2D affine as [a, b, c, d, e, f] — the argument order of setTransform. */
export type Affine = [number, number, number, number, number, number]

export const IDENTITY: Affine = [1, 0, 0, 1, 0, 0]

export function translate(x: number, y: number): Affine {
  return [1, 0, 0, 1, x, y]
}

export function multiply(m: Affine, n: Affine): Affine {
  return [
    m[0] * n[0] + m[2] * n[1],
    m[1] * n[0] + m[3] * n[1],
    m[0] * n[2] + m[2] * n[3],
    m[1] * n[2] + m[3] * n[3],
    m[0] * n[4] + m[2] * n[5] + m[4],
    m[1] * n[4] + m[3] * n[5] + m[5],
  ]
}

export function invert(m: Affine): Affine | null {
  const determinant = m[0] * m[3] - m[1] * m[2]
  if (Math.abs(determinant) < 1e-12) return null
  return [
    m[3] / determinant,
    -m[1] / determinant,
    -m[2] / determinant,
    m[0] / determinant,
    (m[2] * m[5] - m[3] * m[4]) / determinant,
    (m[1] * m[4] - m[0] * m[5]) / determinant,
  ]
}

export function isIdentity(m: Affine, epsilon = 1e-6): boolean {
  return (
    Math.abs(m[0] - 1) < epsilon && Math.abs(m[1]) < epsilon &&
    Math.abs(m[2]) < epsilon && Math.abs(m[3] - 1) < epsilon &&
    Math.abs(m[4]) < epsilon && Math.abs(m[5]) < epsilon
  )
}

/**
 * The affine a crop op applies, mapping input space to its output space.
 * Mirrors `applyCrop`'s stage order exactly — the two must agree or a
 * co-transformed mask lands somewhere the pixels are not.
 */
export function cropAffine(
  params: CropParams,
  inputWidth: number,
  inputHeight: number
): { matrix: Affine; width: number; height: number } {
  const rect = params.rect ?? { x: 0.5, y: 0.5, width: 1, height: 1 }
  const { width, height } = cropPreviewSize(
    Math.max(1, Math.round(inputWidth * rect.width)),
    Math.max(1, Math.round(inputHeight * rect.height)),
    params.rotation90,
  )

  const rotation = (params.rotation ?? 0) + ((params.rotation90 ?? 0) * Math.PI) / 2
  const cos = Math.cos(rotation)
  const sin = Math.sin(rotation)

  // Rotate the frame with the crop, preserving its source dimensions.
  let drawWidth = width
  let drawHeight = height
  if (params.rotation90 === 1 || params.rotation90 === 3) {
    drawWidth = height
    drawHeight = width
  }

  const sourceX = (rect.x - rect.width / 2) * inputWidth
  const sourceY = (rect.y - rect.height / 2) * inputHeight
  const sourceWidth = rect.width * inputWidth
  const sourceHeight = rect.height * inputHeight

  // Composed in the order the canvas applies them, outermost last. drawImage
  // maps the source window onto a box centred on the origin, and the flip and
  // rotation then act on THAT box — folding the flip in earlier mirrors about
  // the wrong point.
  const flip: Affine = [params.flipX ? -1 : 1, 0, 0, params.flipY ? -1 : 1, 0, 0]
  const rotate: Affine = [cos, sin, -sin, cos, 0, 0]
  const toFrameCentre: Affine = [1, 0, 0, 1, width / 2, height / 2]

  // Mirrors applyCrop exactly, branch for branch. If these two ever disagree,
  // a mask co-transforms into a frame the pixels were never put in — which is
  // invisible until something lands in the wrong place.
  const cropRotation = params.cropRotation ?? 0
  let inner: Affine
  if (cropRotation !== 0) {
    const cropCos = Math.cos(-cropRotation)
    const cropSin = Math.sin(-cropRotation)
    const toCropCentre: Affine = [1, 0, 0, 1, -rect.x * inputWidth, -rect.y * inputHeight]
    const straighten: Affine = [cropCos, cropSin, -cropSin, cropCos, 0, 0]
    inner = multiply(straighten, toCropCentre)
  } else {
    const toSourceOrigin: Affine = [1, 0, 0, 1, -sourceX, -sourceY]
    const scaleToDraw: Affine = [drawWidth / sourceWidth, 0, 0, drawHeight / sourceHeight, 0, 0]
    const centreOnOrigin: Affine = [1, 0, 0, 1, -drawWidth / 2, -drawHeight / 2]
    inner = multiply(centreOnOrigin, multiply(scaleToDraw, toSourceOrigin))
  }

  const matrix = multiply(toFrameCentre, multiply(rotate, multiply(flip, inner)))
  return { matrix, width, height }
}

/**
 * The composed geometry of every enabled geometry op strictly below `index`,
 * plus the frame size at that point. This is what an op's payloads live in.
 */
export function geometryBelow(
  doc: StackDocument,
  index: number
): { matrix: Affine; width: number; height: number } {
  let matrix: Affine = IDENTITY
  let width = doc.canvas.width
  let height = doc.canvas.height

  for (let i = 0; i < index && i < doc.edits.length; i++) {
    const op = doc.edits[i]
    if (!op.enabled) continue
    // Expand grows the frame and translates everything by the new top-left
    // margins. It counts only once a candidate is picked — a staged expand
    // composites as a no-op, and the mirror law (geometry must agree with the
    // compositor branch for branch) therefore requires it contributes no
    // geometry either.
    if (op.class === 'patch' && (op as any).operation === 'expand') {
      if (!pickedCandidate(op)) continue
      const frame = expandedFrame(
        expandEdgesFromParams((op as any).params), width, height,
      )
      matrix = multiply(translate(frame.left, frame.top), matrix)
      width = frame.width
      height = frame.height
      continue
    }
    if (op.class !== 'parametric' || (op as any).exec?.kind !== 'crop') continue
    const stage = cropAffine((op as any).params || {}, width, height)
    matrix = multiply(stage.matrix, matrix)
    width = stage.width
    height = stage.height
  }
  return { matrix, width, height }
}

/**
 * `M_new ∘ M_old⁻¹` — the rewrite that carries a payload from the space it was
 * created in into the space it now applies to. Null when the old geometry is
 * not invertible, which is the caller's cue to keep the master rather than
 * produce a wrong derivative.
 */
export function coTransform(oldMatrix: Affine, newMatrix: Affine): Affine | null {
  const inverse = invert(oldMatrix)
  if (!inverse) return null
  return multiply(newMatrix, inverse)
}

/**
 * Canonical anchor for pixels authored in a stack stage.
 *
 * `frame.matrix` maps permanent document coordinates into the authored stage.
 * Its inverse therefore maps that stage back into document space. Compact
 * payload origins are folded into the same affine so position can never drift
 * into a second coordinate system.
 */
export function payloadToDocument(
  frame: { matrix: number[] },
  origin: [number, number] = [0, 0],
): Affine | null {
  const documentFromFrame = invert(frame.matrix as Affine)
  if (!documentFromFrame) return null
  return multiply(documentFromFrame, translate(origin[0], origin[1]))
}

/**
 * Project a canonically anchored payload into the input stage of `index`.
 */
export function stageFromPayload(
  doc: StackDocument,
  index: number,
  documentFromPayload: Affine,
): { matrix: Affine; width: number; height: number } {
  const stage = geometryBelow(doc, index)
  return {
    matrix: multiply(stage.matrix, documentFromPayload),
    width: stage.width,
    height: stage.height,
  }
}

/**
 * Redraw a payload through a co-transform into the new frame.
 *
 * Always fed the as-created master, never the previous derivative, so a crop
 * followed by an un-crop restores the payload exactly instead of compounding
 * resampling loss.
 */
export function rewritePayload(
  master: CanvasImageSource,
  matrix: Affine,
  width: number,
  height: number
): HTMLCanvasElement {
  const canvas = document.createElement('canvas')
  canvas.width = width
  canvas.height = height
  const ctx = canvas.getContext('2d')!
  ctx.setTransform(matrix[0], matrix[1], matrix[2], matrix[3], matrix[4], matrix[5])
  ctx.drawImage(master, 0, 0)
  ctx.setTransform(1, 0, 0, 1, 0, 0)
  return canvas
}

/** Where a point in the master's space lands after a co-transform. */
export function applyToPoint(m: Affine, x: number, y: number): [number, number] {
  return [m[0] * x + m[2] * y + m[4], m[1] * x + m[3] * y + m[5]]
}

/**
 * Whether a payload still intersects the frame. A payload wholly outside
 * composites as a no-op and its row reads `Out of frame` — still toggleable,
 * never an error, because the geometry below it might come back.
 */
export function intersectsFrame(
  matrix: Affine,
  masterWidth: number,
  masterHeight: number,
  frameWidth: number,
  frameHeight: number
): boolean {
  const corners: Array<[number, number]> = [
    [0, 0], [masterWidth, 0], [0, masterHeight], [masterWidth, masterHeight],
  ]
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity
  for (const [x, y] of corners) {
    const [tx, ty] = applyToPoint(matrix, x, y)
    minX = Math.min(minX, tx); maxX = Math.max(maxX, tx)
    minY = Math.min(minY, ty); maxY = Math.max(maxY, ty)
  }
  return maxX > 0 && maxY > 0 && minX < frameWidth && minY < frameHeight
}

// -- vector payloads ---------------------------------------------------------

/**
 * Carry annotation shapes through a co-transform.
 *
 * Shapes are stored normalized against the frame they were authored in, so a
 * crop below them does not merely resize their canvas — it changes what 0.5
 * means. Without this an arrow drawn over someone's face slides off it the
 * moment the crop is removed, which is the whole reason the raster payloads
 * are rewritten too. Sizes and stroke widths scale with the geometry; a
 * straightening crop also turns the shapes with it.
 */
export function transformShapes(
  shapes: any[],
  matrix: Affine,
  oldWidth: number,
  oldHeight: number,
  newWidth: number,
  newHeight: number
): any[] {
  const scaleX = Math.hypot(matrix[0], matrix[1])
  const scaleY = Math.hypot(matrix[2], matrix[3])
  const angle = Math.atan2(matrix[1], matrix[0])

  /** Normalized in the old frame → normalized in the new one. */
  const point = (x: number, y: number) => {
    const [px, py] = applyToPoint(matrix, x * oldWidth, y * oldHeight)
    return { x: px / newWidth, y: py / newHeight }
  }
  const spanX = (value: number) => (value * oldWidth * scaleX) / newWidth
  const spanY = (value: number) => (value * oldHeight * scaleY) / newHeight

  return shapes.map(shape => {
    const next: any = { ...shape, ...point(shape.x, shape.y) }

    if (typeof shape.rotation === 'number') next.rotation = shape.rotation + angle
    // strokeWidth is in pixels of the frame, so it follows the scale directly.
    if (typeof shape.strokeWidth === 'number') {
      next.strokeWidth = shape.strokeWidth * ((scaleX + scaleY) / 2)
    }

    if (typeof shape.width === 'number') next.width = spanX(shape.width)
    if (typeof shape.height === 'number') next.height = spanY(shape.height)
    // Text keeps a reference size at the base font size; it has to move with
    // the display size or the glyph scale silently changes.
    if (typeof shape.baseWidth === 'number') next.baseWidth = spanX(shape.baseWidth)
    if (typeof shape.baseHeight === 'number') next.baseHeight = spanY(shape.baseHeight)
    if (typeof shape.rx === 'number') next.rx = spanX(shape.rx)
    if (typeof shape.ry === 'number') next.ry = spanY(shape.ry)

    if (typeof shape.x1 === 'number') {
      const a = point(shape.x1, shape.y1)
      const b = point(shape.x2, shape.y2)
      next.x1 = a.x; next.y1 = a.y; next.x2 = b.x; next.y2 = b.y
    }
    for (const key of ['points', 'rawPoints', 'smoothedPath']) {
      if (Array.isArray(shape[key])) {
        next[key] = shape[key].map((p: any) => point(p.x, p.y))
      }
    }
    return next
  })
}
