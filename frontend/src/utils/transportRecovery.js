import { createRecoveryWindow } from './recoveryWindow.js'

/**
 * Native recovery phases (mobile/contract/transport-recovery.json). Requests
 * are held while the shell checks or re-establishes the connection, for the
 * budget it reports; while the server is unavailable they fail fast and the
 * page keeps what it already shows.
 */
export const RECOVERY_PHASES = Object.freeze({
  checking: { holdRequests: true },
  reconnecting: { holdRequests: true },
  ready: { holdRequests: false },
  unavailable: { holdRequests: false },
})

/** A quick check should not flash a banner; a slower one should say so. */
export const REVEAL_DELAY_MS = 1000

/**
 * The page's half of connection recovery: one state machine for request
 * admission, socket replacement and the visible reconnecting state.
 *
 * Shells that publish `stimma:transport-state` drive it by generation and
 * phase (`nativeState`). Older shells only say whether HTTP is ready and when
 * the transport resumed (`legacyConnection`, `legacyResumed`); they keep the
 * fixed grace window they always had.
 *
 * Each time the path becomes suspect (backgrounding, a check, a failure) a
 * new disruption epoch opens. `onReady` listeners run once when that epoch
 * becomes ready again: that is when the socket is replaced and screens
 * refresh, never twice for the same recovery.
 */
export function createTransportRecovery({
  legacyDelay = 2000,
  revealDelay = REVEAL_DELAY_MS,
  schedule = setTimeout,
  cancel = clearTimeout,
  changed = () => {},
} = {}) {
  const requests = createRecoveryWindow({ delay: legacyDelay, schedule, cancel })
  let foreground = true
  let native = null
  let httpReady = true
  let socketReady = true
  let epoch = 0
  let announced = 0
  let revealTimer = null
  let revealed = false
  let status = null
  // After the app returns, a ready state from before it left is not trusted
  // until the shell confirms it (or says what it is doing instead).
  let confirming = false
  let confirmTimer = null
  const readyListeners = new Set()
  const admitListeners = new Set()
  let admitted = true

  function disrupt() { if (announced === epoch) epoch++ }

  function announce() {
    if (announced === epoch) return
    announced = epoch
    notify(readyListeners, epoch)
  }

  function connectionReady() { return native ? native.phase === 'ready' && !confirming : httpReady }

  function stopConfirming() { confirming = false; cancel(confirmTimer); confirmTimer = null }

  function notify(listeners, value) {
    for (const listener of [...listeners]) {
      try { listener(value) } catch (error) { console.error('[recovery] listener failed', error) }
    }
  }

  function present() {
    const admits = foreground && connectionReady()
    if (admits !== admitted) { admitted = admits; if (admits) notify(admitListeners) }
    const settled = connectionReady() && socketReady
    if (!foreground || settled) {
      cancel(revealTimer); revealTimer = null; revealed = false
    } else if (revealTimer === null && !revealed) {
      revealTimer = schedule(() => { revealTimer = null; revealed = true; present() }, native ? revealDelay : legacyDelay)
    }
    let next = null
    if (foreground && native?.phase === 'unavailable') next = 'unavailable'
    else if (foreground && native?.phase === 'reconnecting') next = 'reconnecting'
    else if (foreground && !settled && revealed) next = 'reconnecting'
    if (next !== status) { status = next; changed(snapshot()) }
  }

  function snapshot() {
    return { status, visible: status !== null, foreground, generation: native?.generation ?? null, phase: native?.phase ?? null, epoch }
  }

  function applyNative() {
    if (!native) return
    const phase = native.phase
    if (phase === 'ready') {
      httpReady = true
      requests.setReady(true)
      if (foreground) announce()
    } else {
      disrupt()
      httpReady = false
      if (!foreground) return
      if (phase === 'unavailable') requests.fail()
      else requests.hold(native.budgetMs)
    }
  }

  return {
    suspend() {
      foreground = false
      stopConfirming()
      disrupt()
      requests.suspend()
      present()
    },
    resume() {
      if (foreground) return
      foreground = true
      requests.resume()
      if (native?.phase === 'ready') {
        // Shells report what recovery they start on return. One that reports
        // nothing new (a dev-server page, say) is taken at its word shortly.
        confirming = true
        requests.hold(legacyDelay)
        confirmTimer = schedule(() => { confirmTimer = null; confirming = false; applyNative(); present() }, legacyDelay)
      } else if (native) applyNative()
      present()
    },
    /** The shell's recovery state. Older generations never override newer ones. */
    nativeState(state) {
      if (!state || typeof state.generation !== 'number' || !(state.phase in RECOVERY_PHASES)) return
      if (native && state.generation < native.generation) return
      if (native && state.generation === native.generation && state.phase === native.phase && !confirming) return
      stopConfirming()
      native = { generation: state.generation, phase: state.phase, budgetMs: Math.max(0, Number(state.budgetMs) || 0) }
      applyNative()
      present()
    },
    /** `stimma:connection-state` from a shell that does not publish recovery phases. */
    legacyConnection(state) {
      if (native) return
      httpReady = state === 'ready'
      if (!httpReady) disrupt()
      if (foreground) requests.setReady(httpReady)
      present()
    },
    /** `stimma:transport-resumed` from a shell that does not publish recovery phases: sockets were dropped. */
    legacyResumed() {
      if (native) return
      httpReady = true
      if (foreground) requests.setReady(true)
      disrupt()
      if (foreground) announce()
      present()
    },
    socket(ready) {
      socketReady = ready
      present()
    },
    wait(signal) { return requests.wait(signal) },
    invalidate() { requests.invalidate() },
    onReady(listener) {
      readyListeners.add(listener)
      return () => readyListeners.delete(listener)
    },
    /** Runs whenever sockets become admissible again, including without a replacement (a dropped socket may reconnect). */
    onAdmit(listener) {
      admitListeners.add(listener)
      return () => admitListeners.delete(listener)
    },
    /** Whether a socket may be opened now: foreground, and the shell says the path is usable. */
    get admitsSocket() { return foreground && connectionReady() },
    get native() { return native !== null },
    /** The current disruption epoch; a socket opened in an earlier one is suspect. */
    get epoch() { return epoch },
    snapshot,
  }
}
