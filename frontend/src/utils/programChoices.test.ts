import test from 'node:test'
import assert from 'node:assert/strict'
import {
  asWrittenState, changedCount, cleanState, drawable, isAsWritten, isChanged, leaveOut, numberRepeats, optionsOf, pillsOf, pillValue,
  isOff, resetState, swatchesOf, toggleToken, tokenText, turnOn, zonesOf, PALETTE_CLS,
} from './programChoices.ts'
import type { ChoicePool, ProgramChoice, ProgramChoices, ProgramSlot } from './programWire.ts'

const pet: ProgramChoice = {
  id: 'pet', slot: 'pet', kind: 'pick', label: 'Pet', options: ['pet', 'tabby cat'],
  zones: [{ id: 'kinds', title: 'Kinds of pet' }, { id: 'instead', title: 'Instead of pet' }],
}
const petPool: ChoicePool = {
  options: ['pet', 'tabby cat', 'basset hound', 'gray parrot', 'mug of coffee', 'stack of books'],
  zones: { kinds: ['pet', 'tabby cat', 'basset hound', 'gray parrot'], instead: ['mug of coffee', 'stack of books'] },
  short: { 'basset hound': 'basset' },
}
const hair: ProgramChoice = { id: 'man.hair', slot: 'man', kind: 'pick', label: 'Hair', options: ['buzz cut'] }
const hairPool: ChoicePool = {
  options: ['buzz cut', 'crew cut', 'man bun', 'long waves'],
  groups: { length: { short: ['buzz cut', 'crew cut'], long: ['man bun', 'long waves'] }, style: { tied: ['man bun'] } },
}

test('nothing chosen draws from the default zone; "Any X" and the default zone alone store nothing', () => {
  assert.deepEqual([...drawable(pet, petPool, null)!], ['pet', 'tabby cat', 'basset hound', 'gray parrot'])
  assert.equal(cleanState(pet, { zones: ['kinds'] }), null)
  assert.equal(cleanState(hair, { zones: ['all'] }), null)
  assert.equal(cleanState(pet, { values: [], groups: { length: [] } }), null)
  assert.deepEqual(cleanState(pet, { zones: ['kinds', 'instead'] }), { zones: ['kinds', 'instead'] })
  assert.deepEqual(cleanState(pet, { zones: ['kinds'], values: ['mug of coffee'] }), { values: ['mug of coffee'], zones: ['kinds'] })
})

test('choosing adds: options, groups with every member, zones', () => {
  let s = toggleToken(pet, null, { kind: 'value', value: 'basset hound' })
  s = toggleToken(pet, s, { kind: 'zone', zone: 'instead' })
  assert.deepEqual([...drawable(pet, petPool, s)!].sort(), ['basset hound', 'mug of coffee', 'stack of books'])
  const g = toggleToken(hair, null, { kind: 'group', facet: 'style', part: 'tied' })
  assert.deepEqual([...drawable(hair, hairPool, g)!], ['man bun'])
  // Clicking again takes it back out; the last one out is no choice at all.
  assert.equal(toggleToken(hair, g, { kind: 'group', facet: 'style', part: 'tied' }), null)
})

test('left out replaces what is chosen; choosing again brings it back', () => {
  const s = leaveOut({ values: ['tabby cat'], add: ['three-legged greyhound'] })
  assert.deepEqual(s, { off: true, add: ['three-legged greyhound'] })
  assert.equal(drawable(pet, petPool, s), null)
  assert.ok(isChanged(s))
  assert.deepEqual(toggleToken(pet, s, { kind: 'value', value: 'pet' }), { values: ['pet'], add: ['three-legged greyhound'] })
})

test('reset keeps the user’s own options in the list', () => {
  assert.deepEqual(resetState({ values: ['x'], add: ['x'] }), { add: ['x'] })
  assert.equal(resetState({ values: ['x'] }), null)
  assert.ok(!isChanged({ add: ['x'] }))
})

test('own options lead the first zone, before the pool arrives too', () => {
  assert.deepEqual(zonesOf(pet, null, { add: ['dragon'] }).map(z => z.options), [['dragon', 'pet', 'tabby cat'], []])
  assert.deepEqual(optionsOf(pet, { ...petPool, mine: ['axolotl'] }, { add: ['dragon'] }).slice(0, 3), ['dragon', 'axolotl', 'pet'])
})

const slotPet: ProgramSlot = { id: 'pet', n: 2, kind: 'free', label: 'Pet', words: 'pet', details: ['pet'] }

