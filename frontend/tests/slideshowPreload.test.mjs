import assert from 'node:assert/strict'
import test from 'node:test'

import {
  nearbyPreloadIndices,
  shouldPreloadVideoBytes,
  SMALL_VIDEO_PRELOAD_MAX_BYTES,
} from '../src/utils/slideshowPreload.js'

test('slideshow preload favors the current navigation direction', () => {
  assert.deepEqual(nearbyPreloadIndices(4, 10, 1, 3), [5, 3, 6])
  assert.deepEqual(nearbyPreloadIndices(4, 10, -1, 3), [3, 5, 2])
})

test('slideshow preload stays in bounds and fills its budget at an edge', () => {
  assert.deepEqual(nearbyPreloadIndices(0, 5, 1, 3), [1, 2, 3])
  assert.deepEqual(nearbyPreloadIndices(4, 5, 1, 3), [3, 2, 1])
})

test('slideshow preload handles empty and invalid collections', () => {
  assert.deepEqual(nearbyPreloadIndices(0, 1), [])
  assert.deepEqual(nearbyPreloadIndices(Number.NaN, 5), [])
})

test('small video preload is capped below five MiB', () => {
  assert.equal(shouldPreloadVideoBytes(4 * 1024 * 1024), true)
  assert.equal(shouldPreloadVideoBytes(SMALL_VIDEO_PRELOAD_MAX_BYTES - 1), true)
  assert.equal(shouldPreloadVideoBytes(SMALL_VIDEO_PRELOAD_MAX_BYTES), false)
  assert.equal(shouldPreloadVideoBytes(undefined), false)
})
