import assert from 'node:assert/strict'
import test from 'node:test'
import { imageParts, isSlotRun, undoUse, usedState, type ImageWorld } from './fromImage.ts'
import type { ChoicePool } from './programWire.ts'

const pool: ChoicePool = {
  kind: 'variants', state: 'ready', options: [],
  variants: [{ text: 'a freckled 28-year-old young woman of Irish descent', seeds: { descent: 'Irish', gender: 'woman', age: '28-year-old' } }],
  person: {
    descent: { list: 'person.ethnicity', label: 'Descent', browse: 'region', parts: [{ id: 'Northern Europe', values: ['Irish', 'Swedish'] }] },
    gender: { list: 'person.gender', label: 'Gender', options: ['woman', 'trans woman'] },
    age: { list: 'person.age_band', label: 'Age', options: ['young adult'], stages: [{ id: 'young adult', label: 'Young adult', span: [18, 34], years: [18, 24, 28, 34] }] },
  },
}
const world = (states = {}, words = 'lighting'): ImageWorld => ({
  slots: [
    { id: 'light', n: 2, kind: 'light', label: 'Lighting', words },
    { id: 'woman', n: 1, kind: 'person', label: 'Woman', words: 'young woman' },
  ],
  choices: [
    { id: 'woman', kind: 'variants', label: 'Woman', slot: 'woman' },
    { id: 'light', kind: 'variants', label: 'Lighting', slot: 'light' },
    { id: 'list1', kind: 'pick', label: 'Season', source: 'list', options: ['summer', 'autumn'] },
  ],
  states,
  pools: { woman: pool },
})
const run = { key: 'k', version: 'slots-1', draws: [
  { id: 'woman', value: 'a freckled 28-year-old young woman of Irish descent', about: 'young woman', seeds: { descent: 'Irish', gender: 'woman', age: '28-year-old' } },
  { id: 'light', value: 'soft window light', about: 'lighting' },
  { id: 'list1', value: 'autumn', source: 'list' },
  // An earlier Fluent's person detail: not a part.
  { id: 'woman.age', value: '24-year-old' },
  // A slot the prompt no longer has.
  { id: 'gone', value: 'a red scarf', about: 'scarf', label: 'Scarf' },
  // A slot that went in as its words: nothing to use.
  { id: 'cup', value: 'cup', about: 'cup', source: 'words' },
] }

test('a part per slot and list the image drew, in its order; a person has its broad strokes', () => {
  const parts = imageParts(run, world())
  assert.deepEqual(parts.map(p => [p.key, p.label, p.text, p.here]), [
    ['woman', 'Woman', 'a freckled 28-year-old young woman of Irish descent', true],
    ['light', 'Lighting', 'soft window light', true],
    ['list1', 'Season', 'autumn', true],
    ['gone', 'Scarf', 'a red scarf', false],
  ])
  assert.deepEqual(parts[0].person, { pronoun: 'her', facets: [
    { id: 'age', says: 'age 28', value: 28 }, { id: 'gender', says: 'woman', value: 'woman' }, { id: 'descent', says: 'Irish', value: 'Irish' },
  ] })
  assert.equal(parts[1].person, undefined)
})

test('a slot whose words changed since is not in the prompt now', () => {
  const light = imageParts(run, world({}, 'warm lighting')).find(p => p.key === 'light')!
  assert.equal(light.here, false)
  assert.equal(usedState(light, {}, null), undefined)
})

test('using adds to the picks, never replaces them; the same again changes nothing', () => {
  const [, light] = imageParts(run, world())
  const states = { light: { values: ['neon'], add: ['mine'] } }
  const next = usedState(light, states, null)
  assert.deepEqual(next, { values: ['neon', 'soft window light'], add: ['mine'] })
  assert.equal(usedState(light, { light: next! }, null), undefined)
})

test('a person’s age, gender and descent are each a seed pick; covered already, nothing changes', () => {
  const [woman] = imageParts(run, world())
  const [age, gender, descent] = woman.person!.facets
  assert.deepEqual(usedState(woman, {}, pool, age), { seeds: { age: { years: [28] } } })
  assert.deepEqual(usedState(woman, {}, pool, gender), { seeds: { gender: { values: ['woman'] } } })
  assert.deepEqual(usedState(woman, { woman: { seeds: { gender: { values: ['trans woman'] } } } }, pool, gender),
    { seeds: { gender: { values: ['trans woman', 'woman'] } } })
  assert.deepEqual(usedState(woman, {}, pool, descent), { seeds: { descent: { values: ['Irish'] } } })
  assert.equal(usedState(woman, { woman: { seeds: { age: { values: ['young adult'] } } } }, pool, age), undefined)
  assert.equal(usedState(woman, { woman: { seeds: { descent: { groups: { region: ['Northern Europe'] } } } } }, pool, descent), undefined)
})

test('only images made from slots offer it', () => {
  assert.equal(isSlotRun(run), true)
  assert.equal(isSlotRun({ ...run, version: undefined }), false)
  assert.equal(isSlotRun({ ...run, fallback: { rung: 'words' } }), false)
  assert.deepEqual(imageParts({ key: 'k', draws: run.draws }, world()), [])
  assert.deepEqual(imageParts({ ...run, draws: [{ id: 'woman.age', value: '24-year-old' }] }, world()), [])
})

test('Undo takes back only what that use added: use age, use descent, undo age keeps the descent', () => {
  const [woman, light] = imageParts(run, world())
  const [age, , descent] = woman.person!.facets
  // Before: a gender picked by hand.
  const start = { seeds: { gender: { values: ['woman'] } } }
  const afterAge = usedState(woman, { woman: start }, pool, age)!
  const afterDescent = usedState(woman, { woman: afterAge }, pool, descent)!
  // A picker edit after both uses.
  const edited = { ...afterDescent, values: ['a freckled 28-year-old young woman of Irish descent'] }
  assert.deepEqual(undoUse(woman, { woman: edited }, start, age),
    { values: ['a freckled 28-year-old young woman of Irish descent'], seeds: { gender: { values: ['woman'] }, descent: { values: ['Irish'] } } })
  // Undoing the descent too leaves the hand-picked gender and the edit.
  const both = undoUse(woman, { woman: undoUse(woman, { woman: edited }, start, age)! }, afterAge, descent)
  assert.deepEqual(both, { values: ['a freckled 28-year-old young woman of Irish descent'], seeds: { gender: { values: ['woman'] } } })
  // What was already picked before the use stays on Undo; so does a value removed since.
  assert.deepEqual(undoUse(light, { light: { values: ['soft window light', 'neon'] } }, { values: ['soft window light'] }), { values: ['soft window light', 'neon'] })
  assert.deepEqual(undoUse(light, { light: { values: ['neon', 'soft window light'] } }, { values: ['neon'] }), { values: ['neon'] })
  assert.deepEqual(undoUse(light, { light: { values: ['neon'] } }, null), { values: ['neon'] })
})
