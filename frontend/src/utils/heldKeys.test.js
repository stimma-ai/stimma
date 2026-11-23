import assert from 'node:assert/strict'
import test from 'node:test'
import { nextTick, ref } from 'vue'
import { holdKeys } from './heldKeys.js'

test('a key shows only after it has held, and drops out at once', async (t) => {
  t.mock.timers.enable({ apis: ['setTimeout'] })
  const raw = ref(new Set(['a']))
  const held = holdKeys(() => raw.value, 3000)
  t.mock.timers.tick(2999)
  assert.equal(held.value.has('a'), false)
  t.mock.timers.tick(1)
  assert.equal(held.value.has('a'), true)
  raw.value = new Set()
  await nextTick()
  assert.equal(held.value.has('a'), false)
})

test('a key that leaves and returns starts its hold over', async (t) => {
  t.mock.timers.enable({ apis: ['setTimeout'] })
  const raw = ref(new Set(['a']))
  const held = holdKeys(() => raw.value, 3000)
  t.mock.timers.tick(2500)
  raw.value = new Set()
  await nextTick()
  raw.value = new Set(['a'])
  await nextTick()
  t.mock.timers.tick(2500)
  assert.equal(held.value.has('a'), false)
  t.mock.timers.tick(500)
  assert.equal(held.value.has('a'), true)
})
