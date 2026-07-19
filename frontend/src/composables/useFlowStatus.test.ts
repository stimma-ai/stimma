import assert from 'node:assert/strict'
import test from 'node:test'

import { deriveFlowStatusLabel } from '../utils/flowStatus.ts'

test('surfaces a missing tool ahead of downstream pending work', () => {
  assert.equal(
    deriveFlowStatusLabel('running', { waiting_for_tool: 1, pending: 2 }),
    'Tool unavailable',
  )
})

test('keeps an actionable human task ahead of tool unavailability', () => {
  assert.equal(
    deriveFlowStatusLabel('running', { awaiting_input: 1, waiting_for_tool: 1 }),
    'Your Turn',
  )
})

test('keeps failures ahead of tool unavailability', () => {
  assert.equal(
    deriveFlowStatusLabel('running', { failed: 1, waiting_for_tool: 1 }),
    'Error',
  )
})

test('continues to report ordinary pending work as running', () => {
  assert.equal(
    deriveFlowStatusLabel('running', { pending: 1 }),
    'Running',
  )
})
