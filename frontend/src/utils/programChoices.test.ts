import assert from 'node:assert/strict'
import test from 'node:test'
import {
  addOwn, asWritten, listChoiceAt, carriedIds, followId, carryChoices, chooseAny, cleanState, clearSeed, isChanged, keptPieces, leaveOut, lineText, lookOf,
  numberRepeats, optionsOf, pinTo, regionNote, resetState, shownVariants, toggleGender, toggleHeritage, toggleRegion, toggleValue, wireState,
} from './programChoices.ts'
import type { ChoicePool, ProgramSlot } from './programWire.ts'

const ready: Pick<ProgramSlot, 'state'> = { state: 'ready' }
const descent = {
  list: 'person.ethnicity', label: 'Descent', browse: 'region',
  parts: [{ id: 'East Asia', values: ['Korean', 'Japanese', 'Chinese'] }, { id: 'Northern Europe', values: ['Swedish', 'Danish'] }],
}
const pool: ChoicePool = {
  kind: 'variants', state: 'ready', options: [],
  variants: [
    { text: 'young woman of Korean descent with a sharp bob', seeds: { descent: 'Korean', gender: 'woman' } },
    { text: 'young woman of Swedish descent with a bleached crop', seeds: { descent: 'Swedish', gender: 'trans woman' } },
    { text: 'young woman of Japanese descent with a silver bob', seeds: { descent: 'Japanese', gender: 'trans woman' } },
    { text: 'young woman with freckles', own: true },
  ],
  person: { descent, gender: { list: 'person.gender', label: 'Gender', options: ['woman', 'trans woman'] } },
}
const [korean, swedish, japanese] = pool.variants!.map(v => v.text)

test('a state is stored lean: empties dropped, off and as written alone with the user’s own', () => {
  assert.equal(cleanState({ values: [], seeds: { descent: { values: [], groups: { region: [] } } } }), null)
  assert.deepEqual(cleanState({ off: true, values: ['x'], add: ['mine'] }), { off: true, add: ['mine'] })
  assert.deepEqual(cleanState({ as_written: true, seeds: { gender: { values: ['woman'] } } }), { as_written: true })
  assert.deepEqual(cleanState({ values: ['a', 'a', ' '], seeds: { gender: { values: ['woman'] } } }), { values: ['a'], seeds: { gender: { values: ['woman'] } } })
  // Where a pin came from holds only for a single pin.
  assert.deepEqual(cleanState({ values: ['a'], from: 7 }), { values: ['a'], from: 7 })
  assert.deepEqual(cleanState({ values: ['a', 'b'], from: 7 }), { values: ['a', 'b'] })
  assert.deepEqual(wireState({ values: ['a'], from: 7 }), { values: ['a'] })
})

test('pinning adds and removes; any, as written and leave out; the user’s own stay', () => {
  let s = toggleValue(null, korean)
  assert.deepEqual(s, { values: [korean] })
  s = toggleValue(s, swedish)
  assert.deepEqual(s, { values: [korean, swedish] })
  assert.deepEqual(toggleValue(s, korean), { values: [swedish] })
  assert.equal(chooseAny(s), null)
  assert.deepEqual(asWritten({ values: [korean], add: ['mine'] }), { as_written: true, add: ['mine'] })
  assert.deepEqual(leaveOut({ values: [korean] }), { off: true })
  // Pinning brings a slot left out back.
  assert.deepEqual(toggleValue({ off: true }, korean), { values: [korean] })
  assert.deepEqual(addOwn({ values: [korean] }, ' a tall one '), { values: [korean, 'a tall one'], add: ['a tall one'] })
  assert.deepEqual(resetState({ values: [korean], add: ['mine'] }), { add: ['mine'] })
  assert.deepEqual(pinTo({ add: ['mine'] }, korean, 12), { values: [korean], add: ['mine'], from: 12 })
  assert.ok(!isChanged({ add: ['mine'] }) && isChanged({ as_written: true }) && isChanged({ seeds: { gender: { values: ['woman'] } } }))
})

