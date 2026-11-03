// Install listeners before changing MSE state, and release them on every exit.
export function mediaOperation(target, event, action, signal) {
  return new Promise((resolve, reject) => {
    const cleanup = () => {
      target.removeEventListener(event, done)
      target.removeEventListener('error', fail)
      target.removeEventListener('abort', aborted)
      signal?.removeEventListener('abort', aborted)
    }
    const done = () => { cleanup(); resolve() }
    const fail = () => { cleanup(); reject(new Error(`Media operation failed: ${event}`)) }
    const aborted = () => { cleanup(); reject(new DOMException('Playback cancelled', 'AbortError')) }
    target.addEventListener(event, done, { once: true })
    target.addEventListener('error', fail, { once: true })
    target.addEventListener('abort', aborted, { once: true })
    signal?.addEventListener('abort', aborted, { once: true })
    if (signal?.aborted) { aborted(); return }
    try { action() } catch (error) { cleanup(); reject(error) }
  })
}

export const appendBuffer = (buffer, bytes, signal) => mediaOperation(buffer, 'updateend', () => buffer.appendBuffer(bytes), signal)
export const removeBuffer = (buffer, start, end, signal) => end > start
  ? mediaOperation(buffer, 'updateend', () => buffer.remove(start, end), signal)
  : Promise.resolve()
