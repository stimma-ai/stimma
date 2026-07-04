export function diffInsertedLiveIds(newIds, oldIds) {
  if (!Array.isArray(newIds) || !Array.isArray(oldIds)) return []

  const known = new Set(oldIds)
  const inserted = []
  for (let index = 0; index < newIds.length; index += 1) {
    const key = newIds[index]
    if (known.has(key)) continue
    inserted.push({ key, index })
  }
  return inserted
}

export function shouldQueueLiveArrival({ currentIndex, insertIndex, followStream, randomized }) {
  if (!Number.isFinite(currentIndex) || !Number.isFinite(insertIndex)) return false
  if (insertIndex < 0 || randomized || !followStream) return false
  return currentIndex >= insertIndex
}

export function orderLiveAdvanceCandidates(candidates) {
  return [...candidates].sort((a, b) => b.index - a.index)
}

export function orderLiveAdvanceKeys(keys, providerOrderIds) {
  if (!Array.isArray(keys) || !Array.isArray(providerOrderIds)) return []

  const seen = new Set()
  const uniqueKeys = []
  for (const key of keys) {
    if (seen.has(key)) continue
    seen.add(key)
    uniqueKeys.push(key)
  }

  return uniqueKeys
    .map(key => ({ key, index: providerOrderIds.indexOf(key) }))
    .filter(item => item.index >= 0)
    .sort((a, b) => b.index - a.index)
    .map(item => item.key)
}
