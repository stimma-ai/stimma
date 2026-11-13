import assert from 'node:assert/strict'
import test from 'node:test'

import { cleanSuggestions, slotCovers, type SuggestedAdd } from './promptSuggestions.ts'

const camera: SuggestedAdd = { name: 'camera', label: 'camera', kind: 'camera', lists: ['camera.lens', 'camera.angle'] }
const light: SuggestedAdd = { name: 'light', label: 'light', kind: 'light', lists: ['lighting.natural'] }
const grade: SuggestedAdd = { name: 'color grade', label: 'color grade', kind: 'list', lists: ['camera.color_grade'] }

test('a /suggest answer keeps a photography add\'s kind and lists, and plain adds as they were', () => {
  const got = cleanSuggestions({
    vary: [{ from: 0, to: 3, text: 'cat' }, { from: 'x' }],
    adds: [{ name: 'background' }, { ...camera, lists: ['camera.lens', 4, 'camera.angle'] }, { name: '' }, { name: 'sky', kind: 7 }],
  })
  assert.deepEqual(got.vary, [{ from: 0, to: 3, text: 'cat' }])
  assert.deepEqual(got.adds, [{ name: 'background', label: 'background' }, camera, { name: 'sky', label: 'sky' }])
  assert.deepEqual(cleanSuggestions(null), { vary: [], adds: [] })
})

test('an add keeps where it goes only when both its words and its insert came back', () => {
  const got = cleanSuggestions({ adds: [
    { name: 'light', after: 'at dusk', insert: ', lit by <light>' },
    { name: 'sky', after: 'at dusk' },
    { name: 'pet', after: 3, insert: ', <pet>' },
  ] })
  assert.deepEqual(got.adds, [
    { name: 'light', label: 'light', after: 'at dusk', insert: ', lit by <light>' },
    { name: 'sky', label: 'sky' },
    { name: 'pet', label: 'pet' },
  ])
})

test('a slot read as a photography add\'s kind, or drawing from one of its lists, covers it', () => {
  const read = { kinds: ['person', 'light'], lists: ['person.age', 'camera.angle'] }
  assert.equal(slotCovers(light, read), true)
  assert.equal(slotCovers(camera, read), true)  // an angle slot is part of the camera
  assert.equal(slotCovers(grade, read), false)
  assert.equal(slotCovers(grade, { kinds: ['list'], lists: ['camera.color_grade'] }), true)
})

test('a list kind alone covers nothing, nor does anything before the slots are read', () => {
  assert.equal(slotCovers(grade, { kinds: ['list'], lists: ['person.age'] }), false)
  assert.equal(slotCovers(light, null), false)
  assert.equal(slotCovers({ name: 'light', label: 'light' }, { kinds: ['light'], lists: [] }), false)  // the model's own add
})
