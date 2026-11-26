import assert from 'node:assert/strict'
import test from 'node:test'

import { applySavedElement } from './elementCache.ts'

const version = (media_id: number, cover: string, name = 'Mira', asset_id = 7) => ({ asset_id, media_id, name, cover })

test('a new cover is cached under the new version only', () => {
  const cache = new Map([[10, version(10, 'face')]])
  applySavedElement(cache, version(11, 'angry'))
  assert.equal(cache.get(10)?.cover, 'face')
  assert.equal(cache.get(11)?.cover, 'angry')
})

test('a rename reaches every cached version of that element and no other', () => {
  const cache = new Map([[10, version(10, 'face')], [11, version(11, 'angry')], [20, version(20, 'x', 'Wen', 8)]])
  applySavedElement(cache, version(11, 'angry', 'Mira K'))
  assert.deepEqual([...cache.values()].map(e => [e.media_id, e.name, e.cover]), [
    [10, 'Mira K', 'face'], [11, 'Mira K', 'angry'], [20, 'Wen', 'x'],
  ])
})
