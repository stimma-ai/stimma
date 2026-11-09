import assert from 'node:assert/strict'
import test from 'node:test'

import { CAPTION, parseAspect, placeTiles } from './sheetLayout.ts'

const items = (ratios: number[], caption = false) => ratios.map((ratio, i) => ({ id: `t${i}`, ratio, caption }))

test('rows keep every picture at its own aspect and fill the width', () => {
  const { rects } = placeTiles(items([1.5, 0.75, 1, 1.78, 1.5, 0.66]), 900, 'rows', 'm')
  for (const [id, r] of Object.entries(rects)) {
    const ratio = [1.5, 0.75, 1, 1.78, 1.5, 0.66][Number(id.slice(1))]
    assert.ok(Math.abs(r.w / r.h - ratio) < 1e-6, `${id} keeps its aspect`)
    assert.equal(r.letterbox, false)
  }
  // A full row reaches the right edge.
  const first = Object.values(rects).filter(r => r.y === 0)
  const right = Math.max(...first.map(r => r.x + r.w))
  assert.ok(Math.abs(right - 900) < 1)
})

test('a homogeneous set comes out as an even grid', () => {
  const { rects } = placeTiles(items(new Array(8).fill(16 / 9)), 1000, 'rows', 'm')
  const heights = new Set(Object.values(rects).map(r => Math.round(r.h)))
  assert.equal(heights.size <= 2, true) // full rows equal; only a short last row may differ
})

test('a short last row keeps the target height instead of blowing up', () => {
  const { rects } = placeTiles(items([1.5, 1.5, 1.5, 1.5, 1.5]), 1000, 'rows', 'm')
  const last = rects.t4
  assert.ok(last.h <= 190 + 1)
})

test('captions reserve a line under their row', () => {
  const { rects, height } = placeTiles(items([1, 1], true), 400, 'rows', 'm')
  assert.equal(rects.t0.cap, CAPTION)
  assert.ok(height >= rects.t0.h + CAPTION)
})

test('a wrapped caption reserves its measured height for the whole row', () => {
  const list = [{ id: 'a', ratio: 1, caption: 40 }, { id: 'b', ratio: 1, caption: true }, { id: 'c', ratio: 1, caption: 0 }]
  const { rects, height } = placeTiles(list, 600, 'rows', 'm')
  assert.equal(rects.a.cap, 40)
  assert.equal(rects.b.cap, 40)
  assert.ok(height >= rects.a.h + 40)
  const grid = placeTiles(list, 700, 'uniform', 'm', 1)
  assert.equal(grid.rects.c.cap, 40)
})

test('masonry puts each picture into the shortest column', () => {
  const { rects } = placeTiles(items([0.5, 2, 2, 2]), 460, 'masonry', 'm')
  // Two columns: the tall picture fills the left, the wide ones stack right.
  assert.equal(rects.t0.x, 0)
  assert.ok(rects.t1.x > 0 && rects.t2.x === rects.t1.x)
})

test('uniform letterboxes into equal cells', () => {
  const { rects } = placeTiles(items([0.5, 2, 1]), 700, 'uniform', 'm', parseAspect('16/9'))
  const sizes = new Set(Object.values(rects).map(r => `${Math.round(r.w)}x${Math.round(r.h)}`))
  assert.equal(sizes.size, 1)
  assert.ok(Object.values(rects).every(r => r.letterbox))
})

test('aspect parsing accepts the forms an agent writes', () => {
  assert.equal(parseAspect('16/9'), 16 / 9)
  assert.equal(parseAspect('4 : 3'), 4 / 3)
  assert.equal(parseAspect('1.5'), 1.5)
  assert.equal(parseAspect('nonsense'), 1)
})
