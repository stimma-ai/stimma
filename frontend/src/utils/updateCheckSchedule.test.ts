import assert from 'node:assert/strict'
import test from 'node:test'

import {
  CANARY_UPDATE_CHECK_INTERVAL_MS,
  DEFAULT_UPDATE_CHECK_INTERVAL_MS,
  updateCheckIntervalMs,
} from './updateCheckSchedule.ts'

test('canary checks for updates every 15 minutes', () => {
  assert.equal(updateCheckIntervalMs('canary'), CANARY_UPDATE_CHECK_INTERVAL_MS)
  assert.equal(updateCheckIntervalMs('CANARY'), 15 * 60 * 1000)
})

test('other channels retain the six-hour update cadence', () => {
  for (const channel of ['production', 'beta', 'sandbox', 'debug']) {
    assert.equal(updateCheckIntervalMs(channel), DEFAULT_UPDATE_CHECK_INTERVAL_MS)
  }
})
