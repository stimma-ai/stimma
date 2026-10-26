/**
 * Delays between WebSocket reconnect attempts.
 *
 * A local backend restarts in a moment and the app should follow it quickly,
 * so local connections keep a short fixed retry. A remote server that is down
 * or unreachable gets bounded exponential backoff with jitter instead, so a
 * phone on a weak network does not hammer it (or its own radio) every half
 * second, and many clients do not retry in lockstep after a server restart.
 *
 * Backoff resets once a connection has stayed up for `stableMs`: a socket that
 * opens and immediately drops again keeps backing off, a healthy one does not
 * carry earlier failures into its next outage. Callers that learn the network
 * changed or the app returned to the foreground can `reset()` and retry at once.
 */
export const LOCAL_RECONNECT = Object.freeze({ baseMs: 500, maxMs: 500, jitter: 0 })
export const REMOTE_RECONNECT = Object.freeze({ baseMs: 500, maxMs: 30_000, jitter: 0.5 })
export const STABLE_CONNECTION_MS = 10_000

export function createReconnectBackoff({ random = Math.random, now = Date.now, stableMs = STABLE_CONNECTION_MS } = {}) {
  let failures = 0
  let openedAt = null

  return {
    /** The delay before the next attempt under `policy`; counts the attempt. */
    next(policy = LOCAL_RECONNECT) {
      const ceiling = Math.min(policy.maxMs, policy.baseMs * 2 ** Math.min(failures, 20))
      failures += 1
      // Jitter spreads attempts below the ceiling, never above it.
      return Math.round(ceiling * (1 - policy.jitter) + ceiling * policy.jitter * random())
    },
    opened() { openedAt = now() },
    /** The socket closed; a connection that had been stable forgets earlier failures. */
    closed() {
      if (openedAt !== null && now() - openedAt >= stableMs) failures = 0
      openedAt = null
    },
    reset() { failures = 0 },
    get failures() { return failures },
  }
}
