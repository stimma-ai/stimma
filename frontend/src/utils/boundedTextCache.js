// Per-view LRU. Bound both entry count and retained text so streaming revisions
// and unusually large tool outputs cannot grow the cache indefinitely.
export function createBoundedTextCache(maxEntries = 2048, maxCharacters = 8 * 1024 * 1024) {
  const entries = new Map()
  let characters = 0
  return {
    get(key, compute) {
      const hit = entries.get(key)
      if (hit) {
        entries.delete(key)
        entries.set(key, hit)
        return hit.value
      }
      const value = compute()
      const valueSize = typeof value === 'string'
        ? value.length
        : value.reduce((size, segment) => size + (segment.content?.length || 16), 0)
      const size = key.length + valueSize
      if (size > maxCharacters) return value
      while (entries.size && (entries.size >= maxEntries || characters + size > maxCharacters)) {
        const oldest = entries.keys().next().value
        characters -= entries.get(oldest).size
        entries.delete(oldest)
      }
      entries.set(key, { value, size })
      characters += size
      return value
    },
    clear() {
      entries.clear()
      characters = 0
    },
  }
}
