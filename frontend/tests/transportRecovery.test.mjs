import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { createTransportRecovery, RECOVERY_PHASES } from '../src/utils/transportRecovery.js'

const contract = JSON.parse(readFileSync(new URL('../../mobile/contract/transport-recovery.json', import.meta.url), 'utf8'))

function fixture() {
  let now = 0, id = 0, state = { status: null }
  const timers = new Map()
  const recovery = createTransportRecovery({
    changed: value => { state = value },
    schedule: (fn, delay) => { timers.set(++id, { fn, at: now + delay }); return id },
    cancel: handle => timers.delete(handle),
  })
  const ready = []
  recovery.onReady(epoch => ready.push(epoch))
  return {
    recovery, ready,
    get state() { return state },
    native: (generation, phase) => recovery.nativeState({ generation, phase, budgetMs: contract.budgetsMs[phase] ?? 0 }),
    advance(ms) {
      const end = now + ms
      for (;;) {
        const next = [...timers].filter(([, timer]) => timer.at <= end).sort((a, b) => a[1].at - b[1].at)[0]
        if (!next) break
        timers.delete(next[0]); now = next[1].at; next[1].fn()
      }
      now = end
    },
  }
}

const settled = promise => promise.then(() => 'sent', error => error.message)

test('the page follows the phases and budgets the native contract defines', () => {
  assert.equal(contract.event, 'stimma:transport-state')
  assert.deepEqual(Object.keys(RECOVERY_PHASES).sort(), Object.keys(contract.phases).sort())
  for (const [phase, { holdRequests }] of Object.entries(contract.phases)) {
    assert.equal(RECOVERY_PHASES[phase].holdRequests, holdRequests, phase)
  }
})

test('a check holds requests for the native budget, not a fixed two seconds, and releases them once', async () => {
  const f = fixture()
  f.native(1, 'ready')
  f.recovery.suspend(); f.recovery.resume()
  f.native(2, 'checking')
  let sent = 0
  const write = f.recovery.wait().then(() => sent++)
  f.advance(contract.budgetsMs.checking - 100)
  assert.equal(sent, 0)
  f.native(2, 'ready')
  await write
  assert.equal(sent, 1)
  assert.deepEqual(f.ready, [1])
})

test('a short outage stays quiet; a slower check, reconnecting and unavailable are visible', () => {
  const f = fixture()
  f.native(1, 'ready')
  f.native(2, 'checking')
  f.advance(900)
  assert.equal(f.state.status, null, 'a quick check does not flash a banner')
  f.advance(200)
  assert.equal(f.state.status, 'reconnecting')
  f.native(2, 'reconnecting')
  assert.equal(f.state.status, 'reconnecting')
  f.native(2, 'unavailable')
  assert.equal(f.state.status, 'unavailable')
  f.native(2, 'ready')
  assert.equal(f.state.status, null)
})

test('a long outage holds through reconnecting, then fails fast without replaying anything', async () => {
  const f = fixture()
  f.native(1, 'ready')
  f.native(2, 'checking')
  const held = settled(f.recovery.wait())
  f.advance(3000)
  // A new phase brings its own budget, measured from when it began.
  f.native(2, 'reconnecting')
  f.advance(contract.budgetsMs.reconnecting - 1000)
  f.native(2, 'unavailable')
  assert.match(await held, /Still reconnecting/)
  assert.match(await settled(f.recovery.wait()), /Still reconnecting/, 'new requests fail fast while unavailable')
  assert.equal(f.recovery.admitsSocket, false)
  f.native(2, 'ready')
  assert.equal(await settled(f.recovery.wait()), 'sent')
  assert.deepEqual(f.ready, [1], 'one recovery, one ready')
})

test('a stale or repeated state cannot announce a recovery twice, and older shell events are ignored', () => {
  const f = fixture()
  f.native(3, 'ready')
  f.native(4, 'checking')
  f.native(3, 'ready')
  assert.equal(f.recovery.snapshot().phase, 'checking', 'an older generation cannot declare the new one ready')
  assert.deepEqual(f.ready, [])
  f.native(4, 'ready')
  f.native(4, 'ready')
  f.recovery.legacyResumed()
  f.recovery.legacyConnection('connecting')
  assert.deepEqual(f.ready, [1])
  assert.equal(f.recovery.admitsSocket, true)
})

test('a ready state from before the app left is confirmed before the socket is replaced', () => {
  const f = fixture()
  f.native(1, 'ready')
  f.recovery.suspend(); f.recovery.resume()
  assert.equal(f.recovery.admitsSocket, false)
  // The shell reports the same state: nothing needed checking (a dev-server page).
  f.native(1, 'ready')
  assert.deepEqual(f.ready, [1])
  f.recovery.suspend(); f.recovery.resume()
  // No answer at all: taken at its word after the grace period.
  f.advance(2000)
  assert.deepEqual(f.ready, [1, 2])
})

test('older shells keep the fixed grace window and replace the socket on every resume', async () => {
  const f = fixture()
  f.recovery.legacyConnection('connecting')
  const held = settled(f.recovery.wait())
  f.advance(1999)
  assert.equal(f.state.status, null)
  f.advance(1)
  assert.match(await held, /Still reconnecting/)
  assert.equal(f.state.status, 'reconnecting')
  f.recovery.legacyResumed()
  f.recovery.socket(true)
  assert.equal(f.state.status, null)
  f.recovery.legacyResumed()
  assert.equal(f.ready.length, 2)
})

test('a profile change cancels held reads; backgrounding cancels everything unsent', async () => {
  const f = fixture()
  f.native(1, 'ready')
  f.native(2, 'checking')
  const switched = settled(f.recovery.wait())
  f.recovery.invalidate()
  assert.match(await switched, /workspace changed/)
  const asleep = settled(f.recovery.wait())
  f.recovery.suspend()
  assert.match(await asleep, /background/)
  assert.equal(f.state.status, null, 'nothing is shown while in the background')
})
