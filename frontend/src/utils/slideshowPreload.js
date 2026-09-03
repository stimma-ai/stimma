/**
 * Return nearby slideshow positions in the order they should be warmed.
 *
 * The direction the person most recently moved is the best predictor of the
 * next key press (and of Play mode), but keeping one item warm behind them
 * makes reversing direction instant too. The caller controls the small
 * budget so full-resolution files cannot turn preloading into a bulk download.
 */
export function nearbyPreloadIndices(currentIndex, totalCount, direction = 1, limit = 3) {
  if (!Number.isFinite(currentIndex) || !Number.isFinite(totalCount) || totalCount <= 1 || limit <= 0) {
    return []
  }

  const primaryDirection = direction < 0 ? -1 : 1
  const candidates = []
  for (let distance = 1; candidates.length < limit && distance < totalCount; distance += 1) {
    for (const delta of [primaryDirection * distance, -primaryDirection * distance]) {
      const index = currentIndex + delta
      if (index < 0 || index >= totalCount || candidates.includes(index)) continue
      candidates.push(index)
      if (candidates.length === limit) break
    }
  }
  return candidates
}