test('a long list comes whole with the prompt; its pool adds only what it lacks', () => {
  const faces = Array.from({ length: 500 }, (_, i) => `face ${i}`)
  const face: ProgramChoice = { id: 'man.face', slot: 'man', kind: 'pick', label: 'Face', cls: 'person.face', options: faces }
  const got = optionsOf(face, { options: ['a face of my own'] })
  assert.equal(got.length, 501)
  assert.equal(got[0], 'a face of my own')
  // A short list's pool is what it draws from now.
  assert.deepEqual(optionsOf(hair, hairPool), hairPool.options)
})

test('as written draws the slot’s own words', () => {
  const s = asWrittenState(slotPet)
  assert.ok(isAsWritten(slotPet, s))
  assert.equal(pillValue(pet, petPool, s, slotPet), 'as written')
  assert.ok(!isAsWritten(slotPet, { values: ['pet', 'tabby cat'] }))
})

test('a pill says the value short, or how many', () => {
  assert.equal(pillValue(pet, petPool, { values: ['basset hound'] }), 'basset')
  assert.equal(pillValue(pet, petPool, { values: ['basset hound', 'gray parrot'] }), 'basset +1')
  assert.equal(pillValue(hair, hairPool, { groups: { length: ['short'] } }), 'short')
  assert.equal(pillValue(pet, petPool, { zones: ['instead'] }), 'Instead of pet')
  assert.equal(pillValue(pet, petPool, { zones: ['instead'], values: ['pet'] }), '2 chosen')
  assert.equal(tokenText(hair, hairPool, { kind: 'group', facet: 'length', part: 'short' }), 'any short')
  // Color placeholders read as the app shows them; no word rewriting.
  assert.equal(pillValue(hair, null, { values: ['a {main} parka'] }), 'a parka')
})

test('a palette reads as swatches only when every color is known', () => {
  assert.equal(swatchesOf('burgundy, cream and charcoal')?.length, 3)
  assert.equal(swatchesOf('burgundy and a color nobody named'), null)
})

// A person, a free slot and the user's own list.
const man: ProgramSlot = {
  id: 'man', n: 1, kind: 'person', label: 'Young man', words: 'young man',
  details: ['man.age', 'man.hair', 'man.build', 'man.outfit', 'man.outfit.colors'], stated: { age: 'young' },
}
const light: ProgramSlot = { id: 'light', n: 3, kind: 'light', label: 'Light', words: 'light', details: ['light'] }
const ch = (id: string, label: string, extra: Partial<ProgramChoice> = {}): ProgramChoice => ({ id, kind: 'pick', label, options: [], ...extra })
const choices: ProgramChoice[] = [
  ch('man.age', 'Age', { slot: 'man' }), hair, ch('man.build', 'Build', { slot: 'man' }), ch('man.outfit', 'Outfit', { slot: 'man' }),
  ch('man.outfit.colors', 'Colors', { slot: 'man', follows: 'man.outfit', cls: PALETTE_CLS }),
  pet, ch('light', 'Light', { slot: 'light' }), ch('list1', 'Season', { source: 'list', options: ['summer', 'autumn'] }),
]
const world = (states: ProgramChoices) => ({ slots: [light, slotPet, man], choices, states, pools: { pet: petPool } })

test('every slot has a pill, in prompt order, and each list one; untouched ones show only their label', () => {
  const pills = pillsOf(world({}))
  assert.deepEqual(pills.map(p => [p.label, p.value, p.changed]), [
    ['Young man', '', false], ['Pet', '', false], ['Light', '', false], ['Season', '', false],
  ])
  assert.deepEqual(pills[0].open, { slot: 'man' })
  assert.deepEqual(pills[3].open, { choice: 'list1' })
})

test('a person’s chosen details are pills of their own, folding into one at three', () => {
  const two = pillsOf(world({ 'man.hair': { values: ['buzz cut'] }, 'man.outfit.colors': { values: ['navy, white and gray'] } }))
  assert.deepEqual(two.slice(0, 3).map(p => [p.label, p.value]), [['Young man', ''], ['Hair', 'buzz cut'], ['Colors', 'navy, white and gray']])
  assert.equal(two[2].swatches?.length, 3)
  assert.deepEqual(two[1].open, { choice: 'man.hair' })
  const three = pillsOf(world({ 'man.hair': { values: ['buzz cut'] }, 'man.age': { values: ['24-year-old'] }, 'man.build': { off: true } }))
  assert.deepEqual([three[0].label, three[0].value, three[0].folded], ['Young man', '24-year-old, buzz cut, no build', true])
  assert.equal(three[1].label, 'Pet')
  assert.ok(three[0].resets.includes('man.outfit.colors'))
})

