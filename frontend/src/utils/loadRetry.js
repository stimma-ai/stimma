/** Waits between automatic attempts: quick at first, then settling at 30 s. */
export const LOAD_RETRY_DELAYS_MS = Object.freeze([2000, 5000, 10000, 20000, 30000])
let defaultDelays = LOAD_RETRY_DELAYS_MS

/** Tests: replace the default waits (null restores them). */
export function setLoadRetryDelays(delays) {
  defaultDelays = delays ? Object.freeze([...delays]) : LOAD_RETRY_DELAYS_MS
}

/**
 * Retry a failed read on its own until it succeeds.
 *
 * A screen that loads once and shows an error waits for a reconnect to try
 * again, and the reconnect never comes when the socket stayed up while the
 * read failed (a phone whose network was still settling at launch). Call
 * `failed()` after a failed load and `succeeded()` after a good one; the next
 * attempt runs after a backing-off delay, never while the page is hidden.
 */
export function createLoadRetry(run, {
  delays = null,
  schedule = setTimeout,
  cancel = clearTimeout,
  hidden = () => typeof document !== 'undefined' && document.visibilityState === 'hidden',
} = {}) {
  let timer = null
  let failures = 0

  function stop() {
    if (timer !== null) cancel(timer)
    timer = null
  }

  function arm() {
    const waits = delays || defaultDelays
    const delay = waits[Math.min(failures - 1, waits.length - 1)]
    timer = schedule(() => {
      timer = null
      // Hidden pages wait; the attempt runs once the page is back.
      if (hidden()) { arm(); return }
      run()
    }, delay)
  }

  return {
    failed() {
      failures++
      stop()
      arm()
    },
    succeeded() {
      failures = 0
      stop()
    },
    stop,
  }
}
