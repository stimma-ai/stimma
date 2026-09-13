/**
 * Canvas 2D compositor for the op stack.
 *
 * Main thread, no WebGL, no wasm. The old editor already does full-frame
 * Canvas 2D pixel work acceptably on target hardware, target assets are
 * marketing-scale rather than gigapixel, and the Mac webview is WKWebView,
 * which cannot be version-pinned — Canvas 2D is its most conservative fully
 * supported surface.
 *
 * Two WKWebView-driven rules hold throughout:
 *  - never use canvas `filter:` for the mask feather (unreliable there); the
 *    blur is our own separable box pass over the mask alpha;
 *  - feature-detect anything newer and always keep the main-thread path.
 *
 * Replay is content-hash keyed: `hash(i+1) = H(hash(i), canonical(op(i)))`, so
 * any edit invalidates exactly the ops at and above it and everything below is
 * a cache hit. Disabled ops hash as identity, which is why toggling one off is
 * instant. Reordering swaps hash inputs the same way — there is no special
 * dirty logic anywhere.
 */

import type { Op, StackDocument } from './types'
import { pickedCandidate } from './types'
import { canonicalOp, stackHashes } from './stackHashes'
import { expandEdgesFromParams, expandedFrame } from './expandGeometry'
import {
  geometryBelow, multiply, payloadToDocument,
  rewritePayload, transformShapes, translate,
} from './geometryTransform'
import type { Affine } from './geometryTransform'
export { canonicalOp, stackHashes }
import {
  applyAnnotations,
  applyCrop,
  applyAdjust,
  applyRasterLayer,
  cropOutputSize,
  adjustIsIdentity,
} from './opExecutors'
import { featherAlpha } from './featherAlpha'
import { gradientMaskCanvas, isGradientMask } from './regionMask'
import {
  composeMaskCanvases,
  luminanceToAlphaCanvas,
  type MaskComposeLayer,
} from './maskComponents'
import type { GradientMask, MaskComponent } from './types'
import { retouchRegionAlpha } from './retouchRegionAlpha'
import { cutoutAlpha } from './cutoutAlpha'
import { maskedRetouchAdjustmentParams } from './adjustSections'
import { canReusePositionedPayload } from './positionedPayload'

export interface CompositeStage {
  /** Input hash for this op — the cache key of the composite BELOW it. */
  inputHash: string
  op: Op
}

export interface PreparedPatchMask {
  x: number
  y: number
  width: number
  height: number
  /** Feathered coverage, compact to the only rectangle that can change. */
  alpha: Uint8ClampedArray
}

function makeCanvas(width: number, height: number): HTMLCanvasElement {
  const canvas = document.createElement('canvas')
  canvas.width = width
  canvas.height = height
  return canvas
}

/**
 * Composite a generative patch over its input through a feathered mask.
 *
 * This is the VAE-roundtrip correction, and it is the whole reason the patch op
 * class exists: only the pixels inside the mask come from the model. Everything
 * outside is the input, untouched, however much the model repainted it.
 */
export function compositePatch(
  input: CanvasImageSource,
  patch: CanvasImageSource,
  mask: CanvasImageSource,
  width: number,
  height: number,
  options: {
    origin?: [number, number]
    featherPx?: number
    opacity?: number
    preparedMask?: PreparedPatchMask | null
  } = {}
): HTMLCanvasElement {
  const { origin = [0, 0], featherPx = 6, opacity = 1 } = options

  const prepared = options.preparedMask === undefined
    ? preparePatchMask(mask, width, height, featherPx)
    : options.preparedMask

  // An empty mask is a no-op, but callers still expect an owned output canvas.
  const out = makeCanvas(width, height)
  const ctx = out.getContext('2d')!
  ctx.drawImage(input, 0, 0, width, height)
  if (!prepared) return out

  // Patch CPU work stays inside the affected rectangle. The old path allocated,
  // read and feathered width×height buffers for every small removal.
  const patchCanvas = makeCanvas(prepared.width, prepared.height)
  const patchCtx = patchCanvas.getContext('2d', { willReadFrequently: true })!
  patchCtx.drawImage(
    patch,
    origin[0] - prepared.x,
    origin[1] - prepared.y,
  )
  const patchData = patchCtx.getImageData(0, 0, prepared.width, prepared.height)
  for (let i = 0, p = 0; i < patchData.data.length; i += 4, p++) {
    patchData.data[i + 3] = Math.round(
      patchData.data[i + 3] * (prepared.alpha[p] / 255),
    )
  }
  patchCtx.putImageData(patchData, 0, 0)

  ctx.globalAlpha = opacity
  ctx.drawImage(patchCanvas, prepared.x, prepared.y)
  ctx.globalAlpha = 1
  return out
}

/**
 * Prepare the input-independent part of a patch composite once.
 *
 * The full mask is scanned only to discover its bounds. Feathering and every
 * later per-pixel pass operate on a compact rectangle, expanded by the exact
 * support of the three box-blur passes.
 */
