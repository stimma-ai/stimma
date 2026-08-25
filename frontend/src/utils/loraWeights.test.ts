import assert from 'node:assert/strict'
import test from 'node:test'

import { clampLoraWeight } from './loraWeights.ts'

test('LoRA weights preserve negatives and clamp to the supported range', () => {
  assert.equal(clampLoraWeight(-4.25), -4.25)
  assert.equal(clampLoraWeight(-11), -10)
  assert.equal(clampLoraWeight(11), 10)
})
