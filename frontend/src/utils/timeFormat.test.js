import { test } from 'node:test'
import assert from 'node:assert/strict'

// Pin the zone before any Date math so local-day boundaries are deterministic.
process.env.TZ = 'America/New_York'
const { formatMessageTime, formatFullTime } = await import('./timeFormat.js')

const NOW = Date.parse('2026-11-23T20:00:00Z') // 3:00 PM ET

test('naive UTC server time reads as UTC, shown in local time', () => {
  assert.equal(formatMessageTime('2026-11-23T19:42:07.123456', NOW), '2:42 PM')
  assert.equal(formatMessageTime('2026-11-23T19:42:07Z', NOW), '2:42 PM')
})

test('older messages carry the day', () => {
  assert.equal(formatMessageTime('2026-11-22T14:05:00', NOW), 'Yesterday 9:05 AM')
  assert.equal(formatMessageTime('2026-11-20T14:05:00', NOW), 'Nov 20, 9:05 AM')
  assert.equal(formatMessageTime('2025-11-20T14:05:00', NOW), 'Nov 20, 2025, 9:05 AM')
})

test('local midnight, not UTC midnight, splits days', () => {
  // 11:30 PM ET on the 22nd is already the 23rd in UTC.
  assert.equal(formatMessageTime('2026-11-23T04:30:00', NOW), 'Yesterday 11:30 PM')
})

test('missing or bad values render nothing', () => {
  assert.equal(formatMessageTime(null, NOW), '')
  assert.equal(formatMessageTime('nope', NOW), '')
  assert.equal(formatFullTime(''), '')
  assert.match(formatFullTime('2026-11-23T19:42:07'), /November 23, 2026.*2:42:07\sPM/)
})