test('descent: a region picked whole takes over its heritages; un-picking one in it keeps the rest', () => {
  let s = toggleHeritage(null, 'Korean', pool)
  assert.deepEqual(s, { seeds: { descent: { values: ['Korean'] } } })
  s = toggleRegion(s, 'East Asia', pool)
  assert.deepEqual(s, { seeds: { descent: { groups: { region: ['East Asia'] } } } })
  assert.equal(regionNote(s, descent.parts[0]), 'all')
  s = toggleHeritage(s, 'Japanese', pool)
  assert.deepEqual(s, { seeds: { descent: { values: ['Korean', 'Chinese'] } } })
  assert.equal(regionNote(s, descent.parts[0]), '2 of 3')
  assert.equal(regionNote(s, descent.parts[1]), '2')
  assert.equal(clearSeed(s, 'descent', pool), null)
})

test('a seed pick drops pins it rules out, keeps the user’s own, and the picker lists what matches', () => {
  const s = toggleGender({ values: [korean, swedish, 'young woman with freckles'] }, 'trans woman', pool)
  assert.deepEqual(s, { values: [swedish, 'young woman with freckles'], seeds: { gender: { values: ['trans woman'] } } })
  assert.deepEqual(shownVariants(pool, { seeds: { gender: { values: ['trans woman'] } } }).map(v => v.text), [swedish, japanese, 'young woman with freckles'])
  assert.deepEqual(shownVariants(pool, { seeds: { descent: { groups: { region: ['East Asia'] } } } }).map(v => v.text), [korean, japanese, 'young woman with freckles'])
  // A pin kept from an image the pool doesn't hold leads the list.
  assert.deepEqual(shownVariants(pool, { values: ['an older variant'] }).map(v => v.text)[0], 'an older variant')
})

test('how a slot shows: writing, varying, pinned, kept, several, as written, left out', () => {
  assert.equal(lookOf(null, null), 'writing')
  assert.equal(lookOf({ state: 'reading' }, null), 'writing')
  assert.equal(lookOf({ state: 'writing' }, null), 'writing')
  assert.equal(lookOf(ready, null, { options: [], state: 'writing' }), 'writing')
  assert.equal(lookOf(ready, null, pool), 'varying')
  assert.equal(lookOf(ready, { values: [korean] }), 'pinned')
  assert.equal(lookOf(ready, { values: [korean], from: 3 }), 'keep')
  assert.equal(lookOf(ready, { values: [korean, swedish] }), 'several')
  assert.equal(lookOf(ready, { seeds: { gender: { values: ['woman'] } } }), 'several')
  assert.equal(lookOf(ready, { as_written: true }), 'written')
  assert.equal(lookOf({ state: 'as_written' }, null), 'written')
  assert.equal(lookOf(ready, { off: true }), 'off')
})

test('a line says what is set in a few words', () => {
  assert.equal(lineText(null), '')
  assert.equal(lineText({ off: true }), 'left out')
  assert.equal(lineText({ as_written: true }), 'as written')
  assert.equal(lineText({ values: ['window light'] }), 'window light')
  assert.equal(lineText({ values: ['a', 'b', 'c'] }), '3 variants')
  assert.equal(lineText({ seeds: { descent: { groups: { region: ['East Asia'] } }, gender: { values: ['trans woman'] } } }), 'East Asia · Trans woman')
  assert.equal(lineText({ seeds: { descent: { values: ['Korean', 'Irish', 'Samoan'] } } }), 'Korean, Irish +1')
})

test('the slot’s own words in a variant are found for showing quieter', () => {
  const pieces = (t: string, w: string, keep?: string[]) => keptPieces(t, w, keep).map(p => (p.kept ? `[${p.t}]` : p.t)).join('')
  assert.equal(pieces('freckled dominant young woman with copper curls', 'dominant young woman'), 'freckled [dominant young woman] with copper curls')
  // The category word was replaced by a kind of it: the rest still shows.
  assert.equal(pieces('a white cardigan slightly open in the front', 'clothing slightly open in the front'), 'a white cardigan [slightly open in the front]')
  assert.equal(pieces('mirror selfie in a smudged mirror', 'type of selfie'), 'mirror [selfie] in a smudged mirror')
  // The server's runs, when it names them; a hyphen reads as a space.
  assert.equal(pieces('a sun-lit room', 'sun lit room', ['sun lit']), 'a [sun-lit] room')
  assert.equal(pieces('nothing alike', 'room'), 'nothing alike')
  // A slot that is only its category word keeps none of it: nothing reads quieter.
  assert.equal(pieces('warm lighting from a lamp', 'lighting', []), 'warm lighting from a lamp')
})

