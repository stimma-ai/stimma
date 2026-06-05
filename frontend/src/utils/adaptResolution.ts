/**
 * Adapts source image dimensions to a target tool's resolution system.
 *
 * Given a source width/height and the target tool's resolution system type + constraints,
 * returns the closest valid configuration for that tool.
 */

export type ResolutionSystem = 'width-height' | 'constrained' | 'aspect-ratio' | 'megapixels'

export interface ResolutionConstraints {
  /** For 'constrained' system: list of allowed [width, height] pairs */
  allowedDimensions?: Array<{ width: number; height: number }>
  /** For 'aspect-ratio' system: list of aspect ratio strings like '16:9' */
  aspectChoices?: string[]
  /** For 'megapixels' system: range constraints */
  range?: { min: number; max: number; step: number }
  /** For 'width-height' system: width range constraints */
  widthRange?: { min: number; max: number; step: number }
  /** For 'width-height' system: height range constraints */
  heightRange?: { min: number; max: number; step: number }
}

export function adaptResolution(
  sourceWidth: number,
  sourceHeight: number,
  targetSystem: ResolutionSystem,
  targetConstraints: ResolutionConstraints
): Record<string, any> {
  switch (targetSystem) {
    case 'width-height':
      return adaptToWidthHeight(sourceWidth, sourceHeight, targetConstraints)
    case 'constrained':
      return adaptToConstrained(sourceWidth, sourceHeight, targetConstraints)
    case 'aspect-ratio':
      return adaptToAspectRatio(sourceWidth, sourceHeight, targetConstraints)
    case 'megapixels':
      return adaptToMegapixels(sourceWidth, sourceHeight, targetConstraints)
    default:
      return { width: sourceWidth, height: sourceHeight }
  }
}

function clampAndRound(value: number, min: number, max: number, step: number): number {
  const clamped = Math.max(min, Math.min(max, value))
  return Math.round(clamped / step) * step
}

function adaptToWidthHeight(
  sourceWidth: number,
  sourceHeight: number,
  constraints: ResolutionConstraints
): Record<string, any> {
  const wRange = constraints.widthRange ?? { min: 256, max: 2048, step: 64 }
  const hRange = constraints.heightRange ?? { min: 256, max: 2048, step: 64 }

  return {
    width: clampAndRound(sourceWidth, wRange.min, wRange.max, wRange.step),
    height: clampAndRound(sourceHeight, hRange.min, hRange.max, hRange.step),
  }
}

function adaptToConstrained(
  sourceWidth: number,
  sourceHeight: number,
  constraints: ResolutionConstraints
): Record<string, any> {
  const dims = constraints.allowedDimensions
  if (!dims || dims.length === 0) {
    return { width: sourceWidth, height: sourceHeight }
  }

  const sourceRatio = sourceWidth / sourceHeight
  const sourceArea = sourceWidth * sourceHeight

  // Find closest by aspect ratio similarity, then by area
  let best = dims[0]
  let bestScore = Infinity

  for (const dim of dims) {
    const ratio = dim.width / dim.height
    const area = dim.width * dim.height
    // Primary: aspect ratio difference (weighted heavily)
    // Secondary: area difference (normalized)
    const ratioDiff = Math.abs(ratio - sourceRatio)
    const areaDiff = Math.abs(area - sourceArea) / sourceArea
    const score = ratioDiff * 10 + areaDiff
    if (score < bestScore) {
      bestScore = score
      best = dim
    }
  }

  return { width: best.width, height: best.height }
}

function adaptToAspectRatio(
  sourceWidth: number,
  sourceHeight: number,
  constraints: ResolutionConstraints
): Record<string, any> {
  const choices = constraints.aspectChoices
  if (!choices || choices.length === 0) {
    return { aspect_ratio: '1:1' }
  }

  const sourceRatio = sourceWidth / sourceHeight

  // Find closest aspect ratio from choices
  let bestChoice = choices[0]
  let bestDiff = Infinity

  for (const choice of choices) {
    const parts = choice.split(':')
    if (parts.length !== 2) continue
    const w = parseInt(parts[0])
    const h = parseInt(parts[1])
    if (isNaN(w) || isNaN(h) || h === 0) continue
    const ratio = w / h
    const diff = Math.abs(ratio - sourceRatio)
    if (diff < bestDiff) {
      bestDiff = diff
      bestChoice = choice
    }
  }

  // Determine image_size based on total pixels
  const totalPixels = sourceWidth * sourceHeight
  let imageSize = '1K'
  if (totalPixels > 8_000_000) {
    imageSize = '4K'
  } else if (totalPixels > 2_000_000) {
    imageSize = '2K'
  }

  return { aspect_ratio: bestChoice, image_size: imageSize }
}

function adaptToMegapixels(
  sourceWidth: number,
  sourceHeight: number,
  constraints: ResolutionConstraints
): Record<string, any> {
  const range = constraints.range ?? { min: 0.3, max: 4.0, step: 0.1 }
  const mp = (sourceWidth * sourceHeight) / 1_000_000
  const clamped = clampAndRound(mp, range.min, range.max, range.step)
  // Round to 1 decimal to avoid floating point artifacts
  return { megapixels: Math.round(clamped * 10) / 10 }
}
