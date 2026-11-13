import assert from 'node:assert/strict'
import test from 'node:test'
import { flipRow, isSlotRun, keepRows, type KeepWorld } from './keepFromThis.ts'

const world = (states = {}): KeepWorld => ({
  slots: [
    { id: 'light', n: 2, kind: 'light', label: 'Lighting', words: 'lighting' },
    { id: 'woman', n: 1, kind: 'person', label: 'Woman', words: 'young woman' },
  ],
  choices: [
    { id: 'woman', kind: 'variants', label: 'Woman', slot: 'woman' },
    { id: 'light', kind: 'variants', label: 'Lighting', slot: 'light' },
    { id: 'list1', kind: 'pick', label: 'Season', source: 'list', options: ['summer', 'autumn'] },
  ],
  states,
  pools: {},
})
const run = { key: 'k', version: 'slots-1', draws: [
  { id: 'light', value: 'soft window light' },
  { id: 'woman', value: 'young woman of Korean descent with a sharp bob' },
  { id: 'list1', value: 'autumn' },
  // An earlier Fluent's person detail: matches no choice now.
  { id: 'woman.age', value: '24-year-old' },
  { id: 'gone', value: 'x' },
] }

test('a line per slot in the prompt’s order, then the user’s lists; old detail draws pass by', () => {
  const rows = keepRows(run, world())
  assert.deepEqual(rows.map(r => [r.key, r.label, r.text, r.on]), [
    ['woman', 'Woman', 'young woman of Korean descent with a sharp bob', false],
    ['light', 'Lighting', 'soft window light', false],
    ['list1', 'Season', 'autumn', false],
  ])
})

test('a tick pins exactly what the image drew, with the image; unticking lets it vary', () => {
  const [, light] = keepRows(run, world({ light: { add: ['mine'] } }))
  const set = flipRow(light, { light: { add: ['mine'] } }, 42)
  assert.deepEqual(set, { light: { values: ['soft window light'], add: ['mine'], from: 42 } })
  const ticked = keepRows(run, world(set))[1]
  assert.equal(ticked.on, true)
  assert.deepEqual(flipRow(ticked, set as any), { light: { add: ['mine'] } })
  // Anything more chosen than this one variant is not this image's line.
  assert.equal(keepRows(run, world({ light: { values: ['soft window light', 'neon'] } }))[1].on, false)
})

test('only images made from slots offer it', () => {
  assert.equal(isSlotRun(run), true)
  assert.equal(isSlotRun({ ...run, version: undefined }), false)
  assert.equal(isSlotRun({ ...run, fallback: { rung: 'words' } }), false)
  assert.deepEqual(keepRows({ key: 'k', draws: run.draws }, world()), [])
  assert.deepEqual(keepRows({ ...run, draws: [{ id: 'woman.age', value: '24-year-old' }] }, world()), [])
})
