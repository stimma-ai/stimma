import assert from 'node:assert/strict'
import test from 'node:test'

import { appendWords, cleanSuggestions, shownWords } from './promptSuggestions.ts'

test('a /suggest answer keeps well-formed vary phrases, looks and adds', () => {
  const got = cleanSuggestions({
    vary: [{ from: 2, to: 8, text: 'farmer', label: 'different farmers' }, { from: 'x' }, { from: 0, to: 1, text: 'a', mode: 'one' }],
    looks: [{ text: 'documentary photo, wide shot, soft mist', label: 'documentary photo' }, { text: '' }, { label: 'x' }],
    adds: [{ text: 'carrying a bamboo basket' }, 4],
  })
  assert.deepEqual(got.vary, [{ from: 2, to: 8, text: 'farmer', label: 'different farmers', mode: 'kind' }, { from: 0, to: 1, text: 'a', label: 'a', mode: 'one' }])
  assert.deepEqual(got.looks, [{ text: 'documentary photo, wide shot, soft mist', label: 'documentary photo' }])
  assert.deepEqual(got.adds, [{ text: 'carrying a bamboo basket', label: 'carrying a bamboo basket' }])
  assert.deepEqual(cleanSuggestions(null), { vary: [], looks: [], adds: [] })
  // An answer in the old shape gives nothing.
  assert.deepEqual(cleanSuggestions({ adds: [{ name: 'light', label: 'light' }] }).adds, [])
})

test('words go after a comma at the end of the last picture line', () => {
  assert.equal(appendWords('a farmer in rural Vietnam', 'soft morning mist'), 'a farmer in rural Vietnam, soft morning mist')
  assert.equal(appendWords('a farmer,  ', 'mist'), 'a farmer, mist  ')
  assert.equal(appendWords('a farmer\n# keep it calm\n', 'mist'), 'a farmer, mist\n# keep it calm\n')
  assert.equal(appendWords('# only a note', 'mist'), '# only a note\nmist')
  assert.equal(appendWords('', 'mist'), 'mist')
})

test('once a look is in the prompt the others go; an add already there goes', () => {
  const s = cleanSuggestions({
    looks: [{ text: 'documentary photo, wide shot' }, { text: 'cinematic still, low angle' }],
    adds: [{ text: 'carrying a basket' }, { text: 'a water buffalo' }],
  })
  assert.equal(shownWords(s, 'a farmer').looks.length, 2)
  const after = appendWords('a farmer', 'cinematic still, low angle')
  assert.deepEqual(shownWords(s, after).looks, [])
  assert.deepEqual(shownWords(s, 'a farmer, carrying a basket').adds.map(a => a.text), ['a water buffalo'])
})
