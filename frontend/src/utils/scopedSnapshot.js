/**
 * One authoritative copy of a read per scope, shared by everyone who asks.
 *
 * - `read(scope)` returns the stored value while it is fresh enough, joins a
 *   request already in flight for the scope, or starts one.
 * - `refresh(scope)` always asks the server and becomes the value later
 *   readers see, so a forced read can never be overtaken by an older one.
 * - `invalidate()` forgets values and in-flight requests; a request that was
 *   already running when its scope was invalidated still answers its own
 *   caller but is never stored.
 *
 * Failures are never stored. Every caller receives its own copy, so editing a
 * returned object (forms do) cannot leak into what the next caller reads.
 */
export function createScopedSnapshot(load, { now = () => Date.now() } = {}) {
  const values = new Map() // scope -> { value, at }
  const inflight = new Map() // scope -> { promise, generation }
  // Bumped per scope on invalidation, so late answers cannot be stored.
  const generations = new Map()
  const generationOf = scope => generations.get(scope) || 0
  // Requests are numbered so an older answer arriving late cannot replace a newer one.
  let sequence = 0

  function start(scope) {
    const generation = generationOf(scope)
    const order = ++sequence
    // Start the request synchronously: it must carry the identity of the
    // scope it is stored under, not whatever is current a microtask later.
    const promise = new Promise(resolve => resolve(load(scope)))
      .then(value => {
        const stored = values.get(scope)
        if (generationOf(scope) === generation && !(stored?.order > order)) values.set(scope, { value, at: now(), order })
        return value
      })
      .finally(() => {
        if (inflight.get(scope)?.promise === promise) inflight.delete(scope)
      })
    inflight.set(scope, { promise, generation })
    return promise.then(copy)
  }

  return {
    read(scope, { maxAgeMs = Infinity } = {}) {
      const stored = values.get(scope)
      if (stored && now() - stored.at <= maxAgeMs) return Promise.resolve(copy(stored.value))
      const pending = inflight.get(scope)
      if (pending && pending.generation === generationOf(scope)) return pending.promise.then(copy)
      return start(scope)
    },
    refresh(scope) {
      return start(scope)
    },
    peek(scope) {
      return values.has(scope) ? copy(values.get(scope).value) : null
    },
    /** Scopes that currently hold a stored value. */
    scopes() {
      return [...values.keys()]
    },
    /** Forget every scope, or only those `keep(scope)` rejects. */
    invalidate(keep = () => false) {
      for (const scope of new Set([...values.keys(), ...inflight.keys()])) {
        if (keep(scope)) continue
        values.delete(scope)
        inflight.delete(scope)
        generations.set(scope, generationOf(scope) + 1)
      }
    },
  }
}

function copy(value) {
  return value && typeof value === 'object' ? structuredClone(value) : value
}
