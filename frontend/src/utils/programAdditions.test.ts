import assert from 'node:assert/strict'
import test from 'node:test'

import { additionList, isOwnOption } from './programAdditions.ts'

test('a choice keeps additions under its list, the pools naming it first', () => {
  assert.equal(additionList({ cls: 'person.eye_colour' }, { cls: 'person.eye_color' }), 'person.eye_color')
  assert.equal(additionList({ cls: 'person.hairstyle' }, null), 'person.hairstyle')
  assert.equal(additionList({}, null), null)
})

test('the user\'s own options: added here, or kept for the list', () => {
  const braid = 'a messy fishtail braid'
  assert.ok(isOwnOption(braid, { add: [braid] }, null))
  assert.ok(isOwnOption(braid, {}, { mine: [braid] }))
  assert.ok(!isOwnOption('a bob', { add: [braid] }, { mine: [braid] }))
  assert.ok(!isOwnOption(braid, undefined, undefined))
})
