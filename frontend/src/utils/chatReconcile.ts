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
//
// The fetch races live updates. `before` holds the transcript's items as they
// were when the fetch started; anything the live path added, replaced, or
// removed since then is newer than the snapshot and wins.

export interface ChatItemLike {
  id: number
}

export interface ReconcileOptions<T extends ChatItemLike> {
  // The server has items older than the snapshot's oldest one.
  hasMore: boolean
  // The transcript's items, by ID, at the moment the fetch was issued.
  before: Map<number, T>
}

export interface ReconcileResult<T> {
  items: T[]
  changed: boolean
}

function sameContent(a: unknown, b: unknown): boolean {
  if (a === b) return true
  try {
    return JSON.stringify(a) === JSON.stringify(b)
  } catch {
    return false
  }
}

// `current` is the transcript now; `fresh` is the snapshot in display order
// (oldest first). Returns `current` itself when nothing changed, and keeps
// the identity of every unchanged item so the view does not re-render it.
export function reconcileChatItems<T extends ChatItemLike>(
  current: T[],
  fresh: T[],
  { hasMore, before }: ReconcileOptions<T>,
): ReconcileResult<T> {
  // A partial snapshot with no items says nothing about what exists.
  if (hasMore && fresh.length === 0) return { items: current, changed: false }

  const windowStart = hasMore ? fresh[0].id : Number.NEGATIVE_INFINITY
  const freshById = new Map<number, T>()
  for (const item of fresh) freshById.set(item.id, item)

  let changed = false
  const merged: T[] = []
  const present = new Set<number>()
  for (const item of current) {
    present.add(item.id)
    const touchedSinceFetch = before.get(item.id) !== item
    if (touchedSinceFetch) {
      // Arrived or was replaced live while the fetch was in flight.
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
    } else if (sameContent(item, server)) {
      merged.push(item)
    } else {
      merged.push(server)
      changed = true
    }
  }

  for (const item of fresh) {
    if (present.has(item.id)) continue
    // Removed locally while the fetch was in flight (live delete, retry).
    if (before.has(item.id)) continue
    const at = merged.findIndex(existing => existing.id > item.id)
    if (at === -1) merged.push(item)
    else merged.splice(at, 0, item)
    changed = true
  }

  return changed ? { items: merged, changed } : { items: current, changed }
}
