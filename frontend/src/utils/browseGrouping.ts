/**
 * Group by in the Assets browser: the choices, when grouping is available,
 * how a server group becomes a grid section (title, span, count, fold), the
 * remembered folds, and the reload pacing for live updates.
 *
 * The server owns membership and order (`/api/assets/browse/groups`); this
 * module only names and folds what it returns.
 */
import { formatDate, formatDayLabel, formatDaySpan, formatMonthLabel, parseServerTime } from './timeFormat.js'
import { sectionIndexOf, type GridSection } from './groupedRows.ts'

export type GroupBy = 'auto' | 'theme' | 'day' | 'month' | 'project' | 'none'

export const GROUP_BY_OPTIONS: { value: GroupBy, label: string }[] = [
  { value: 'auto', label: 'Auto' },
  { value: 'theme', label: 'Theme' },
  { value: 'day', label: 'Day' },
  { value: 'month', label: 'Month' },
  { value: 'project', label: 'Project' },
  { value: 'none', label: 'None' },
]

export const DEFAULT_GROUP_BY: GroupBy = 'auto'

export function isGroupBy(value: unknown): value is GroupBy {
  return GROUP_BY_OPTIONS.some(option => option.value === value)
}

/** The trigger's label: "Group by auto", or "No grouping". */
export function groupByTriggerLabel(groupBy: GroupBy): string {
  if (groupBy === 'none') return 'No grouping'
  const option = GROUP_BY_OPTIONS.find(o => o.value === groupBy)
  return `Group by ${(option?.label || groupBy).toLowerCase()}`
}

/** Thumbnail size slider: the minimum tile width in px. */
export const TILE_MIN = { min: 120, max: 360, default: 200 } as const

export function clampTileMin(value: unknown): number {
  const n = Number(value)
  if (!Number.isFinite(n)) return TILE_MIN.default
  return Math.round(Math.min(TILE_MIN.max, Math.max(TILE_MIN.min, n)))
}

interface SortAndSimilarity {
  sortBy?: string
  similarTo?: unknown[]
  similarFaceTo?: unknown[]
  similarToText?: string
}

/**
 * Why grouping can't apply to this list, or null. Similarity search and random
 * order are answered ungrouped by the server.
 */
export function groupingUnavailableReason(filters: SortAndSimilarity, similarSearchActive = false): string | null {
  const similarity = similarSearchActive
    || filters.sortBy === 'similarity'
    || (filters.similarTo?.length ?? 0) > 0
    || (filters.similarFaceTo?.length ?? 0) > 0
    || !!filters.similarToText?.trim()
  if (similarity) return 'Not available with similarity search'
  if (filters.sortBy === 'random') return 'Not available in random order'
  return null
}

/** Minutes east of UTC, as the server's `tz_offset` wants it. */
export function localTzOffset(date = new Date()): number {
  return -date.getTimezoneOffset()
}

export interface AssetGroup {
  key: string
  title: string | null
  project_id: number | null
  first_at: string | null
  last_at: string | null
  count: number
  total: number
  offset: number
  refs?: Record<string, unknown>[]
}

export interface AssetGroupsResponse {
  groups: AssetGroup[]
  total: number
  pending: number
  grouping_version: string | null
  grouped: boolean
}

export const PENDING_GROUP = '__pending'

/** A group with nothing new in this long starts folded. */
export const FOLD_STALE_MS = 48 * 3600 * 1000

/** Fold choices remembered per device, most recent last. */
export type FoldState = 'open' | 'folded'
export const FOLD_MEMORY_CAP = 500

export function rememberFolds(
  folds: Map<string, FoldState>,
  changes: [string, FoldState][],
  cap = FOLD_MEMORY_CAP,
): Map<string, FoldState> {
  const next = new Map(folds)
  for (const [key, state] of changes) {
    next.delete(key)
    next.set(key, state)
  }
  while (next.size > cap) next.delete(next.keys().next().value as string)
  return next
}

export function parseFolds(raw: string | null): Map<string, FoldState> {
  if (!raw) return new Map()
  try {
    const entries = JSON.parse(raw)
    if (!Array.isArray(entries)) return new Map()
    return new Map(entries.filter((entry): entry is [string, FoldState] =>
      Array.isArray(entry) && typeof entry[0] === 'string' && (entry[1] === 'open' || entry[1] === 'folded')))
  } catch {
    return new Map()
  }
}

export function serializeFolds(folds: Map<string, FoldState>): string {
  return JSON.stringify([...folds.entries()])
}

export function isGroupOpen(group: AssetGroup, folds: Map<string, FoldState>, now: number): boolean {
  const remembered = folds.get(group.key)
  if (remembered) return remembered === 'open'
  const last = parseServerTime(group.last_at)
  return !last || now - last < FOLD_STALE_MS
}

/** A day or month key ("2026-11-03", "2026-11") as a local date. */
function keyDate(key: string): Date | null {
  const match = key.match(/^(\d{4})-(\d{2})(?:-(\d{2}))?$/)
  if (!match) return null
  return new Date(Number(match[1]), Number(match[2]) - 1, match[3] ? Number(match[3]) : 1, 12)
}

