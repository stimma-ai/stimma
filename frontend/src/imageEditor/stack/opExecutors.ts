/**
 * Executors for the op kinds that carry over from the snapshot editor.
 *
 * The pixel math is the snapshot editor's, copied into `imageEditor/ported/`
 * rather than reimplemented — a second implementation of the color and effect
 * maths would drift, and the migrated documents have to look identical or the
 * migration is a lie. Copied rather than imported because the snapshot editor
 * is frozen and this editor has to outlive its package.
 *
 * What changes is the *shape*: the snapshot editor applied these as fields on
 * one flat state object in a fixed order, and here each is a step in a stack
 * that can be toggled, reordered and scoped. The Adjust op deliberately holds
 * every touched section (Light, Color, Film, Effects) rather than one op per
 * filter, because the user-facing unit is a adjust session, not a slider.
 */

import { cropPreviewSize } from '../ported/cropPreview.ts'
import {
  applyColorIsolation,
  applyColorMatrix,
  applyGradientMap,
  applySplitToning,
  combineAdjustments,
  multiplyColorMatrices,
} from '../ported/colorMatrix'
import { applyEffects, hasEffects, setEffectsSeed } from '../ported/effects'
import { FILTER_MATRICES } from '../ported/filterMatrices'
import { renderShapes } from '../ported/shapes'
import {
  applyPhotographicAdjustments,
  hasPhotographicAdjustments,
} from './photoAdjustments'
import { wholeImageAdjustmentParams } from './adjustSections'
import type { ToneCurve } from './toneCurve.ts'

export interface CropParams {
  /**
   * The crop rectangle, normalised against the input.
   *
   * `x`/`y` are the crop's CENTRE, not its top-left — the convention the
   * snapshot editor's crop UI produces and its writer consumes. Kept rather
   * than converted so migration is a straight copy: a coordinate conversion is
   * exactly the kind of thing that is wrong in one place and right in another.
   * An identity crop is therefore `{ x: 0.5, y: 0.5, width: 1, height: 1 }`.
   */
  rect: { x: number; y: number; width: number; height: number }
  /**
   * The crop WINDOW's own tilt, in radians — what the rotation lollipop sets.
   * Distinct from `rotation`, which turns the image inside the frame: tilting
   * the window turns the content the opposite way, which is what straightening
   * a horizon means.
   */
  cropRotation?: number
  /** Fine straightening, radians. */
  rotation?: number
  /** Quarter turns clockwise. */
  rotation90?: 0 | 1 | 2 | 3
  flipX?: boolean
  flipY?: boolean
}

export interface AdjustParams {
  // Light + color
  brightness?: number
  contrast?: number
  saturation?: number
  exposure?: number
  highlights?: number
  shadows?: number
  whites?: number
  blacks?: number
  curve?: ToneCurve
  temperature?: number
  tint?: number
  hue?: number
  gamma?: number
  vibrance?: number
  colorizeHue?: number
  colorizeAmount?: number
  defringe?: number
  filter?: string | null
  /** Preset strength, 0-100; below 100 blends the preset toward identity. */
  filterAmount?: number
  colorMatrix?: number[] | null
  // Film
  splitToningEnabled?: boolean
  splitToningShadowHue?: number
  splitToningShadowSat?: number
  splitToningHighlightHue?: number
  splitToningHighlightSat?: number
  splitToningBalance?: number
  gradientMapEnabled?: boolean
  gradientMapShadowColor?: any
  gradientMapHighlightColor?: any
  gradientMapIntensity?: number
  colorIsolationEnabled?: boolean
  colorIsolationHue?: number
  colorIsolationRange?: number
  colorIsolationFeather?: number
  // Effects
  blur?: number
  sharpen?: number
  noise?: number
  glow?: number
  pixelate?: number
  chromaticAberration?: number
  motionBlur?: number
  motionBlurAngle?: number
  vignette?: number
  texture?: number
  clarity?: number
  dehaze?: number
  moire?: number
  noiseReduction?: number
  sharpenRadius?: number
  sharpenDetail?: number
  sharpenMasking?: number
  noiseReductionDetail?: number
  noiseReductionContrast?: number
  colorNoiseReduction?: number
  colorNoiseReductionDetail?: number
  colorNoiseReductionSmoothness?: number
  grainSize?: number
  grainRoughness?: number
  halftone?: number
  halftoneAngle?: number
  vhs?: number
  glitch?: number
  glitchBlockSize?: number
  ditherEnabled?: boolean
  ditherPalette?: string
}