export function preparePatchMask(
  mask: CanvasImageSource,
  width: number,
  height: number,
  featherPx: number,
): PreparedPatchMask | null {
  const maskCanvas = makeCanvas(width, height)
  const maskCtx = maskCanvas.getContext('2d', { willReadFrequently: true })!
  maskCtx.drawImage(mask, 0, 0, width, height)
  const maskData = maskCtx.getImageData(0, 0, width, height)

  let minX = width
  let minY = height
  let maxX = -1
  let maxY = -1
  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      if (maskData.data[(y * width + x) * 4] === 0) continue
      minX = Math.min(minX, x)
      minY = Math.min(minY, y)
      maxX = Math.max(maxX, x)
      maxY = Math.max(maxY, y)
    }
  }
  if (maxX < minX || maxY < minY) return null

  const support = Math.max(0, Math.round(featherPx)) * 3 + 1
  minX = Math.max(0, minX - support)
  minY = Math.max(0, minY - support)
  maxX = Math.min(width - 1, maxX + support)
  maxY = Math.min(height - 1, maxY + support)
  const compactWidth = maxX - minX + 1
  const compactHeight = maxY - minY + 1
  const luminance = new Uint8ClampedArray(compactWidth * compactHeight)
  for (let y = 0; y < compactHeight; y++) {
    const sourceRow = (minY + y) * width
    const targetRow = y * compactWidth
    for (let x = 0; x < compactWidth; x++) {
      luminance[targetRow + x] = maskData.data[
        (sourceRow + minX + x) * 4
      ]
    }
  }
  return {
    x: minX,
    y: minY,
    width: compactWidth,
    height: compactHeight,
    alpha: featherAlpha(luminance, compactWidth, compactHeight, featherPx),
  }
}

/**
 * Composite a cached Retouch result through its independently editable mask.
 *
 * Old documents stored identical alpha in both payloads, so `min` preserves
 * their pixels exactly at Feather 0. Newer results may be opaque under the
 * mask; in that case the mask alone supplies the region shape.
 */
export function compositeRetouchRegion(
  input: CanvasImageSource,
  result: CanvasImageSource,
  mask: CanvasImageSource,
  width: number,
  height: number,
  options: { featherPx?: number; opacity?: number } = {},
): HTMLCanvasElement {
  const { featherPx = 0, opacity = 1 } = options
  const maskCanvas = makeCanvas(width, height)
  const maskCtx = maskCanvas.getContext('2d', { willReadFrequently: true })!
  maskCtx.drawImage(mask, 0, 0, width, height)
  const maskData = maskCtx.getImageData(0, 0, width, height)

  let minX = width
  let minY = height
  let maxX = -1
  let maxY = -1
  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      if (maskData.data[(y * width + x) * 4 + 3] === 0) continue
      minX = Math.min(minX, x)
      minY = Math.min(minY, y)
      maxX = Math.max(maxX, x)
      maxY = Math.max(maxY, y)
    }
  }
  const output = makeCanvas(width, height)
  const outputCtx = output.getContext('2d')!
  outputCtx.drawImage(input, 0, 0, width, height)
  if (maxX < minX || maxY < minY) return output

  const support = Math.max(0, Math.round(featherPx)) * 3 + 1
  minX = Math.max(0, minX - support)
  minY = Math.max(0, minY - support)
  maxX = Math.min(width - 1, maxX + support)
  maxY = Math.min(height - 1, maxY + support)
  const localWidth = maxX - minX + 1
  const localHeight = maxY - minY + 1

  const resultCanvas = makeCanvas(localWidth, localHeight)
  const resultCtx = resultCanvas.getContext('2d', { willReadFrequently: true })!
  resultCtx.drawImage(result, -minX, -minY, width, height)
  const resultData = resultCtx.getImageData(0, 0, localWidth, localHeight)
  const maskAlpha = new Uint8ClampedArray(localWidth * localHeight)
  const resultAlpha = new Uint8ClampedArray(localWidth * localHeight)
  for (let y = 0; y < localHeight; y++) {
    const sourceRow = (minY + y) * width
    const targetRow = y * localWidth
    for (let x = 0; x < localWidth; x++) {
      const target = targetRow + x
      maskAlpha[target] = maskData.data[(sourceRow + minX + x) * 4 + 3]
      resultAlpha[target] = resultData.data[target * 4 + 3]
    }
  }
  const compositingAlpha = retouchRegionAlpha(
    resultAlpha,
    maskAlpha,
    localWidth,
    localHeight,
    featherPx,
  )
  for (let i = 3, pixel = 0; i < resultData.data.length; i += 4, pixel++) {
    resultData.data[i] = compositingAlpha[pixel]
  }
  resultCtx.putImageData(resultData, 0, 0)

  outputCtx.globalAlpha = opacity
  outputCtx.drawImage(resultCanvas, minX, minY)
  outputCtx.globalAlpha = 1
  return output
}

/**
 * Composite a cutout (Remove background) step: multiply the input's alpha by
 * the matte's alpha.
 *
 * The matte is a full-frame candidate whose COLOR pixels are deliberately
 * ignored — the kept foreground is the live composite below, so edits under
 * the cutout keep showing through it. Where the positioned matte has no
 * coverage (geometry changed under a stale step) the alpha is zero and those
 * pixels cut away; the staleness advisory is what says to resample.
 */
export function applyCutout(
  input: CanvasImageSource,
  matte: CanvasImageSource,
  width: number,
  height: number,
  options: { featherPx?: number; opacity?: number } = {},
): HTMLCanvasElement {
  const { featherPx = 0, opacity = 1 } = options

  const output = makeCanvas(width, height)
  const outputCtx = output.getContext('2d', { willReadFrequently: true })!
  outputCtx.drawImage(input, 0, 0, width, height)
  const outputData = outputCtx.getImageData(0, 0, width, height)

  const matteCanvas = makeCanvas(width, height)
  const matteCtx = matteCanvas.getContext('2d', { willReadFrequently: true })!
  matteCtx.drawImage(matte, 0, 0, width, height)
  const matteData = matteCtx.getImageData(0, 0, width, height)

  const inputAlpha = new Uint8ClampedArray(width * height)
  const matteAlpha = new Uint8ClampedArray(width * height)
  for (let i = 3, pixel = 0; i < outputData.data.length; i += 4, pixel++) {
    inputAlpha[pixel] = outputData.data[i]
    matteAlpha[pixel] = matteData.data[i]
  }
  const composited = cutoutAlpha(
    inputAlpha, matteAlpha, width, height, featherPx, opacity,
  )
  for (let i = 3, pixel = 0; i < outputData.data.length; i += 4, pixel++) {
    outputData.data[i] = composited[pixel]
  }
  outputCtx.putImageData(outputData, 0, 0)
  return output
}

