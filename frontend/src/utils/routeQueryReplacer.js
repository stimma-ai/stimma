// Several watchers can rewrite the same URL query in one tick (for example,
// "Clear all" drops both the similarity and Made with params). Vue Router only
// updates `currentRoute` once a navigation finishes, and a newer replace()
// cancels an older pending one, so building each update from `currentRoute`
// would lose the earlier change. This chains every update onto the query that
// is still pending, so the last replace() carries all of them.
export function createRouteQueryReplacer(router) {
  let pending = null

  // `update(query)` edits the copy in place and returns whether it changed.
  // `reapply` asks the view to re-read filters from the resulting URL; it
  // sticks for the rest of a merged batch. Returns null when nothing changed.
  return function replaceRouteQuery(update, { reapply = false, onError } = {}) {
    const base = pending ? pending.query : router.currentRoute.value.query
    const query = { ...base }
    if (!update(query)) return null

    const entry = { query, reapply: reapply || !!pending?.reapply }
    pending = entry
    router.replace({ query })
      .catch((error) => { if (onError) onError(error); else throw error })
      .finally(() => { if (pending === entry) pending = null })
    return entry
  }
}