function makeCanvas(width: number, height: number): HTMLCanvasElement {
  const canvas = document.createElement('canvas')
  canvas.width = width
  canvas.height = height
  return canvas
}

/**
 * Output dimensions after a geometry op. Ops above a crop work in the cropped
 * space, so this has to be answerable without rendering.
 *
 * Quarter turns deliberately do NOT swap the output dimensions: the snapshot
 * editor rotates the drawn image inside a frame sized by the crop rectangle,
 * and a migrated document has to land on the same canvas.
 */
export function cropOutputSize(
  input: { width: number; height: number },
  params: CropParams
): { width: number; height: number } {
  return cropPreviewSize(
    Math.max(1, Math.round(input.width * (params.rect?.width ?? 1))),
    Math.max(1, Math.round(input.height * (params.rect?.height ?? 1))),
    params.rotation90,
  )
}

/**
 * Crop, straighten and flip.
 *
 * The stage order mirrors the snapshot editor's writer exactly — rotation
 * (fine + quarter turns as one angle), then flips, then the crop window drawn
 * about the output centre — because a different order produces a different
 * image, and a migrated document has to match pixel for pixel.
 */
export function applyCrop(
  input: CanvasImageSource,
  inputWidth: number,
  inputHeight: number,
  params: CropParams
): HTMLCanvasElement {
  const rect = params.rect ?? { x: 0.5, y: 0.5, width: 1, height: 1 }
  const { width, height } = cropOutputSize(
    { width: inputWidth, height: inputHeight },
    params
  )

  const sourceWidth = rect.width * inputWidth
  const sourceHeight = rect.height * inputHeight
  // Centre-based rect: the top-left of the crop window is the centre minus
  // half its size.
  const sourceX = (rect.x - rect.width / 2) * inputWidth
  const sourceY = (rect.y - rect.height / 2) * inputHeight

  const out = makeCanvas(width, height)
  const ctx = out.getContext('2d')!

  ctx.save()
  ctx.translate(width / 2, height / 2)
  const rotation = (params.rotation ?? 0) + ((params.rotation90 ?? 0) * Math.PI) / 2
  if (rotation !== 0) ctx.rotate(rotation)
  if (params.flipX || params.flipY) {
    ctx.scale(params.flipX ? -1 : 1, params.flipY ? -1 : 1)
  }

  // Rotate the frame with the crop, preserving its source dimensions.
  let drawWidth = width
  let drawHeight = height
  if (params.rotation90 === 1 || params.rotation90 === 3) {
    drawWidth = height
    drawHeight = width
  }

  const cropRotation = params.cropRotation ?? 0
  if (cropRotation !== 0) {
    // A tilted crop window is the image counter-tilted: the window's own axes
    // become the output's, so the content turns the OTHER way. Sampling has to
    // be done by transform rather than by a source rectangle, because the
    // region wanted is a rotated quadrilateral and drawImage only takes an
    // axis-aligned one. Output size equals the crop size in source pixels, so
    // no scale is needed — the same reasoning the snapshot editor's writer used.
    ctx.rotate(-cropRotation)
    ctx.translate(-rect.x * inputWidth, -rect.y * inputHeight)
    ctx.drawImage(input, 0, 0)
  } else {
    ctx.drawImage(
      input,
      sourceX, sourceY, sourceWidth, sourceHeight,
      -drawWidth / 2, -drawHeight / 2, drawWidth, drawHeight
    )
  }
  ctx.restore()
  return out
}

