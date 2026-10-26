/**
 * Join concurrent identical reads. Several consumers refreshing after the
 * same reconnect (every job strip, say) share one request instead of each
 * starting its own; a read that starts after the previous one settled always
 * goes to the network. Nothing is cached. Include everything that changes the
 * answer, such as the profile, in the key.
 */
const inflight = new Map()

export function sharedRead(key, read) {
  const existing = inflight.get(key)
  if (existing) return existing
  const promise = Promise.resolve().then(read).finally(() => {
    if (inflight.get(key) === promise) inflight.delete(key)
  })
  inflight.set(key, promise)
  return promise
}
