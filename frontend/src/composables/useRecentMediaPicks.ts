import { makeStorageKey } from '../utils/storageKeys'
import type { RecentInputKind } from './useRecentMediaInputs'

/**
 * Recently-picked media backing the picker popover's "Recents" tab.
 *
 * Distinct from useRecentMediaInputs: that store covers every entry path into
 * a MediaPicker slot (drag, send-to, popover) and ranks by frecency for the
 * blended "All" tab. This one records only picks made through the popover
 * itself and keeps plain last-picked-first order.
 *
 * Scope: profile (via the db-guid key, which also keeps media ids from
 * resurfacing after a database reset) plus optional project — the same media
 * thrown between tools should surface in every tool's popover, so tool id and
 * tool instance are deliberately NOT part of the key.
 */

export interface RecentMediaPick {
  mediaId: number
  fileHash: string
  fileFormat: string
  kind: RecentInputKind
  pickedAt: number // epoch ms
}

const MAX_ENTRIES = 60

function storageKey(projectId: number | null): string {
  return makeStorageKey('media_picker', 'recent_picks', projectId == null ? 'global' : `project_${projectId}`)
}

function load(projectId: number | null): RecentMediaPick[] {
  try {
    const raw = localStorage.getItem(storageKey(projectId))
    if (!raw) return []
    const parsed = JSON.parse(raw)
    return Array.isArray(parsed) ? parsed : []
  } catch {
    return []
  }
}

function save(projectId: number | null, entries: RecentMediaPick[]) {
  try {
    localStorage.setItem(storageKey(projectId), JSON.stringify(entries))
  } catch {}
}

/** Record a pick made through the popover. */
export function recordMediaPick(
  input: { mediaId: number; fileHash: string; fileFormat: string; kind: RecentInputKind },
  projectId: number | null,
) {
  if (!input.mediaId || !input.fileHash) return
  const entries = load(projectId).filter(e => e.mediaId !== input.mediaId)
  entries.unshift({ ...input, pickedAt: Date.now() })
  if (entries.length > MAX_ENTRIES) entries.length = MAX_ENTRIES
  save(projectId, entries)
}

/** Drop an entry everywhere (e.g. its media 404s when picked). */
export function removeRecentMediaPick(mediaId: number) {
  // Entries live in one key per project scope — sweep every scope's key.
  const prefix = storageKey(null).replace(/_global$/, '')
  for (let i = localStorage.length - 1; i >= 0; i--) {
    const key = localStorage.key(i)
    if (!key || !key.startsWith(prefix)) continue
    try {
      const parsed = JSON.parse(localStorage.getItem(key) || '[]')
      if (!Array.isArray(parsed)) continue
      const remaining = parsed.filter((e: RecentMediaPick) => e.mediaId !== mediaId)
      if (remaining.length !== parsed.length) localStorage.setItem(key, JSON.stringify(remaining))
    } catch {}
  }
}

/** Recently-picked media of the given kinds for a project scope, newest first. */
export function recentMediaPicks(kinds: RecentInputKind[], projectId: number | null, limit = 30): RecentMediaPick[] {
  const kindSet = new Set(kinds)
  return load(projectId)
    .filter(e => kindSet.has(e.kind))
    .sort((a, b) => b.pickedAt - a.pickedAt)
    .slice(0, limit)
}
