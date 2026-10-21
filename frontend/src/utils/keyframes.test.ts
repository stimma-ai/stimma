import test from 'node:test'
import assert from 'node:assert/strict'

import {
  clipLengths, effectiveAt, fromWire, keyframesConfigFromSchema, keyframesProblems, lineageIds, toWire,
  type KeyframeItem,
} from './keyframes.ts'

const SCHEMA = {
  type: 'array',
  'x-control': 'keyframes',
  'x-max-items': 6,
  'x-timeline': { duration: 'duration', fps: 24 },
  'x-clip-frames': { min: 5, step: 17 },
  items: { properties: { media: {}, at: {}, from: {}, length: {}, sound: {} } },
}
const config = keyframesConfigFromSchema('keyframes', SCHEMA)

const still = (id: string, at: number, extra: Partial<KeyframeItem> = {}): KeyframeItem =>
  ({ id, path: `/lib/${id}.png`, isVideo: false, at, mediaId: 10, ...extra })

test('config reads the schema', () => {
  assert.deepEqual(config, {
    name: 'keyframes', max: 6, positions: 'any', durationParam: 'duration', fps: 24,
    clipFrames: { min: 5, step: 17 }, sound: true,
  })
  const stills = keyframesConfigFromSchema('kf', { ...SCHEMA, items: { properties: { media: {}, at: {} } } })
  assert.equal(stills.clipFrames, null)
  assert.equal(stills.sound, false)
})

test('wire shape is sorted, anchored, and carries clip fields only for clips', () => {
  const items: KeyframeItem[] = [
    still('end', 0, { anchor: 'end' }),
    { id: 'clip', path: '/lib/take.mp4', sourcePath: '/lib/take.mp4', thumbPath: '/tmp/f.png', isVideo: true,
      from: 4.7, length: 22 / 24, sound: true, at: 5.8, mediaId: 7 },
    still('start', 3, { anchor: 'start', mediaId: undefined }),
  ]
  assert.deepEqual(toWire(items, 8), [
    { media: '/lib/start.png', at: 0 },
    { media: '/lib/take.mp4', at: 5.8, from: 4.7, length: 0.917, sound: true },
    // End stills send the duration itself so they land on the last frame.
    { media: '/lib/end.png', at: 8 },
  ])
  assert.deepEqual(lineageIds(items, 8), [null, 7, 10])
})

test('end-anchored clips end at the end', () => {
  const clip: KeyframeItem = { id: 'c', path: '/v.mp4', sourcePath: '/v.mp4', isVideo: true, from: 0, length: 1, at: 2, anchor: 'end' }
  assert.equal(effectiveAt(clip, 8), 7)
  assert.equal(toWire([clip], 8)[0].at, 7)
})

test('a frame from a video sends its still', () => {
  const frame: KeyframeItem = { id: 'f', path: '/tmp/frame.png', sourcePath: '/lib/v.mp4', thumbPath: '/tmp/frame.png', isVideo: true, from: 3, at: 1 }
  assert.deepEqual(toWire([frame], 8), [{ media: '/tmp/frame.png', at: 1 }])
})

test('clip lengths follow the frame grid and the limit', () => {
  assert.deepEqual(clipLengths(config, 10).map(s => Math.round(s * 24)), [5, 22, 39, 56])
  assert.deepEqual(clipLengths(config, 1).map(s => Math.round(s * 24)), [5, 22])
  assert.deepEqual(clipLengths({ ...config, clipFrames: null }, 10), [])
})

test('problems flag keyframes past the end and too many items', () => {
  const late = still('late', 7.5)
  const clip: KeyframeItem = { id: 'c', path: '/v.mp4', isVideo: true, from: 0, length: 1, at: 7.5 }
  assert.deepEqual(keyframesProblems([late, clip], 8, config).map(p => p.id), ['c'])
  assert.deepEqual(keyframesProblems([still('x', 9)], 8, config).map(p => p.reason), ['Past the end of the video'])
  const many = Array.from({ length: 7 }, (_, i) => still(`s${i}`, i))
  assert.equal(keyframesProblems(many, 8, config).at(-1)?.reason, 'Up to 6 keyframes')
})

test('restoring from a past job rebuilds items and anchors', () => {
  const items = fromWire([
    { media: '/lib/a.png', at: 0 },
    { media: '/lib/take.mp4', at: 4, from: 1, length: 0.9, sound: true },
    { media: '/lib/b.png', at: 8 },
    { nope: true },
  ], [11, 12], 8)
  assert.deepEqual(items.map(i => [i.path, i.anchor, i.isVideo, i.mediaId, i.length ?? null]), [
    ['/lib/a.png', 'start', false, 11, null],
    ['/lib/take.mp4', null, true, 12, 0.9],
    ['/lib/b.png', 'end', false, undefined, null],
  ])
  assert.deepEqual(fromWire(undefined, undefined, 8), [])
})
