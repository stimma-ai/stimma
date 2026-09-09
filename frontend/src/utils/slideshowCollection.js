// Remap loaded pages by identity when a live collection changes. Keep the
// selected item even when an earlier request completes or a later batch starts.
export function reconcileSlideshowCollection(oldIds, newIds, cache, currentIndex) {
  const indices = new Map(newIds.map((id, index) => [id, index]))
  const nextCache = new Map()
  for (const [index, item] of cache) {
    const nextIndex = indices.get(oldIds[index])
    if (nextIndex !== undefined) nextCache.set(nextIndex, item)
  }
  const selectedIndex = indices.get(oldIds[currentIndex])
  return {
    cache: nextCache,
    index: selectedIndex ?? Math.max(0, Math.min(currentIndex, newIds.length - 1)),
    removed: selectedIndex === undefined,
  }
}
