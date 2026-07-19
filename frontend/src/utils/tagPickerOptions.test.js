import assert from 'node:assert/strict'
import test from 'node:test'

import { shouldShowTagInPicker } from './tagPickerOptions.js'

test('tag picker only shows tags assigned to live items', () => {
  assert.equal(shouldShowTagInPicker({ usage_count: 0 }), false)
  assert.equal(shouldShowTagInPicker({}), false)
  assert.equal(shouldShowTagInPicker({ usage_count: 1 }), true)
})

test('tag picker keeps a newly created tag visible until it is saved', () => {
  assert.equal(shouldShowTagInPicker({ usage_count: 0 }, 'add'), true)
})
