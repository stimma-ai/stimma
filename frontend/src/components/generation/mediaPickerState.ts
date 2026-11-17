/**
 * The media picker popover's sticky view: which feed, which markers, the
 * prompt filter, the sort and where the list was scrolled. One value per
 * profile, shared by every picker, so the next open lands where the last one
 * left off.
 */

export type PickerFeed = 'used' | 'all' | 'generated' | 'imported'
export type PickerSort = 'created_desc' | 'created_asc' | 'indexed_desc' | 'edited_desc' | 'random'

export interface PickerViewState {
  feed: PickerFeed
  /** Any-of marker filter, combined with the feed. */
  markerIds: number[]
  /** Prompt filter (the browser's `prompt_query`). */
  query: string
  searchOpen: boolean
  sort: PickerSort
  /** Seed for the random sort, so paging and reopening keep one order. */
  seed: number
  /** Scroll offset of the list, valid only for the view named by scrollKey. */
  scrollTop: number
  scrollKey: string
}

export const PICKER_FEEDS: Array<{ key: PickerFeed; label: string }> = [
  { key: 'used', label: 'Used before' },
  { key: 'all', label: 'All' },
  { key: 'generated', label: 'Generated' },
  { key: 'imported', label: 'Imported' },
]

export const PICKER_SORTS: Array<{ value: PickerSort; label: string; triggerLabel?: string }> = [
  { value: 'created_desc', label: 'Newest first', triggerLabel: 'Newest' },
  { value: 'created_asc', label: 'Oldest first', triggerLabel: 'Oldest' },
  { value: 'indexed_desc', label: 'Recently imported', triggerLabel: 'Imported' },
  { value: 'edited_desc', label: 'Recently edited', triggerLabel: 'Edited' },
  { value: 'random', label: 'Random' },
]

const FEED_KEYS = new Set<string>(PICKER_FEEDS.map(f => f.key))
const SORT_KEYS = new Set<string>(PICKER_SORTS.map(s => s.value))

export function defaultPickerState(feed: PickerFeed = 'all'): PickerViewState {
  return {
    feed,
    markerIds: [],
    query: '',
    searchOpen: false,
    sort: 'created_desc',
    seed: 1,
    scrollTop: 0,
    scrollKey: '',
  }
}

/**
 * Read a stored value, keeping each field that is still valid. Returns null
 * when nothing usable was stored, so the caller can pick a first-run default.
 */
export function parsePickerState(raw: string | null | undefined): PickerViewState | null {
  if (!raw) return null
  let value: any
  try { value = JSON.parse(raw) } catch { return null }
  if (!value || typeof value !== 'object' || !FEED_KEYS.has(value.feed)) return null
  const state = defaultPickerState(value.feed)
  if (Array.isArray(value.markerIds)) {
    state.markerIds = value.markerIds.filter((id: unknown) => Number.isSafeInteger(id))
  }
  if (typeof value.query === 'string') state.query = value.query
  state.searchOpen = value.searchOpen === true
  if (SORT_KEYS.has(value.sort)) state.sort = value.sort
  if (Number.isSafeInteger(value.seed)) state.seed = value.seed
  if (typeof value.scrollTop === 'number' && value.scrollTop >= 0) state.scrollTop = value.scrollTop
  if (typeof value.scrollKey === 'string') state.scrollKey = value.scrollKey
  return state
}

/**
 * Names one list: the feed and everything that narrows or orders it. A saved
 * scroll offset only applies to the list it was taken in.
 */
export function pickerViewKey(state: PickerViewState, accept: string): string {
  const markers = [...state.markerIds].sort((a, b) => a - b).join(',')
  const sort = state.feed === 'used' ? 'used' : state.sort
  const seed = sort === 'random' ? state.seed : ''
  return [accept, state.feed, markers, state.query.trim(), sort, seed].join('|')
}

/** Order "Used before" entries by their last use, newest first, one per media. */
export function mergeUsedBefore<T extends { mediaId: number; usedAt: number }>(...lists: T[][]): T[] {
  const best = new Map<number, T>()
  for (const entry of lists.flat()) {
    const seen = best.get(entry.mediaId)
    if (!seen || entry.usedAt > seen.usedAt) best.set(entry.mediaId, entry)
  }
  return [...best.values()].sort((a, b) => b.usedAt - a.usedAt)
}
