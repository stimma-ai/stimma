import assert from 'node:assert/strict'
import test from 'node:test'
import { createReconnectBackoff, REMOTE_RECONNECT } from '../src/utils/reconnectBackoff.js'
import { websocketHarness } from './fixtures/websocketHarness.mjs'

// The real useWebSocket singleton with controlled sockets, timers and the
// real recovery state machine (see fixtures/websocketHarness.mjs).
const flush = () => new Promise(resolve => setImmediate(resolve))
const fixture = ({ mobile = true, remote = false } = {}) => websocketHarness({ mobile, remoteDevice: remote })

test('native recovery replaces an apparently OPEN socket once and refreshes through the normal reconnect event', () => {
  const { api, sockets, recovery, native } = fixture()
  let refreshed = 0, gaps = 0
  api.on('websocket_reconnected', () => refreshed++)
  api.on('websocket_disconnected', () => gaps++)
  native(1, 'ready')
  sockets[0].open()
  const old = sockets[0]
  // WebKit keeps the suspended socket OPEN; native recovery checks the path.
  recovery.suspend(); recovery.resume()
  native(2, 'checking', 5000)
  assert.equal(sockets.length, 1, 'no socket is attempted while the path is being checked')
  native(2, 'ready')
  assert.equal(old.closed, true)
  assert.equal(old.onclose, null, 'late close must not erase the replacement')
  assert.equal(gaps, 1, 'the replaced socket counts as a gap')
  assert.equal(sockets.length, 2)
  sockets[1].open()
  assert.equal(api.connected.value, true)
  assert.equal(refreshed, 2)
  // An older shell event or a repeated state for the same recovery does nothing more.
  native(2, 'ready')
  recovery.legacyResumed()
  api.connect()
  assert.equal(sockets.length, 2, 'only one socket per recovery')
})

test('no retries are attempted while backgrounded or while the server is unavailable', () => {
  const { api, sockets, clock, recovery, native } = fixture()
  native(1, 'ready')
  sockets[0].open()
  recovery.suspend()
  sockets[0].drop()
  clock.advance(60_000)
  assert.equal(sockets.length, 1, 'a backgrounded phone does not hammer the server')
  recovery.resume()
  native(2, 'checking', 5000)
  native(2, 'reconnecting', 20_000)
  native(2, 'unavailable')
  clock.advance(60_000)
  assert.equal(sockets.length, 1)
  assert.equal(api.reconnecting.value, true)
  native(2, 'ready')
  assert.equal(sockets.length, 2, 'ready opens exactly one socket')
  sockets[1].open()
  assert.equal(api.connected.value, true)
})

test('remote failures back off exponentially with jitter, bounded, and reset after a stable connection', () => {
  const { sockets, clock } = fixture({ mobile: false, remote: true })
  sockets[0].drop()
  const delays = []
  for (let attempt = 0; attempt < 8; attempt++) {
    delays.push(clock.pending()[0])
    clock.advance(delays.at(-1))
    sockets.at(-1).drop()
  }
  assert.deepEqual(delays, [500, 1000, 2000, 4000, 8000, 16000, 30000, 30000])
  // A connection that stayed up resets the schedule.
  clock.advance(clock.pending()[0])
  sockets.at(-1).open()
  clock.advance(15_000)
  sockets.at(-1).drop()
  assert.deepEqual(clock.pending(), [500])
})

test('jitter spreads attempts below the bound', () => {
  const low = createReconnectBackoff({ random: () => 0 })
  const high = createReconnectBackoff({ random: () => 1 })
  for (let i = 0; i < 4; i++) { low.next(REMOTE_RECONNECT); high.next(REMOTE_RECONNECT) }
  assert.equal(low.next(REMOTE_RECONNECT), 4000)
  assert.equal(high.next(REMOTE_RECONNECT), 8000)
  for (let i = 0; i < 20; i++) high.next(REMOTE_RECONNECT)
  assert.equal(high.next(REMOTE_RECONNECT), 30_000)
})

test('a local backend keeps quick fixed retries', () => {
  const { sockets, clock } = fixture({ mobile: false })
  for (let attempt = 0; attempt < 6; attempt++) {
    sockets.at(-1).drop()
    assert.deepEqual(clock.pending(), [500])
    clock.advance(500)
  }
})

test('the network coming back skips the remaining backoff', () => {
  const { sockets, clock, window } = fixture({ mobile: false, remote: true })
  for (let attempt = 0; attempt < 5; attempt++) { sockets.at(-1).drop(); clock.advance(clock.pending()[0]) }
  sockets.at(-1).drop()
  assert.equal(clock.pending()[0], 16_000)
  window.dispatchEvent(new Event('online'))
  assert.equal(sockets.length, 7)
  assert.deepEqual(clock.pending(), [], 'the pending retry was replaced by the immediate attempt')
})

