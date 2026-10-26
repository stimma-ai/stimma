/**
 * A single foreground grace window. Requests are held before dispatch, never
 * replayed: once the window expires, held and new requests fail with a
 * reconnecting error and the caller decides whether to retry.
 *
 * Without native timing the window is `delay` long. A native shell that
 * reports its recovery phase supplies that phase's own budget through
 * `hold(budgetMs)`, so requests wait exactly as long as native recovery may
 * take, and `fail()` ends the wait at once when recovery reports the server
 * unavailable.
 */
export function createRecoveryWindow({ delay = 2000, changed = () => {}, schedule = setTimeout, cancel = clearTimeout } = {}) {
  let foreground = true, ready = true, expired = false, timer = null, budget = delay
  const waiting = new Set()
  const unavailable = () => new Error('Still reconnecting. Please try again.')
  function publish() { changed({ ready, foreground, expired, visible: foreground && !ready && expired }) }
  function settle(error) { for (const finish of [...waiting]) finish(error) }
  function stop() { cancel(timer); timer = null }
  function arm() {
    if (timer !== null || expired || ready || !foreground) return
    timer = schedule(() => { timer = null; expired = true; settle(unavailable()); publish() }, budget)
  }
  return {
    suspend() {
      foreground = false; ready = false; expired = false
      stop()
      settle(new Error('Request cancelled while the app is in the background.'))
      publish()
    },
    resume() { foreground = true; arm(); publish() },
    setReady(value) {
      ready = value
      if (value) { stop(); expired = false; budget = delay; settle() }
      else arm()
      publish()
    },
    /** A recovery phase began: hold requests for its budget, measured from now. */
    hold(budgetMs) {
      ready = false; expired = false; budget = budgetMs
      stop(); arm(); publish()
    },
    /** Recovery reported the server unavailable: fail waiting and new requests now. */
    fail() {
      ready = false; stop()
      if (!expired) { expired = true; settle(unavailable()) }
      publish()
    },
    invalidate() { settle(new Error('The active workspace changed. Please try again.')) },
    wait(signal) {
      if (signal?.aborted) return Promise.reject(signal.reason ?? new DOMException('Aborted', 'AbortError'))
      if (ready) return Promise.resolve()
      if (!foreground || expired) return Promise.reject(unavailable())
      return new Promise((resolve, reject) => {
        const abort = () => finish(signal.reason ?? new DOMException('Aborted', 'AbortError'))
        const finish = error => { waiting.delete(finish); signal?.removeEventListener('abort', abort); error ? reject(error) : resolve() }
        waiting.add(finish)
        signal?.addEventListener('abort', abort, { once: true })
      })
    },
  }
}
