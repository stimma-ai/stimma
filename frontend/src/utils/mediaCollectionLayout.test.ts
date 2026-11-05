import assert from 'node:assert/strict'
import test from 'node:test'
import { gridColumns, heroHeight, startingView, stripTileSize, visibleTiles } from './mediaCollectionLayout.ts'

test('a set that fits opens as a grid; a larger one opens in preview', () => {
  assert.equal(startingView(12, false), 'grid')
  assert.equal(startingView(13, false), 'preview')
  assert.equal(startingView(9, true), 'grid')
  assert.equal(startingView(10, true), 'preview')
})

test('small sets avoid a hole in the last row', () => {
  assert.equal(gridColumns({ count: 8, width: 880, size: 'm', compact: false }), 4)
  assert.equal(gridColumns({ count: 9, width: 880, size: 'm', compact: false }), 3)
  assert.equal(gridColumns({ count: 3, width: 880, size: 'm', compact: false }), 3)
})

test('phones use three columns and honour the size choice', () => {
  assert.equal(gridColumns({ count: 20, width: 390, size: 'm', compact: true }), 3)
  assert.equal(gridColumns({ count: 20, width: 390, size: 's', compact: true }), 4)
  assert.equal(gridColumns({ count: 4, width: 390, size: 'm', compact: true }), 2)
})

test('a collapsed grid stops at three rows', () => {
  assert.equal(visibleTiles({ count: 60, columns: 5, expanded: false }), 15)
  assert.equal(visibleTiles({ count: 60, columns: 5, expanded: true }), 60)
  assert.equal(visibleTiles({ count: 8, columns: 4, expanded: false }), 8)
})

test('picture, strip and header fit in the chat together', () => {
  const stripSize = stripTileSize('l', false)
  const height = heroHeight({ chatHeight: 620, width: 880, size: 'l', stripSize })
  assert.ok(height + stripSize + 44 <= 620)
  assert.equal(heroHeight({ chatHeight: 2000, width: 880, size: 'l', stripSize }), 640)
  assert.equal(heroHeight({ chatHeight: 120, width: 880, size: 'l', stripSize }), 200)
  assert.ok(heroHeight({ chatHeight: 800, width: 366, size: 'l', stripSize }) <= 403)
})
