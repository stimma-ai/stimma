/** H3 Image takes image prose, while H3 Video uses audiovisual Context-IR. */
export function isMiniMaxH3VideoModel(model: string | null | undefined): boolean {
  const name = model || ''
  const h3 = /(?:minimax[\s._-]*h3|hailuo[\s._-]*(?:h3|0?3|3(?:\.0)?))/i
  const image = /(?:minimax[\s._-]*h3|hailuo[\s._-]*(?:h3|0?3|3(?:\.0)?))[\s._-]*image/i
  return h3.test(name) && !image.test(name)
}
