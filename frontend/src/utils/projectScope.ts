/**
 * Project scoping helpers shared by asset menus, pickers and upload callers.
 * A project is its own small world: anything created while working in project
 * P (uploads, saves, new boards and chats) lands in P.
 */

export type ProjectId = number | null

/** Normalizes any id-ish value into a positive integer project id, or null. */
export function toProjectId(value: unknown): ProjectId {
  if (value == null || value === '') return null
  const parsed = typeof value === 'number' ? value : parseInt(String(value), 10)
  return Number.isSafeInteger(parsed) && parsed > 0 ? parsed : null
}

/**
 * Picks the project an action should use. An explicit owner (the chat, tool
 * tab or menu caller) wins over the active working project. `undefined` means
 * "no opinion"; `null` is an explicit "no project" and is respected.
 */
export function resolveProjectId(...candidates: Array<unknown>): ProjectId {
  for (const candidate of candidates) {
    if (candidate === undefined) continue
    return toProjectId(candidate)
  }
  return null
}

/** Adds `project_id` to an upload form when the upload belongs to a project. */
export function appendProjectId(form: FormData, projectId: ProjectId): FormData {
  if (projectId != null) form.append('project_id', String(projectId))
  return form
}

/** Query params for project-scoped lists: a project id, or `none` for the top level. */
export function projectListParam(projectId: ProjectId): string {
  return projectId == null ? 'none' : String(projectId)
}

// --- Membership -----------------------------------------------------------

export type MembershipState = 'all' | 'some' | 'none'

export interface ProjectRef {
  id: number
  name?: string | null
  [key: string]: unknown
}

/**
 * Counts how many targets belong to each project, given each target's list of
 * live projects.
 */
export function countMemberships(perTarget: Array<Array<{ id: number }> | null | undefined>): Map<number, number> {
  const counts = new Map<number, number>()
  for (const list of perTarget) {
    const seen = new Set<number>()
    for (const project of list || []) {
      if (project == null || seen.has(project.id)) continue
      seen.add(project.id)
      counts.set(project.id, (counts.get(project.id) || 0) + 1)
    }
  }
  return counts
}

export function membershipState(counts: Map<number, number>, total: number, projectId: number): MembershipState {
  const count = counts.get(projectId) || 0
  if (total <= 0 || count <= 0) return 'none'
  return count >= total ? 'all' : 'some'
}

/** Clicking a project row removes when every target is already in it, otherwise adds. */
export function membershipToggleAction(state: MembershipState): 'add' | 'remove' {
  return state === 'all' ? 'remove' : 'add'
}

/** Applies a completed add/remove to the local membership counts. */
export function applyMembershipChange(
  counts: Map<number, number>,
  total: number,
  projectId: number,
  action: 'add' | 'remove',
): Map<number, number> {
  const next = new Map(counts)
  if (action === 'add') next.set(projectId, total)
  else next.delete(projectId)
  return next
}

/** Pins the current project to the top, keeping the rest in their given order. */
export function orderProjectsCurrentFirst<T extends ProjectRef>(projects: T[], currentId: ProjectId): T[] {
  if (currentId == null) return projects
  const current = projects.find(project => project.id === currentId)
  if (!current) return projects
  return [current, ...projects.filter(project => project.id !== currentId)]
}

/** Whether "Remove from Project" applies: some target is in the scope project. */
export function canRemoveFromProject(counts: Map<number, number>, projectId: ProjectId): boolean {
  return projectId != null && (counts.get(projectId) || 0) > 0
}

// --- Asset browser scope --------------------------------------------------

export interface AssetScopeFilters {
  includeProjects?: boolean | null
  selectedProjects?: Array<number | string> | null
  projectMembership?: string | null
}

/**
 * Whether the top-level browser should include project assets. Asking for a
 * specific project, or for "in any project", implies it.
 */
export function includesProjectAssets(filters: AssetScopeFilters = {}): boolean {
  return !!filters.includeProjects
    || (Array.isArray(filters.selectedProjects) && filters.selectedProjects.length > 0)
    || filters.projectMembership === 'any'
}

/**
 * The `scope` param for asset browse and facet requests. Inside a project the
 * project id scopes the request and no scope param is sent; Trash stays global.
 * At the top level the browser shows unfiled assets unless project assets are
 * included.
 */
export function assetBrowseScope(
  filters: AssetScopeFilters = {},
  { projectId = null, isTrashMode = false }: { projectId?: ProjectId, isTrashMode?: boolean } = {},
): 'unfiled' | 'all' | undefined {
  if (projectId != null || isTrashMode) return undefined
  return includesProjectAssets(filters) ? 'all' : 'unfiled'
}
