/**
 * Detection of the "resolution family" special controls from an STP properties
 * map (`{ name: stpProperty }`).
 *
 * This is the SINGLE source of truth for which inputs get a dedicated picker
 * instead of plain number/enum fields. Both ToolView (`useToolSchemaFeatures`)
 * and the flow input form (`FlowInputForm`) call it, so a flow's controls look
 * the same before and after it's frozen into a tool.
 *
 * Triggers are intentionally identical to what ToolView has always used:
 *  - width + height            -> ResolutionPicker            (name-based)
 *  - megapixels                -> MegapixelsPicker            (name-based)
 *  - aspect_ratio              -> GeminiResolutionPicker      (name-based)
 *  - width.x-allowed-dimensions-> ResolutionPicker, list mode (hint-based)
 *  - scale_factor|resolution
 *      w/ x-control:
 *      "upscale_resolution"    -> UpscaleResolutionPicker     (hint-based)
 */

/**
 * Bounds the upscale picker must honour for a given tool's scale_factor.
 *
 * Upscalers disagree about what a legal factor is — SeedVR2 takes any 0.5–4,
 * P-Image wants integers up to 16x, Bria accepts literally only 2 or 4. The
 * picker reads these off the schema instead of assuming, so it can never offer
 * a factor the provider will reject.
 */
export interface ScaleFactorConstraints {
  min: number
  max: number
  step: number
  /** Discrete legal factors. When set, the picker offers ONLY these. */
  allowedValues: number[] | null
}

export interface ResolutionControls {
  hasWidthHeight: boolean
  hasMegapixels: boolean
  hasAspectRatio: boolean
  allowedDimensions: [number, number][] | null
  hasScaleFactor: boolean
  hasUpscaleResolution: boolean
  showUpscalePicker: boolean
  scaleFactor: ScaleFactorConstraints
}

/** Legacy defaults — what the picker hardcoded before it read the schema. */
const DEFAULT_SCALE_CONSTRAINTS: ScaleFactorConstraints = {
  min: 0.5,
  max: 4,
  step: 0.1,
  allowedValues: null,
}

type Props = Record<string, any> | null | undefined

export function detectResolutionControls(props: Props): ResolutionControls {
  const p = props || {}

  const hasWidthHeight =
    p.width?.['x-paired-with'] === 'height' ||
    p.height?.['x-paired-with'] === 'width' ||
    ('width' in p && 'height' in p)

  const dims = p.width?.['x-allowed-dimensions']
  const allowedDimensions =
    Array.isArray(dims) && dims.length > 0 ? (dims as [number, number][]) : null

  const hasScaleFactor = p.scale_factor?.['x-control'] === 'upscale_resolution'
  const hasUpscaleResolution = p.resolution?.['x-control'] === 'upscale_resolution'

  const sf = p.scale_factor
  const sfAllowed = sf?.['x-allowed-values']
  const scaleFactor: ScaleFactorConstraints = hasScaleFactor
    ? {
        min: Number.isFinite(Number(sf?.minimum)) ? Number(sf.minimum) : DEFAULT_SCALE_CONSTRAINTS.min,
        max: Number.isFinite(Number(sf?.maximum)) ? Number(sf.maximum) : DEFAULT_SCALE_CONSTRAINTS.max,
        step: Number(sf?.['x-step']) || (sf?.type === 'integer' ? 1 : DEFAULT_SCALE_CONSTRAINTS.step),
        allowedValues:
          Array.isArray(sfAllowed) && sfAllowed.length > 0 ? (sfAllowed as number[]) : null,
      }
    : { ...DEFAULT_SCALE_CONSTRAINTS }

  return {
    hasWidthHeight,
    hasMegapixels: 'megapixels' in p,
    hasAspectRatio: 'aspect_ratio' in p,
    allowedDimensions,
    hasScaleFactor,
    hasUpscaleResolution,
    showUpscalePicker: hasScaleFactor || hasUpscaleResolution,
    scaleFactor,
  }
}

/** Snap a factor onto the tool's legal rungs. Mirrors the backend snap in
 *  stimma-cloud runware-provider.executeUpscale. */
export function snapScaleFactor(c: ScaleFactorConstraints, value: number): number {
  if (!Number.isFinite(value)) return c.allowedValues?.[0] ?? c.min
  if (c.allowedValues?.length) {
    return c.allowedValues.reduce((best, v) =>
      Math.abs(v - value) < Math.abs(best - value) ? v : best
    , c.allowedValues[0])
  }
  const clamped = Math.min(c.max, Math.max(c.min, value))
  if (!c.step) return clamped
  const snapped = c.min + Math.round((clamped - c.min) / c.step) * c.step
  // Re-clamp: rounding can overshoot when (max - min) isn't a whole multiple of step.
  return Math.min(c.max, Math.max(c.min, Number(snapped.toFixed(4))))
}

/**
 * Snap a (width, height) onto a tool's legal grid so inherited or edited
 * source dimensions land on a size the model actually accepts — a 640×384
 * image-to-image source should run at 640×384, an off-grid size snaps to the
 * nearest legal one. Mirrors the backend snap (stimma-cloud tool-params.ts,
 * agent stp_utils.snap_dims_to_schema): nearest allowed pair for constrained
 * tools, otherwise clamp+round each axis to the schema's min/max/step.
 */
export function snapDimsToGrid(props: Props, width: number, height: number): { width: number; height: number } {
  if (!Number.isFinite(width) || !Number.isFinite(height)) return { width, height }
  const p = props || {}
  const dims = detectResolutionControls(p).allowedDimensions
  if (dims && dims.length) {
    let best = dims[0]
    let bestDist = Infinity
    for (const [w, h] of dims) {
      const d = (w - width) ** 2 + (h - height) ** 2
      if (d < bestDist) { bestDist = d; best = [w, h] }
    }
    return { width: best[0], height: best[1] }
  }
  const snapAxis = (v: number, axis: any) => {
    const step = Number(axis?.['x-step']) || 1
    let x = Math.round(v / step) * step
    if (axis?.minimum != null) x = Math.max(Number(axis.minimum), x)
    if (axis?.maximum != null) x = Math.min(Number(axis.maximum), x)
    return x
  }
  return { width: snapAxis(width, p.width), height: snapAxis(height, p.height ?? p.width) }
}

/**
 * Param names a picker fully owns, so callers can hide the raw fields that the
 * picker subsumes. Depends on which pickers are active for this schema.
 */
export function paramsConsumedByResolutionPickers(props: Props): Set<string> {
  const c = detectResolutionControls(props)
  const consumed = new Set<string>()
  if (c.allowedDimensions || c.hasWidthHeight) {
    consumed.add('width')
    consumed.add('height')
  }
  if (c.hasMegapixels) consumed.add('megapixels')
  if (c.hasAspectRatio) {
    consumed.add('aspect_ratio')
    consumed.add('image_size')
  }
  if (c.showUpscalePicker) {
    consumed.add('scale_factor')
    consumed.add('resolution')
  }
  return consumed
}