test('left out reads "No light"; a person with every detail off is as written', () => {
  const pills = pillsOf(world({ light: { off: true } }))
  assert.deepEqual(pills.find(p => p.id === 'light')!.label, 'No light')
  const off = Object.fromEntries(man.details.map(id => [id, { off: true }]))
  assert.deepEqual(pillsOf(world(off)).slice(0, 2).map(p => [p.label, p.value]), [['Young man', 'as written'], ['Pet', '']])
})

test('Reset counts each changed choice', () => {
  assert.equal(changedCount(world({ light: { off: true } })), 1)
  assert.equal(changedCount(world({ light: { off: true }, 'man.hair': { values: ['buzz cut'] } })), 2)
  assert.equal(changedCount(world({ 'man.hair': { add: ['mohawk'] } })), 0)
})

test('two people say whose detail a pill is', () => {
  const woman: ProgramSlot = { id: 'woman', n: 4, kind: 'person', label: 'Old woman', words: 'old woman', details: ['woman.hair'] }
  const pills = pillsOf({ ...world({ 'man.hair': { values: ['buzz cut'] } }), slots: [man, woman], choices: [...choices, ch('woman.hair', 'Hair', { slot: 'woman' })] })
  assert.equal(pills[1].label, 'Young man’s hair')
})

test('the same words twice read as two, numbered in order', () => {
  const slot = (id: string, n: number, label: string) => ({ id, n, kind: 'person' as const, label, words: label.toLowerCase(), details: [] })
  const out = numberRepeats([slot('friend', 1, 'Friend'), slot('dog', 2, 'Dog'), slot('friend_2', 3, 'Friend')])
  assert.deepEqual(out.map(s => s.label), ['Friend 1', 'Dog', 'Friend 2'])
})

test('a face starts left out: untouched it draws nothing; Any, a value or a group turns it on; leave out goes back', () => {
  const face: ProgramChoice = { id: 'man.face', slot: 'man', kind: 'pick', label: 'Face', options: ['a small nose', 'freckles'], starts_off: true }
  assert.equal(isOff(face, null), true)
  assert.equal(drawable(face, null, null), null)
  assert.equal(pillValue(face, null, null), '')
  assert.deepEqual(cleanState(face, turnOn(null)), { on: true })
  assert.equal(isOff(face, { on: true }), false)
  assert.deepEqual([...drawable(face, null, { on: true })!], ['a small nose', 'freckles'])
  const picked = toggleToken(face, null, { kind: 'value', value: 'freckles' })
  assert.deepEqual(picked, { values: ['freckles'] })
  assert.equal(isOff(face, picked), false)
  assert.equal(leaveOut(picked, face), null)
  assert.equal(cleanState(face, { off: true }), null)
  assert.deepEqual(cleanState(face, { off: true, add: ['scar'] }), { add: ['scar'] })
  assert.equal(isOff(face, { add: ['scar'] }), true)
  // Untouched, the person's pill doesn't count it as changed or as written.
  const all = [...choices, face]
  const slot = { ...man, details: [...man.details, 'man.face'] }
  const w = (states: ProgramChoices) => ({ slots: [light, slotPet, slot], choices: all, states, pools: { pet: petPool } })
  assert.deepEqual(pillsOf(w({}))[0].value, '')
  assert.equal(changedCount(w({})), 0)
  const off = Object.fromEntries(man.details.map(id => [id, { off: true }]))
  assert.equal(pillsOf(w(off))[0].value, 'as written')
  assert.deepEqual(pillsOf(w({ 'man.face': { on: true } })).map(p => p.label).slice(0, 2), ['Young man', 'Face'])
})

test('a slot still being read shows as reading; one that couldn’t be read went in as written', () => {
  const reading: ProgramSlot = { id: 'lamp', n: 1, kind: 'free', label: 'lamp', words: 'lamp', details: [], state: 'reading' }
  const written: ProgramSlot = { id: 'rug', n: 2, kind: 'free', label: 'rug', words: 'rug', details: [], state: 'ready', degraded: true }
  const pills = pillsOf({ slots: [reading, written], choices: [], states: {}, pools: {} })
  assert.deepEqual(pills.map(p => [p.label, p.value, p.pending, p.changed]), [
    ['lamp', '', 'reading', false], ['rug', 'as written', 'written', false],
  ])
})
