import assert from 'node:assert/strict'
import test from 'node:test'

import { equationHasUnavailableTool } from './useFlowGrouping.ts'
import type { FlowEquation } from './useFlowsApi.ts'

function equation(
  equationKey: string,
  status: string,
  dependencies: string[] = [],
): FlowEquation {
  return {
    equation_key: equationKey,
    equation_type: 'tool_call',
    status,
    phase_path: [],
    attempt: 0,
    result_media_ids: [],
    dependencies,
  }
}

test('identifies an equation parked on an unavailable tool', () => {
  const unavailable = equation('tool$0', 'waiting_for_tool')
  const all = new Map([[unavailable.equation_key, unavailable]])

  assert.equal(equationHasUnavailableTool(unavailable, all), true)
})

test('carries tool unavailability through downstream pending equations', () => {
  const unavailable = equation('tool$0', 'waiting_for_tool')
  const second = equation('tool$1', 'pending', ['tool$0'])
  const third = equation('tool$2', 'pending', ['tool$1'])
  const all = new Map([unavailable, second, third].map((eq) => [eq.equation_key, eq]))

  assert.equal(equationHasUnavailableTool(second, all), true)
  assert.equal(equationHasUnavailableTool(third, all), true)
})

test('does not misclassify ordinary upstream work as unavailable', () => {
  const running = equation('tool$0', 'computing')
  const pending = equation('tool$1', 'pending', ['tool$0'])
  const all = new Map([running, pending].map((eq) => [eq.equation_key, eq]))

  assert.equal(equationHasUnavailableTool(pending, all), false)
})
