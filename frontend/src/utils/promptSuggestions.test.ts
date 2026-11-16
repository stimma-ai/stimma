import assert from 'node:assert/strict'
import test from 'node:test'

import { cleanSuggestions, insertAdd, NO_SUGGESTIONS, phraseLabel } from './promptSuggestions.ts'

test('a /suggest answer keeps well-formed phrases and adds', () => {
  const got = cleanSuggestions({
    phrases: [
      { from: 2, to: 8, text: 'farmer', kind: ' person ', way: 'detail', mode: 'kind' },
      { from: 12, to: 21, text: 'short bob', kind: 'hairstyle', way: 'any' },
      { from: 0, to: 1, text: 'a', way: 'any', mode: 'one' },       // Any without a kind: Detail
      { from: 'x', to: 3, text: 'b' }, { from: 1, to: 2 }, null,
    ],
    adds: [
      { key: 'face', label: 'Face', at: 8, text: ' with <face>' },
      { key: 'camera', at: 25, text: ', <camera>' },                 // no label: its key
      { key: 'light', label: 'Light', at: 3, text: ', soft light' }, // no slot in it
      { key: 'x', label: 'X', at: 1.5, text: '<x>' }, { label: 'Y', at: 0, text: '<y>' }, 4,
    ],
  })
  assert.deepEqual(got.phrases, [
    { from: 2, to: 8, text: 'farmer', kind: 'person', way: 'detail', mode: 'kind' },
    { from: 12, to: 21, text: 'short bob', kind: 'hairstyle', way: 'any', mode: 'kind' },
    { from: 0, to: 1, text: 'a', kind: '', way: 'detail', mode: 'one' },
  ])
  assert.deepEqual(got.adds, [
    { key: 'face', label: 'Face', at: 8, text: ' with <face>' },
    { key: 'camera', label: 'camera', at: 25, text: ', <camera>' },
  ])
  assert.deepEqual(cleanSuggestions(null), NO_SUGGESTIONS)
  // An answer in the old shape gives nothing.
  assert.deepEqual(cleanSuggestions({ vary: [{ from: 2, to: 8, text: 'farmer', label: 'different farmers' }],
    looks: [{ text: 'documentary photo', label: 'documentary' }], adds: [{ text: 'carrying a basket', label: 'basket' }] }), NO_SUGGESTIONS)
})

test('a phrase chip says Detail with its words, or Any with its kind', () => {
  assert.equal(phraseLabel({ text: 'dog', kind: 'animal', way: 'detail' }), 'Detail dog')
  assert.equal(phraseLabel({ text: 'short bob', kind: 'hairstyle', way: 'any' }), 'Any hairstyle')
  assert.equal(phraseLabel({ text: 'dog', kind: 'animal', way: 'detail' }, 'any'), 'Any animal')
  assert.equal(phraseLabel({ text: 'short bob', kind: 'hairstyle', way: 'any' }, 'detail'), 'Detail short bob')
  assert.equal(phraseLabel({ text: 'dog', kind: '', way: 'any' }), 'Detail dog')
})

test('an add goes in where Suggest placed it, and says where its slot starts', () => {
  const prompt = 'a farmer in rural Vietnam'
  assert.deepEqual(insertAdd(prompt, { key: 'face', label: 'Face', at: 8, text: ' with <face>' }),
    { text: 'a farmer with <face> in rural Vietnam', slotAt: 14 })
  assert.deepEqual(insertAdd(prompt, { key: 'camera', label: 'Camera', at: 25, text: ', <camera>' }),
    { text: 'a farmer in rural Vietnam, <camera>', slotAt: 27 })
  assert.deepEqual(insertAdd('a woman with a bob', { key: 'face', label: 'Face', at: 13, text: '<face> and ' }),
    { text: 'a woman with <face> and a bob', slotAt: 13 })
  // A place past either end is held to the text.
  assert.equal(insertAdd('a cat', { key: 'camera', label: 'Camera', at: 99, text: ', <camera>' }).text, 'a cat, <camera>')
  assert.equal(insertAdd('a cat', { key: 'x', label: 'X', at: -3, text: '<x> ' }).text, '<x> a cat')
})
