/**
 * Where each picture in a contact sheet's media group goes. Pictures are never
 * cropped: each tile gets a rectangle of its own aspect (rows, masonry) or a
 * letterboxed cell (uniform).
 *
 *   rows     justified rows in reading order (the default). Mixed aspects share
 *            a row height; a homogeneous set comes out as an even grid.
 *   masonry  equal columns, each picture at its own height, placed in order
 *            into the shortest column. For portrait-heavy mixes.
 *   uniform  equal cells (aspect "16/9" etc.). For sweeps and comparisons.
 */

export type SheetLayout = 'rows' | 'masonry' | 'uniform'
export type SheetSize = 's' | 'm' | 'l'

export interface LayoutItem {
  id: string
  /** width / height */
  ratio: number
  /** Caption space under the picture: its measured height, or true for one line. */
  caption: boolean | number
}

export interface TileRect {
  x: number
  y: number
  w: number
  h: number
  /** Caption height reserved under the picture. */
  cap: number
  letterbox: boolean
}

export interface Placement {
  rects: Record<string, TileRect>
  height: number
}

export const GAP: Record<SheetSize, number> = { s: 4, m: 6, l: 8 }
/** Target row height for rows. */
export const ROW: Record<SheetSize, number> = { s: 88, m: 190, l: 300 }
/** Target column width for masonry and uniform. */
export const COLUMN: Record<SheetSize, number> = { s: 110, m: 220, l: 320 }
/** One caption line, reserved until the real caption has been measured. */
export const CAPTION = 22

const captionOf = (item: LayoutItem) => (typeof item.caption === 'number' ? item.caption : item.caption ? CAPTION : 0)

export function parseLayout(value: unknown): SheetLayout {
  return value === 'masonry' || value === 'uniform' ? value : 'rows'
}

export function parseSize(value: unknown): SheetSize {
  return value === 's' || value === 'l' ? value : 'm'
}

/** "16/9", "16:9", "1.5" or "4 / 3" to a width/height ratio. */
export function parseAspect(value: unknown): number {
  const text = String(value ?? '').trim()
  const parts = text.split(/\s*[/:]\s*/).map(Number)
  const ratio = parts.length === 2 ? parts[0] / parts[1] : parts[0]
  return Number.isFinite(ratio) && ratio > 0.1 && ratio < 10 ? ratio : 1
}

export function placeTiles(
  items: LayoutItem[],
  width: number,
  layout: SheetLayout = 'rows',
  size: SheetSize = 'm',
  aspect = 1,
): Placement {
  const W = Math.floor(width)
  const rects: Record<string, TileRect> = {}
  if (!W || !items.length) return { rects, height: 0 }
  const gap = GAP[size]

  if (layout === 'rows') {
    const target = Math.min(ROW[size], W * 0.75)
    let row: LayoutItem[] = []
    let ratioSum = 0
    let y = 0
    const flush = (last: boolean) => {
      if (!row.length) return
      const available = W - gap * (row.length - 1)
      let h = available / ratioSum
      // A short last row keeps the target height rather than blowing up.
      if (last && h > target * 1.25) h = target
      const cap = Math.max(0, ...row.map(captionOf))
      let x = 0
      for (const item of row) {
        const w = h * item.ratio
        rects[item.id] = { x, y, w, h, cap, letterbox: false }
        x += w + gap
      }
      y += h + cap + gap
      row = []
      ratioSum = 0
    }
    for (const item of items) {
      row.push(item)
      ratioSum += item.ratio
      if ((W - gap * (row.length - 1)) / ratioSum <= target) flush(false)
    }
    flush(true)
    return { rects, height: Math.max(0, y - gap) }
  }

  const columns = Math.max(1, Math.floor((W + gap) / (COLUMN[size] + gap)))
  const cw = (W - gap * (columns - 1)) / columns
  if (layout === 'masonry') {
    const tops = new Array(columns).fill(0)
    for (const item of items) {
      const column = tops.indexOf(Math.min(...tops))
      const h = cw / item.ratio
      const cap = captionOf(item)
      rects[item.id] = { x: column * (cw + gap), y: tops[column], w: cw, h, cap, letterbox: false }
      tops[column] += h + cap + gap
    }
    return { rects, height: Math.max(0, Math.max(...tops) - gap) }
  }

  // Each grid row reserves the tallest caption in it.
  const ch = cw / aspect
  let y = 0
  for (let start = 0; start < items.length; start += columns) {
    const row = items.slice(start, start + columns)
    const cap = Math.max(0, ...row.map(captionOf))
    row.forEach((item, index) => {
      rects[item.id] = { x: index * (cw + gap), y, w: cw, h: ch, cap, letterbox: true }
    })
    y += ch + cap + gap
  }
  return { rects, height: Math.max(0, y - gap) }
}
