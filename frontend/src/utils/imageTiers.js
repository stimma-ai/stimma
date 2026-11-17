/**
 * Image delivery tiers: which bytes to fetch for a picture on screen.
 *
 * Never show fewer pixels than the screen can show; never ship more until the
 * person looks closer. The tier follows from resolution alone:
 *
 *   needed = displayed CSS size × devicePixelRatio × zoom
 *
 * thumb     the 1024 px fit thumbnail (usually warm from the grid)
 * screen    2560 px long side WebP, derived by the backend
 * full      full resolution, lossy (JPEG 4:4:4, or WebP with alpha) for remote zoom
 * original  the file itself, for local zoom and every non-viewing use
 *
 * The skip rule mirrors backend/utils/image_variants.py `variant_serves_original`:
 * when a variant would not help, it IS the original, and the client asks for
 * the original URL directly so the same pixels are never fetched twice.
 */

// Bump with VARIANT_VERSION in backend/utils/image_variants.py so browsers
// drop variants cached under the old encoding.
export const IMAGE_VARIANT_URL_VERSION = 1

export const THUMB_LONG_SIDE = 1024
export const SCREEN_LONG_SIDE = 2560
export const SCREEN_SKIP_LONG_SIDE = SCREEN_LONG_SIDE * 1.25 // 3200
export const SCREEN_SKIP_BYTES = 512 * 1024
export const FULL_SKIP_BYTES = 3 * 1024 * 1024

const VARIANT_SOURCE_FORMATS = new Set(['jpg', 'jpeg', 'png', 'webp', 'bmp'])
const LOSSY_FORMATS = new Set(['jpg', 'jpeg', 'webp'])
const IMAGE_FORMATS = new Set([...VARIANT_SOURCE_FORMATS, 'gif'])

export function isTieredImage(item) {
  return IMAGE_FORMATS.has(String(item?.file_format || '').toLowerCase())
}

export function imageLongSide(item) {
  const width = Number(item?.width) || 0
  const height = Number(item?.height) || 0
  return Math.max(width, height)
}

/** True when `tier` ('screen' | 'full') would just be the original file. */
export function tierServesOriginal(item, tier) {
  if (tier === 'original') return true
  const format = String(item?.file_format || '').toLowerCase()
  if (!VARIANT_SOURCE_FORMATS.has(format)) return true
  const fileSize = Number(item?.file_size) || 0
  if (fileSize && fileSize <= SCREEN_SKIP_BYTES) return true
  const longSide = imageLongSide(item)
  if (longSide && longSide <= SCREEN_SKIP_LONG_SIDE) return true
  if (tier === 'full') {
    if (LOSSY_FORMATS.has(format)) return true
    if (fileSize && fileSize <= FULL_SKIP_BYTES) return true
  }
  return false
}

/** The pixels a tier actually holds along the image's long side. */
export function tierLongSide(item, tier) {
  const longSide = imageLongSide(item)
  if (tier === 'thumb') return longSide ? Math.min(longSide, THUMB_LONG_SIDE) : THUMB_LONG_SIDE
  if (tier === 'screen' && !tierServesOriginal(item, 'screen')) return SCREEN_LONG_SIDE
  return longSide || Infinity
}

/**
 * Device pixels needed along the image's long side for a box of `boxWidth` ×
 * `boxHeight` CSS px showing the image at object-fit: contain, then zoomed.
 */
export function neededDevicePx(item, boxWidth, boxHeight, { dpr = 1, zoom = 1 } = {}) {
  const width = Number(item?.width) || 0
  const height = Number(item?.height) || 0
  if (!boxWidth || !boxHeight) return 0
  let renderedLongSide
  if (width && height) {
    const fit = Math.min(boxWidth / width, boxHeight / height)
    renderedLongSide = Math.max(width, height) * fit
  } else {
    renderedLongSide = Math.max(boxWidth, boxHeight)
  }
  return Math.ceil(renderedLongSide * (dpr || 1) * (zoom || 1))
}

/**
 * The smallest tier that covers `needed` device px. `remote` picks `full`
 * over `original` once the need outgrows `screen`.
 */
export function pickImageTier(item, needed, { remote = false } = {}) {
  if (!isTieredImage(item)) return 'original'
  if (tierServesOriginal(item, 'screen')) return 'original'
  if (!needed || needed <= SCREEN_LONG_SIDE) return 'screen'
  if (remote && !tierServesOriginal(item, 'full')) return 'full'
  return 'original'
}

/**
 * The tier a progressive image should start with: the thumbnail, unless the
 * original is about as small as the thumbnail anyway.
 */
export function placeholderTier(item) {
  const longSide = imageLongSide(item)
  if (longSide && longSide <= THUMB_LONG_SIDE * 1.25) return null
  return 'thumb'
}

/** Two tiers resolve to the same bytes. */
export function sameTierBytes(item, a, b) {
  const resolve = (tier) => (tier !== 'thumb' && tierServesOriginal(item, tier) ? 'original' : tier)
  return resolve(a) === resolve(b)
}
