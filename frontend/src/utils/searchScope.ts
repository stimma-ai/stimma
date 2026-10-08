/**
 * Search scope rules. Inside a project, search is scoped to it; the omnibox
 * also runs the unscoped query and offers the matches that lie outside.
 */

interface Hit { id: number; project_id?: number | null }

export interface EntityHits {
  chats?: Hit[]
  flows?: Hit[]
  boards?: Hit[]
  projects?: Hit[]
}

export interface OutsideCount {
  count: number
  /** A category hit its fetch limit, so the true count may be higher. */
  capped: boolean
}

/**
 * Matches outside `projectId`: chats, flows and boards that belong elsewhere
 * (they are strictly scoped), other projects, and assets the unscoped search
 * found beyond the scoped total. Presets aren't scoped, so they never count.
 */
export function countOutside(
  global: EntityHits | null | undefined,
  projectId: number,
  limit: number,
  assetTotals: { scoped: number; global: number } = { scoped: 0, global: 0 },
): OutsideCount {
  let count = 0
  let capped = false
  for (const kind of ['chats', 'flows', 'boards'] as const) {
    const hits = global?.[kind] ?? []
    if (hits.length >= limit) capped = true
    count += hits.filter(h => (h.project_id ?? null) !== projectId).length
  }
  const projects = global?.projects ?? []
  if (projects.length >= limit) capped = true
  count += projects.filter(p => p.id !== projectId).length
  count += Math.max(0, assetTotals.global - assetTotals.scoped)
  return { count, capped }
}

export function outsideLabel({ count, capped }: OutsideCount, projectName: string) {
  const n = capped ? `${count}+` : String(count)
  return `${n} more ${count === 1 && !capped ? 'result' : 'results'} outside ${projectName || 'Untitled project'}`
}

interface Recent { type: string; projectId?: number | null }

/**
 * Recents shown for a scope. Scoped to a project: its own chats, boards and
 * flows plus tools (which open in the project), never projects or items
 * whose project isn't known. Unscoped (`null`): everything.
 */
export function recentsInScope<T extends Recent>(entries: T[], projectId: number | null): T[] {
  if (projectId == null) return entries
  return entries.filter(e => e.type === 'tool' || (e.type !== 'project' && e.projectId === projectId))
}
