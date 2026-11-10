// The chat dock's rules, as plain functions (see composables/useChatDock.ts).

export type DockWin = 'row' | 'open'

export interface DockEntry {
  chatId: number
  win: DockWin
  /** When it was docked (or brought to the corner): the newest sits in the corner. */
  at: number
}

export const MAX_OPEN = 2

/** What a stored dock document holds, cleaned: one entry per chat. */
export function sanitizeDock(raw: unknown, now = Date.now()): DockEntry[] {
  const list = (raw && typeof raw === 'object' && Array.isArray((raw as any).entries)) ? (raw as any).entries : []
  const seen = new Set<number>()
  const out: DockEntry[] = []
  for (const e of list) {
    const chatId = Number(e?.chatId)
    if (!Number.isFinite(chatId) || seen.has(chatId)) continue
    seen.add(chatId)
    out.push({
      chatId,
      win: e?.win === 'open' ? 'open' : 'row',
      at: Number.isFinite(e?.at) ? e.at : now,
    })
  }
  return out
}

/**
 * At most `max` windows open at once, not counting `keep` (the one being
 * opened) or the chat on screen full size (its window steps aside). The
 * oldest open ones fold to rows. Returns the new entries and who folded.
 */
export function foldOpenWindows(entries: DockEntry[], keep: number, onScreen: number | null, max = MAX_OPEN) {
  const open = entries
    .filter(e => e.win === 'open' && e.chatId !== keep && e.chatId !== onScreen)
    .sort((a, b) => b.at - a.at)
  const folded = new Set(open.slice(max - 1).map(e => e.chatId))
  return {
    entries: folded.size ? entries.map(e => folded.has(e.chatId) ? { ...e, win: 'row' as DockWin } : e) : entries,
    folded: [...folded],
  }
}

export interface DockLayout {
  rowWidth: number
  shown: number[]
  hidden: number[]
}

export const DOCK_SIZES = { row: 264, narrowRow: 196, open: 380, gap: 8, edge: 16, more: 88 }

/**
 * Fit docked chats (newest first) along `width`: open windows at full width,
 * rows at full width if there's room for all of them, else narrower; only
 * then does the rest fold into "+N more".
 */
export function fitDock(visible: Pick<DockEntry, 'chatId' | 'win'>[], width: number, sizes = DOCK_SIZES): DockLayout {
  const opens = visible.filter(e => e.win === 'open').length
  const rows = visible.length - opens
  const room = width - sizes.edge * 2 - opens * (sizes.open + sizes.gap)
  const rowWidth = rows && room < rows * (sizes.row + sizes.gap) ? sizes.narrowRow : sizes.row
  const shown: number[] = []
  let used = sizes.edge * 2
  for (const [i, e] of visible.entries()) {
    const w = (e.win === 'open' ? sizes.open : rowWidth) + sizes.gap
    const reserve = i + 1 < visible.length ? sizes.more : 0
    if (shown.length && used + w + reserve > width) break
    shown.push(e.chatId)
    used += w
  }
  const shownSet = new Set(shown)
  return { rowWidth, shown, hidden: visible.filter(e => !shownSet.has(e.chatId)).map(e => e.chatId) }
}
