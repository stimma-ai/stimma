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
 *  - width.x-allowed-dimensions-> ConstrainedResolutionPicker (hint-based)
 *  - scale_factor|resolution
 *      w/ x-control:
 *      "upscale_resolution"    -> UpscaleResolutionPicker     (hint-based)
 */

export interface ResolutionControls {
  hasWidthHeight: boolean
  hasMegapixels: boolean
  hasAspectRatio: boolean
  allowedDimensions: [number, number][] | null
  hasScaleFactor: boolean
  hasUpscaleResolution: boolean
  showUpscalePicker: boolean
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

  return {
    hasWidthHeight,
    hasMegapixels: 'megapixels' in p,
    hasAspectRatio: 'aspect_ratio' in p,
    allowedDimensions,
    hasScaleFactor,
    hasUpscaleResolution,
    showUpscalePicker: hasScaleFactor || hasUpscaleResolution,
  }
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
