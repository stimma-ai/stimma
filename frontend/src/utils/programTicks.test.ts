import test from 'node:test'
import assert from 'node:assert/strict'
import { deletable, isLimited, pinsFor, ticksOf, toggleTick } from './programTicks.ts'

const car = { said: 'yellow ferrari' }
const plain = {}
const options = ['yellow ferrari', 'red lamborghini', 'silver porsche']

test("a choice that stands for the user's words shows only their words ticked", () => {
  assert.deepEqual([...ticksOf(car, undefined, options)], ['yellow ferrari'])
  assert.deepEqual([...ticksOf(car, [], options)], ['yellow ferrari'])
  assert.equal(isLimited(car, undefined, options), false)
  // any other choice shows nothing ticked: every option is drawn
  assert.deepEqual([...ticksOf(plain, undefined, options)], [])
})

test('ticking others widens it; going back to their words alone stores no pins', () => {
  const widened = toggleTick(car, undefined, options, 'red lamborghini')
  assert.deepEqual(widened, ['yellow ferrari', 'red lamborghini'])
  assert.equal(isLimited(car, widened, options), true)
  assert.deepEqual(toggleTick(car, widened, options, 'red lamborghini'), [])
  // unticking their words leaves only the others; unticking everything is their words again
  assert.deepEqual(toggleTick(car, widened, options, 'yellow ferrari'), ['red lamborghini'])
  assert.deepEqual(toggleTick(car, ['red lamborghini'], options, 'red lamborghini'), [])
  assert.deepEqual(toggleTick(car, undefined, options, 'yellow ferrari'), [])
  // "Use these choices" pinning their words is the same as the default
  assert.equal(isLimited(car, ['yellow ferrari'], options), false)
})

test('other choices tick as before', () => {
  assert.deepEqual(toggleTick(plain, undefined, options, 'silver porsche'), ['silver porsche'])
  assert.deepEqual(toggleTick(plain, ['silver porsche'], options, 'silver porsche'), [])
  assert.deepEqual(pinsFor(plain, ['silver porsche', 'yellow ferrari'], options), ['yellow ferrari', 'silver porsche'])
  assert.equal(isLimited(plain, ['gone'], options), false)  // pins the options no longer hold
})

test("their words can't be deleted; once gone from the options they aren't ticked", () => {
  assert.equal(deletable(car, 'yellow ferrari'), false)
  assert.equal(deletable(car, 'red lamborghini'), true)
  assert.equal(deletable(plain, 'yellow ferrari'), true)
  assert.deepEqual([...ticksOf(car, undefined, ['red lamborghini'])], [])
})