export function groupTitle(group: AssetGroup, groupBy: GroupBy, now = new Date()): string {
  if (group.key === PENDING_GROUP) return group.title || 'New'
  if (groupBy === 'day' || groupBy === 'month') {
    const date = keyDate(group.key)
    if (date) return groupBy === 'day' ? formatDayLabel(date, now) : formatMonthLabel(date)
  }
  return group.title || 'Untitled'
}

/** What sits beside the title: the span, unless the title is a time already. */
export function groupSub(group: AssetGroup, groupBy: GroupBy, now = new Date()): string {
  if (groupBy === 'day' || groupBy === 'month') {
    const date = keyDate(group.key)
    if (!date) return ''
    if (groupBy === 'month') return String(date.getFullYear())
    // "Today", "Yesterday" and weekdays get the date; "Tue Nov 3" already has it.
    return /\s/.test(formatDayLabel(date, now)) ? '' : formatDate(date)
  }
  const first = parseServerTime(group.first_at)
  const last = parseServerTime(group.last_at)
  if (!first || !last) return ''
  return formatDaySpan(new Date(first), new Date(last), now)
}

/** "29", or "6 of 29" when filters narrow the group. */
export function groupCountLabel(group: AssetGroup, filtering: boolean): string {
  return filtering && group.total > group.count ? `${group.count} of ${group.total}` : String(group.count)
}

export interface BrowseSection extends GridSection {
  sub: string
  countLabel: string
  total: number
  refs: Record<string, unknown>[]
  projectId: number | null
  projectName: string | null
  /** Where a revisit's "Made from" frames live: their home group. */
  home: { key: string, label: string } | null
}

export interface SectionOptions {
  groupBy: GroupBy
  folds: Map<string, FoldState>
  now: number
  filtering: boolean
  /** Project names for the header dot's label; omit to hide the dot. */
  projectName?: (id: number) => string | null
}

export function toSections(groups: AssetGroup[], options: SectionOptions): BrowseSection[] {
  const now = new Date(options.now)
  const byKey = new Map(groups.map(group => [group.key, group]))
  return groups.map(group => {
    const refs = group.refs || []
    let home: BrowseSection['home'] = null
    if (refs.length) {
      // Each ref names its home group (the server's `home_key`).
      const homeKey = refs.map(ref => (ref as { home_key?: string | null }).home_key).find(Boolean)
      const homeGroup = homeKey && homeKey !== group.key ? byKey.get(homeKey) : undefined
      if (homeGroup) {
        const when = parseServerTime(homeGroup.last_at)
        const title = groupTitle(homeGroup, options.groupBy, now)
        home = { key: homeGroup.key, label: when ? `${title}, ${formatDate(new Date(when))}` : title }
      }
    }
    const showDot = options.projectName && options.groupBy !== 'project' && group.project_id != null
    return {
      key: group.key,
      title: groupTitle(group, options.groupBy, now),
      sub: groupSub(group, options.groupBy, now),
      countLabel: groupCountLabel(group, options.filtering),
      count: group.count,
      total: group.total,
      offset: group.offset,
      refs,
      open: isGroupOpen(group, options.folds, options.now),
      projectId: group.project_id,
      projectName: showDot ? (options.projectName!(group.project_id!) ?? 'Project') : null,
      home,
    }
  })
}

export type ReloadReason = 'created' | 'groups'

/**
 * Paces grouped reloads from live events. [Sol S5]
 * - A new asset ('created') reloads 500 ms after the last one.
 * - Grouping progress ('groups') reloads at most once every 3 s.
 * One run reloads both the sections and the pages, and never overlaps itself.
 */
export function createGroupedReloadScheduler(options: {
  run: () => Promise<void>
  debounceMs?: number
  minIntervalMs?: number
  now?: () => number
  setTimer?: (fn: () => void, ms: number) => unknown
  clearTimer?: (handle: unknown) => void
}) {
  const debounceMs = options.debounceMs ?? 500
  const minIntervalMs = options.minIntervalMs ?? 3000
  const now = options.now ?? (() => Date.now())
  const setTimer = options.setTimer ?? ((fn, ms) => setTimeout(fn, ms))
  const clearTimer = options.clearTimer ?? (handle => clearTimeout(handle as ReturnType<typeof setTimeout>))
  let timer: unknown = null
  let dueAt = 0
  let lastRunAt = -Infinity
  let running = false
  let again: ReloadReason | null = null

  function schedule(at: number) {
    if (timer != null) clearTimer(timer)
    dueAt = at
    timer = setTimer(fire, Math.max(0, at - now()))
  }

  async function fire() {
    timer = null
    if (running) { again = again ?? 'created'; return }
    running = true
    lastRunAt = now()
    try {
      await options.run()
    } finally {
      running = false
      if (again) {
        const reason = again
        again = null
        request(reason)
      }
    }
  }

  function request(reason: ReloadReason) {
    if (running) { again = reason === 'created' || again === 'created' ? 'created' : 'groups'; return }
    const t = now()
    if (reason === 'created') {
      schedule(t + debounceMs)
      return
    }
    const at = Math.max(t + debounceMs, lastRunAt + minIntervalMs)
    // A run already due sooner covers this one.
    if (timer != null && dueAt <= at) return
    schedule(at)
  }

  function cancel() {
    if (timer != null) clearTimer(timer)
    timer = null
    again = null
  }

  return { request, cancel }
}
