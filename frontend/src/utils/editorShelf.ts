/**
 * Shelf rules for open editors: order, capacity, and flyout grouping.
 *
 * An editor tab is a shortcut to an Asset, not a document that needs a name —
 * the op stack persists server-side against the asset, so removing a chip
 * removes the shortcut and nothing else. That makes the shelf a working set
 * rather than a list of things to keep alive, which is why it can be capped:
 * chips past the cap move behind a +N chip instead of growing the sidebar.
 *
 * Pure so the rules are testable without a DOM; see useEditorShelf.ts for the
 * live binding to workspace tabs.
 */

/** Chip edge and gap in px. Mirrors the w-8 / gap-1.5 classes on the shelf. */
export const CHIP_PX = 32
/** Touch target edge: a finger gets the full 44px+ chip. */
export const CHIP_TOUCH_PX = 44
export const CHIP_GAP_PX = 6

/** Rows the shelf may occupy before the rest goes behind +N. */
export const SHELF_ROWS = 2

export interface ShelfEntry {
  tabId: string
  assetId: string
  mediaId?: string
  displayName: string
  pinned: boolean
  /** Stack has edits the version chain doesn't have yet. */
  unsaved: boolean
  /**
   * Last navigation to this editor. Tabs persisted before the shelf existed
   * have no timestamp; they fall back to creation order, which keeps their old
   * relative order and sorts them below anything actually touched since.
   */
  touchedAt: number
  /** When the editor was opened. Newer chips sit before older chips. */
  createdOrder: number
}

/**
 * Chips that fit one row at `widthPx`. The sidebar is resizable, so the shelf
 * measures its own content box rather than assuming a column count.
 */
export function shelfColumns(widthPx: number, chipPx: number = CHIP_PX): number {
  if (!Number.isFinite(widthPx) || widthPx <= 0) return 1
  return Math.max(1, Math.floor((widthPx + CHIP_GAP_PX) / (chipPx + CHIP_GAP_PX)))
}

/**
 * Ranking decides MEMBERSHIP — which chips are on the shelf and which are
 * behind the +N chip. It deliberately does not decide position: pinned first,
 * then unsaved, then most recently touched. Unsaved outranks recency so a
 * half-done edit can't be pushed behind the door by a run of quick opens.
 */
export function rankShelfEntries(entries: ShelfEntry[]): ShelfEntry[] {
  return [...entries].sort((a, b) => (
    Number(b.pinned) - Number(a.pinned) ||
    Number(b.unsaved) - Number(a.unsaved) ||
    b.touchedAt - a.touchedAt
  ))
}

/**
 * Split ranked entries into the chips on the shelf and the ones behind +N.
 * The door costs a slot, so overflow only starts above `capacity`.
 *
 * Pinned entries never overflow. If more are pinned than fit, the shelf grows
 * past its row cap — that growth is user-caused and user-reversible, unlike
 * the automatic population, which is the whole reason the cap exists.
 */
export function splitShelf<T extends { pinned: boolean }>(
  ranked: T[],
  capacity: number,
): { visible: T[], overflow: T[] } {
  const cap = Math.max(1, capacity)
  if (ranked.length <= cap) return { visible: ranked, overflow: [] }
  const pinnedCount = ranked.filter(e => e.pinned).length
  const slots = Math.max(cap - 1, pinnedCount)
  return { visible: ranked.slice(0, slots), overflow: ranked.slice(slots) }
}

/**
 * Display order — separate from ranking on purpose. New editors enter at the
 * front, while clicking an existing one never moves it: activation changes an
 * entry's rank, and rank only decides what's behind the +N chip. A chip moves
 * when shelf membership changes, or when the user pins it. Nothing else.
 */
export function orderForDisplay(entries: ShelfEntry[]): ShelfEntry[] {
  return [...entries].sort((a, b) => (
    Number(b.pinned) - Number(a.pinned) ||
    b.createdOrder - a.createdOrder
  ))
}

/**
 * Flyout order: most recently touched first, and nothing else. Date headings
 * and an unsaved-first bucket were more structure than a grid of thumbnails
 * needs — you're looking for a picture you recognize, not running a query.
 */
export function orderByRecency(entries: ShelfEntry[]): ShelfEntry[] {
  return [...entries].sort((a, b) => b.touchedAt - a.touchedAt)
}