/**
 * Bounding box of a mask's non-black pixels, grown by `margin`.
 * Used to crop a model output down to the patch that is actually kept.
 */
export function maskBounds(
  mask: CanvasImageSource,
  width: number,
  height: number,
  margin = 0
): { x: number; y: number; width: number; height: number } | null {
  const canvas = makeCanvas(width, height)
  const ctx = canvas.getContext('2d', { willReadFrequently: true })!
  ctx.drawImage(mask, 0, 0, width, height)
  const { data } = ctx.getImageData(0, 0, width, height)

  let minX = width, minY = height, maxX = -1, maxY = -1
  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      if (data[(y * width + x) * 4] > 8) {
        if (x < minX) minX = x
        if (x > maxX) maxX = x
        if (y < minY) minY = y
        if (y > maxY) maxY = y
      }
    }
  }
  if (maxX < 0) return null

  minX = Math.max(0, minX - margin)
  minY = Math.max(0, minY - margin)
  maxX = Math.min(width - 1, maxX + margin)
  maxY = Math.min(height - 1, maxY + margin)
  return { x: minX, y: minY, width: maxX - minX + 1, height: maxY - minY + 1 }
}

/**
 * Crop a model output to the mask's bounds. Only this region is ever kept, so
 * storing the full frame would be storing pixels the composite discards.
 */
export function extractPatch(
  output: CanvasImageSource,
  bounds: { x: number; y: number; width: number; height: number }
): HTMLCanvasElement {
  const canvas = makeCanvas(bounds.width, bounds.height)
  canvas.getContext('2d')!.drawImage(
    output,
    bounds.x, bounds.y, bounds.width, bounds.height,
    0, 0, bounds.width, bounds.height
  )
  return canvas
}

/**
 * The share of a mask's coverage the picked sample cannot supply: composed
 * coverage weighted where the positioned patch has no pixels. Zero for
 * shrink-only edits — the whole point of live recompositing — and grows as
 * the mask is pushed past what the model actually painted.
 */
export function measureCoverageDebt(
  prepared: PreparedPatchMask,
  patch: CanvasImageSource,
): number {
  const scratch = makeCanvas(prepared.width, prepared.height)
  const ctx = scratch.getContext('2d', { willReadFrequently: true })!
  ctx.drawImage(patch, -prepared.x, -prepared.y)
  const data = ctx.getImageData(0, 0, prepared.width, prepared.height).data
  let covered = 0
  let owed = 0
  for (let p = 0, i = 3; p < prepared.alpha.length; p++, i += 4) {
    const want = prepared.alpha[p]
    if (!want) continue
    covered += want
    if (data[i] < 16) owed += want
  }
  return covered ? owed / covered : 0
}

export function canvasToBlob(canvas: HTMLCanvasElement, type = 'image/png'): Promise<Blob> {
  return new Promise((resolve, reject) => {
    canvas.toBlob(blob => (blob ? resolve(blob) : reject(new Error('canvas encode failed'))), type)
  })
}

export interface CompositorDeps {
  /**
   * Resolve a payload ref to something drawable. `revision` changes whenever
   * mutable paint pixels are rewritten under the same ref.
   */
  loadPayload: (ref: string, revision?: number) => Promise<CanvasImageSource>
  /** Resolve the base revision's pixels. */
  loadBase: () => Promise<CanvasImageSource>
  /**
   * The image as of each step, for the row previews — emitted during the
   * replay, where each intermediate composite already exists. Computing these
   * separately would mean replaying the stack once per row.
   *
   * Only steps the render actually recomputed are emitted: a render that
   * resumes from a cached intermediate leaves the ones below it untouched, and
   * their previews are unchanged by definition.
   */
  onStepPreview?: (opId: string, preview: string) => void
}

/** Longest edge of a row preview, in device-independent pixels. */
const STEP_PREVIEW_PX = 72

/**
 * A row-preview-sized snapshot of a composite, cropped square from the center
 * so a column of them reads as a column regardless of each frame's aspect.
 */
function squarePreview(source: HTMLCanvasElement): string {
  const size = Math.min(source.width, source.height)
  const canvas = makeCanvas(STEP_PREVIEW_PX, STEP_PREVIEW_PX)
  canvas.getContext('2d')!.drawImage(
    source,
    (source.width - size) / 2, (source.height - size) / 2, size, size,
    0, 0, STEP_PREVIEW_PX, STEP_PREVIEW_PX
  )
  // JPEG: the composite is opaque (it starts from the base), and a lossless
  // 72px tile per step would hold megabytes of data URL on a long stack.
  return canvas.toDataURL('image/jpeg', 0.72)
}

/**
 * Replays a stack into a composite, caching intermediates by input hash.
 *
 * Two byte-budgeted LRUs: replay stages and completed branch heads. Keeping
 * recent heads separate means an on/off branch cannot evict the exact canvas
 * needed to toggle back merely by filling the stage cache while it replays.
 * Byte budgets, rather than entry counts, make a 512px preview and an 8MP
 * source pay their actual memory cost.
 */
/** A stable 32-bit seed from an op id — same step, same grain, every render. */
function seedFrom(id: string): number {
  let hash = 0x811c9dc5
  for (let i = 0; i < id.length; i++) {
    hash ^= id.charCodeAt(i)
    hash = Math.imul(hash, 0x01000193)
  }
  return hash >>> 0
}

