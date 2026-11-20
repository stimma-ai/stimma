import assert from 'node:assert/strict'
import test from 'node:test'
import { gridColumns, heroHeight, placeGrid, startingView, stripTileSize, visibleTiles } from './mediaCollectionLayout.ts'

test('a set that fits opens as a grid; a larger one opens in preview', () => {
  assert.equal(startingView(12, false), 'grid')
  assert.equal(startingView(13, false), 'preview')
  assert.equal(startingView(9, true), 'grid')
  assert.equal(startingView(10, true), 'preview')
})

test('columns follow the width, not a size control', () => {
  assert.equal(gridColumns({ count: 20, width: 390 }), 2)
  assert.equal(gridColumns({ count: 20, width: 600 }), 3)
  assert.equal(gridColumns({ count: 20, width: 880 }), 4)
  assert.equal(gridColumns({ count: 24, width: 1400 }), 6)
})

test('a small set fills one row instead of stacking pairs', () => {
  assert.equal(gridColumns({ count: 4, width: 880 }), 4)
  assert.equal(gridColumns({ count: 3, width: 880 }), 3)
  // Three columns at 600px even for four pictures: shorter than a 2×2 of portraits.
  assert.equal(gridColumns({ count: 4, width: 600 }), 3)
})

test('a column is given up to even out the last row only while three remain', () => {
  assert.equal(gridColumns({ count: 9, width: 880 }), 3)
  assert.equal(gridColumns({ count: 8, width: 880 }), 4)
  assert.equal(gridColumns({ count: 6, width: 600 }), 3)
})

test('one aspect makes an even grid with no letterbox', () => {
  const ratio = 832 / 1216
  const { rects, rowOf } = placeGrid({ ratios: new Array(9).fill(ratio), width: 880, columns: 3 })
  assert.deepEqual(rowOf, [0, 0, 0, 1, 1, 1, 2, 2, 2])
  for (const r of rects) {
    assert.ok(Math.abs(r.w / r.h - ratio) < 0.001)
    assert.ok(Math.abs(r.w - (880 - 4) / 3) < 0.01)
  }
})

test('mixed aspects pack into full-width rows, each picture at its own shape', () => {
  const ratios = [1.46, 0.68, 1, 0.57, 1.75, 1, 0.57, 1.46, 1.75, 0.68, 1.75]
  const { rects, rowOf } = placeGrid({ ratios, width: 880, columns: 4 })
  ratios.forEach((ratio, i) => assert.ok(Math.abs(rects[i].w / rects[i].h - ratio) < 0.001))
  const rows = Math.max(...rowOf) + 1
  for (let row = 0; row < rows - 1; row += 1) {
    const inRow = rects.filter((_, i) => rowOf[i] === row)
    const right = Math.max(...inRow.map(r => r.x + r.w))
    assert.ok(Math.abs(right - 880) < 0.5, `row ${row} fills the width`)
  }
})

test('a short last row keeps the height of the row above', () => {
  const { rects, rowOf } = placeGrid({ ratios: [1, 1, 1, 1, 1], width: 600, columns: 3 })
  assert.equal(rowOf[4], 1)
  assert.equal(rects[4].h, rects[0].h)
  assert.ok(rects[4].x + rects[4].w < 600)
})

test('labels add a line under every row', () => {
  const bare = placeGrid({ ratios: [1, 1, 1], width: 600, columns: 3 })
  const labeled = placeGrid({ ratios: [1, 1, 1], width: 600, columns: 3, caption: 20 })
  assert.equal(labeled.rects[0].h, bare.rects[0].h + 20)
  assert.equal(labeled.height, bare.height + 20)
})

test('a collapsed grid stops at three rows', () => {
  const placement = placeGrid({ ratios: new Array(60).fill(1), width: 880, columns: 4 })
  assert.equal(visibleTiles({ placement, count: 60, expanded: false }), 12)
  assert.equal(visibleTiles({ placement, count: 60, expanded: true }), 60)
  const small = placeGrid({ ratios: new Array(8).fill(1), width: 880, columns: 4 })
  assert.equal(visibleTiles({ placement: small, count: 8, expanded: false }), 8)
})

test('the strip follows the width and fills a short set', () => {
  assert.equal(stripTileSize({ width: 390, count: 40 }), 56)
  assert.equal(stripTileSize({ width: 880, count: 40 }), 84)
  assert.equal(stripTileSize({ width: 880, count: 3 }), 96)
})

test('picture, strip and header fit in the chat together', () => {
  const stripSize = stripTileSize({ width: 880, count: 40 })
  const height = heroHeight({ chatHeight: 620, width: 880, stripSize })
  assert.ok(height + stripSize + 44 <= 620)
  assert.equal(heroHeight({ chatHeight: 2000, width: 880, stripSize }), 640)
  assert.equal(heroHeight({ chatHeight: 120, width: 880, stripSize }), Math.round(200 * 0.84))
  assert.ok(heroHeight({ chatHeight: 800, width: 366, stripSize }) <= 403)
})
