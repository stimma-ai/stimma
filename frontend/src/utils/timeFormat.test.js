import { test } from 'node:test'
import assert from 'node:assert/strict'

// Pin the zone before any Date math so local-day boundaries are deterministic.
process.env.TZ = 'America/New_York'
const { formatMessageTime, formatFullTime, formatDate } = await import('./timeFormat.js')

// Fixtures are built in local time in the current year, and expectations use the
// machine's own locale, so the assertions hold on any locale and in any year.
const YEAR = new Date().getFullYear()
const NOW = new Date(YEAR, 10, 23, 15, 0).getTime()
const naiveUtc = date => date.toISOString().slice(0, -1) // the backend's format: no Z
const clock = date => date.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' })

test('naive UTC server time reads as UTC, shown in local time', () => {
  const sent = new Date(YEAR, 10, 23, 14, 42, 7)
  assert.equal(formatMessageTime(naiveUtc(sent), NOW), clock(sent))
  assert.equal(formatMessageTime(sent.toISOString(), NOW), clock(sent))
  // 14:42 ET is 19:42 UTC; reading the naive string as local would say 19:42.
  assert.equal(naiveUtc(sent).slice(11, 16), '19:42')
})

test('older messages carry the day', () => {
  const yesterday = new Date(YEAR, 10, 22, 9, 5)
  assert.equal(formatMessageTime(naiveUtc(yesterday), NOW), `Yesterday ${clock(yesterday)}`)
  const older = new Date(YEAR, 10, 20, 9, 5)
  assert.equal(formatMessageTime(naiveUtc(older), NOW), `${formatDate(older)}, ${clock(older)}`)
  const lastYear = new Date(YEAR - 1, 10, 20, 9, 5)
  const lastYearDate = lastYear.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })
  assert.equal(formatMessageTime(naiveUtc(lastYear), NOW), `${lastYearDate}, ${clock(lastYear)}`)
})

test('local midnight, not UTC midnight, splits days', () => {
  // 11:30 PM ET on the 22nd is already the 23rd in UTC.
  const late = new Date(YEAR, 10, 22, 23, 30)
  assert.equal(naiveUtc(late).slice(8, 10), '23')
  assert.equal(formatMessageTime(naiveUtc(late), NOW), `Yesterday ${clock(late)}`)
})

test('missing or bad values render nothing', () => {
  assert.equal(formatMessageTime(null, NOW), '')
  assert.equal(formatMessageTime('nope', NOW), '')
  assert.equal(formatFullTime(''), '')
  const sent = new Date(YEAR, 10, 23, 14, 42, 7)
  assert.equal(formatFullTime(naiveUtc(sent)), sent.toLocaleString(undefined, { dateStyle: 'full', timeStyle: 'medium' }))
})