/** Compact deterministic cache key for an internal stage. */
function contentHash(value: string): string {
  return seedFrom(value).toString(16).padStart(8, '0')
}

export class StackCompositor {
  private cache = new Map<string, HTMLCanvasElement>()
  private cacheBytes = 0
  /** Recent completed branches are retained separately from replay stages. */
  private heads = new Map<string, HTMLCanvasElement>()
  private headBytes = 0
  /**
   * The immutable base has its own trust domain. It must never be populated
   * from a replay stage or a persisted head projection.
   */
  private bases = new Map<string, HTMLCanvasElement>()
  /** Input-independent, compact feather masks reused across lower-stack edits. */
  private preparedPatchMasks = new Map<string, PreparedPatchMask | null>()
  private preparedPatchMaskBytes = 0
  private readonly maxPreparedPatchMaskBytes = 32 * 1024 * 1024
  /** Ops that could not be applied on the last render, for the UI to report. */
  readonly failedOpIds = new Set<string>()
  /**
   * Coverage debt per generative op with a composite mask: the share of its
   * composed coverage the picked sample never painted (0..1). Written when
   * the op is actually recomputed; a cached stage keeps its last value.
   */
  readonly maskDebt = new Map<string, number>()
  private readonly maxCacheBytes: number
  private readonly maxHeadBytes: number

  constructor(
    private deps: CompositorDeps,
    options: { stageCacheBytes?: number; headCacheBytes?: number } = {},
  ) {
    this.maxCacheBytes = options.stageCacheBytes ?? 160 * 1024 * 1024
    this.maxHeadBytes = options.headCacheBytes ?? 96 * 1024 * 1024
  }

  clear() {
    this.cache.clear()
    this.cacheBytes = 0
    this.maskDebt.clear()
    this.heads.clear()
    this.headBytes = 0
    this.bases.clear()
    this.gradientRaster.clear()
    this.preparedPatchMasks.clear()
    this.preparedPatchMaskBytes = 0
  }

  /**
   * Seed an exact materialized stage, typically the persisted cold-open head.
   *
   * Restoring the head deliberately avoids replaying every source-resolution
   * edit, so its intermediate composites do not exist yet. Use the head's
   * real image as an immediate fallback for those rows instead of leaving a
   * column of empty thumbnail wells. Any later replay replaces the fallback
   * with that step's exact preview through the normal callback.
   */
  prime(hash: string, canvas: HTMLCanvasElement, fallbackPreviewOpIds: string[] = []) {
    this.rememberHead(hash, canvas)
    if (!fallbackPreviewOpIds.length) return
    const preview = squarePreview(canvas)
    for (const opId of fallbackPreviewOpIds) {
      this.deps.onStepPreview?.(opId, preview)
    }
  }

  /** Drop cached composites at and above a given input hash. */
  invalidateFrom(hash: string) {
    this.deleteStage(hash)
    this.deleteHead(hash)
  }

  private canvasBytes(canvas: HTMLCanvasElement): number {
    return canvas.width * canvas.height * 4
  }

  private deleteStage(key: string) {
    const existing = this.cache.get(key)
    if (!existing) return
    this.cacheBytes -= this.canvasBytes(existing)
    this.cache.delete(key)
  }

  private deleteHead(key: string) {
    const existing = this.heads.get(key)
    if (!existing) return
    this.headBytes -= this.canvasBytes(existing)
    this.heads.delete(key)
  }

  private remember(key: string, canvas: HTMLCanvasElement) {
    this.deleteStage(key)
    const bytes = this.canvasBytes(canvas)
    while (this.cache.size && this.cacheBytes + bytes > this.maxCacheBytes) {
      const oldest = this.cache.keys().next().value
      if (oldest === undefined) break
      this.deleteStage(oldest)
    }
    this.cache.set(key, canvas)
    this.cacheBytes += bytes
  }

  private rememberHead(key: string, canvas: HTMLCanvasElement) {
    this.deleteHead(key)
    const bytes = this.canvasBytes(canvas)
    while (this.heads.size && this.headBytes + bytes > this.maxHeadBytes) {
      const oldest = this.heads.keys().next().value
      if (oldest === undefined) break
      this.deleteHead(oldest)
    }
    this.heads.set(key, canvas)
    this.headBytes += bytes
  }

  private cached(key: string): HTMLCanvasElement | null {
    const canvas = this.cache.get(key)
    if (!canvas) return null
    // A get refreshes recency, keeping the stages nearest active edits hot.
    this.cache.delete(key)
    this.cache.set(key, canvas)
    return canvas
  }

  private cachedHead(key: string): HTMLCanvasElement | null {
    const canvas = this.heads.get(key)
    if (!canvas) return null
    this.heads.delete(key)
    this.heads.set(key, canvas)
    return canvas
  }

  private preparedPatchMask(
    key: string,
    mask: CanvasImageSource,
    width: number,
    height: number,
    featherPx: number,
  ): PreparedPatchMask | null {
    if (this.preparedPatchMasks.has(key)) {
      const cached = this.preparedPatchMasks.get(key) ?? null
      this.preparedPatchMasks.delete(key)
      this.preparedPatchMasks.set(key, cached)
      return cached
    }
    const prepared = preparePatchMask(mask, width, height, featherPx)
    const bytes = prepared?.alpha.byteLength ?? 1
    while (
      this.preparedPatchMasks.size
      && this.preparedPatchMaskBytes + bytes > this.maxPreparedPatchMaskBytes
    ) {
      const oldest = this.preparedPatchMasks.keys().next().value
      if (oldest === undefined) break
      const removed = this.preparedPatchMasks.get(oldest)
      this.preparedPatchMaskBytes -= removed?.alpha.byteLength ?? 1
      this.preparedPatchMasks.delete(oldest)
    }
    this.preparedPatchMasks.set(key, prepared)
    this.preparedPatchMaskBytes += bytes
    return prepared
  }

