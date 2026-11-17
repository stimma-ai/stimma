import assert from 'node:assert/strict'
import test from 'node:test'
import {
  SCREEN_LONG_SIDE,
  neededDevicePx,
  pickImageTier,
  placeholderTier,
  sameTierBytes,
  tierLongSide,
  tierServesOriginal,
} from './imageTiers.js'

const bigPng = { file_format: 'png', width: 3392, height: 4608, file_size: 19_700_000 }
const bigJpeg = { file_format: 'jpg', width: 6000, height: 4000, file_size: 4_000_000 }
const smallPng = { file_format: 'png', width: 2400, height: 3200, file_size: 9_000_000 }
const tinyBigPng = { file_format: 'png', width: 6000, height: 4000, file_size: 300_000 }
const gif = { file_format: 'gif', width: 5000, height: 5000, file_size: 30_000_000 }

test('screen skips to the original when the original is barely larger or already small', () => {
  assert.equal(tierServesOriginal(bigPng, 'screen'), false)
  assert.equal(tierServesOriginal(smallPng, 'screen'), true) // 3200 = 1.25 × 2560
  assert.equal(tierServesOriginal({ ...smallPng, height: 3201 }, 'screen'), false)
  assert.equal(tierServesOriginal(tinyBigPng, 'screen'), true)
  assert.equal(tierServesOriginal(gif, 'screen'), true) // animation survives
  assert.equal(tierServesOriginal({ file_format: 'mp4', width: 8000, height: 8000 }, 'screen'), true)
})

test('full skips to the original for lossy or small files', () => {
  assert.equal(tierServesOriginal(bigPng, 'full'), false)
  assert.equal(tierServesOriginal(bigJpeg, 'full'), true)
  assert.equal(tierServesOriginal({ ...bigPng, file_size: 2_500_000 }, 'full'), true)
  assert.equal(tierServesOriginal(bigJpeg, 'screen'), false)
})

test('needed device pixels follow the fitted box, DPR and zoom', () => {
  // Portrait 3392×4608 in a 1600×900 box: height-bound, 900 CSS px tall.
  assert.equal(neededDevicePx(bigPng, 1600, 900), 900)
  assert.equal(neededDevicePx(bigPng, 1600, 900, { dpr: 2 }), 1800)
  assert.equal(neededDevicePx(bigPng, 1600, 900, { dpr: 2, zoom: 2 }), 3600)
  assert.equal(neededDevicePx(bigPng, 0, 900), 0)
})

test('tier picking: screen at fit, original locally and full remotely on zoom', () => {
  assert.equal(pickImageTier(bigPng, 1800), 'screen')
  assert.equal(pickImageTier(bigPng, SCREEN_LONG_SIDE), 'screen')
  assert.equal(pickImageTier(bigPng, 3600), 'original')
  assert.equal(pickImageTier(bigPng, 3600, { remote: true }), 'full')
  // A lossy original has no `full`: remote zoom goes straight to it.
  assert.equal(pickImageTier(bigJpeg, 5000, { remote: true }), 'original')
  // Small originals are always just the original.
  assert.equal(pickImageTier(smallPng, 900), 'original')
  assert.equal(pickImageTier(gif, 900), 'original')
})

test('tier pixel coverage and shared bytes', () => {
  assert.equal(tierLongSide(bigPng, 'thumb'), 1024)
  assert.equal(tierLongSide(bigPng, 'screen'), 2560)
  assert.equal(tierLongSide(smallPng, 'screen'), 3200)
  assert.equal(tierLongSide(bigPng, 'original'), 4608)
  assert.ok(sameTierBytes(smallPng, 'screen', 'original'))
  assert.ok(!sameTierBytes(bigPng, 'screen', 'original'))
  assert.ok(sameTierBytes(bigJpeg, 'full', 'original'))
  assert.ok(!sameTierBytes(bigPng, 'thumb', 'screen'))
})

test('thumb placeholder only when it is meaningfully smaller than the original', () => {
  assert.equal(placeholderTier(bigPng), 'thumb')
  assert.equal(placeholderTier({ file_format: 'png', width: 1024, height: 1024 }), null)
  assert.equal(placeholderTier({ file_format: 'png' }), 'thumb')
})
