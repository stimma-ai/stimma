/** An element's kind as people read it: "character" → "Character". Empty stays empty. */
export function kindLabel(kind: string | null | undefined): string {
  const k = (kind || '').trim()
  return k ? k[0].toUpperCase() + k.slice(1) : ''
}
