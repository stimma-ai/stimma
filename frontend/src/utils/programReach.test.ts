import test from 'node:test'
import assert from 'node:assert/strict'
import { litSetting, reachOrder, reachSettings, ticksForSetting, type ChoiceReach } from './programReach.ts'
import { defaultTicks, stateFor, ticksOf } from './programTicks.ts'

const none: ReadonlySet<string> = new Set()
const eth = ['Korean', 'Irish', 'Scottish', 'Welsh', 'Italian', 'Greek']
const irish: ChoiceReach = { said: ['Irish'], fits: ['Irish', 'Scottish', 'Welsh'], any: eth }

test('a stated value offers Just, Similar and Any, in the choice\'s words', () => {
  const s = reachSettings(irish, eth, none)
  assert.deepEqual(s.map(x => [x.key, x.label, x.values.length]), [['said', 'Just Irish', 1], ['fits', 'Similar', 3], ['any', 'Any', 6]])
})

test('settings that draw the same values merge under the wider name; one left keeps the All row', () => {
  const narrowed: ChoiceReach = { fits: ['a', 'b'], any: ['a', 'b', 'c'], words: 'young' }
  assert.deepEqual(reachSettings(narrowed, ['a', 'b', 'c'], none).map(x => x.label), ['Young', 'Any'])
  assert.deepEqual(reachSettings({ fits: ['a', 'b'], any: ['a', 'b', 'c'] }, ['a', 'b', 'c'], none).map(x => x.label), ['What fits', 'Any'])
  assert.deepEqual(reachSettings({ said: ['x'], fits: ['x', 'y'], any: ['x', 'y'] }, ['x', 'y'], none).map(x => [x.key, x.label]), [['said', 'Just x'], ['any', 'Any']])
  assert.deepEqual(reachSettings({ fits: ['a', 'b'], any: ['a', 'b'] }, ['a', 'b'], none), [])
  assert.deepEqual(reachSettings(null, ['a'], none), [])
})

test('the lit setting is read from the ticks; anything else is yours', () => {
  const s = reachSettings(irish, eth, none)
  assert.equal(litSetting(s, new Set(['Irish'])), 'said')
  assert.equal(litSetting(s, new Set(['Welsh', 'Scottish', 'Irish'])), 'fits')
  assert.equal(litSetting(s, new Set(eth)), 'any')
  assert.equal(litSetting(s, new Set(['Irish', 'Greek'])), 'yours')
  assert.equal(litSetting(s, new Set()), 'none')
})

test('the user\'s own options and unplaced options never change the setting', () => {
  const own = new Set(['Atlantean'])
  const opts = [...eth, 'Atlantean', 'a writer seed']
  const s = reachSettings({ ...irish, any: [...eth, 'Atlantean'] }, opts, own)
  assert.ok(!s.some(x => x.values.includes('Atlantean')))
  assert.equal(litSetting(s, new Set(['Irish', 'Atlantean', 'a writer seed'])), 'said')
  // a setting keeps them as the user left them
  assert.deepEqual([...ticksForSetting(s, 'fits', new Set(['Irish', 'Atlantean']))].sort(), ['Atlantean', 'Irish', 'Scottish', 'Welsh'])
  assert.deepEqual([...ticksForSetting(s, 'said', new Set(eth))], ['Irish'])
})

test('each setting stores and reads back through the ticks, old saved ticks included', () => {
  const car = { said: 'Irish' }
  const s = reachSettings(irish, eth, none)
  for (const key of ['said', 'fits', 'any'] as const) {
    const state = stateFor(car, ticksForSetting(s, key, defaultTicks(car, eth)), eth)
    assert.equal(litSetting(s, ticksOf(car, state.pins, state, eth)), key)
  }
  assert.equal(litSetting(s, ticksOf(car, ['Irish', 'Greek'], {}, eth)), 'yours')
  // A narrowed choice starts on what fits: its rest stands by (drawn once ticked).
  const ages = ['18', '20', '25', '40', '60', '8']
  const young: ChoiceReach = { fits: ['18', '20', '25'], any: ['18', '20', '25', '40', '60'], words: 'young' }
  const standby = new Set(['40', '60', '8'])
  const a = reachSettings(young, ages, none)
  assert.equal(litSetting(a, ticksOf({}, [], {}, ages, standby)), 'fits')
  const wide = stateFor({}, ticksForSetting(a, 'any', defaultTicks({}, ages, standby)), ages, standby)
  assert.deepEqual(wide.pins, ['18', '20', '25', '40', '60'])   // never the value drawn only when asked for
  assert.equal(litSetting(a, ticksOf({}, wide.pins, wide, ages, standby)), 'any')
  // An open choice starts on Any, as before.
  const open: ChoiceReach = { fits: ['a', 'b', 'c'], any: ['a', 'b', 'c', 'd'] }
  const o = reachSettings(open, ['a', 'b', 'c', 'd'], none)
  assert.equal(litSetting(o, ticksOf({}, [], {}, ['a', 'b', 'c', 'd'])), 'any')
  const fits = stateFor({}, ticksForSetting(o, 'fits', new Set(['a', 'b', 'c', 'd'])), ['a', 'b', 'c', 'd'])
  assert.deepEqual(fits, { pins: [], out: ['d'], none: false })
})

test('the list leads with your own, then what you said, what fits, and the rest after the line', () => {
  const own = new Set(['mine'])
  const opts = ['Korean', 'Scottish', 'Irish', 'Greek', 'mine', 'Welsh']
  assert.deepEqual(reachOrder(opts, irish, own), { inside: ['mine', 'Irish', 'Scottish', 'Welsh'], beyond: ['Korean', 'Greek'] })
  assert.deepEqual(reachOrder(opts, { any: opts }, own), { inside: opts, beyond: [] })
  assert.deepEqual(reachOrder(['x', 'y'], { said: ['x'], any: ['x', 'y'] }, none), { inside: ['x'], beyond: ['y'] })
})
