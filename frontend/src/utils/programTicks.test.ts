import test from 'node:test'
import assert from 'node:assert/strict'
import { defaultTicks, isLimited, stateFor, ticksOf, wireEdits } from './programTicks.ts'

const car = { said: 'yellow ferrari' }
const plain = {}
const cars = ['yellow ferrari', 'red lamborghini', 'silver porsche']
const six = ['a', 'b', 'c', 'd', 'e', 'f']
const clean = { pins: [], out: [], none: false }

/** The ticks a stored state reads back as. */
const read = (c: { said?: string }, s: { pins: string[]; out: string[]; none: boolean }, options: string[], standby?: Set<string>) =>
  [...ticksOf(c, s.pins, { out: s.out, none: s.none }, options, standby)]

test('everything starts ticked, and that stores nothing', () => {
  assert.deepEqual([...ticksOf(plain, undefined, undefined, six)], six)
  assert.deepEqual([...ticksOf(plain, [], {}, six)], six)
  assert.equal(isLimited(plain, undefined, undefined, six), false)
  assert.deepEqual(stateFor(plain, six, six), clean)
})

test('unticking one of many stores the one left out', () => {
  const s = stateFor(plain, ['a', 'b', 'd', 'e', 'f'], six)
  assert.deepEqual(s, { pins: [], out: ['c'], none: false })
  assert.deepEqual(read(plain, s, six), ['a', 'b', 'd', 'e', 'f'])
  assert.equal(isLimited(plain, s.pins, s, six), true)
})

test('"only" stores the one ticked as a pin', () => {
  const s = stateFor(plain, ['d'], six)
  assert.deepEqual(s, { pins: ['d'], out: [], none: false })
  assert.deepEqual(read(plain, s, six), ['d'])
})

test('ticking back to all is a clean state again', () => {
  const one = stateFor(plain, ['d'], six)
  assert.deepEqual(stateFor(plain, [...read(plain, one, six), 'a', 'b', 'c', 'e', 'f'], six), clean)
  const most = stateFor(plain, ['a', 'b', 'c', 'd', 'e'], six)
  assert.deepEqual(stateFor(plain, [...read(plain, most, six), 'f'], six), clean)
})

test('nothing ticked is stored as none, not as every value', () => {
  const s = stateFor(plain, [], six)
  assert.deepEqual(s, { pins: [], out: [], none: true })
  assert.deepEqual(read(plain, s, six), [])
  assert.equal(isLimited(plain, s.pins, s, six), true)
  // a choice with no options has nothing to leave out
  assert.deepEqual(stateFor(plain, [], []), clean)
})

test('the stored side switches at the half-way point, in the options order', () => {
  assert.deepEqual(stateFor(plain, ['c', 'a'], six), { pins: ['a', 'c'], out: [], none: false })
  assert.deepEqual(stateFor(plain, ['a', 'b', 'c'], six), { pins: ['a', 'b', 'c'], out: [], none: false })  // exactly half: pins
  assert.deepEqual(stateFor(plain, ['a', 'b', 'c', 'd'], six), { pins: [], out: ['e', 'f'], none: false })
  // a long list never stores more than half of itself
  const long = Array.from({ length: 2950 }, (_, i) => `v${i}`)
  const most = stateFor(plain, long.slice(3), long)
  assert.deepEqual(most.out, ['v0', 'v1', 'v2'])
  assert.equal(most.pins.length, 0)
  assert.equal(stateFor(plain, long.slice(0, 3), long).pins.length, 3)
})

test("a choice that stands for the user's words starts with only their words ticked", () => {
  assert.deepEqual([...ticksOf(car, undefined, undefined, cars)], ['yellow ferrari'])
  assert.equal(isLimited(car, undefined, undefined, cars), false)
  // ticking others widens it, as pins
  const widened = stateFor(car, ['yellow ferrari', 'red lamborghini'], cars)
  assert.deepEqual(widened, { pins: ['yellow ferrari', 'red lamborghini'], out: [], none: false })
  assert.equal(isLimited(car, widened.pins, widened, cars), true)
  // every option ticked is still pins, never "all"
  assert.deepEqual(stateFor(car, cars, cars), { pins: cars, out: [], none: false })
  // back to their words alone, or to nothing, is the same as never having ticked
  assert.deepEqual(stateFor(car, ['yellow ferrari'], cars), clean)
  assert.deepEqual(stateFor(car, [], cars), clean)
  assert.deepEqual(stateFor(car, ['red lamborghini'], cars), { pins: ['red lamborghini'], out: [], none: false })
  // a pin of only their words is the default; out and none never apply
  assert.equal(isLimited(car, ['yellow ferrari'], undefined, cars), false)
  assert.deepEqual([...ticksOf(car, undefined, { out: ['yellow ferrari'], none: true }, cars)], ['yellow ferrari'])
  // once their words are gone from the options, it is a plain choice
  assert.deepEqual([...ticksOf(car, undefined, undefined, ['red lamborghini'])], ['red lamborghini'])
})

test('stored values the options no longer hold are ignored', () => {
  assert.deepEqual([...ticksOf(plain, ['gone'], undefined, six)], six)
  assert.equal(isLimited(plain, ['gone'], undefined, six), false)
  assert.deepEqual([...ticksOf(plain, ['gone', 'b'], undefined, six)], ['b'])
  assert.deepEqual([...ticksOf(plain, undefined, { out: ['gone', 'b'] }, six)], ['a', 'c', 'd', 'e', 'f'])
  assert.equal(isLimited(plain, undefined, { out: ['gone'] }, six), false)
  assert.deepEqual(stateFor(plain, ['gone', 'a'], six), { pins: ['a'], out: [], none: false })
})

test('existing stored pins read as before', () => {
  assert.deepEqual([...ticksOf(plain, ['silver porsche'], undefined, cars)], ['silver porsche'])
  assert.deepEqual([...ticksOf(car, ['red lamborghini'], undefined, cars)], ['red lamborghini'])
})

test('standby values start unticked, and ticking one stores pins', () => {
  const ages = ['8', '12', '20', '30', '40', '50']
  const standby = new Set(['8', '12'])
  assert.deepEqual([...defaultTicks(plain, ages, standby)], ['20', '30', '40', '50'])
  assert.deepEqual([...ticksOf(plain, undefined, undefined, ages, standby)], ['20', '30', '40', '50'])
  assert.equal(isLimited(plain, undefined, undefined, ages, standby), false)
  assert.deepEqual(stateFor(plain, ['20', '30', '40', '50'], ages, standby), clean)
  // leaving one out counts against the values that start ticked
  const s = stateFor(plain, ['20', '30', '40'], ages, standby)
  assert.deepEqual(s, { pins: [], out: ['50'], none: false })
  assert.deepEqual(read(plain, s, ages, standby), ['20', '30', '40'])
  // a standby value is only drawn from a pin, however many are ticked
  const all = stateFor(plain, ages, ages, standby)
  assert.deepEqual(all, { pins: ages, out: [], none: false })
  assert.equal(isLimited(plain, all.pins, all, ages, standby), true)
})

test('the server reads values left out as removed, and nothing ticked as off', () => {
  assert.deepEqual(wireEdits({
    a: { add: ['x'], remove: ['r'], out: ['o', 'r'] },
    b: { none: true },
    c: { off: true, remove: ['r'] },
    d: {},
  }), {
    a: { add: ['x'], remove: ['r', 'o'] },
    b: { off: true },
    c: { remove: ['r'], off: true },
  })
  assert.deepEqual(wireEdits({}), {})
})