test('options: a slot’s variant texts, a list’s options, the user’s own first', () => {
  assert.deepEqual(optionsOf({ id: 'w', kind: 'variants', label: 'W', slot: 'w' }, pool, { add: ['mine'] }).slice(0, 2), ['mine', korean])
  assert.deepEqual(optionsOf({ id: 'list1', kind: 'pick', label: 'Season', source: 'list', options: ['summer', 'autumn'] }, null), ['summer', 'autumn'])
})

test('choices follow their slots through an edit, by `was`', () => {
  const prev = { key: 'k1', slots: [{ id: 'mug_2', n: 2, kind: 'free' as const, label: 'Mug', words: 'mug' }], choices: [{ id: 'mug_2', kind: 'variants' as const, label: 'Mug', slot: 'mug_2' }] }
  const next = { from: 'k1', slots: [{ id: 'mug', n: 1, kind: 'free' as const, label: 'Mug', words: 'mug', was: 'mug_2' }], choices: [{ id: 'mug', kind: 'variants' as const, label: 'Mug', slot: 'mug' }] }
  const ids = carriedIds(prev, next)
  assert.deepEqual(ids, { mug_2: 'mug' })
  assert.deepEqual(carryChoices({ mug_2: { values: ['blue mug'] } }, ids, prev, next), { mug: { values: ['blue mug'] } })
  assert.equal(carriedIds(prev, { ...next, from: 'other' }), null)
})

test('repeated labels are numbered in order', () => {
  const s = (id: string, n: number) => ({ id, n, kind: 'person' as const, label: 'Friend', words: 'friend' })
  assert.deepEqual(numberRepeats([s('a', 1), s('b', 2)]).map(x => x.label), ['Friend 1', 'Friend 2'])
})

test('a list in the text is its list choice: same place and options, else the one with those options', () => {
  const list = (id: string, options: string[]) => ({ id, kind: 'pick' as const, label: id, source: 'list' as const, options })
  const choices = [{ id: 'w', kind: 'variants' as const, label: 'W', slot: 'w' }, list('list1', ['a', 'b']), list('list2', ['c', 'd'])]
  assert.equal(listChoiceAt([{ items: ['a', 'b'] }, { items: ['c', 'd'] }], choices, 2)?.id, 'list2')
  // A list typed before them: found by its options.
  assert.equal(listChoiceAt([{ items: ['x', 'y'] }, { items: ['a', 'b'] }, { items: ['c', 'd'] }], choices, 3)?.id, 'list2')
  // Just typed, or edited since it was read: none yet.
  assert.equal(listChoiceAt([{ items: ['x', 'y'] }], choices, 1), null)
  assert.equal(lineText({ values: ['summer', 'autumn'] }, true), 'summer, autumn')
  assert.equal(lineText({ values: ['a', 'b', 'c', 'd'] }, true), 'a, b, c +1')
})


test('a late More like these follows its slot through an edit, and is dropped when the slot is gone', () => {
  const two = {
    key: 'k1', choices: [{ id: 'mug', kind: 'variants', label: 'Mug' }, { id: 'mug_2', kind: 'variants', label: 'Mug' }],
    slots: [{ id: 'mug', n: 1, words: 'mug', ...ready }, { id: 'mug_2', n: 2, words: 'mug', ...ready }],
  } as any
  assert.equal(followId('mug', two, two), 'mug')
  // the first <mug> deleted: the survivor is `mug` now, and was `mug_2`
  const one = { key: 'k2', from: 'k1', choices: [{ id: 'mug', kind: 'variants', label: 'Mug' }],
                slots: [{ id: 'mug', n: 1, words: 'mug', was: 'mug_2', ...ready }] } as any
  assert.equal(followId('mug', two, one), null)       // the deleted slot's batch goes nowhere
  assert.equal(followId('mug_2', two, one), 'mug')    // the survivor's batch follows it
  const later = { ...one, key: 'k3', from: 'k2' }
  assert.equal(followId('mug_2', two, later), null)   // moved on further: dropped
  assert.equal(followId('mug', null, two), null)
})
