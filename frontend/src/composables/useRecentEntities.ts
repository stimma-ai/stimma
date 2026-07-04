import { makeStorageKey } from '../utils/storageKeys'

/**
 * Cross-entity recents with frecency, backing the global search omnibox.
 *
 * Every entity open funnels through useWorkspaceTabs.addTab (the sidebar's
 * route watcher creates a tab for each tool/chat/board/project/flow visit),
 * which calls recordEntityVisit here. The omnibox empty state and ranking
 * tie-breaks read recentEntities().
 *
 * Storage is a small per-profile array in localStorage, read/modified/written
 * on each call — no in-memory singleton to keep in sync across profile
 * switches.
 */

export type RecentEntityType = 'tool' | 'chat' | 'board' | 'project' | 'flow'

export interface RecentEntity {
  type: RecentEntityType
  id: string          // entityId: fullToolId for tools, numeric id string otherwise
  name: string
  lastVisited: number // epoch ms
  count: number
}

const MAX_ENTRIES = 60
// Frecency decay half-life: a visit loses half its weight every 3 days.
const HALF_LIFE_MS = 3 * 24 * 60 * 60 * 1000

const RECORDABLE_TYPES: ReadonlySet<string> = new Set(['tool', 'chat', 'board', 'project', 'flow'])

// makeStorageKey (db-guid scoped), NOT makeProfileKey: entries hold database
// ids, which must not resurface against a different database after a reset.
function storageKey(): string {
  return makeStorageKey('global_search', 'recents')
}

function load(): RecentEntity[] {
  try {
    const raw = localStorage.getItem(storageKey())
    if (!raw) return []
    const parsed = JSON.parse(raw)
    return Array.isArray(parsed) ? parsed : []
  } catch {
    return []
  }
}

function save(entries: RecentEntity[]) {
  try {
    localStorage.setItem(storageKey(), JSON.stringify(entries))
  } catch {}
}

export function frecencyScore(entry: RecentEntity, now = Date.now()): number {
  const age = Math.max(0, now - entry.lastVisited)
  return entry.count * Math.pow(2, -age / HALF_LIFE_MS)
}

/**
 * Record a visit to an entity. `name` updates the cached display name when
 * it's a real name (callers often only have the raw id on first visit).
 */
export function recordEntityVisit(type: RecentEntityType, id: string, name?: string) {
  if (!RECORDABLE_TYPES.has(type) || !id) return
  const entries = load()
  const existing = entries.find(e => e.type === type && e.id === id)
  if (existing) {
    existing.lastVisited = Date.now()
    existing.count += 1
    if (name && name !== id) existing.name = name
  } else {
    entries.push({
      type,
      id,
      name: name && name !== id ? name : '',
      lastVisited: Date.now(),
      count: 1,
    })
  }
  // Trim the long tail by frecency so a burst of one-off visits can't evict
  // the standbys.
  if (entries.length > MAX_ENTRIES) {
    const now = Date.now()
    entries.sort((a, b) => frecencyScore(b, now) - frecencyScore(a, now))
    entries.length = MAX_ENTRIES
  }
  save(entries)
}

/** Backfill a display name (entity names often resolve after navigation). */
export function updateRecentEntityName(type: RecentEntityType, id: string, name: string) {
  if (!RECORDABLE_TYPES.has(type) || !id || !name || name === id) return
  const entries = load()
  const existing = entries.find(e => e.type === type && e.id === id)
  if (existing && existing.name !== name) {
    existing.name = name
    save(entries)
  }
}

/** Drop an entity from recents (e.g. it was deleted and navigation 404s). */
export function removeRecentEntity(type: RecentEntityType, id: string) {
  const entries = load()
  const remaining = entries.filter(e => !(e.type === type && e.id === id))
  if (remaining.length !== entries.length) save(remaining)
}

/** Recents ranked by frecency, best first. */
export function recentEntities(limit = 8): RecentEntity[] {
  const now = Date.now()
  return load()
    .filter(e => e.name) // nameless entries render badly; names backfill fast
    .sort((a, b) => frecencyScore(b, now) - frecencyScore(a, now))
    .slice(0, limit)
}

/** Frecency score lookup used to break ranking ties in search results. */
export function frecencyFor(type: RecentEntityType, id: string): number {
  const entry = load().find(e => e.type === type && e.id === id)
  return entry ? frecencyScore(entry) : 0
}