test('a half-open remote socket is detected by an unanswered ping and replaced', () => {
  const { api, sockets, clock, native } = fixture()
  native(1, 'ready')
  sockets[0].open()
  let gaps = 0
  api.on('websocket_disconnected', () => gaps++)
  clock.advance(24_000)
  assert.deepEqual(sockets[0].sent, [], 'a socket with recent traffic is not pinged')
  sockets[0].message('progress')
  clock.advance(30_000)
  assert.deepEqual(sockets[0].sent.map(message => message.event), ['ping'])
  sockets[0].message('pong')
  clock.advance(10_000)
  assert.equal(api.connected.value, true, 'an answered ping keeps the socket')
  clock.advance(30_000)
  assert.equal(sockets[0].sent.length, 2)
  clock.advance(10_000)
  assert.equal(sockets[0].closed, true, 'no answer: the socket is dead')
  assert.equal(api.connected.value, false)
  assert.equal(gaps, 1)
  clock.advance(clock.pending()[0])
  assert.equal(sockets.length, 2)
})

test('optional reconnect work waits for the active screen, and a superseded open never runs it', async () => {
  const { api, sockets, clock, window } = fixture({ mobile: false, remote: true })
  const order = []
  let finishScreen
  api.on('websocket_reconnected', ({ generation }) => { order.push(`screen ${generation}`); return new Promise(resolve => { finishScreen = resolve }) })
  api.on('websocket_reconnected', ({ generation }) => order.push(`status ${generation}`))
  api.on('websocket_reconnected', ({ generation }) => order.push(`optional ${generation}`), { optional: true })
  window.addEventListener('stimma:media-reconnected', () => order.push('artwork'))
  sockets[0].open()
  await flush()
  assert.deepEqual(order, ['screen 1', 'status 1'])
  finishScreen(); await flush()
  assert.deepEqual(order, ['screen 1', 'status 1', 'optional 1', 'artwork'])
  // Reads that never settle delay optional work only up to its bound.
  const reopen = () => { sockets.at(-1).drop(); window.dispatchEvent(new Event('online')); sockets.at(-1).open() }
  reopen()
  await flush()
  clock.advance(3000)
  assert.deepEqual(order.slice(4), ['screen 2', 'status 2', 'optional 2', 'artwork'])
  // A newer open supersedes optional work still waiting from the previous one.
  reopen()
  reopen()
  finishScreen(); await flush(); clock.advance(3000)
  assert.equal(order.filter(entry => entry === 'optional 3').length, 0)
  assert.equal(order.filter(entry => entry === 'optional 4').length, 1)
})

test('a local backend runs reconnect work without deferral', async () => {
  const { api, sockets } = fixture({ mobile: false })
  const order = []
  api.on('websocket_reconnected', () => { order.push('screen'); return new Promise(() => {}) })
  api.on('websocket_reconnected', () => order.push('optional'), { optional: true })
  sockets[0].open()
  assert.deepEqual(order, ['screen', 'optional'])
})

test('a browser on another machine is a remote connection even when its server is "local"', () => {
  const { sockets, clock } = websocketHarness({ url: 'ws://studio.example:9191/ws' })
  sockets[0].open()
  clock.advance(30_000)
  assert.ok(sockets[0].sent.some(message => message.event === 'ping'), 'liveness runs')
  sockets[0].message('pong')
  sockets[0].drop()
  const delays = []
  for (let attempt = 0; attempt < 4; attempt++) {
    delays.push(clock.pending()[0])
    clock.advance(delays.at(-1))
    sockets.at(-1).drop()
  }
  assert.deepEqual(delays, [500, 1000, 2000, 4000])
  // A backend reached through loopback keeps the quick retry.
  const local = websocketHarness({ url: 'ws://127.0.0.1:9192/ws' })
  local.sockets[0].drop()
  local.clock.advance(500)
  local.sockets.at(-1).drop()
  assert.deepEqual(local.clock.pending(), [500])
})

test('without a recovery machine, transport-resumed still replaces the socket and counts as a gap', () => {
  const { api, sockets, window } = websocketHarness()
  let gaps = 0, reconnects = 0
  api.on('websocket_disconnected', () => gaps++)
  api.on('websocket_reconnected', () => reconnects++)
  sockets[0].open()
  window.dispatchEvent(new Event('stimma:transport-resumed'))
  assert.equal(sockets[0].closed, true)
  assert.equal(sockets.length, 2)
  assert.equal(gaps, 1)
  sockets[1].open()
  assert.equal(reconnects, 2)
})
