/** A single foreground grace window. Requests are held before dispatch, never replayed. */
export function createRecoveryWindow({ delay = 2000, changed = () => {}, schedule = setTimeout, cancel = clearTimeout } = {}) {
  let foreground = true, ready = true, expired = false, timer = null
  const waiting = new Set()
  const unavailable = () => new Error('Still reconnecting. Please try again.')
  function publish() { changed({ ready, foreground, expired, visible: foreground && !ready && expired }) }
  function settle(error) { for (const finish of [...waiting]) finish(error) }
  function arm() {
    if (timer !== null || expired || ready || !foreground) return
    timer = schedule(() => { timer = null; expired = true; settle(unavailable()); publish() }, delay)
  }
  return {
    suspend() {
      foreground = false; ready = false; expired = false
      cancel(timer); timer = null
      settle(new Error('Request cancelled while the app is in the background.'))
      publish()
    },
    resume() { foreground = true; arm(); publish() },
    setReady(value) {
      ready = value
      if (value) { cancel(timer); timer = null; expired = false; settle() }
      else arm()
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
