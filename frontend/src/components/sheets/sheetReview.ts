/**
 * The review every picture on a contact sheet takes without the agent adding
 * anything: a quick rating (thumbs, or stars when the sheet asks for them) and
 * the labels the sheet defines. Comments are separate rows.
 *
 * The sheet only chooses the style and the labels: once for the sheet with
 * <stimma-review rating labels>, or for one section with the same attributes.
 */
/** 'none' is a section's off switch: its pictures aren't up for judgment. */
export type RatingStyle = 'thumbs' | 'stars' | 'none'

export interface MediaReview {
  thumb?: 'up' | 'down'
  stars?: number
  labels?: string[]
}

/** The overall feedback answer's anchor: the sheet itself. */
export const SHEET_ANCHOR = 'sheet'
export const MAX_LABELS = 8
export const MAX_LABEL_LENGTH = 32

export function parseRatingStyle(value: unknown, allowNone = false): RatingStyle {
  const style = String(value ?? '').trim().toLowerCase()
  if (style === 'none' && allowNone) return 'none'
  return style === 'stars' ? 'stars' : 'thumbs'
}

export function parseLabels(value: unknown): string[] {
  const out: string[] = []
  for (const part of String(value ?? '').split(',')) {
    const label = part.trim().replace(/\s+/g, ' ').slice(0, MAX_LABEL_LENGTH).trim()
    if (label && !out.includes(label)) out.push(label)
  }
  return out.slice(0, MAX_LABELS)
}

/** A stored answer as a picture's review; anything else reads as no review. */
export function readMediaReview(value: unknown): MediaReview {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return {}
  const raw = value as Record<string, unknown>
  const out: MediaReview = {}
  if (raw.thumb === 'up' || raw.thumb === 'down') out.thumb = raw.thumb
  const stars = Math.round(Number(raw.stars))
  if (stars >= 1 && stars <= 5) out.stars = stars
  if (Array.isArray(raw.labels)) {
    const labels = raw.labels.map(String).filter(Boolean)
    if (labels.length) out.labels = labels
  }
  return out
}

/** The review with a change applied. Only what is set is kept, so clearing everything leaves {}. */
export function patchMediaReview(current: MediaReview, patch: { thumb?: 'up' | 'down' | null; stars?: number | null; labels?: string[] }): MediaReview {
  const next: MediaReview = { ...current }
  if ('thumb' in patch) patch.thumb ? (next.thumb = patch.thumb) : delete next.thumb
  if ('stars' in patch) patch.stars ? (next.stars = patch.stars) : delete next.stars
  if ('labels' in patch) patch.labels?.length ? (next.labels = [...patch.labels]) : delete next.labels
  return next
}

export function isEmptyAnswer(value: unknown): boolean {
  if (value == null || value === false || value === '' || value === 0) return true
  if (Array.isArray(value)) return value.length === 0
  if (typeof value === 'object') return Object.values(value as object).every(isEmptyAnswer)
  return false
}
