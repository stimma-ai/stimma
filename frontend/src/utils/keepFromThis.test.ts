import test from 'node:test'
import assert from 'node:assert/strict'
import { flipRow, isSlotRun, keepGroups, type KeepWorld } from './keepFromThis.ts'
import type { ProgramChoice } from './programWire.ts'

const ch = (id: string, label: string, extra: Partial<ProgramChoice> = {}): ProgramChoice => ({ id, kind: 'pick', label, options: [], ...extra })
const world = (states = {}): KeepWorld => ({
  slots: [
    { id: 'young_man', n: 1, kind: 'person', label: 'Young man', words: 'young man',
      details: ['young_man.age', 'young_man.descent', 'young_man.hair', 'young_man.outfit', 'young_man.outfit.colors'] },
    { id: 'light', n: 2, kind: 'light', label: 'Light', words: 'light', details: ['light'] },
    { id: 'pet', n: 3, kind: 'free', label: 'Pet', words: 'pet', details: ['pet'] },
  ],
  choices: [
    ch('young_man.age', 'Age', { slot: 'young_man' }), ch('young_man.descent', 'Descent', { slot: 'young_man' }),
    ch('young_man.hair', 'Hair', { slot: 'young_man' }), ch('young_man.outfit', 'Outfit', { slot: 'young_man', cls: 'person.outfit.casual' }),
    ch('young_man.outfit.colors', 'Colors', { slot: 'young_man', cls: 'person.palette', follows: 'young_man.outfit' }),
    ch('light', 'Light', { slot: 'light' }), ch('pet', 'Pet', { slot: 'pet' }),
    ch('list1', 'Season', { source: 'list', line: 1 }),
  ],
  states,
  pools: { light: { options: [], short: { 'cool daylight through a tall window': 'cool daylight' } },
    'young_man.outfit': { options: [], short: { 'a {main} flannel shirt and {neutral} jeans': 'flannel and jeans' } } },
})
const run = {
  key: 'k1', version: 'slots-1',
  draws: [
    { id: 'young_man.age', value: '24-year-old', kind: 'pick' }, { id: 'young_man.descent', value: 'Korean', kind: 'pick' },
    { id: 'young_man.hair', value: 'buzz cut', kind: 'pick' },
    { id: 'young_man.outfit', value: 'a navy flannel shirt and gray jeans', template: 'a {main} flannel shirt and {neutral} jeans', kind: 'pick' },
    { id: 'young_man.outfit.colors', value: 'navy, white and gray', kind: 'pick' },
    { id: 'light', value: 'cool daylight through a tall window', kind: 'pick' },
    { id: 'pet', value: null, kind: 'pick' },  // left out in this image
    { id: 'list1', value: 'autumn', kind: 'pick' },
    { id: 'gone', value: 'x', kind: 'pick' },
  ],
}

test('a person is their look and their outfit; every other slot and list is a line', () => {
  const g = keepGroups(run, world())
  assert.deepEqual(g.map(x => [x.label, x.rows.map(r => [r.label, r.text])]), [
    ['Young man', [['Look', '24-year-old, Korean, buzz cut'], ['Outfit', 'flannel and jeans']]],
    ['', [['Light', 'cool daylight'], ['Season', 'autumn']]],
  ])
  const outfit = g[0].rows[1]
  assert.equal(outfit.swatches?.length, 3)
  // The outfit is kept as its template, its colors as their own choice.
  assert.deepEqual(outfit.drawn, [{ id: 'young_man.outfit', value: 'a {main} flannel shirt and {neutral} jeans' },
    { id: 'young_man.outfit.colors', value: 'navy, white and gray' }])
})

test('ticking sets each choice to the image’s value; the tick is read from the choices', () => {
  const look = keepGroups(run, world())[0].rows[0]
  assert.equal(look.on, false)
  const set = flipRow(look, { 'young_man.hair': { add: ['mullet'] } })
  assert.deepEqual(set, {
    'young_man.age': { values: ['24-year-old'] }, 'young_man.descent': { values: ['Korean'] },
    'young_man.hair': { values: ['buzz cut'], add: ['mullet'] },
  })
  const after = keepGroups(run, world(set))[0].rows[0]
  assert.equal(after.on, true)
  // Unticking puts them back, keeping the user's own options.
  assert.deepEqual(flipRow(after, set), { 'young_man.age': null, 'young_man.descent': null, 'young_man.hair': { add: ['mullet'] } })
  // Anything more chosen than this image's value is not "this image".
  assert.equal(keepGroups(run, world({ ...set, 'young_man.age': { values: ['24-year-old', '27-year-old'] } }))[0].rows[0].on, false)
})

test('only images made from slots offer anything', () => {
  assert.ok(isSlotRun(run))
  assert.ok(!isSlotRun({ ...run, version: undefined }))
  assert.ok(!isSlotRun({ ...run, fallback: { rung: 'words' } }))
  assert.deepEqual(keepGroups({ key: 'k', draws: run.draws, mode: 'prose', elaborate: true }, world()), [])
})