  /**
   * The composite an op at `index` applies to — everything strictly below it.
   * Resampling a step needs this, not the head: a step re-samples against what
   * it actually sits on.
   */
  async renderUpTo(doc: StackDocument, index: number): Promise<HTMLCanvasElement> {
    return this.render({ ...doc, edits: doc.edits.slice(0, index) })
  }

  private async renderBase(doc: StackDocument): Promise<HTMLCanvasElement> {
    const key = JSON.stringify([
      doc.base.file_hash,
      doc.base.payload_ref ?? null,
      doc.canvas.width,
      doc.canvas.height,
    ])
    const cached = this.bases.get(key)
    if (cached) return cached

    const source = await this.deps.loadBase()
    const base = makeCanvas(doc.canvas.width, doc.canvas.height)
    base.getContext('2d')!.drawImage(
      source,
      0,
      0,
      doc.canvas.width,
      doc.canvas.height,
    )
    this.bases.set(key, base)
    return base
  }

  async render(doc: StackDocument): Promise<HTMLCanvasElement> {
    const { inputs, head } = stackHashes(doc)

    // This is a correctness boundary, not merely a fast path. When every edit
    // is disabled, no replay or persisted projection is allowed to answer for
    // the original image. Only the immutable base source can supply it.
    if (!doc.edits.some(op => op.enabled)) {
      const base = await this.renderBase(doc)
      this.rememberHead(head, base)
      const preview = squarePreview(base)
      for (const op of doc.edits) this.deps.onStepPreview?.(op.id, preview)
      return base
    }

    const cachedHead = this.cachedHead(head) ?? this.cached(head)
    if (cachedHead) return cachedHead
    this.failedOpIds.clear()

    const width = doc.canvas.width
    const height = doc.canvas.height

    // Start from the deepest cached point rather than the base.
    let startIndex = 0
    let current: HTMLCanvasElement | null = null
    for (let i = doc.edits.length - 1; i >= 0; i--) {
      const cached = this.cached(inputs[i]) ?? this.cachedHead(inputs[i])
      if (cached) {
        current = cached
        startIndex = i
        break
      }
    }
    if (!current) {
      current = await this.renderBase(doc)
      if (doc.edits.length) this.remember(inputs[0], current)
    }

    for (let i = startIndex; i < doc.edits.length; i++) {
      const op = doc.edits[i]
      // A geometry op resizes the frame, and every op above it works in the
      // new space — which is why the working size is carried forward rather
      // than read from the document.
      //
      // An op whose payload cannot be loaded contributes nothing rather than
      // failing the render: one unreadable mask must not blank the canvas and
      // hide every other step's work.
      try {
        current = await this.applyOp(
          current,
          op,
          current.width,
          current.height,
          doc,
          i,
          inputs[i],
        )
      } catch (error) {
        this.failedOpIds.add(op.id)
        console.warn(`[imageStack] step "${op.label}" could not be applied`, error)
      }
      const isHead = i + 1 >= inputs.length
      const nextHash = isHead ? head : inputs[i + 1]
      if (!isHead) this.remember(nextHash, current)
      this.deps.onStepPreview?.(op.id, squarePreview(current))
    }
    this.rememberHead(head, current)
    return current
  }

  /**
   * A payload, carried from the frame it was MADE in into the frame it is
   * being USED in.
   *
   * Every spatial payload — a mask, a paint layer, a region — records the
   * geometry that was below it when it was created (`payload_frame`). That
   * recording is the anchor: it makes the payload's pixels addressable in the
   * ORIGINAL image's coordinates, `M_created⁻¹`, and from there they can be
   * carried into whatever the geometry is now, `M_now ∘ M_created⁻¹`. Without
   * an anchor there is nothing to translate through: a crop removed after the
   * payload was made leaves it sitting at coordinates that meant something in
   * a frame that no longer exists.
   *
   * Derived at composite time rather than baked, so removing a crop and
   * putting it back lands the payload exactly where it started instead of
   * resampling it twice.
   */
  private async loadAnchored(
    ref: string,
    doc: StackDocument,
    index: number,
    width: number,
    height: number,
    options: {
      /** Canonical local-payload → document transform. */
      payloadToDocument?: number[]
      /** Compatibility origin in the authored frame. */
      origin?: [number, number]
      /** Compatibility frame when the canonical transform is absent. */
      payloadFrame?: { matrix: number[] }
      revision?: number
    } = {},
  ): Promise<CanvasImageSource> {
    const op = doc.edits[index] as any
    const payload = await this.deps.loadPayload(
      ref,
      options.revision ?? op?._revision ?? 0,
    )
    const now = geometryBelow(doc, index)
    const previewScale = Number((doc as any)._preview_scale ?? 1)
    const documentToPreview: Affine = [
      previewScale, 0, 0, previewScale, 0, 0,
    ]
    const nowFromDocument = multiply(now.matrix, documentToPreview)
    const origin = options.origin ?? [0, 0]
    const canonical = options.payloadToDocument as Affine | undefined
    const legacyFrame = options.payloadFrame
    const documentFromPayload = canonical
      ?? (legacyFrame ? payloadToDocument(legacyFrame, origin) : null)

    // Unanchored legacy payloads still live in the stage they are being used
    // in. Fold a compact origin into one transform so the compositor never
    // positions transformed pixels a second time.
    const matrix = documentFromPayload
      ? multiply(nowFromDocument, documentFromPayload)
      : multiply(documentToPreview, translate(origin[0], origin[1]))
    return canReusePositionedPayload(payload, matrix, width, height)
      ? payload
      : rewritePayload(payload, matrix, width, height)
  }

