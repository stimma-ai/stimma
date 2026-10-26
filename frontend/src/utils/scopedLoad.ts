/**
 * One loading policy for a screen whose data belongs to a scope (server,
 * profile, project, ...). Mount and reactivation both call `request`; the
 * coordinator decides whether that needs a network load:
 *
 * - A request for the scope already loading joins the in-flight load, however
 *   long it takes. A slow read on a poor connection is never abandoned and
 *   restarted; that would only add competing reads for the same data.
 * - A completed load stays fresh for `freshMs` unless `invalidate()` marks it
 *   stale (a change event, a reconnect). A change seen while a load is in
 *   flight keeps the result stale, because that response may predate it.
 * - A forced request (an explicit retry or a known change) starts a new read
 *   even while one is in flight. Both belong to the same scope, so whichever
 *   answers first is used.
 * - A request for a different scope makes every earlier read obsolete.
 *   Loaders get an `isCurrent()` guard and must drop their results once it
 *   turns false, so a late response can never replace another scope's data.
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
  let inflight: { key: string; promise: Promise<boolean> } | null = null
  let freshKey: string | null = null
  let freshAt = 0
  let changes = 0

  function isFresh(key: string) {
    return freshKey === key && now() - freshAt < freshMs
  }

  return {
    /** Scope of the most recent request (in flight or settled). */
    get activeKey() { return activeKey },

    /**
     * Load `key` unless that load is already running or fresh. Resolves true
     * when this call (or the load it joined) actually ran the loader.
     */
    request(key: string, load: Loader, { force = false } = {}): Promise<boolean> {
      if (key !== activeKey) {
        epoch++
        activeKey = key
        inflight = null
        freshKey = null
      }
      if (inflight && !force) return inflight.promise
      if (!force && isFresh(key)) return Promise.resolve(false)
      const mine = epoch
      const startedAt = changes
      const isCurrent = () => mine === epoch
      const promise = (async () => {
        try {
          const ok = await load(isCurrent)
          if (isCurrent() && ok !== false && startedAt === changes) {
            freshKey = key
            freshAt = now()
          }
          return true
        } finally {
          if (inflight?.promise === promise) inflight = null
        }
      })()
      inflight = { key, promise }
      return promise
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
