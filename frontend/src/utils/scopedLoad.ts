/**
 * One loading policy for a screen whose data belongs to a scope (server,
 * profile, project, ...). Mount and reactivation both call `request`; the
 * coordinator decides whether that needs a network load. It is strictly
 * single-flight: at most one read runs at a time, so replies are applied in
 * the order their reads started and can never overtake each other.
 *
 * - A request while a read is running joins it, however long it takes. A
 *   slow read on a poor connection is never abandoned and restarted.
 * - A forced request (an explicit retry, a known change), or any request
 *   after `invalidate()` while a read is running, does not start a second
 *   read. It schedules one rerun once the current read settles; any number
 *   of such requests coalesce into that single rerun.
 * - A completed read stays fresh for `freshMs`. It counts as fresh only if
 *   it succeeded, nothing invalidated it while it ran, and no rerun is due.
 * - A request for a different scope makes the running read obsolete and
 *   cancels any rerun. Loaders get an `isCurrent()` guard and must drop their
 *   results once it turns false, so a late reply can never replace another
 *   scope's data.
 */
export type ScopeKeyPart = string | number | null | undefined

export function scopeKey(...parts: ScopeKeyPart[]): string {
  return JSON.stringify(parts.map(part => part ?? null))
}

type Loader = (isCurrent: () => boolean) => Promise<boolean | void>

export interface ScopedLoadOptions {
  freshMs: number
  now?: () => number
}

export function createScopedLoad({ freshMs, now = Date.now }: ScopedLoadOptions) {
  // Bumped whenever the requested scope changes; reads from an earlier epoch
  // are obsolete.
  let epoch = 0
  let activeKey: string | null = null
  let inflight: { promise: Promise<boolean>; changesAtStart: number } | null = null
  // A rerun requested while a read was running, and the promise its callers
  // wait on.
  let rerun: { load: Loader; done: Promise<boolean>; settle: (ran: Promise<boolean>) => void } | null = null
  let freshKey: string | null = null
  let freshAt = 0
  let changes = 0

  function isFresh(key: string) {
    return freshKey === key && now() - freshAt < freshMs
  }

  function start(key: string, load: Loader): Promise<boolean> {
    const mine = epoch
    const changesAtStart = changes
    const isCurrent = () => mine === epoch
    const promise = (async () => {
      let ok: boolean | void = false
      try {
        ok = await load(isCurrent)
      } catch {
        ok = false
      }
      if (!isCurrent()) return true
      inflight = null
      if (ok !== false && changesAtStart === changes && !rerun) {
        freshKey = key
        freshAt = now()
      }
      if (rerun) {
        const next = rerun
        rerun = null
        next.settle(start(key, next.load))
      }
      return true
    })()
    inflight = { promise, changesAtStart }
    return promise
  }

  return {
    /** Scope of the most recent request (in flight or settled). */
    get activeKey() { return activeKey },

    /**
     * Load `key` unless it is fresh. Joins a running read, or schedules one
     * rerun after it when forced or invalidated. Resolves once the read this
     * call depends on has settled.
     */
    request(key: string, load: Loader, { force = false } = {}): Promise<boolean> {
      if (key !== activeKey) {
        epoch++
        activeKey = key
        inflight = null
        rerun?.settle(Promise.resolve(false))
        rerun = null
        freshKey = null
      }
      if (inflight) {
        if (!force && inflight.changesAtStart === changes) return inflight.promise
        if (rerun) {
          rerun.load = load
          return rerun.done
        }
        let settle!: (ran: Promise<boolean>) => void
        const done = new Promise<boolean>(resolve => { settle = ran => resolve(ran) })
        rerun = { load, done, settle }
        return done
      }
      if (!force && isFresh(key)) return Promise.resolve(false)
      return start(key, load)
    },

    /** A guard for a partial reload of the current scope. */
    guard(): () => boolean {
      const mine = epoch
      return () => mine === epoch
    },

    /** Mark the current data stale; the next request reloads it. */
    invalidate() {
      changes++
      freshKey = null
    },
  }
}
