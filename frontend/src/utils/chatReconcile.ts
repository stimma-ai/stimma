// Merge a fresh server snapshot of a chat's recent items into the loaded
// transcript after a gap in live updates (socket reconnect, KeepAlive
// reactivation).
//
// Chat items carry no version field, so matching IDs prove nothing: an item
// can complete, fail, or be edited in place while the client is away. Each
// returned item is therefore compared by content and replaced when it differs.
//
// The snapshot covers only the newest window of the chat, so absence from it
// proves deletion only inside that window. Older history loaded by paging is
// kept as-is; deletions there are not detected (no tombstones exist yet).
// When the history known to be contiguous (see coveredThrough) does not reach
// the snapshot window, it is dropped instead, so no unpageable hole is left.
//
// The fetch races live updates. The caller records every live change made
// while the fetch is in flight in a journal (an item, or null for a
// deletion), including changes to items the transcript has not loaded yet.
// Journaled changes are newer than the snapshot and always win.

export interface ChatItemLike {
  id: number
}

export type LiveJournal<T> = Map<number, T | null>

export interface ReconcileOptions<T extends ChatItemLike> {
  // The server has items older than the snapshot's oldest one.
  hasMore: boolean
  // IDs of the transcript's items when the fetch was issued.
  before: Set<number>
  // Live changes since the fetch was issued: the newest item, or null if deleted.
  journal: LiveJournal<T>
  // Coverage: the newest item ID the transcript is known to hold contiguous
  // server history up to. Only server responses (the initial load, applied
  // snapshots) advance it; live appends never do, because a socket gap can
  // hide items before them. -Infinity when nothing is covered.
  coveredThrough: number
}

export interface ReconcileResult<T> {
  items: T[]
  changed: boolean
  // Coverage after applying this snapshot.
  coveredThrough: number
  // Whether any history older than the snapshot's first item remains. If not,
  // the server's has_more describes the transcript's start.
  olderSurvives: boolean
}

// Field-wise comparison with early exit. Most fields are primitives; only
// nested values (metadata, tool args/results, layouts) are serialized.
export function sameChatItem(a: object, b: object): boolean {
  if (a === b) return true
  const left = a as Record<string, unknown>
  const right = b as Record<string, unknown>
  const keys = Object.keys(left)
  if (keys.length !== Object.keys(right).length) return false
  for (const key of keys) {
    const x = left[key]
    const y = right[key]
    if (x === y) continue
    if (x === null || y === null || typeof x !== 'object' || typeof y !== 'object') return false
    try {
      if (JSON.stringify(x) !== JSON.stringify(y)) return false
    } catch {
      return false
    }
  }
  return true
}

function insertById<T extends ChatItemLike>(list: T[], item: T) {
  // New items are almost always the newest; scan from the end.
  let at = list.length
  while (at > 0 && list[at - 1].id > item.id) at--
  list.splice(at, 0, item)
}

// `current` is the transcript now; `fresh` is the snapshot in display order
// (oldest first). Returns `current` itself when nothing changed, and keeps
// the identity of every unchanged item so the view does not re-render it.
export function reconcileChatItems<T extends ChatItemLike>(
  current: T[],
  fresh: T[],
  { hasMore, before, journal, coveredThrough }: ReconcileOptions<T>,
): ReconcileResult<T> {
  // A partial snapshot with no items says nothing about what exists.
  if (hasMore && fresh.length === 0) return { items: current, changed: false, coveredThrough, olderSurvives: true }

  const windowStart = hasMore ? fresh[0].id : Number.NEGATIVE_INFINITY
  const freshById = new Map<number, T>()
  for (const item of fresh) freshById.set(item.id, item)

  // If covered history does not reach a partial snapshot, the snapshot may
  // begin far past it (history grew a lot while away). Keeping both would
  // leave a hole that paging, which only fetches before the oldest loaded
  // item, could never fill. Drop everything older than the snapshot; it
  // becomes the transcript's new start and paging continues from there.
  const disjoint = hasMore && coveredThrough < windowStart

  let changed = false
  const merged: T[] = []
  const present = new Set<number>()
  for (const item of current) {
    if (disjoint && item.id < windowStart) {
      changed = true
      continue
    }
    present.add(item.id)
    if (journal.has(item.id) || !before.has(item.id)) {
      // Changed or added live while the fetch was in flight (or paged in).
      merged.push(item)
      continue
    }
    const server = freshById.get(item.id)
    if (server === undefined) {
      if (item.id >= windowStart) {
        // Inside the snapshot window (or newer than its newest item while
        // already loaded before the fetch): the server no longer has it.
        changed = true
        continue
      }
      merged.push(item)
    } else if (sameChatItem(item, server)) {
      merged.push(item)
    } else {
      merged.push(server)
      changed = true
    }
  }

  for (const item of fresh) {
    if (present.has(item.id)) continue
    // Removed locally while the fetch was in flight.
    if (before.has(item.id)) continue
    if (journal.has(item.id)) {
      // The live path saw a newer version (or a deletion) of an item the
      // transcript had not loaded yet.
      const live = journal.get(item.id)
      if (!live) continue
      insertById(merged, live)
    } else {
      insertById(merged, item)
    }
    changed = true
  }

  // The snapshot is contiguous through its newest item, and joins covered
  // history unless it was disjoint (then the older run is gone).
  const snapshotEnd = fresh.length ? fresh[fresh.length - 1].id : Number.NEGATIVE_INFINITY
  const covered = disjoint || !hasMore ? snapshotEnd : Math.max(coveredThrough, snapshotEnd)
  const freshStart = fresh.length ? fresh[0].id : Number.POSITIVE_INFINITY
  const result = changed ? merged : current
  return {
    items: result,
    changed,
    coveredThrough: covered,
    olderSurvives: result.length > 0 && result[0].id < freshStart,
  }
}