/** Whether a Adjust op would change any pixel — a no-op still costs a copy. */
export function adjustIsIdentity(params: AdjustParams): boolean {
  const zeroish = (v: number | undefined) => !v
  const photo = wholeImageAdjustmentParams(params)
  return (
    zeroish(photo.brightness) && zeroish(photo.contrast) && zeroish(photo.saturation) &&
    zeroish(photo.exposure) && zeroish(photo.temperature) && zeroish(photo.tint) &&
    (photo.gamma === undefined || photo.gamma === 1) &&
    !hasPhotographicAdjustments(photo) &&
    !params.filter && !params.colorMatrix &&
    !params.splitToningEnabled && !params.gradientMapEnabled && !params.colorIsolationEnabled &&
    !hasEffects(effectsStateFrom({ ...params, ...photo }))
  )
}

export function effectsStateFrom(params: AdjustParams) {
  return {
    blur: params.blur ?? 0,
    sharpen: params.sharpen ?? 0,
    noise: params.noise ?? 0,
    glow: params.glow ?? 0,
    pixelate: params.pixelate ?? 0,
    chromaticAberration: params.chromaticAberration ?? 0,
    motionBlur: params.motionBlur ?? 0,
    motionBlurAngle: params.motionBlurAngle ?? 0,
    vignette: params.vignette ?? 0,
    texture: params.texture ?? 0,
    clarity: params.clarity ?? 0,
    noiseReduction: params.noiseReduction ?? 0,
    sharpenRadius: params.sharpenRadius ?? 1,
    sharpenDetail: params.sharpenDetail ?? 0,
    sharpenMasking: params.sharpenMasking ?? 0,
    noiseReductionDetail: params.noiseReductionDetail ?? 0,
    noiseReductionContrast: params.noiseReductionContrast ?? 0,
    colorNoiseReduction: params.colorNoiseReduction ?? 0,
    colorNoiseReductionDetail: params.colorNoiseReductionDetail ?? 0,
    colorNoiseReductionSmoothness: params.colorNoiseReductionSmoothness ?? 0,
    grainSize: params.grainSize ?? 0,
    grainRoughness: params.grainRoughness ?? 50,
    moire: params.moire ?? 0,
    defringe: params.defringe ?? 0,
    halftone: params.halftone ?? 0,
    halftoneAngle: params.halftoneAngle ?? 0,
    vhs: params.vhs ?? 0,
    glitch: params.glitch ?? 0,
    glitchBlockSize: params.glitchBlockSize ?? 16,
    ditherEnabled: params.ditherEnabled ?? false,
    ditherPalette: (params.ditherPalette === 'none' ? '8bit' : params.ditherPalette) ?? '8bit',
  } as any
}

/**
 * The whole parametric adjustment family, in the snapshot editor's order:
 * base adjustments → filter preset → explicit matrix → split tone → gradient
 * map → color isolation → effects.
 */
