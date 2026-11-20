// Sizing rules for an agent's media collection in chat. Pure so the rules can
// be read and tested without a browser. There is no size control: the
// collection's width decides.
export type CollectionView = 'grid' | 'preview'

export interface GridRect { x: number; y: number; w: number; h: number }
export interface GridPlacement { rects: GridRect[]; rowOf: number[]; height: number }

const GAP = 2
const TILE_TARGET = 190
const MAX_COLUMNS = 6
const COLLAPSED_ROWS = 3
const HEADER_HEIGHT = 44
const HERO_MIN = 200
const HERO_MAX = 640
const HERO_SCALE = 0.84
const CHAT_MARGIN = 24

// Grid when the whole set fits on screen without paging; past that, Preview,
// whose height stays bounded however many images the agent shows.
export function startingView(count: number, compact: boolean): CollectionView {
  return count <= (compact ? 9 : 12) ? 'grid' : 'preview'
}

// Columns come from the width, so a wide chat gets three or more instead of
// tall pairs of portraits. A small set never stretches past its count, and a
// column is given up to even out the last row only while three remain.
export function gridColumns({ count, width }: { count: number; width: number }): number {
  const fit = Math.max(2, Math.min(MAX_COLUMNS, Math.floor((width + GAP) / (TILE_TARGET + GAP))))
  const most = Math.min(count, fit)
  if (count <= fit) return Math.max(1, most)
  const hole = (columns: number) => (columns - (count % columns)) % columns
  return [most, most - 1].filter(c => c >= 3 || c === most).sort((a, b) => hole(a) - hole(b))[0]
}

// Grid tiles at each picture's own aspect (width / height), in reading order:
// the contact sheet's justified rows. A set of one aspect comes out as an even
// grid of `columns`; a mixed set packs into rows of about the same height.
// Nothing is letterboxed, so every chip sits on its own picture. `caption`
// reserves a label line under each row.
export function placeGrid({ ratios, width, columns, caption = 0 }: { ratios: number[]; width: number; columns: number; caption?: number }): GridPlacement {
  const W = Math.floor(width)
  const rects: GridRect[] = []
  const rowOf: number[] = []
  if (!W || !ratios.length) return { rects, rowOf, height: 0 }
  const sorted = [...ratios].sort((a, b) => a - b)
  const typical = sorted[Math.floor(sorted.length / 2)]
  const cell = (W - GAP * (columns - 1)) / columns
  // Half a pixel of slack so a row of one aspect closes at exactly `columns`.
  const target = cell / typical + 0.5
  let row: number[] = []
  let sum = 0
  let y = 0
  let previous = 0
  let rowIndex = 0
  const flush = (last: boolean) => {
    if (!row.length) return
    let h = (W - GAP * (row.length - 1)) / sum
    // A short last row keeps the height of the rows above instead of blowing up.
    if (last && h > target) h = previous || target - 0.5
    let x = 0
    for (const i of row) {
      const w = h * ratios[i]
      rects[i] = { x, y, w, h: h + caption }
      rowOf[i] = rowIndex
      x += w + GAP
    }
    previous = h
    y += h + caption + GAP
    rowIndex += 1
    row = []
    sum = 0
  }
  ratios.forEach((ratio, i) => {
    row.push(i)
    sum += ratio
    if ((W - GAP * (row.length - 1)) / sum <= target) flush(i === ratios.length - 1)
  })
  flush(true)
  return { rects, rowOf, height: Math.max(0, y - GAP) }
}

// Collapsed, the grid shows its first three rows.
export function visibleTiles({ placement, count, expanded }: { placement: GridPlacement; count: number; expanded: boolean }): number {
  if (expanded) return count
  return placement.rowOf.filter(r => r < COLLAPSED_ROWS).length || count
}

// The strip scales with the width; a short set grows its tiles to fill the row.
export function stripTileSize({ width, count }: { width: number; count: number }): number {
  const base = Math.max(56, Math.min(84, Math.round(width / 10)))
  const fill = Math.floor((width - GAP * (count - 1)) / count)
  return Math.max(base, Math.min(96, fill))
}

// The picture, its strip and the header fit the chat together, so moving
// through a set never asks for a vertical scroll.
export function heroHeight({ chatHeight, width, stripSize }: { chatHeight: number; width: number; stripSize: number }): number {
  const fit = Math.max(HERO_MIN, chatHeight - HEADER_HEIGHT - stripSize - CHAT_MARGIN)
  return Math.min(HERO_MAX, Math.round(width * 1.1) || HERO_MAX, Math.round(fit * HERO_SCALE))
}
