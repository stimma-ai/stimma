/**
 * Rows for a media grid cut into groups (the Assets browser's Group by).
 *
 * The grid pages by flat index over the whole grouped list, so a section is
 * a contiguous run of flat indexes, [offset, offset + count). This module
 * turns sections plus the loaded items into the rows the virtual scroller
 * draws, each with its own height:
 *
 * - `header`: one per section (checkbox, title, span, count).
 * - `refs`: a revisit's "Made from" frames, under the header, open or folded.
 * - `tiles`: an open section's tile rows, breaking at the section's edges.
 * - `strip`: a folded section's single strip of small thumbnails.
 *
 * Pure: no Vue, no DOM, so the page math can be tested in node.
 */

export interface GridSection {
  key: string
  title: string
  count: number
  offset: number
  open: boolean
  refs?: unknown[]
  [extra: string]: unknown
}

export interface RowMetrics {
  /** Tiles across an open section. */
  perRow: number
  /** Height of one tile row (tile plus the row gutter). */
  tileRowHeight: number
  /** Height of a section header row. */
  headerHeight: number
  /** Height of a folded section's strip row. */
  stripHeight: number
  /** Thumbnails a strip has room for (already capped). */
  stripCells: number
  /** Height of the "Made from" row. */
  refsHeight: number
  /** Flat list length; indexes at or past it are never drawn. */
  total: number
}

export type GridRow =
  | { id: string, type: 'header', size: number, sectionKey: string, sectionIndex: number }
  | { id: string, type: 'refs', size: number, sectionKey: string, sectionIndex: number }
  | { id: string, type: 'tiles', size: number, sectionKey: string, sectionIndex: number,
      isPlaceholder: boolean, items: unknown[], startIndex: number, cells: number }
  | { id: string, type: 'strip', size: number, sectionKey: string, sectionIndex: number,
      startIndex: number, cells: number, items: (unknown | null)[] }

/** A strip never shows more than this many thumbnails. */
export const STRIP_MAX_CELLS = 60

/** Thumbnails that fit across `inner` px at `cellPx` with `gap` px between, capped. */
export function stripCapacity(inner: number, cellPx: number, gap: number): number {
  if (!(inner > 0) || !(cellPx > 0)) return 0
  return Math.max(1, Math.min(STRIP_MAX_CELLS, Math.floor((inner + gap) / (cellPx + gap))))
}

function sectionEnd(section: GridSection, total: number): number {
  return Math.min(section.offset + Math.max(0, section.count), total)
}

/**
 * Build the grouped rows. `getItem(index)` returns the loaded item at a flat
 * index, or undefined while its page is still loading.
 */
export function buildSectionRows(
  sections: GridSection[],
  metrics: RowMetrics,
  getItem: (index: number) => unknown,
): GridRow[] {
  const rows: GridRow[] = []
  const perRow = Math.max(1, metrics.perRow)
  sections.forEach((section, sectionIndex) => {
    const start = Math.max(0, section.offset)
    const end = sectionEnd(section, metrics.total)
    const key = section.key
    rows.push({ id: `h:${key}`, type: 'header', size: metrics.headerHeight, sectionKey: key, sectionIndex })
    if (section.refs && section.refs.length > 0) {
      rows.push({ id: `r:${key}`, type: 'refs', size: metrics.refsHeight, sectionKey: key, sectionIndex })
    }
    if (end <= start) return
    if (!section.open) {
      const cells = Math.min(Math.max(1, metrics.stripCells), end - start)
      const items: (unknown | null)[] = []
      for (let i = 0; i < cells; i++) items.push(getItem(start + i) ?? null)
      rows.push({ id: `s:${key}`, type: 'strip', size: metrics.stripHeight, sectionKey: key, sectionIndex, startIndex: start, cells, items })
      return
    }
    for (let rowStart = start, k = 0; rowStart < end; rowStart += perRow, k++) {
      const cells = Math.min(perRow, end - rowStart)
      const items: unknown[] = []
      for (let i = 0; i < cells; i++) {
        const item = getItem(rowStart + i)
        if (item) {
          const record = item as { _gridIndex?: number }
          if (record._gridIndex !== rowStart + i) record._gridIndex = rowStart + i
          items.push(item)
        }
      }
      rows.push({
        id: `t:${key}:${k}`, type: 'tiles', size: metrics.tileRowHeight, sectionKey: key, sectionIndex,
        isPlaceholder: items.length === 0, items, startIndex: rowStart, cells,
      })
    }
  })
  return rows
}

/** Each row's top, plus the content height as the last entry. */
export function rowTops(rows: { size: number }[]): number[] {
  const tops = new Array<number>(rows.length + 1)
  let y = 0
  for (let i = 0; i < rows.length; i++) {
    tops[i] = y
    y += rows[i].size
  }
  tops[rows.length] = y
  return tops
}

