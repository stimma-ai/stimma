import assert from 'node:assert/strict'
import test from 'node:test'
import { createLoadRetry } from './loadRetry.js'

function fakeClock() {
  const timers = []
  return {
    timers,
    schedule: (fn, delay) => { const t = { fn, delay, live: true }; timers.push(t); return t },
    cancel: (t) => { t.live = false },
    fire() { const t = timers.filter(x => x.live).at(-1); t.live = false; t.fn(); return t.delay },
  }
}

test('retries a failed load with growing delays until it succeeds', () => {
  const clock = fakeClock()
  let calls = 0
  const run = () => { calls++ }
  const retry = createLoadRetry(run, { delays: [1, 2, 3], schedule: clock.schedule, cancel: clock.cancel, hidden: () => false })
  retry.failed()
  assert.equal(clock.fire(), 1)
  retry.failed()
  assert.equal(clock.fire(), 2)
  retry.failed()
  retry.failed()
  assert.equal(clock.fire(), 3)
  assert.equal(calls, 3)
  retry.succeeded()
  assert.equal(clock.timers.some(t => t.live), false)
  // Success resets the backoff: the next failure waits the first delay again.
  retry.failed()
  assert.equal(clock.fire(), 1)
})

test('keeps one pending attempt and waits while the page is hidden', () => {
  const clock = fakeClock()
  let calls = 0
  const run = () => { calls++ }
  let isHidden = true
  const retry = createLoadRetry(run, { delays: [5], schedule: clock.schedule, cancel: clock.cancel, hidden: () => isHidden })
  retry.failed()
  retry.failed()
  assert.equal(clock.timers.filter(t => t.live).length, 1)
  clock.fire()
  assert.equal(calls, 0)
  isHidden = false
  clock.fire()
  assert.equal(calls, 1)
})

test('stop cancels the pending attempt', () => {
  const clock = fakeClock()
  let calls = 0
  const run = () => { calls++ }
  const retry = createLoadRetry(run, { schedule: clock.schedule, cancel: clock.cancel, hidden: () => false })
  retry.failed()
  retry.stop()
  assert.equal(clock.timers.some(t => t.live), false)
})
