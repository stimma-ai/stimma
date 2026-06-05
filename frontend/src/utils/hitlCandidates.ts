// Shared candidate normalization + identity matching for hitl.select UIs.
// Used by HitlBrowseSheet, HitlSelectInline, and CompletedSelectPanel so the
// three surfaces stay in sync about what counts as the "same" candidate
// (media_id match, url match, etc.) and how to render labels/thumbs.

export interface NormalizedCandidate {
  key: string
  mediaId: number | null
  mediaUrl: string | null
  label: string
  value: any
  identities: Set<string>
}

export function normalizeCandidate(c: any, idx: number): NormalizedCandidate {
  if (typeof c === 'number') {
    return {
      key: String(c),
      mediaId: c,
      mediaUrl: null,
      label: `#${c}`,
      value: c,
      identities: identitiesFor(c, idx),
    }
  }
  if (typeof c === 'string') {
    return {
      key: c,
      mediaId: null,
      mediaUrl: null,
      label: c,
      value: c,
      identities: identitiesFor(c, idx),
    }
  }
  if (c && typeof c === 'object') {
    const mid = c.media_id ?? c.mediaId ?? c.id ?? null
    const media = c.media && typeof c.media === 'object' ? c.media : null
    const urlMedia = isUrlMedia(media) ? media : (isUrlMedia(c) ? c : null)
    const mediaUrl = firstString(urlMedia?.url, urlMedia?.image_url, media?.source_url, c.image_url, c.url)
    return {
      key: String(mid ?? mediaUrl ?? c.key ?? idx),
      mediaId: typeof mid === 'number' ? mid : null,
      mediaUrl,
      label: c.label || c.name || c.title || (mid != null ? `#${mid}` : String(idx + 1)),
      value: c,
      identities: identitiesFor(c, idx),
    }
  }
  return {
    key: String(idx),
    mediaId: null,
    mediaUrl: null,
    label: String(idx + 1),
    value: c,
    identities: identitiesFor(c, idx),
  }
}

export function identitiesFor(value: any, idx: number): Set<string> {
  const ids = new Set<string>()
  const add = (kind: string, raw: any) => {
    if (raw == null) return
    const text = String(raw).trim()
    if (text) ids.add(`${kind}:${text}`)
  }
  if (typeof value === 'number' || typeof value === 'string') {
    add('value', value)
    return ids
  }
  if (value && typeof value === 'object') {
    const media = value.media && typeof value.media === 'object' ? value.media : null
    add('media', value.media_id ?? value.mediaId ?? value.id)
    add('key', value.key)
    add('url', value.url)
    add('url', value.image_url)
    add('url', media?.url)
    add('url', media?.image_url)
    add('url', media?.source_url)
    return ids
  }
  add('index', idx)
  return ids
}

export function valuesEquivalent(a: any[], b: any[]): boolean {
  if (a.length !== b.length) return false
  const used = new Set<number>()
  return a.every((av) => {
    const ai = identitiesFor(av, 0)
    const match = b.findIndex((bv, idx) => {
      if (used.has(idx)) return false
      return setsOverlap(ai, identitiesFor(bv, 0))
    })
    if (match < 0) return false
    used.add(match)
    return true
  })
}

export function setsOverlap(a: Set<string>, b: Set<string>): boolean {
  for (const item of a) {
    if (b.has(item)) return true
  }
  return false
}

export function firstString(...values: any[]): string | null {
  for (const value of values) {
    if (typeof value === 'string' && value.trim()) return value
  }
  return null
}

export function isUrlMedia(value: any): boolean {
  if (!value || typeof value !== 'object') return false
  const kind = value.type || value.media_type
  return ['url_media', 'remote_media', 'url'].includes(kind)
    && typeof value.url === 'string'
    && value.url.length > 0
}

// Build a Set of identity strings from a list of selected raw values, for
// fast lookup when checking whether a candidate is currently picked.
export function buildSelectedIdSet(values: any[]): Set<string> {
  const set = new Set<string>()
  for (const value of values) {
    for (const id of identitiesFor(value, 0)) set.add(id)
  }
  return set
}

export function isCandidatePicked(c: NormalizedCandidate, picked: Set<string>): boolean {
  for (const id of c.identities) {
    if (picked.has(id)) return true
  }
  return false
}
