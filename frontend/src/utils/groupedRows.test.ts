import assert from 'node:assert/strict'
import test from 'node:test'

import {
  STRIP_MAX_CELLS,
  buildSectionRows,
  pagesForRange,
  resolveFlatRange,
  rowIndexAt,
  rowTops,
  sectionIndexOf,
  sectionSelectState,
  sectionTop,
  stickySectionAt,
  stripCapacity,
  type GridSection,
  type RowMetrics,
} from './groupedRows.ts'

const metrics = (over: Partial<RowMetrics> = {}): RowMetrics => ({
  perRow: 4, tileRowHeight: 100, headerHeight: 48, stripHeight: 40, stripCells: 3, refsHeight: 56, total: 1000, ...over,
})
const loaded = (n: number) => {
  const items = new Map<number, { id: number, asset_id: number, _gridIndex?: number }>()
  for (let i = 0; i < n; i++) items.set(i, { id: 100 + i, asset_id: 100 + i })
  return (i: number) => items.get(i)
}
const section = (key: string, offset: number, count: number, open = true, extra: Partial<GridSection> = {}): GridSection =>
  ({ key, title: key, offset, count, open, ...extra })

test('open sections break their tile rows at their own edges', () => {
  const rows = buildSectionRows([section('a', 0, 6), section('b', 6, 3)], metrics({ total: 9 }), loaded(9))
  assert.deepEqual(rows.map(r => r.id), ['h:a', 't:a:0', 't:a:1', 'h:b', 't:b:0'])
  const tiles = rows.filter(r => r.type === 'tiles')
  assert.deepEqual(tiles.map(r => [r.startIndex, r.cells]), [[0, 4], [4, 2], [6, 3]])
  // A row never borrows from the next section.
  assert.deepEqual(tiles[1].items.map((item: any) => item._gridIndex), [4, 5])
  assert.deepEqual(tiles[2].items.map((item: any) => item._gridIndex), [6, 7, 8])
})

test('every row carries its own height', () => {
  const rows = buildSectionRows(
    [section('a', 0, 5, true, { refs: [{ id: 1 }] }), section('b', 5, 10, false)],
    metrics({ total: 15 }),
    loaded(15),
  )
  assert.deepEqual(rows.map(r => [r.type, r.size]), [
    ['header', 48], ['refs', 56], ['tiles', 100], ['tiles', 100], ['header', 48], ['strip', 40],
  ])
  const tops = rowTops(rows)
  assert.deepEqual(tops, [0, 48, 104, 204, 304, 352, 392])
})

test('a folded section is one strip of its first indexes, capped by width and size', () => {
  const rows = buildSectionRows([section('a', 0, 2, false), section('b', 2, 50, false)], metrics({ total: 52, stripCells: 5 }), loaded(4))
  const strips = rows.filter(r => r.type === 'strip')
  assert.equal(strips.length, 2)
  assert.deepEqual([strips[0].startIndex, strips[0].cells], [0, 2])
  assert.deepEqual([strips[1].startIndex, strips[1].cells], [2, 5])
  // Unloaded strip cells stay as gaps, not as shifted neighbours.
  assert.deepEqual(strips[1].items.map((item: any) => item?.id ?? null), [102, 103, null, null, null])
})

test('strip capacity fits the width and never passes the cap', () => {
  assert.equal(stripCapacity(200, 40, 2), 4)
  assert.equal(stripCapacity(100000, 40, 2), STRIP_MAX_CELLS)
  assert.equal(stripCapacity(0, 40, 2), 0)
  assert.equal(stripCapacity(10, 40, 2), 1)
})

test('a revisit shows its "Made from" row folded or open', () => {
  const refs = [{ id: 9 }]
  const open = buildSectionRows([section('a', 0, 2, true, { refs })], metrics({ total: 2 }), loaded(2))
  const folded = buildSectionRows([section('a', 0, 2, false, { refs })], metrics({ total: 2 }), loaded(2))
  assert.deepEqual(open.map(r => r.type), ['header', 'refs', 'tiles'])
  assert.deepEqual(folded.map(r => r.type), ['header', 'refs', 'strip'])
})

test('unloaded tile rows are placeholders that know their cell count', () => {
  const rows = buildSectionRows([section('a', 0, 3)], metrics({ total: 3 }), () => undefined)
  const [, tiles] = rows
  assert.equal(tiles.type, 'tiles')
  assert.equal((tiles as any).isPlaceholder, true)
  assert.equal((tiles as any).cells, 3)
})

