// Where people in Fluent's pictures are from when the prompt doesn't say: one app-wide
// setting on the server (a place's code, or "anywhere").

export const ANYWHERE = 'anywhere'

/** The place a browser locale names: its region ("en-GB" -> "GB") when it is one of `codes`,
    else "anywhere" (a locale with no region, "en", names no place). */
export function placeFromLocale(locale: string | undefined | null, codes: Iterable<string>): string {
  let region = ''
  try {
    region = locale ? (new Intl.Locale(locale).region ?? '') : ''
  } catch {
    region = ''
  }
  const known = new Set(codes)
  return region && known.has(region.toUpperCase()) ? region.toUpperCase() : ANYWHERE
}

/** The picker's options: Anywhere first, then the places by name. */
export function placeOptions(places: { code: string; name: string }[]): { value: string; label: string }[] {
  return [{ value: ANYWHERE, label: 'Anywhere' }, ...places.map(p => ({ value: p.code, label: p.name }))]
}
