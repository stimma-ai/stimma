import assert from 'node:assert/strict'
import test from 'node:test'

import { disableUnavailableLoras } from './availableLoras.ts'

const items = [
  { lora: 'kept', weight: 0.7, enabled: true },
  { lora: 'deleted', weight: 1.2, enabled: true },
  { lora: 'already-off', weight: -0.5, enabled: false },
]

test('deselects deleted LoRAs while retaining their pool entries and weights', () => {
  const updated = disableUnavailableLoras(items, new Set(['kept']))
  assert.deepEqual(updated, [items[0], { ...items[1], enabled: false }, items[2]])
  assert.equal(items[1].enabled, true)
})

test('an empty provider list deselects everything, but a missing list changes nothing', () => {
  assert.deepEqual(disableUnavailableLoras(items, new Set()), items.map(item => ({ ...item, enabled: false })))
  assert.equal(disableUnavailableLoras(items, null), items)
  assert.equal(disableUnavailableLoras(items, new Set(['kept', 'deleted'])), items)
})
