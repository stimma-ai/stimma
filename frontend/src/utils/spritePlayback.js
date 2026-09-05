/** Logical frames survive WebP's merging of consecutive identical images. */
export function spriteFrameIndices(anim, encodedDurations) {
  const count = anim.frameCount
  const mapping = anim.frameIndices
  if (mapping != null) {
    if (!Array.isArray(mapping) || mapping.length !== count
      || mapping.some(i => !Number.isInteger(i) || i < 0 || i >= encodedDurations.length)) {
      throw new Error('Invalid sprite frame mapping')
    }
    return mapping
  }
  if (encodedDurations.length === count) return Array.from({ length: count }, (_, i) => i)
  if (encodedDurations.length === 1) return Array(count).fill(0)
  if (!encodedDurations.length) throw new Error('Sprite has no encoded frames')
  const result = []
  let index = 0
  let elapsed = 0
  let boundary = encodedDurations[0]
  for (let i = 0; i < count; i++) {
    const duration = anim.durations[i] || Math.max(1, Math.round(1000 / anim.fps))
    if (duration <= 0 || elapsed + duration > boundary) {
      throw new Error('Encoded frame boundaries do not match the document timeline')
    }
    result.push(index)
    elapsed += duration
    if (elapsed === boundary && index + 1 < encodedDurations.length) {
      boundary += encodedDurations[++index]
    }
  }
  if (elapsed !== encodedDurations.reduce((a, b) => a + b, 0)) {
    throw new Error('Encoded duration does not match the document timeline')
  }
  return result
}

/** Advance within the loop span without duplicating ping-pong endpoints. */
export function nextSpriteFrame({ index, direction, first, last, looping, mode }) {
  if (!looping) {
    return { index: Math.min(index + 1, last), direction: 1, playing: index < last }
  }
  if (mode === 'pingpong' && first < last) {
    if (index >= last) direction = -1
    else if (index <= first) direction = 1
    return { index: index + direction, direction, playing: true }
  }
  return { index: index >= last ? first : index + 1, direction: 1, playing: true }
}