/** Index of the row that contains y (clamped to the rows). */
export function rowIndexAt(tops: number[], y: number): number {
  const count = tops.length - 1
  if (count <= 0) return -1
  let lo = 0
  let hi = count - 1
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1
    if (tops[mid] <= y) lo = mid
    else hi = mid - 1
  }
  return lo
}

/** The flat indexes a row needs loaded, as [start, end), or null for none. */
export function rowIndexRange(row: GridRow): [number, number] | null {
  if (row.type === 'tiles' || row.type === 'strip') return [row.startIndex, row.startIndex + row.cells]
  return null
}

/**
 * Pages (0-based, `pageSize` items each) that the rows overlapping
 * [fromY, toY] need. Folded sections only ask for the pages their strips
 * show, so a scroll past a long folded group never loads all of it.
 */
export function pagesForRange(rows: GridRow[], tops: number[], fromY: number, toY: number, pageSize: number): number[] {
  if (rows.length === 0) return []
  const first = rowIndexAt(tops, Math.max(0, fromY))
  const last = rowIndexAt(tops, Math.max(0, toY))
  const pages = new Set<number>()
  for (let i = first; i <= last; i++) {
    const range = rowIndexRange(rows[i])
    if (!range || range[1] <= range[0]) continue
    const firstPage = Math.floor(range[0] / pageSize)
    const lastPage = Math.floor((range[1] - 1) / pageSize)
    for (let page = firstPage; page <= lastPage; page++) pages.add(page)
  }
  return [...pages].sort((a, b) => a - b)
}

/**
 * The section whose header has scrolled under the top edge, for the floating
 * header, and how far the next header pushes it up (0 or negative px).
 * Null while the current section's own header is still in view.
 */
export function stickySectionAt(rows: GridRow[], tops: number[], scrollTop: number, headerHeight: number):
  { sectionIndex: number, sectionKey: string, push: number } | null {
  if (rows.length === 0 || scrollTop <= 0) return null
  const at = rowIndexAt(tops, scrollTop)
  let headerRow = -1
  for (let i = at; i >= 0; i--) {
    if (rows[i].type === 'header') { headerRow = i; break }
  }
  if (headerRow < 0 || tops[headerRow] >= scrollTop) return null
  const row = rows[headerRow] as Extract<GridRow, { type: 'header' }>
  let push = 0
  for (let i = headerRow + 1; i < rows.length; i++) {
    if (rows[i].type !== 'header') continue
    const gap = tops[i] - scrollTop
    if (gap < headerHeight) push = Math.min(0, gap - headerHeight)
    break
  }
  return { sectionIndex: row.sectionIndex, sectionKey: row.sectionKey, push }
}

/** Top of a section's header row, or null when the section isn't drawn. */
export function sectionTop(rows: GridRow[], tops: number[], key: string): number | null {
  const index = rows.findIndex(row => row.type === 'header' && row.sectionKey === key)
  return index < 0 ? null : tops[index]
}

/** The section that holds a flat index (sections are sorted by offset). */
export function sectionIndexOf(sections: GridSection[], flatIndex: number): number {
  let lo = 0
  let hi = sections.length - 1
  let found = -1
  while (lo <= hi) {
    const mid = (lo + hi) >> 1
    if (sections[mid].offset <= flatIndex) { found = mid; lo = mid + 1 } else hi = mid - 1
  }
  if (found < 0) return -1
  const section = sections[found]
  return flatIndex < section.offset + section.count ? found : -1
}

export type SelectState = 'none' | 'some' | 'all'

/**
 * The header checkbox: how much of a section is selected. `knownIds` is the
 * section's full id list when it has been fetched (a group checkbox was
 * used); otherwise only loaded items can be counted, and a section that isn't
 * fully loaded can be at most 'some'.
 */
export function sectionSelectState(
  section: GridSection,
  selected: Set<number>,
  getItemId: (index: number) => number | undefined,
  refIds: number[] = [],
  knownIds?: number[] | null,
): SelectState {
  if (selected.size === 0) return 'none'
  let hit = 0
  let size = 0
  let complete = true
  if (knownIds) {
    size = knownIds.length
    for (const id of knownIds) if (selected.has(id)) hit++
  } else {
    for (let i = section.offset; i < section.offset + section.count; i++) {
      const id = getItemId(i)
      if (id == null) { complete = false; continue }
      size++
      if (selected.has(id)) hit++
    }
  }
  for (const id of refIds) {
    size++
    if (selected.has(id)) hit++
  }
  if (hit === 0) return 'none'
  return hit === size && complete ? 'all' : 'some'
}

/**
 * A shift-click range in a grouped list, by flat index, inclusive. The ids
 * come from the server's grouped id list, so members of a folded group (never
 * loaded) are included. [Sol S8]
 */
export async function resolveFlatRange(fetchIds: () => Promise<number[]>, from: number, to: number): Promise<number[]> {
  const start = Math.max(0, Math.min(from, to))
  const end = Math.max(from, to)
  const ids = await fetchIds()
  return ids.slice(start, end + 1)
}
