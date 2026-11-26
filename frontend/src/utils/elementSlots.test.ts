import test from 'node:test'
import assert from 'node:assert/strict'
import { applyLoras, applyRefs, renderGuidance } from './elementSlots.ts'

const ref = (id: number, key = `k${id}`, el = 1) => ({ element_asset_id: el, member_key: key, media_id: id, file_path: `/lib/${id}.png` })

test('an element pick swaps in place; the user’s images never move', () => {
  const user = { mediaId: 9, path: '/lib/9.png' }
  const first = applyRefs([user], [], [ref(1)], 3)
  assert.deepEqual(first.items.map(i => i.mediaId), [9, 1])
  // The prompt changed: pick 1 becomes pick 2, in the same slot.
  const swapped = applyRefs([first.items[1], user], first.picks, [ref(2)], 3)
  assert.deepEqual(swapped.items.map(i => i.mediaId), [2, 9])
  assert.deepEqual(swapped.picks, [{ element_asset_id: 1, member_key: 'k2', mediaId: 2 }])
})

test('a kept or user-placed image is never placed twice or replaced', () => {
  const kept = { mediaId: 1, path: '/lib/1.png' }   // no longer a pick: the user's
  const out = applyRefs([kept], [], [ref(1), ref(3)], 3)
  assert.deepEqual(out.items.map(i => i.mediaId), [1, 3])
  assert.deepEqual(out.picks.map(p => p.mediaId), [3])
})

test('picks stop at the slot limit, and an unchanged plan keeps the same items', () => {
  const out = applyRefs([], [], [ref(1), ref(2), ref(3)], 2)
  assert.deepEqual(out.items.map(i => i.mediaId), [1, 2])
  const again = applyRefs(out.items, out.picks, [ref(1), ref(2)], 2)
  assert.ok(again.items.every((item, i) => item === out.items[i]))
})

test('element LoRAs come and go; the user’s own LoRA is untouched', () => {
  const user = { lora: 'style.safetensors', weight: 0.6, enabled: true }
  const pool = { lora: 'mira.safetensors', weight: 1, enabled: false }
  const on = applyLoras([user, pool], [], [{ element_asset_id: 1, lora_key: 'mira', path: 'mira.safetensors', weight: 0.8 }])
  assert.deepEqual(on.loras, [user, { lora: 'mira.safetensors', weight: 0.8, enabled: true }])
  // A LoRA the user already has on stays theirs.
  const theirs = applyLoras([user], [], [{ element_asset_id: 1, lora_key: 's', path: 'style.safetensors', weight: 1 }])
  assert.deepEqual(theirs.loras, [user])
  assert.deepEqual(theirs.picks, [])
  // Detached: the pool entry goes back to how the user had it.
  const off = applyLoras(on.loras, on.picks, [])
  assert.deepEqual(off.loras, [user, pool])
  const fresh = applyLoras([user], [], [{ element_asset_id: 1, lora_key: 'n', path: 'new.safetensors', weight: 0.7 }])
  assert.deepEqual(applyLoras(fresh.loras, fresh.picks, []).loras, [user])
})

test('guidance numbers images as they stand in the slots, not in the order they were chosen', () => {
  const selected = [ref(2), ref(3)]
  // A user image first, and the picks landed as [3, 2].
  const items = [{ mediaId: 9 }, { mediaId: 3 }, { mediaId: 2 }]
  assert.equal(
    renderGuidance('Keep her face from {ref:1}; the stall is {ref:2}. Ignore {ref:5}.', selected, items),
    'Keep her face from image 3; the stall is image 2. Ignore a reference image.',
  )
})
