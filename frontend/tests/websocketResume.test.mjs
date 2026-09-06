import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

// Exercise the real singleton with controlled sockets and timers. No server
// is needed to reproduce WebKit retaining an OPEN socket across suspension.
function fixture() {
  const source = readFileSync(new URL('../src/composables/useWebSocket.js', import.meta.url), 'utf8')
    .replace(/^import .*$/gm, '').replace('export function', 'function').replaceAll('import.meta.hot', 'false')
  const sockets = []
  class Socket {
    static OPEN = 1
    static CONNECTING = 0
    readyState = 0
    constructor() { sockets.push(this) }
    close() { this.closed = true }
    open() { this.readyState = 1; this.onopen?.() }
  }
  const window = new EventTarget()
  const timers = new Map()
  let timerId = 0
  const create = new Function('ref', 'getCurrentProfileId', 'getWsBase', 'isApiInitialized', 'addToast', 'removeToast', 'window', 'WebSocket', 'setTimeout', 'clearTimeout', `${source}; return useWebSocket`)
  const useSocket = create(value => ({ value }), () => 'test', () => 'ws://localhost/ws', () => true,
    () => {}, () => {}, window, Socket,
    fn => { timers.set(++timerId, fn); return timerId }, id => timers.delete(id))
  return { api: useSocket(), sockets, timers, resume: () => window.dispatchEvent(new Event('stimma:transport-resumed')) }
}

test('resume replaces an apparently OPEN socket and refetches through the normal reconnect event', () => {
  const { api, sockets, timers, resume } = fixture()
  let refreshed = 0
  api.on('websocket_reconnected', () => refreshed++)
  api.connect()
  sockets[0].open()
  const old = sockets[0]
  resume()
  assert.equal(old.closed, true)
  assert.equal(old.onclose, null, 'late close must not erase the replacement')
  assert.equal(sockets.length, 2)
  sockets[1].open()
  assert.equal(api.connected.value, true)
  assert.equal(refreshed, 2)
  assert.equal(timers.size, 0)
  api.connect()
  assert.equal(sockets.length, 2, 'only one socket remains connected')
})

test('resume clears pending retries and replaces a stuck CONNECTING socket', () => {
  const { api, sockets, timers, resume } = fixture()
  api.connect()
  sockets[0].onclose()
  assert.equal(timers.size, 1)
  resume()
  assert.equal(timers.size, 0)
  assert.equal(sockets.length, 2)
  resume()
  assert.equal(sockets[1].closed, true)
  assert.equal(sockets.length, 3)
  sockets[2].open()
  assert.equal(api.connected.value, true)
})