  /** Rebuild one compact Retouch payload in its full authored frame, then anchor it. */
  private async loadRetouchPayload(
    ref: string,
    region: any,
    doc: StackDocument,
    index: number,
    width: number,
    height: number,
  ): Promise<CanvasImageSource> {
    const payload = await this.deps.loadPayload(ref, 0)
    return this.positionRetouchPayload(payload, region, doc, index, width, height)
  }

  /**
   * A region's coverage, whatever it is made of.
   *
   * Drawn regions load their payload. Gradient regions have no payload: their
   * geometry is rasterised in the authored frame right here, and then travels
   * the identical positioning path, so a ramp co-transforms with a later crop
   * exactly the way a brushed mask does.
   *
   * A composite region positions every component through that same path —
   * each with its OWN authored anchor — and composes them in soft alpha. The
   * component list is the sole authority when present; the legacy single-mask
   * fields keep answering for every document written before it existed.
   */
  private async loadRegionMask(
    region: any,
    doc: StackDocument,
    index: number,
    width: number,
    height: number,
  ): Promise<CanvasImageSource | null> {
    const components = region.mask_components as MaskComponent[] | undefined
    if (components?.length) {
      const layers: MaskComposeLayer[] = []
      for (const component of components) {
        const enabled = component.enabled !== false
        layers.push({
          source: enabled
            ? await this.loadComponentMask(component, doc, index, width, height)
            : null,
          mode: component.mode,
          enabled,
        })
      }
      if (!layers.some(layer => layer.enabled && layer.source)) return null
      return composeMaskCanvases(layers, width, height)
    }
    const mask = region.mask
    if (isGradientMask(mask)) {
      const previewScale = Number((doc as any)._preview_scale ?? 1) || 1
      const frame = region.payload_frame
      const authoredWidth = Math.max(1, Math.round(frame?.width ?? width / previewScale))
      const authoredHeight = Math.max(1, Math.round(frame?.height ?? height / previewScale))
      const rasterised = this.rasteriseGradient(mask, authoredWidth, authoredHeight)
      // Rasterised full-frame, so it has no compact origin of its own.
      return this.positionRetouchPayload(
        rasterised, { ...region, payload_origin: [0, 0] }, doc, index, width, height,
      )
    }
    if (!region.mask_ref) return null
    return this.loadRetouchPayload(region.mask_ref, region, doc, index, width, height)
  }

  /**
   * One component's positioned coverage. The component carries the same
   * anchor fields a region does, so it rides the identical positioning path.
   * An unreadable component contributes nothing rather than blanking the
   * whole composition — the same posture one unreadable op takes toward the stack.
   */
  private async loadComponentMask(
    component: MaskComponent,
    doc: StackDocument,
    index: number,
    width: number,
    height: number,
  ): Promise<CanvasImageSource | null> {
    try {
      const mask = component.mask
      if (isGradientMask(mask)) {
        const previewScale = Number((doc as any)._preview_scale ?? 1) || 1
        const frame = component.payload_frame
        const authoredWidth = Math.max(1, Math.round(frame?.width ?? width / previewScale))
        const authoredHeight = Math.max(1, Math.round(frame?.height ?? height / previewScale))
        const rasterised = this.rasteriseGradient(mask, authoredWidth, authoredHeight)
        return this.positionRetouchPayload(
          rasterised, { ...component, payload_origin: [0, 0] }, doc, index, width, height,
        )
      }
      if (!component.mask_ref) return null
      const positioned = await this.loadRetouchPayload(
        component.mask_ref, component, doc, index, width, height,
      )
      // Generative submission masks keep coverage as opaque luminance;
      // composition mixes in alpha. Translate after positioning, so the
      // opaque black outside the shape does not read as full coverage.
      return component.luminance
        ? luminanceToAlphaCanvas(positioned, width, height)
        : positioned
    } catch (error) {
      console.warn('[imageStack] mask component could not be loaded', error)
      return null
    }
  }

  /**
   * Rasterising a ramp is a full-frame per-pixel pass, and a region's geometry
   * usually does NOT change between renders — every adjustment slider re-renders
   * the same mask. Caching it keeps a gradient region as cheap to re-render as a
   * drawn one; without it, tuning Exposure on a gradient costs several times
   * what tuning it on a brushed region costs.
   *
   * One entry per region geometry: the key is the geometry itself, so a moved
   * handle misses and everything else hits.
   */
  private gradientRaster = new Map<string, HTMLCanvasElement>()

  private rasteriseGradient(
    mask: GradientMask,
    width: number,
    height: number,
  ): HTMLCanvasElement {
    const key = `${JSON.stringify(mask)}@${width}x${height}`
    const cached = this.gradientRaster.get(key)
    if (cached) return cached
    const rasterised = gradientMaskCanvas(mask, width, height)
    // Handle drags walk through many geometries; keep the map from growing
    // without bound while still holding the handful a document really uses.
    if (this.gradientRaster.size > 24) this.gradientRaster.clear()
    this.gradientRaster.set(key, rasterised)
    return rasterised
  }

