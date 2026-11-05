import { sanitizeSvg } from '../../utils/sanitizeHtml'
import type { FamilyId } from '../stack/toolFamilies'

// One optical weight for the family glyphs. The global icon stroke would draw
// every glyph at the same width, but Adjust (three sliders) and Retouch (a
// hatched pill) put about a third more ink in the same box than Annotate or
// Generate, so the dense ones draw a little thinner and the tray reads as one
// set. Measured as ink coverage of the 24px box at the shared stroke.
const FAMILY_STROKE: Partial<Record<FamilyId, number>> = {
  crop: 1.6,
  retouch: 1.5,
  levels: 1.4,
}
const DEFAULT_STROKE = 1.75

/** A family's glyph as a sanitized inline SVG at its optical stroke width. */
export function familyIconSvg(id: FamilyId, paths: string): string {
  const width = FAMILY_STROKE[id] ?? DEFAULT_STROKE
  return sanitizeSvg(
    `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="${width}" data-stroke="own"
      stroke-linecap="round" stroke-linejoin="round">${paths}</svg>`
  )
}
