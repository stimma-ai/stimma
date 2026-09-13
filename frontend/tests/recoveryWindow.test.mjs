import assert from 'node:assert/strict'
import test from 'node:test'
import { createRecoveryWindow } from '../src/utils/recoveryWindow.js'

function fixture() {
  let now = 0, state, id = 0
  const timers = new Map()
  const gate = createRecoveryWindow({
    changed: value => { state = value },
    schedule: (fn, delay) => { timers.set(++id, { fn, at: now + delay }); return id },
    cancel: id => timers.delete(id),
  })
  return { gate, get state() { return state }, advance(ms) {
    now += ms
    for (const [id, timer] of [...timers]) if (timer.at <= now) { timers.delete(id); timer.fn() }
  } }
}

test('ten seconds asleep does not consume the two-second foreground grace', async () => {
  const f = fixture()
  f.gate.suspend(); f.advance(10000); f.gate.resume()
  let sent = 0
  const action = f.gate.wait().then(() => sent++)
  f.advance(1999)
  assert.equal(f.state.visible, false)
  assert.equal(sent, 0)
  f.gate.setReady(true)
  await action
  assert.equal(sent, 1)
  f.advance(5000)
  assert.equal(f.state.visible, false)
})

test('repeated reconnect attempts share a deadline; expired writes never dispatch later', async () => {
  const f = fixture()
  f.gate.setReady(false)
  const action = assert.rejects(f.gate.wait(), /Still reconnecting/)
  f.advance(1500); f.gate.setReady(false); f.advance(500)
  await action
  assert.equal(f.state.visible, true)
  await assert.rejects(f.gate.wait(), /Still reconnecting/)
  f.gate.setReady(true)
  assert.equal(f.state.visible, false)
})

test('abort, profile change, and a second sleep cancel unsent work', async () => {
  const f = fixture()
  f.gate.setReady(false)
  const controller = new AbortController()
  const aborted = assert.rejects(f.gate.wait(controller.signal), { name: 'AbortError' })
  controller.abort(); await aborted
  const switched = assert.rejects(f.gate.wait(), /workspace changed/)
  f.gate.invalidate(); await switched
  const asleep = assert.rejects(f.gate.wait(), /background/)
  f.gate.suspend(); await asleep
  f.gate.resume(); f.gate.setReady(true)
  await f.gate.wait()
})
