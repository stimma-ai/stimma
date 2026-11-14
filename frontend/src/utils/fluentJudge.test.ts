import test from 'node:test'
import assert from 'node:assert/strict'
import { unjudgedNote } from './fluentJudge.ts'

test('Generation details notes an unchecked image, and only that', () => {
  assert.equal(unjudgedNote({ fix: { judge: 'v', rounds: [] } }, 'Fluent'), null)
  assert.equal(unjudgedNote({ draws: [] }, 'Fluent'), null)
  assert.equal(unjudgedNote(null, 'Fluent'), null)
  assert.equal(unjudgedNote({ fix: { skipped: 'unavailable' } }, 'Fluent'), 'Choices weren’t checked to fit together: Fluent wasn’t ready.')
})
