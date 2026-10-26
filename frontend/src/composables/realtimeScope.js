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
 *   connect      /ws?realtime=1&profile=P&topic=T...&previews=0|1
 *                &preview_fps=F&preview_bytes=N&preview_bps=R
 *                The server applies this before the first broadcast; the
 *                `connected` welcome echoes it as `realtime`. A welcome
 *                without `realtime` means an older server that sends
 *                everything, which is also safe.
 *   realtime_scope        {profile_id?, topics?, previews?, seq} replace fields
 *   realtime_subscribe    {topics, seq}
 *   realtime_unsubscribe  {topics, seq}
 *
 * The preview budget (fps, bytes per image, bytes per second) is per socket,
 * across every job it follows.
 *
 * This client always sends its complete desired state with `realtime_scope`,
 * so a reconnect restores everything from the connect URL alone. The scope
 * lives with the connection on the server.
 *
 * `ready(topic)` resolves once the server is known to deliver the topic:
 * every scope change sent so far is acknowledged, and the acknowledged scope
 * has this window's profile and the topic. A view that reads state over HTTP
 * after subscribing awaits it first; otherwise an event broadcast between
 * the HTTP snapshot and the server applying the subscription would be lost.
 * It resolves `true` when that is confirmed (or nothing needs confirming)
 * and `false` when it gave up waiting. A view that read provisionally is
 * told through `onLateConfirm` once the topic is confirmed, and reconciles
 * then. `onProfileConfirmed` fires when the server starts filtering for a
 * new profile, so state read during the switch can be reconciled.
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
  let previewPolicy = { maxFps: null, maxBytes: null, maxBytesPerSecond: null }

  let send = null
  // offline | connecting | scoped | legacy
  let mode = 'offline'
  let connecting = null
  // What the server last acknowledged on this socket, and for which message.
  let appliedProfile = null
  let appliedTopics = new Set()
  let sentSeq = 0
  let ackedSeq = 0
  let lastSent = null
  let rejectedKey = null
  let flushQueued = false
  // The profile in the last scope sent, and whether a profile change sent on
  // this socket still awaits a fully caught-up acknowledgement.
  let sentProfile = null
  let profileReconcilePending = false
  const waiters = new Set()
  // Topics a view read without confirmation (its wait timed out).
  const provisional = new Set()
  const lateConfirmListeners = new Set()
  const profileListeners = new Set()

  function desired() {
    return {
      profile_id: profileId,
      topics: [...counts.keys()].sort(),
      previews: {
        enabled: previewsVisible,
        max_fps: previewPolicy.maxFps,
        max_bytes: previewPolicy.maxBytes,
        max_bytes_per_second: previewPolicy.maxBytesPerSecond,
      },
    }
  }

  /** The server delivers `topic` for this window's profile, nothing pending. */
  function confirmed(topic) {
    if (mode === 'legacy') return true
    if (!send) return false
    if (flushQueued || JSON.stringify(desired()) !== lastSent) return false
    if (ackedSeq !== sentSeq) return false
    return appliedProfile === profileId && appliedTopics.has(topic)
  }

  // Nothing to wait for: no socket (the reconnect resynchronizes every
  // view), an older server (it sends everything), or the topic is gone.
  function moot(topic) {
    return !topic || mode === 'offline' || mode === 'legacy' || !counts.has(topic)
  }

  function settle() {
    for (const waiter of [...waiters]) {
      if (moot(waiter.topic) || confirmed(waiter.topic)) {
        waiters.delete(waiter)
        clearTimer(waiter.timer)
        waiter.resolve(true)
      }
    }
    for (const topic of [...provisional]) {
      if (!counts.has(topic)) {
        provisional.delete(topic)
      } else if (confirmed(topic)) {
        provisional.delete(topic)
        for (const listener of [...lateConfirmListeners]) listener(topic)
      }
    }
  }

  function flush() {
    if (mode !== 'scoped' || !send) return
    const state = desired()
    const key = JSON.stringify(state)
    if (key === lastSent || key === rejectedKey) return
    const next = sentSeq + 1
    if (send('realtime_scope', { ...state, seq: next })) {
      sentSeq = next
      lastSent = key
      if (state.profile_id !== sentProfile) profileReconcilePending = true
      sentProfile = state.profile_id
    }
  }

  function requestFlush() {
    if (flushQueued) return
    flushQueued = true
    schedule(() => {
      flushQueued = false
      flush()
      settle()
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
    if (moot(topic) || confirmed(topic)) return Promise.resolve(true)
    return new Promise(resolve => {
      const waiter = { topic, resolve, timer: null }
      // Never stall a view on a slow or lost acknowledgement: it reads
      // provisionally and reconciles once the topic is confirmed.
      waiter.timer = setTimer(() => {
        waiters.delete(waiter)
        provisional.add(topic)
        resolve(false)
      }, timeoutMs)
      waiters.add(waiter)
    })
  }

  function onLateConfirm(listener) {
    lateConfirmListeners.add(listener)
    return () => lateConfirmListeners.delete(listener)
  }

  function onProfileConfirmed(listener) {
    profileListeners.add(listener)
    return () => profileListeners.delete(listener)
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

  function setPreviewPolicy({ maxFps = null, maxBytes = null, maxBytesPerSecond = null } = {}) {
    if (previewPolicy.maxFps === maxFps && previewPolicy.maxBytes === maxBytes
      && previewPolicy.maxBytesPerSecond === maxBytesPerSecond) return
    previewPolicy = { maxFps, maxBytes, maxBytesPerSecond }
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
    if (state.previews.max_bytes_per_second) {
      params.set('preview_bps', String(state.previews.max_bytes_per_second))
    }
    connecting = { key: JSON.stringify(state), profile: state.profile_id, topics: new Set(state.topics) }
    mode = 'connecting'
    send = null
    appliedProfile = null
    appliedTopics = new Set()
    sentSeq = 0
    ackedSeq = 0
    lastSent = null
    rejectedKey = null
    sentProfile = state.profile_id
    // A new connection resynchronizes every view itself.
    profileReconcilePending = false
    return params.toString()
  }

  function socketOpened(sendFn) {
    send = sendFn
    // The connect URL's scope is delivered whatever the server is: a
    // current server applied it before accepting, an older one sends all.
    appliedProfile = connecting?.profile ?? null
    appliedTopics = new Set(connecting?.topics || [])
    lastSent = connecting?.key ?? null
    settle()
  }

  function socketClosed() {
    send = null
    mode = 'offline'
    connecting = null
    appliedTopics = new Set()
    lastSent = null
    // The reconnect resynchronizes every view, provisional reads included.
    provisional.clear()
    settle()
  }

  /** Inspect a server message; returns true for scope protocol messages. */
  function handleServerMessage(event, data) {
    if (event === 'connected') {
      if (data && data.realtime && mode === 'connecting') {
        mode = 'scoped'
        appliedProfile = data.realtime.profile_id ?? null
        appliedTopics = new Set(data.realtime.topics || [])
        flush()
      } else {
        mode = 'legacy'
      }
      settle()
      return false
    }
    if (event === 'realtime_scope_applied') {
      if (typeof data?.seq === 'number') ackedSeq = Math.max(ackedSeq, data.seq)
      appliedProfile = data?.profile_id ?? null
      appliedTopics = new Set(data?.topics || [])
      settle()
      // Fire once per profile change, when the server has caught up with
      // everything sent and filters for this window's current profile, even
      // if later scope changes overlapped the one that switched profiles.
      if (profileReconcilePending && !flushQueued && ackedSeq === sentSeq
        && appliedProfile === profileId && sentProfile === profileId) {
        profileReconcilePending = false
        for (const listener of [...profileListeners]) listener(appliedProfile)
      }
      return true
    }
    if (event === 'realtime_scope_rejected') {
      warn('[Realtime] scope rejected', { seq: data?.seq, reason: data?.reason })
      if (typeof data?.seq === 'number') ackedSeq = Math.max(ackedSeq, data.seq)
      // Never resend the same state. Waiters fall back to their timeout and
      // reconcile if a later scope confirms their topic.
      rejectedKey = lastSent
      return true
    }
    return false
  }

  function snapshot() {
    return { mode, ...desired(), applied: [...appliedTopics].sort(), sentSeq, ackedSeq }
  }

  return {
    acquire,
    ready,
    onLateConfirm,
    onProfileConfirmed,
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
