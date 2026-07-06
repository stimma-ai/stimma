import { makeStorageKey } from '../utils/storageKeys'

/**
 * Recently-used tool inputs with frecency, backing the media picker popover's
 * "Recent" tab.
 *
 * Every library item that lands in a MediaPicker slot funnels through
 * addFromMediaId, which calls recordMediaInputUse here. Entries carry enough
 * to render a thumbnail without a fetch (getThumbnailUrl works off hash), so
 * the Recent tab never needs a per-id lookup.
 *
 * Same storage discipline as useRecentEntities: a small per-db-guid array in
 * localStorage, read/modified/written on each call.
 */

export type RecentInputKind = 'image' | 'video' | 'audio'

export interface RecentMediaInput {
  mediaId: number
  fileHash: string
  fileFormat: string
  kind: RecentInputKind
  lastUsed: number // epoch ms
  count: number
}

const MAX_ENTRIES = 60
// Frecency decay half-life: a use loses half its weight every 3 days.
const HALF_LIFE_MS = 3 * 24 * 60 * 60 * 1000

// makeStorageKey (db-guid scoped), NOT makeProfileKey: entries hold database
// ids, which must not resurface against a different database after a reset.
function storageKey(): string {
  return makeStorageKey('media_picker', 'recent_inputs')
}

function load(): RecentMediaInput[] {
  try {
    const raw = localStorage.getItem(storageKey())
    if (!raw) return []
    const parsed = JSON.parse(raw)
    return Array.isArray(parsed) ? parsed : []
  } catch {
    return []
  }
}

function save(entries: RecentMediaInput[]) {
  try {
    localStorage.setItem(storageKey(), JSON.stringify(entries))
  } catch {}
}

function frecencyScore(entry: RecentMediaInput, now = Date.now()): number {
  const age = Math.max(0, now - entry.lastUsed)
  return entry.count * Math.pow(2, -age / HALF_LIFE_MS)
}

/** Record a library item being used as a tool input. */
export function recordMediaInputUse(input: { mediaId: number; fileHash: string; fileFormat: string; kind: RecentInputKind }) {
  if (!input.mediaId || !input.fileHash) return
  const entries = load()
  const existing = entries.find(e => e.mediaId === input.mediaId)
  if (existing) {
    existing.lastUsed = Date.now()
    existing.count += 1
    // Hash/format can change if the item was edited in place — keep them fresh.
    existing.fileHash = input.fileHash
    existing.fileFormat = input.fileFormat
    existing.kind = input.kind
  } else {
    entries.push({ ...input, lastUsed: Date.now(), count: 1 })
  }
  // Trim the long tail by frecency so a burst of one-off uses can't evict
  // the standbys.
  if (entries.length > MAX_ENTRIES) {
    const now = Date.now()
    entries.sort((a, b) => frecencyScore(b, now) - frecencyScore(a, now))
    entries.length = MAX_ENTRIES
  }
  save(entries)
}

/** Drop an entry (e.g. its media 404s when picked). */
export function removeRecentMediaInput(mediaId: number) {
  const entries = load()
  const remaining = entries.filter(e => e.mediaId !== mediaId)
  if (remaining.length !== entries.length) save(remaining)
}

/** Recently-used inputs of the given kinds, ranked by frecency, best first. */
export function recentMediaInputs(kinds: RecentInputKind[], limit = 30): RecentMediaInput[] {
  const now = Date.now()
  const kindSet = new Set(kinds)
  return load()
    .filter(e => kindSet.has(e.kind))
    .sort((a, b) => frecencyScore(b, now) - frecencyScore(a, now))
    .slice(0, limit)
}
