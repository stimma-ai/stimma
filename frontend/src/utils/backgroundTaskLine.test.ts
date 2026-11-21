import assert from 'node:assert/strict'
import test from 'node:test'

import { backgroundTaskLine, shortDuration } from './backgroundTaskLine.ts'

const counts = (c: Record<string, number>) => ({
  done: 0, failed: 0, cancelled: 0, generating: 0, queued: 0, preparing: 0, waiting: 0, ...c,
})
const videos = (k: number) => Array.from({ length: k }, () => ({ kind: 'video' }))

test('a serial loop that declared nothing gets counts, never a total', () => {
  const line = backgroundTaskLine({
    label: '',
    counts: counts({ done: 23, generating: 1, failed: 2 }),
    items: videos(26),
    progress: null,
  })
  assert.equal(line.title, 'Generating videos')
  assert.equal(line.summary, '23 done · 1 in progress · 2 failed')
  assert.equal(line.fraction, null)
})

test('the agent label names the task but adds no total', () => {
  const line = backgroundTaskLine({ label: 'Five-minute take', counts: counts({ done: 3, generating: 1 }), items: videos(4) })
  assert.equal(line.title, 'Five-minute take')
  assert.equal(line.summary, '3 done · 1 in progress')
  assert.equal(line.fraction, null)
})

test('a declared batch reads "X of Y" and fills the ring', () => {
  const line = backgroundTaskLine({
    label: '',
    counts: counts({ done: 4, generating: 1, failed: 1 }),
    items: videos(6),
    progress: { title: 'Long take', done: 4, failed: 1, total: 35 },
  })
  assert.equal(line.title, 'Long take')
  assert.equal(line.summary, '4 of 35 · 1 failed')
  assert.equal(line.fraction, 5 / 35)
})

test('an open-ended stream counts what it made, with no total', () => {
  const line = backgroundTaskLine({
    label: '',
    counts: counts({ done: 12, generating: 2 }),
    items: [{ kind: 'image' }],
    progress: { title: 'Market vendors', open: true },
  })
  assert.equal(line.title, 'Market vendors')
  assert.equal(line.summary, '12 done · 2 in progress')
  assert.equal(line.fraction, null)
})

test('nothing started yet', () => {
  assert.deepEqual(backgroundTaskLine({ label: '', counts: counts({}) }), { title: 'Working…', summary: '', fraction: null })
})

test('mixed kinds are items', () => {
  assert.equal(backgroundTaskLine({ counts: counts({ done: 2 }), items: [{ kind: 'image' }, { kind: 'video' }] }).title, 'Generating items')
})

test('durations', () => {
  assert.equal(shortDuration(42), '42s')
  assert.equal(shortDuration(240), '4m')
  assert.equal(shortDuration(3600), '1h')
  assert.equal(shortDuration(4320), '1h 12m')
})