export function applyAdjust(
  input: CanvasImageSource,
  width: number,
  height: number,
  params: AdjustParams,
  /**
   * Seeds the grain, VHS and glitch noise. Pass the op's id so a step's noise
   * is its own and never changes: without it every recomposite reshuffles the
   * frame, so dragging an annotation reprints the grain underneath it.
   */
  seed = 0
): HTMLCanvasElement {
  const photo = wholeImageAdjustmentParams(params)
  const out = makeCanvas(width, height)
  const ctx = out.getContext('2d', { willReadFrequently: true })!
  ctx.drawImage(input, 0, 0, width, height)

  const adjustments = {
    brightness: photo.brightness,
    contrast: photo.contrast,
    saturation: photo.saturation,
    exposure: photo.exposure,
    temperature: photo.temperature,
    tint: photo.tint,
    gamma: photo.gamma,
  }
  const hasAdjustments =
    adjustments.brightness !== 0 || adjustments.contrast !== 0 ||
    adjustments.saturation !== 0 || adjustments.exposure !== 0 ||
    adjustments.temperature !== 0 || adjustments.tint !== 0 || adjustments.gamma !== 1

  if (hasAdjustments) {
    const data = ctx.getImageData(0, 0, width, height)
    applyColorMatrix(data, combineAdjustments(adjustments))
    ctx.putImageData(data, 0, 0)
  }

  if (hasPhotographicAdjustments(photo)) {
    const data = ctx.getImageData(0, 0, width, height)
    applyPhotographicAdjustments(data, photo)
    ctx.putImageData(data, 0, 0)
  }

  if (params.filter && (FILTER_MATRICES as any)[params.filter]) {
    const identity = combineAdjustments({
      brightness: 0, contrast: 0, saturation: 0, exposure: 0, temperature: 0, gamma: 1,
    })
    // A preset at less than full strength is the preset blended back toward
    // identity — which is what an amount slider means for a color matrix, and
    // is why a filter step has something to adjust rather than being a switch.
    const amount = params.filterAmount ?? 100
    const preset = (FILTER_MATRICES as any)[params.filter] as number[]
    const IDENTITY_MATRIX = [1,0,0,0,0, 0,1,0,0,0, 0,0,1,0,0, 0,0,0,1,0]
    const blended = amount >= 100
      ? preset
      : preset.map((value, i) => IDENTITY_MATRIX[i] + (value - IDENTITY_MATRIX[i]) * (amount / 100))
    const matrix = multiplyColorMatrices(blended, identity)
    const data = ctx.getImageData(0, 0, width, height)
    applyColorMatrix(data, matrix)
    ctx.putImageData(data, 0, 0)
  }

  if (params.colorMatrix) {
    const data = ctx.getImageData(0, 0, width, height)
    applyColorMatrix(data, params.colorMatrix)
    ctx.putImageData(data, 0, 0)
  }

  if (params.splitToningEnabled) {
    const data = ctx.getImageData(0, 0, width, height)
    applySplitToning(
      data,
      params.splitToningShadowHue ?? 30,
      params.splitToningShadowSat ?? 0,
      params.splitToningHighlightHue ?? 200,
      params.splitToningHighlightSat ?? 0,
      params.splitToningBalance ?? 0
    )
    ctx.putImageData(data, 0, 0)
  }

  if (params.gradientMapEnabled && params.gradientMapShadowColor && params.gradientMapHighlightColor) {
    const data = ctx.getImageData(0, 0, width, height)
    applyGradientMap(
      data,
      params.gradientMapShadowColor,
      params.gradientMapHighlightColor,
      params.gradientMapIntensity ?? 100
    )
    ctx.putImageData(data, 0, 0)
  }

  if (params.colorIsolationEnabled) {
    const data = ctx.getImageData(0, 0, width, height)
    applyColorIsolation(
      data,
      params.colorIsolationHue ?? 0,
      params.colorIsolationRange ?? 30,
      params.colorIsolationFeather ?? 20
    )
    ctx.putImageData(data, 0, 0)
  }

  const effects = effectsStateFrom({ ...params, ...photo })
  if (hasEffects(effects)) {
    setEffectsSeed(seed)
    const result = applyEffects(out, effects)
    ctx.clearRect(0, 0, width, height)
    ctx.drawImage(result, 0, 0)
  }

  return out
}

/**
 * A transparent raster contribution drawn over its input.
 *
 * Paint uses this for a whole layer; Retouch uses it for each independently
 * stored repair result. Imported legacy retouch pixels are Paint layers.
 */
export function applyRasterLayer(
  input: CanvasImageSource,
  layer: CanvasImageSource,
  width: number,
  height: number,
  opacity = 1
): HTMLCanvasElement {
  const out = makeCanvas(width, height)
  const ctx = out.getContext('2d')!
  ctx.drawImage(input, 0, 0, width, height)
  ctx.globalAlpha = opacity
  ctx.drawImage(layer, 0, 0, width, height)
  ctx.globalAlpha = 1
  return out
}

/**
 * Vector annotations. Parametric-class physics: the shapes are params, so
 * re-rendering at any size is free and re-entering the op is lossless.
 */
export function applyAnnotations(
  input: CanvasImageSource,
  width: number,
  height: number,
  shapes: any[],
  sourceForRedaction?: HTMLCanvasElement
): HTMLCanvasElement {
  const out = makeCanvas(width, height)
  const ctx = out.getContext('2d')!
  ctx.drawImage(input, 0, 0, width, height)
  if (shapes?.length) {
    renderShapes(ctx, shapes as any, { width, height }, sourceForRedaction as any)
  }
  return out
}
