import assert from 'node:assert/strict'
import test from 'node:test'
import { createSlideshowSwipe } from '../src/utils/slideshowSwipe.js'
import { createSlideshowDwell } from '../src/utils/slideshowDwell.js'
import { checkMobileDownloadSize, MOBILE_SHARE_LIMIT, saveDownloadBlob } from '../src/utils/mobileDownload.ts'
import { recoveredImageUrl } from '../src/utils/imageRecovery.js'
import { shareFile } from '../src/utils/nativeShare.ts'

test('native share cancellation leaves the dialog open like Web Share cancellation', async () => {
  const file = new File(['image'], 'image.png', { type: 'image/png' })
  await assert.rejects(shareFile(file, { kind: 'ios', saveToDownloads: async () => false }, {}), { name: 'AbortError' })
  assert.equal(await shareFile(file, { kind: 'ios', saveToDownloads: async () => true }, {}), true)
})

function swipeFixture() {
  const calls = []
  let zoom = 1, time = 0
  const swipe = createSlideshowSwipe({ canNavigate: () => zoom === 1, navigate: value => calls.push(value), now: () => time })
  const touch = (x, y = 0, id = 1) => ({ clientX: x, clientY: y, identifier: id })
  const event = (touches, changedTouches = [], control = false) => ({ touches, changedTouches, target: { closest: () => control } })
  return { calls, swipe, touch, event, zoom: value => { zoom = value }, tick: value => { time += value } }
}

test('picture swipe navigates once and suppresses the synthetic tap', () => {
  const f = swipeFixture()
  f.swipe.start(f.event([f.touch(200)])); f.tick(200)
  f.swipe.end(f.event([], [f.touch(20)]))
  f.swipe.end(f.event([], [f.touch(20)]))
  assert.deepEqual(f.calls, ['next'])
  assert.equal(f.swipe.suppressClick(), true)
  f.tick(500)
  assert.equal(f.swipe.suppressClick(), false)
})

test('controls, zoomed pan, pinch, cancellation and other fingers never navigate', () => {
  for (const kind of ['control', 'zoom', 'pinch', 'cancel', 'other-finger']) {
    const f = swipeFixture()
    if (kind === 'zoom') f.zoom(2)
    f.swipe.start(f.event([f.touch(200)], [], kind === 'control'))
    if (kind === 'pinch') {
      f.swipe.move(f.event([f.touch(200), f.touch(250, 20, 2)]))
      f.swipe.move(f.event([f.touch(180)]))
    }
    if (kind === 'cancel') f.swipe.cancel()
    f.swipe.end(f.event([], [f.touch(20, 0, kind === 'other-finger' ? 2 : 1)]))
    assert.deepEqual(f.calls, [], kind)
  }
})

test('a slow drag does not navigate; vertical swipe opens info', () => {
  const f = swipeFixture()
  f.swipe.start(f.event([f.touch(200)])); f.tick(900)
  f.swipe.end(f.event([], [f.touch(0)]))
  assert.deepEqual(f.calls, [])
  f.swipe.start(f.event([f.touch(100, 400)])); f.tick(100)
  f.swipe.end(f.event([], [f.touch(105, 200)]))
  assert.deepEqual(f.calls, ['info'])
})

test('an active gallery drag can be held before releasing', () => {
  const f = swipeFixture()
  f.swipe.start(f.event([f.touch(200)]))
  f.swipe.move(f.event([f.touch(100)]))
  f.tick(1500)
  f.swipe.end(f.event([], [f.touch(20)]))
  assert.deepEqual(f.calls, ['next'])
})

test('suspension freezes remaining dwell across duplicate notifications and long sleep', () => {
  let now = 0
  const dwell = createSlideshowDwell(() => now)
  now = 3000; dwell.pause()
  now = 5000; dwell.pause()
  now = 300000
  assert.equal(dwell.elapsed(), 3000)
  dwell.resume(); dwell.resume()
  now += 2000
  assert.equal(dwell.elapsed(), 5000)
  dwell.pause(); dwell.shown(); now += 9000; dwell.resume()
  assert.equal(dwell.elapsed(), 0, 'new media shown while hidden gets a full dwell')
})

test('oversized phone export fails before reading or bridging bytes', async () => {
  let allocated = false, bridged = false
  const blob = { size: MOBILE_SHARE_LIMIT + 1, arrayBuffer: () => { allocated = true } }
  await assert.rejects(saveDownloadBlob(blob, 'video.mp4', { kind: 'ios', saveToDownloads: () => { bridged = true } }), /64 MB/)
  assert.equal(allocated, false); assert.equal(bridged, false)
  assert.doesNotThrow(() => checkMobileDownloadSize(MOBILE_SHARE_LIMIT, 'ios'))
  assert.doesNotThrow(() => checkMobileDownloadSize(MOBILE_SHARE_LIMIT + 1, 'electron'))
})

test('failed/cancelled exports reject; only successful saves resolve true', async () => {
  const blob = new Blob(['hello'])
  await assert.rejects(saveDownloadBlob(blob, 'test.txt', { kind: 'ios', saveToDownloads: async () => false }), /not saved/)
  await assert.rejects(saveDownloadBlob(blob, 'test.txt', { kind: 'ios', saveToDownloads: async () => { throw new Error('share unavailable') } }), /share unavailable/)
  assert.equal(await saveDownloadBlob(blob, 'test.txt', { kind: 'ios', saveToDownloads: async () => true }), true)
})

test('image recovery bypasses failed URL caches without changing fragments or local blobs', () => {
  assert.equal(recoveredImageUrl('/api/image?size=256#anchor', 2), '/api/image?size=256&_recovery=2#anchor')
  assert.equal(recoveredImageUrl('blob:local', 2), 'blob:local')
  assert.equal(recoveredImageUrl('data:image/png;base64,abc', 2), 'data:image/png;base64,abc')
})
