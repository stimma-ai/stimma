/**
 * Realtime scope: what this client asks the server to send over the WebSocket.
 *
 * The server delivers every broadcast to clients that never declare a scope
 * (older UI packages). A client that connects with `?realtime=1` instead gets
 * only its profile's events, full detail only for the topics it subscribes
 * to, small job summaries for everything else, and preview images only as
 * its preview policy allows. Topics:
 *
 *   chat:<id>        chat items and agent detail for an open chat
 *   generator:<id>   full job detail and progress for one tool feed
 *   generation       the same for every tool feed
 *   previews:<id>    generation preview images for one tool feed
 *
 * Protocol (client -> server; each acknowledged with `realtime_scope_applied`
 * carrying the resulting scope, or `realtime_scope_rejected`):
 *
 *   connect      /ws?realtime=1&profile=P&topic=T...&previews=0|1&preview_fps=F&preview_bytes=N
 *                The server applies this before the first broadcast; the
 *                `connected` welcome echoes it as `realtime`. A welcome
 *                without `realtime` means an older server that sends
 *                everything, which is also safe.
 *   realtime_scope        {profile_id?, topics?, previews?, seq} replace fields
 *   realtime_subscribe    {topics, seq}
 *   realtime_unsubscribe  {topics, seq}
 *
 * This client always sends its complete desired state with `realtime_scope`,
 * so a reconnect restores everything from the connect URL alone. The scope
 * lives with the connection on the server.
 *
 * `ready(topic)` resolves once the server is known to deliver the topic.
 * A view that reads state over HTTP after subscribing awaits it first;
 * otherwise an event broadcast between the HTTP snapshot and the server
 * applying the subscription would be lost.
 */

export const REALTIME_PROTOCOL = 1
const READY_TIMEOUT_MS = 2000

export function createRealtimeScope({
  setTimer = (fn, ms) => setTimeout(fn, ms),
  clearTimer = id => clearTimeout(id),
  schedule = fn => queueMicrotask(fn),
  warn = (...args) => console.warn(...args),
} = {}) {
  const counts = new Map()
  let profileId = null
  let previewsVisible = true
  let previewPolicy = { maxFps: null, maxBytes: null }

  let send = null
  // offline | connecting | scoped | legacy
  let mode = 'offline'
  let connecting = null
  // Topics the server is known to deliver on the current socket.
  let applied = new Set()
  let lastSent = null
  let seq = 0
  let flushQueued = false
  const waiters = new Set()

  function desired() {
    return {
      profile_id: profileId,
      topics: [...counts.keys()].sort(),
      previews: {
        enabled: previewsVisible,
        max_fps: previewPolicy.maxFps,
        max_bytes: previewPolicy.maxBytes,
      },
    }
  }

  function settle(all = false) {
    for (const waiter of [...waiters]) {
      if (all || mode === 'offline' || mode === 'legacy'
        || applied.has(waiter.topic) || !counts.has(waiter.topic)) {
        waiters.delete(waiter)
        clearTimer(waiter.timer)
        waiter.resolve()
      }
    }
  }

  function flush() {
    if (mode !== 'scoped' || !send) return
    const state = desired()
    const key = JSON.stringify(state)
    if (key === lastSent) return
    const next = seq + 1
    if (send('realtime_scope', { ...state, seq: next })) {
      seq = next
      lastSent = key
    }
  }

  function requestFlush() {
    if (flushQueued) return
    flushQueued = true
    schedule(() => {
      flushQueued = false
      flush()
    })
  }

  /** Follow a topic until the returned release function is called. */
  function acquire(topic) {
    counts.set(topic, (counts.get(topic) || 0) + 1)
    if (counts.get(topic) === 1) requestFlush()
    let released = false
    return () => {
      if (released) return
      released = true
      const left = (counts.get(topic) || 1) - 1
      if (left > 0) {
        counts.set(topic, left)
        return
      }
      counts.delete(topic)
      requestFlush()
      settle()
    }
  }

  function ready(topic, timeoutMs = READY_TIMEOUT_MS) {
    if (!topic || mode === 'offline' || mode === 'legacy' || applied.has(topic) || !counts.has(topic)) {
      return Promise.resolve()
    }
    return new Promise(resolve => {
      const waiter = { topic, resolve, timer: null }
      // Never stall a view on a lost acknowledgement.
      waiter.timer = setTimer(() => {
        waiters.delete(waiter)
        resolve()
      }, timeoutMs)
      waiters.add(waiter)
    })
  }

  function setProfile(id) {
    const next = id || null
    if (next === profileId) return
    profileId = next
    requestFlush()
  }

  /** Offscreen (hidden page) clients stop receiving preview images. */
  function setPreviewsVisible(visible) {
    if (previewsVisible === !!visible) return
    previewsVisible = !!visible
    requestFlush()
  }

  function setPreviewPolicy({ maxFps = null, maxBytes = null } = {}) {
    if (previewPolicy.maxFps === maxFps && previewPolicy.maxBytes === maxBytes) return
    previewPolicy = { maxFps, maxBytes }
    requestFlush()
  }

  /** Query string for a new connection, carrying the complete scope. */
  function connectQuery(currentProfileId) {
    if (currentProfileId !== undefined) profileId = currentProfileId || null
    const state = desired()
    const params = new URLSearchParams({ realtime: '1' })
    if (state.profile_id) params.set('profile', state.profile_id)
    for (const topic of state.topics) params.append('topic', topic)
    params.set('previews', state.previews.enabled ? '1' : '0')
    if (state.previews.max_fps) params.set('preview_fps', String(state.previews.max_fps))
    if (state.previews.max_bytes) params.set('preview_bytes', String(state.previews.max_bytes))
    connecting = { key: JSON.stringify(state), topics: new Set(state.topics) }
    mode = 'connecting'
    send = null
    applied = new Set()
    lastSent = null
    return params.toString()
  }

  function socketOpened(sendFn) {
    send = sendFn
    // Topics in the connect URL are delivered whatever the server is: a
    // current server applied them before accepting, an older one sends all.
    applied = new Set(connecting?.topics || [])
    settle()
  }

  function socketClosed() {
    send = null
    mode = 'offline'
    connecting = null
    applied = new Set()
    lastSent = null
    // Nothing to wait for: the reconnect resynchronizes every view.
    settle(true)
  }

  /** Inspect a server message; returns true for scope protocol messages. */
  function handleServerMessage(event, data) {
    if (event === 'connected') {
      if (data && data.realtime && mode === 'connecting') {
        mode = 'scoped'
        applied = new Set(data.realtime.topics || [])
        lastSent = connecting?.key ?? null
        flush()
      } else {
        mode = 'legacy'
      }
      settle()
      return false
    }
    if (event === 'realtime_scope_applied') {
      applied = new Set(data?.topics || [])
      settle()
      return true
    }
    if (event === 'realtime_scope_rejected') {
      warn('[Realtime] scope rejected', { seq: data?.seq, reason: data?.reason })
      lastSent = null
      settle(true)
      return true
    }
    return false
  }

  function snapshot() {
    return { mode, ...desired(), applied: [...applied].sort() }
  }

  return {
    acquire,
    ready,
    setProfile,
    setPreviewsVisible,
    setPreviewPolicy,
    connectQuery,
    socketOpened,
    socketClosed,
    handleServerMessage,
    snapshot,
  }
}

export const realtimeScope = createRealtimeScope()
