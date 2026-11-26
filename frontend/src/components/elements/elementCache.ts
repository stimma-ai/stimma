// How a saved direct edit lands in the by-media-id element cache. Kept apart
// from useElements so it can be tested without the app around it.
//
// One media id is one element version, so each entry keeps its own version's
// content. The saved state goes under its own media id only; the one thing
// every version shares is the element's name, which follows a rename.
export interface CachedElement {
  asset_id: number
  media_id: number
  name: string
}

export function applySavedElement<T extends CachedElement>(cache: Map<number, T>, saved: T) {
  for (const [id, detail] of cache) {
    if (id !== saved.media_id && detail.asset_id === saved.asset_id && detail.name !== saved.name) {
      cache.set(id, { ...detail, name: saved.name })
    }
  }
  cache.set(saved.media_id, saved)
}

/** Media ids of every cached version of these elements (to reread after a rename elsewhere). */
export function cachedVersionsOf(cache: Map<number, CachedElement>, assetIds: Iterable<unknown>): number[] {
  const ids = new Set([...assetIds].map(Number))
  return [...cache].filter(([, detail]) => ids.has(detail.asset_id)).map(([id]) => id)
}
