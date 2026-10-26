/**
 * One loading policy for a screen whose data belongs to a scope (server,
 * profile, project, ...). Mount and reactivation both call `request`; the
 * coordinator decides whether that needs a network load:
 *
 * - A request for the scope already loading joins the in-flight load.
 * - A completed load stays fresh for `freshMs` unless `invalidate()` marks it
 *   stale (a change event, a reconnect). A change seen while a load is in
 *   flight keeps the result stale, because that response may predate it.
 * - A request for a different scope supersedes the previous one. Loaders get
 *   an `isCurrent()` guard and must drop their results once it turns false,
 *   so a late response can never replace the newer scope's data.
 */
export type ScopeKeyPart = string | number | null | undefined

export function scopeKey(...parts: ScopeKeyPart[]): string {
  return JSON.stringify(parts.map(part => part ?? null))
}

type Loader = (isCurrent: () => boolean) => Promise<boolean | void>

export interface ScopedLoadOptions {
  freshMs: number
  /**
   * A load still running after this long is treated as stalled: the next
   * request starts over instead of joining it, and the stalled one's results
   * are ignored.
   */
  maxWaitMs?: number
  now?: () => number
}

export function createScopedLoad({ freshMs, maxWaitMs = Infinity, now = Date.now }: ScopedLoadOptions) {
  let generation = 0
  let activeKey: string | null = null
  let inflight: { key: string; promise: Promise<boolean>; startedAt: number } | null = null
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
      if (inflight && now() - inflight.startedAt >= maxWaitMs) inflight = null
      if (inflight && inflight.key === key && !force) return inflight.promise
      if (!force && !inflight && isFresh(key)) return Promise.resolve(false)
      const mine = ++generation
      const startedAt = changes
      activeKey = key
      if (freshKey !== key) freshKey = null
      const isCurrent = () => mine === generation
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
      inflight = { key, promise, startedAt: now() }
      return promise
    },

    /** A guard for a partial reload of the current scope. */
    guard(): () => boolean {
      const mine = generation
      return () => mine === generation
    },

    /** Mark the current data stale; the next request reloads it. */
    invalidate() {
      changes++
      freshKey = null
    },
  }
}
