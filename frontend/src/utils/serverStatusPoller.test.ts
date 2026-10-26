import assert from 'node:assert/strict'
import test from 'node:test'

import {
  ACTIVE_STATUS_POLL_MS,
  IDLE_STATUS_POLL_MS,
  createStatusPoller,
  statusPollDelay,
  type PollTimers,
} from './serverStatusPoller.ts'
import { serverOperationResult, type ServerOperation } from './serverUpdateState.ts'

/** A virtual clock: timers fire only when the test advances time. */
function virtualClock() {
  let now = 0
  let nextId = 1
  const pending = new Map<number, { at: number, callback: () => void }>()
  const flush = async () => { for (let i = 0; i < 10; i++) await Promise.resolve() }
  const timers: PollTimers = {
    set(callback, ms) { const id = nextId++; pending.set(id, { at: now + ms, callback }); return id },
    clear(handle) { pending.delete(handle as number) },
  }
  async function advance(ms: number) {
    const end = now + ms
    await flush()
    for (;;) {
      const due = [...pending.entries()].filter(([, t]) => t.at <= end).sort((a, b) => a[1].at - b[1].at)[0]
      if (!due) break
      pending.delete(due[0])
      now = due[1].at
      due[1].callback()
      await flush()
    }
    now = end
  }
  return { timers, advance, flush, get now() { return now } }
}

test('poll cadence is fast only while active and suspended in background or offline', () => {
  assert.equal(statusPollDelay({ active: true, foreground: true, online: true }), ACTIVE_STATUS_POLL_MS)
  assert.equal(statusPollDelay({ active: false, foreground: true, online: true }), IDLE_STATUS_POLL_MS)
  assert.equal(statusPollDelay({ active: true, foreground: false, online: true }), null)
  assert.equal(statusPollDelay({ active: true, foreground: true, online: false }), null)
  assert.ok(IDLE_STATUS_POLL_MS >= 5 * 60_000)
})

test('an idle connected client does not poll server status every few seconds', async () => {
  const clock = virtualClock()
  let calls = 0
  const poller = createStatusPoller({ refresh: async () => { calls++ }, isActive: () => false, timers: clock.timers })
  poller.wake()
  await clock.advance(5 * 60_000)
  assert.equal(calls, 1, 'only the initial refresh in five idle minutes')
  await clock.advance(IDLE_STATUS_POLL_MS)
  assert.equal(calls, 2, 'a slow backstop refresh still runs')
  poller.stop()
})

test('an active update polls quickly through a restart and settles back to idle', async () => {
  const clock = virtualClock()
  // The server keeps answering "ready" on the old version briefly, then
  // downloads, disappears while restarting, and returns on the new version.
  const timeline: Array<{ until: number, status?: { status: string, version: string } }> = [
    { until: 4_000, status: { status: 'ready', version: '1.0.0' } },
    { until: 10_000, status: { status: 'downloading', version: '1.0.0' } },
    { until: 20_000 },
    { until: Infinity, status: { status: 'ready', version: '1.1.0' } },
  ]
  let op: ServerOperation | null = { deviceId: 'server', name: 'Server', action: 'update', startedAt: 0,
    fromVersion: '1.0.0', targetVersion: '1.1.0', sawTransition: false, updateMachine: false, machineTarget: null }
  let calls = 0
  const poller = createStatusPoller({
    isActive: () => op !== null,
    timers: clock.timers,
    refresh: async () => {
      calls++
      const status = timeline.find(step => clock.now < step.until)!.status
      if (!status) throw new Error('server restarting')
      if (!op) return
      if (status.status !== 'ready') { op.sawTransition = true; return }
      if (serverOperationResult(op, status) !== 'pending') op = null
    },
  })
  poller.wake()
  await clock.advance(30_000)
  assert.equal(op, null, 'the update reached its terminal state')
  const activeCalls = calls
  assert.ok(activeCalls >= 7, `polled quickly while active (${activeCalls})`)
  await clock.advance(5 * 60_000)
  assert.equal(calls, activeCalls, 'returned to the idle cadence once complete')
  poller.stop()
})

test('a restart that comes back as the same version completes from process identity', async () => {
  const clock = virtualClock()
  let op: ServerOperation | null = { deviceId: 'server', name: 'Server', action: 'restart', startedAt: 0,
    fromVersion: '1.0.0', targetVersion: null, fromStartedAt: 10, sawTransition: false,
    updateMachine: false, machineTarget: null }
  const poller = createStatusPoller({
    isActive: () => op !== null,
    timers: clock.timers,
    refresh: async () => {
      if (!op) return
      const status = clock.now < 6_000 ? { status: 'ready', serverStartedAt: 10 } : { status: 'ready', serverStartedAt: 11 }
      if (serverOperationResult(op, status) === 'complete') op = null
    },
  })
  poller.wake()
  await clock.advance(10_000)
  assert.equal(op, null)
  poller.stop()
})

test('backgrounding suspends polling and returning refreshes once', async () => {
  const clock = virtualClock()
  let calls = 0
  const poller = createStatusPoller({ refresh: async () => { calls++ }, isActive: () => true, timers: clock.timers })
  poller.wake()
  await clock.flush()
  assert.equal(calls, 1)
  poller.setForeground(false)
  await clock.advance(IDLE_STATUS_POLL_MS * 2)
  poller.wake() // Events while hidden must not reach the network either.
  await clock.advance(ACTIVE_STATUS_POLL_MS * 10)
  assert.equal(calls, 1, 'no requests while backgrounded')
  poller.setForeground(true)
  await clock.flush()
  assert.equal(calls, 2, 'one catch-up refresh on return')
  await clock.advance(ACTIVE_STATUS_POLL_MS)
  assert.equal(calls, 3, 'the active cadence resumes')
  poller.stop()
})

test('offline suspends polling until the network returns', async () => {
  const clock = virtualClock()
  let calls = 0
  const poller = createStatusPoller({ refresh: async () => { calls++ }, isActive: () => false,
    timers: clock.timers, online: false })
  poller.wake()
  await clock.advance(IDLE_STATUS_POLL_MS * 2)
  assert.equal(calls, 0)
  poller.setOnline(true)
  await clock.flush()
  assert.equal(calls, 1)
  poller.setForeground(false)
  poller.setOnline(false)
  poller.setOnline(true)
  await clock.flush()
  assert.equal(calls, 1, 'still backgrounded')
  poller.stop()
})

test('becoming active switches to the fast cadence without waiting out the idle timer', async () => {
  const clock = virtualClock()
  let calls = 0
  let active = false
  const poller = createStatusPoller({ refresh: async () => { calls++ }, isActive: () => active, timers: clock.timers })
  poller.wake()
  await clock.advance(60_000)
  assert.equal(calls, 1)
  active = true
  poller.reschedule()
  await clock.advance(ACTIVE_STATUS_POLL_MS)
  assert.equal(calls, 2)
  poller.stop()
})

test('a wake during an in-flight refresh runs one follow-up instead of overlapping', async () => {
  const clock = virtualClock()
  let calls = 0
  let inFlight = 0
  let release: () => void = () => {}
  const poller = createStatusPoller({
    isActive: () => false,
    timers: clock.timers,
    refresh: () => {
      calls++
      inFlight++
      assert.equal(inFlight, 1)
      return new Promise<void>(resolve => { release = () => { inFlight--; resolve() } })
    },
  })
  poller.wake()
  poller.wake()
  poller.wake()
  assert.equal(calls, 1)
  release()
  await clock.flush()
  assert.equal(calls, 2)
  release()
  await clock.flush()
  assert.equal(calls, 2)
  poller.stop()
})