  private positionRetouchPayload(
    payload: CanvasImageSource,
    region: any,
    doc: StackDocument,
    index: number,
    width: number,
    height: number,
  ): CanvasImageSource {
    const created = region.payload_frame
    const [x, y] = region.payload_origin ?? [0, 0]
    const previewScale = Number((doc as any)._preview_scale ?? 1)
    const baseScale: Affine = [previewScale, 0, 0, previewScale, 0, 0]
    const now = geometryBelow(doc, index)
    // Preview documents render document space at a smaller scale. Canonical
    // payload anchors remain in source document pixels; scaling is solely a
    // document-to-stage concern.
    const nowFromDocument = multiply(now.matrix, baseScale)
    const canonical = region.payload_to_document as Affine | undefined
    const documentFromPayload = canonical
      ?? (created ? payloadToDocument(created, [x, y]) : null)
    const positioned = documentFromPayload
      ? multiply(nowFromDocument, documentFromPayload)
      : multiply(baseScale, translate(x, y))
    return canReusePositionedPayload(payload, positioned, width, height)
      ? payload
      : rewritePayload(payload, positioned, width, height)
  }

  private async applyOp(
    input: HTMLCanvasElement,
    op: Op,
    width: number,
    height: number,
    doc: StackDocument,
    index: number,
    inputHash: string,
  ): Promise<HTMLCanvasElement> {
    if (!op.enabled) return input

    const picked = pickedCandidate(op)
    const anyOp = op as any

    if (op.class === 'patch') {
      // No pick yet — the op is staged, and a staged op contributes nothing.
      if (!picked?.patch_ref || !anyOp.mask_ref) return input
      // Expand is the one patch that GROWS the frame. Its candidate is the
      // whole outpainted frame at the grown size (the tool grew the canvas
      // itself), so it becomes the new working canvas and the input is drawn
      // back over the region where the source sits — the original pixels stay
      // authoritative, and the model's seam blending lives outside that rect.
      // The render loop carries the new size forward, exactly as it does for
      // crop; geometryBelow mirrors this branch (picked + enabled) so payloads
      // above anchor into the grown frame.
      if (anyOp.operation === 'expand') {
        const frame = expandedFrame(
          expandEdgesFromParams(anyOp.params), width, height,
        )
        const patch = await this.deps.loadPayload(
          picked.patch_ref, anyOp._revision ?? 0,
        )
        const grown = makeCanvas(frame.width, frame.height)
        const ctx = grown.getContext('2d')!
        // The candidate is CROPPED to the border mask's bounds (a single-edge
        // expand's "ring" is just a strip), positioned by its origin. Drawn at
        // natural size — scaling it to the canvas smeared a ~250px seam strip
        // across the whole frame. Coverage is complete regardless: the patch
        // spans every expanded band plus the ingest margin, and the original
        // overlay below covers the interior.
        const origin = picked.patch_origin ?? [0, 0]
        ctx.drawImage(patch as any, origin[0], origin[1])

        // The original overdraw, feathered on the EXPANDED edges only. The
        // model's border content often comes back softer than the source (a
        // working-resolution round trip), and a hard crisp-against-soft
        // boundary reads as a seam even when the content continues. Fading
        // the overdraw into the candidate over the blend feather hides that
        // discontinuity; near the seam the candidate is the tool's own blend
        // of the original, so nothing of consequence is given up. Un-expanded
        // edges stay hard — they are the image boundary.
        const overlay = makeCanvas(frame.width, frame.height)
        const octx = overlay.getContext('2d')!
        octx.drawImage(input, frame.left, frame.top)
        const featherPx = Math.min(
          Math.max(0, anyOp.blend?.feather_px ?? 0),
          Math.floor(Math.min(width, height) / 4),
        )
        if (featherPx > 0) {
          octx.globalCompositeOperation = 'destination-out'
          const fade = (
            x0: number, y0: number, x1: number, y1: number,
            rx: number, ry: number, rw: number, rh: number,
          ) => {
            const gradient = octx.createLinearGradient(x0, y0, x1, y1)
            gradient.addColorStop(0, 'rgba(0,0,0,1)')
            gradient.addColorStop(1, 'rgba(0,0,0,0)')
            octx.fillStyle = gradient
            octx.fillRect(rx, ry, rw, rh)
          }
          const rightPad = frame.width - frame.left - width
          const bottomPad = frame.height - frame.top - height
          if (frame.left > 0) {
            fade(frame.left, 0, frame.left + featherPx, 0,
              frame.left, frame.top, featherPx, height)
          }
          if (rightPad > 0) {
            fade(frame.left + width, 0, frame.left + width - featherPx, 0,
              frame.left + width - featherPx, frame.top, featherPx, height)
          }
          if (frame.top > 0) {
            fade(0, frame.top, 0, frame.top + featherPx,
              frame.left, frame.top, width, featherPx)
          }
          if (bottomPad > 0) {
            fade(0, frame.top + height, 0, frame.top + height - featherPx,
              frame.left, frame.top + height - featherPx, width, featherPx)
          }
          octx.globalCompositeOperation = 'source-over'
        }
        ctx.globalAlpha = anyOp.blend?.opacity ?? 1
        ctx.drawImage(overlay, 0, 0)
        ctx.globalAlpha = 1
        return grown
      }
      // A cutout's candidate is a matte, not a patch: its alpha cuts the
      // composite instead of its pixels drawing over it.
      if (anyOp.operation === 'cutout') {
        const matte = await this.loadAnchored(picked.patch_ref, doc, index, width, height, {
          payloadToDocument: picked.payload_to_document,
          origin: picked.patch_origin,
          payloadFrame: anyOp.payload_frame,
          revision: anyOp._revision ?? 0,
        })
        return applyCutout(input, matte, width, height, {
          featherPx: anyOp.blend?.feather_px ?? 0,
          opacity: anyOp.blend?.opacity ?? 1,
        })
      }
      // The patch was generated FOR a mask in the same frame, so the two
      // travel together. A composite mask composition outranks the stored
      // submission mask: candidates recomposite LIVE through the composed
      // coverage — shrinking it needs no resample, and coverage the samples
      // never painted honestly shows the input beneath.
      const components = anyOp.mask_components as MaskComponent[] | undefined
      const [patch, mask] = await Promise.all([
        this.loadAnchored(picked.patch_ref, doc, index, width, height, {
          payloadToDocument: picked.payload_to_document,
          origin: picked.patch_origin,
          payloadFrame: anyOp.payload_frame,
          revision: anyOp._revision ?? 0,
        }),
        components?.length
          ? this.loadRegionMask({ mask_components: components }, doc, index, width, height)
          : this.loadAnchored(anyOp.mask_ref, doc, index, width, height, {
              payloadToDocument: anyOp.payload_to_document,
              payloadFrame: anyOp.payload_frame,
              revision: anyOp._revision ?? 0,
            }),
      ])
      // A composition composed to nothing keeps the input untouched — and owes
      // nothing.
      if (!mask) {
        this.maskDebt.delete(op.id)
        return input
      }
      const featherPx = anyOp.blend?.feather_px ?? 6
      const geometry = geometryBelow(doc, index)
      const maskCacheKey = JSON.stringify([
        anyOp.mask_ref,
        components ?? null,
        anyOp._revision ?? 0,
        anyOp.payload_to_document ?? anyOp.payload_frame ?? null,
        geometry.matrix,
        (doc as any)._preview_scale ?? 1,
        width,
        height,
        featherPx,
      ])
      const preparedMask = this.preparedPatchMask(
        maskCacheKey,
        mask,
        width,
        height,
        featherPx,
      )
      // Coverage debt: the share of the composed mask the picked sample never
      // painted. Only a composite mask can grow past its samples; the legacy
      // single mask is exactly what they were generated for.
      if (components?.length) {
        this.maskDebt.set(op.id, preparedMask
          ? measureCoverageDebt(preparedMask, patch)
          : 0)
      } else {
        this.maskDebt.delete(op.id)
      }
      return compositePatch(input, patch, mask, width, height, {
        // Both payloads are already projected into this stage. Keeping a
        // second origin here was the crop-reorder bug.
        origin: [0, 0],
        featherPx,
        opacity: anyOp.blend?.opacity ?? 1,
        preparedMask,
      })
    }

    if (op.class === 'parametric') {
      const kind = anyOp.exec?.kind
      if (kind === 'crop') {
        return applyCrop(input, input.width, input.height, anyOp.params || {})
      }
      if (kind === 'adjust') {
        if (adjustIsIdentity(anyOp.params || {})) return input
        // The op's id seeds its noise, so a step's grain belongs to that step
        // and survives every re-render of everything around it.
        return applyAdjust(input, width, height, anyOp.params || {}, seedFrom(op.id))
      }
      return input
    }

    if (op.class === 'container') {
      const kind = anyOp.exec?.kind
      if (kind === 'annotate') {
        const shapes = anyOp.shapes_in_document
          ? transformShapes(
              anyOp.params?.shapes || [],
              geometryBelow(doc, index).matrix,
              doc.canvas.width,
              doc.canvas.height,
              width,
              height,
            )
          : anyOp.params?.shapes || []
        return applyAnnotations(input, width, height, shapes, input)
      }
      if (kind === 'retouch-regions') {
        let output = input
        let regionStageHash = `retouch:${inputHash}:${op.id}:${width}x${height}`
        for (const region of anyOp.regions ?? []) {
          if (!region.enabled) continue
          regionStageHash = `retouch:${contentHash(
            `${regionStageHash}|${JSON.stringify(region)}`,
          )}`
          const cachedRegion = this.cached(regionStageHash)
          if (cachedRegion) {
            output = cachedRegion
            continue
          }
          const mask = await this.loadRegionMask(region, doc, index, width, height)
          // A region with no coverage yet — no payload, or a gradient dragged
          // to nothing — contributes nothing rather than covering everything.
          if (!mask) continue
          // A local adjustment is parametric: it derives fresh pixels from
          // the composite beneath it on every render, then the retained mask
          // limits those pixels to the authored region. Unlike Heal/Clone it
          // never bakes a result cache or becomes stale.
          if (
            region.kind === 'adjust'
            || region.kind === 'light'
            || region.kind === 'color'
            || region.kind === 'detail'
            || region.kind === 'mixer'
            || region.kind === 'point'
            || region.kind === 'grade'
            || region.kind === 'effects'
            || region.kind === 'stylize'
            || region.kind === 'look'
          ) {
            const settings = region.settings ?? {}
            const adjusted = applyAdjust(
              output,
              width,
              height,
              maskedRetouchAdjustmentParams(settings),
              seedFrom(region.id),
            )
            output = compositeRetouchRegion(
              output,
              adjusted,
              mask,
              width,
              height,
              {
                featherPx: settings.feather_px ?? 0,
                opacity: settings.opacity ?? 1,
              },
            )
            this.remember(regionStageHash, output)
            continue
          }
          if (!region.result_ref) continue
          const result = await this.loadRetouchPayload(
            region.result_ref,
            region,
            doc,
            index,
            width,
            height,
          )
          output = compositeRetouchRegion(
            output,
            result,
            mask,
            width,
            height,
            {
              featherPx: region.settings?.feather_px ?? 0,
              opacity: region.settings?.opacity ?? 1,
            },
          )
          this.remember(regionStageHash, output)
        }
        return output
      }
      if (!anyOp.raster_ref) return input
      const layer = await this.loadAnchored(anyOp.raster_ref, doc, index, width, height, {
        payloadToDocument: anyOp.payload_to_document,
        payloadFrame: anyOp.payload_frame,
      })
      return applyRasterLayer(input, layer, width, height, anyOp.blend?.opacity ?? 1)
    }

    // An op kind this build does not know is a no-op rather than an error: a
    // document written by a newer build must still open and render.
    return input
  }
}
