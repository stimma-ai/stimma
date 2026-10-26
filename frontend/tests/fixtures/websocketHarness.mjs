import { readFileSync } from 'node:fs'
import { createReconnectBackoff, LOCAL_RECONNECT, REMOTE_RECONNECT } from '../../src/utils/reconnectBackoff.js'
import { createTransportRecovery } from '../../src/utils/transportRecovery.js'
import { createRealtimeScope } from '../../src/composables/realtimeScope.js'

/**
 * The real useWebSocket singleton with controlled sockets, timers, the real
 * recovery state machine and the real realtime scope. No server is needed to
 * reproduce WebKit retaining an OPEN socket across suspension, a half-open
 * socket, or a server outage.
 */
export function createClock() {
  let now = 0, id = 0
  const timers = new Map()
  return {
    now: () => now,
    setTimeout: (fn, ms = 0) => { timers.set(++id, { fn, at: now + ms }); return id },
    clearTimeout: handle => { timers.delete(handle) },
    setInterval: (fn, ms) => { timers.set(++id, { fn, at: now + ms, every: ms }); return id },
    clearInterval: handle => { timers.delete(handle) },
    advance(ms) {
      const end = now + ms
      for (;;) {
        const next = [...timers].filter(([, timer]) => timer.at <= end).sort((a, b) => a[1].at - b[1].at)[0]
        if (!next) break
        const [handle, timer] = next
        now = timer.at
        if (timer.every) timer.at += timer.every
        else timers.delete(handle)
        timer.fn()
      }
      now = end
    },
    /** Delays of pending one-shot timers. */
    pending: () => [...timers.values()].filter(timer => !timer.every).map(timer => timer.at - now),
  }
}

const quiet = { log() {}, warn() {}, error() {}, debug() {} }

export function websocketHarness({ mobile = false, remoteDevice = false, profile = 'test', url = 'ws://localhost/ws', location = { protocol: 'http:', host: 'localhost:9192', hostname: 'localhost' }, before = () => {} } = {}) {
  const source = readFileSync(new URL('../../src/composables/useWebSocket.js', import.meta.url), 'utf8')
    .replace(/^import[\s\S]*?from\s+['"][^'"]+['"]\s*$/gm, '')
    .replaceAll('export function', 'function').replaceAll('import.meta.hot', 'false')
  const clock = createClock()
  const sockets = []
  class Socket {
    static OPEN = 1
    static CONNECTING = 0
    readyState = 0
    sent = []
    constructor(socketUrl) { this.url = socketUrl; sockets.push(this) }
    close() { this.closed = true }
    send(text) { this.sent.push(JSON.parse(text)) }
    open() { this.readyState = 1; this.onopen?.() }
    message(event, data = {}) { this.onmessage?.({ data: JSON.stringify({ event, data }) }) }
    receive(event, data) { this.message(event, data) }
    drop() { this.readyState = 3; this.onclose?.() }
  }
  const window = Object.assign(new EventTarget(), { location })
  const document = Object.assign(new EventTarget(), { visibilityState: 'visible' })
  const recovery = createTransportRecovery({ schedule: clock.setTimeout, cancel: clock.clearTimeout })
  const scope = createRealtimeScope({ schedule: fn => fn(), setTimer: clock.setTimeout, clearTimer: clock.clearTimeout, warn: () => {} })
  before(scope)
  const names = ['ref', 'shallowRef', 'getCurrentProfileId', 'getWsBase', 'isApiInitialized', 'addToast', 'removeToast',
    'window', 'document', 'WebSocket', 'setTimeout', 'clearTimeout', 'setInterval', 'clearInterval', 'Date', 'console',
    'mobileRecoveryEnabled', 'mobileTransportAdmitsSocket', 'mobileTransportEpoch', 'onMobileTransportAdmit',
    'onMobileTransportReady', 'setMobileSocketReady', 'createReconnectBackoff', 'LOCAL_RECONNECT', 'REMOTE_RECONNECT',
    'realtimeScope', 'installRealtimeScope']
  const create = new Function(...names, `${source}; return { useWebSocket, setRemoteServerConnection }`)
  const module = create(value => ({ value }), value => ({ value }), () => profile, () => url, () => true, () => {}, () => {},
    window, document, Socket, clock.setTimeout, clock.clearTimeout, clock.setInterval, clock.clearInterval,
    { now: clock.now }, quiet,
    mobile, () => !mobile || recovery.admitsSocket, () => (mobile ? recovery.epoch : 0),
    listener => (mobile ? recovery.onAdmit(listener) : () => {}), listener => (mobile ? recovery.onReady(listener) : () => {}),
    ready => { if (mobile) recovery.socket(ready) },
    () => createReconnectBackoff({ random: () => 1, now: clock.now }), LOCAL_RECONNECT, REMOTE_RECONNECT,
    scope, () => {})
  module.setRemoteServerConnection(remoteDevice)
  const api = module.useWebSocket()
  const native = (generation, phase, budgetMs = 0) => recovery.nativeState({ generation, phase, budgetMs })
  return { api, sockets, clock, window, document, recovery, native, scope }
}