test('sections past the flat total are clamped, empty ones keep their header', () => {
  const rows = buildSectionRows([section('a', 0, 4), section('b', 4, 4)], metrics({ total: 6 }), loaded(6))
  assert.deepEqual(rows.map(r => r.id), ['h:a', 't:a:0', 'h:b', 't:b:0'])
  assert.equal((rows[3] as any).cells, 2)
})

test('visible pages follow variable row heights and skip folded groups', () => {
  // A folded group of 5000 between two open ones: scrolling past its strip
  // must only load the strip's page, not everything in the group.
  const sections = [section('a', 0, 8), section('b', 8, 5000, false), section('c', 5008, 8)]
  const rows = buildSectionRows(sections, metrics({ total: 5016, stripCells: 3 }), () => undefined)
  const tops = rowTops(rows)
  const pageSize = 200
  assert.deepEqual(pagesForRange(rows, tops, 0, 10, pageSize), [], "a header alone needs nothing")
  assert.deepEqual(pagesForRange(rows, tops, 0, 60, pageSize), [0])
  const cTop = sectionTop(rows, tops, 'c')!
  assert.deepEqual(pagesForRange(rows, tops, cTop, cTop + 150, pageSize), [25])
  assert.deepEqual(pagesForRange(rows, tops, 0, tops.at(-1)!, pageSize), [0, 25])
})

test('rowIndexAt finds the row under a y position', () => {
  const tops = [0, 48, 148, 248]
  assert.equal(rowIndexAt(tops, 0), 0)
  assert.equal(rowIndexAt(tops, 47), 0)
  assert.equal(rowIndexAt(tops, 48), 1)
  assert.equal(rowIndexAt(tops, 247), 2)
  assert.equal(rowIndexAt(tops, 9999), 2)
})

test('the floating header is the section scrolled under the top, pushed by the next', () => {
  const rows = buildSectionRows([section('a', 0, 8), section('b', 8, 4)], metrics({ total: 12 }), loaded(12))
  const tops = rowTops(rows)
  assert.equal(stickySectionAt(rows, tops, 0, 48), null)
  assert.deepEqual(stickySectionAt(rows, tops, 60, 48), { sectionIndex: 0, sectionKey: 'a', push: 0 })
  const bTop = sectionTop(rows, tops, 'b')!
  // 20px before b's header reaches the top, a's floating header is pushed up 28px.
  assert.deepEqual(stickySectionAt(rows, tops, bTop - 20, 48), { sectionIndex: 0, sectionKey: 'a', push: -28 })
  // Exactly at b's header, b's own row is in view: no floating header.
  assert.equal(stickySectionAt(rows, tops, bTop, 48), null)
  assert.equal(stickySectionAt(rows, tops, bTop + 1, 48)!.sectionKey, 'b')
})

test('sectionIndexOf maps a flat index to its section', () => {
  const sections = [section('a', 0, 3), section('b', 3, 2), section('c', 5, 4)]
  assert.equal(sectionIndexOf(sections, 0), 0)
  assert.equal(sectionIndexOf(sections, 4), 1)
  assert.equal(sectionIndexOf(sections, 8), 2)
  assert.equal(sectionIndexOf(sections, 9), -1)
})

test('the header checkbox reads all, some or none, including refs', () => {
  const s = section('a', 0, 3)
  const ids = (i: number) => (i < 3 ? 100 + i : undefined)
  assert.equal(sectionSelectState(s, new Set(), ids), 'none')
  assert.equal(sectionSelectState(s, new Set([100]), ids), 'some')
  assert.equal(sectionSelectState(s, new Set([100, 101, 102]), ids), 'all')
  assert.equal(sectionSelectState(s, new Set([100, 101, 102]), ids, [7]), 'some')
  assert.equal(sectionSelectState(s, new Set([100, 101, 102, 7]), ids, [7]), 'all')
  // Not fully loaded: every loaded member selected is still only 'some'.
  const partial = (i: number) => (i === 0 ? 100 : undefined)
  assert.equal(sectionSelectState(s, new Set([100]), partial), 'some')
  // Known ids (from the group checkbox) settle it.
  assert.equal(sectionSelectState(s, new Set([100, 101, 102]), partial, [], [100, 101, 102]), 'all')
})

test('a shift range crossing a folded group takes its unloaded members from the id list', async () => {
  // Groups: a [0,3) open, b [3,8) folded (never loaded), c [8,10) open.
  const groupedIds = [1, 2, 3, 40, 41, 42, 43, 44, 5, 6]
  const range = await resolveFlatRange(async () => groupedIds, 9, 1)
  assert.deepEqual(range, [2, 3, 40, 41, 42, 43, 44, 5, 6])
})
