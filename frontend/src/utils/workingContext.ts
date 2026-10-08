/** Navigation sections have one address per working context. */
export const contextSections = {
  home: 'project-overview',
  browse: 'project-assets',
  boards: 'project-boards',
  chats: 'project-chats',
  flows: 'project-flows',
  'all-tools': 'project-tools',
} as const

export function projectIdFrom(value: unknown): number | null {
  const raw = Array.isArray(value) ? value[0] : value
  if (raw == null || raw === '') return null
  const id = Number(raw)
  return Number.isSafeInteger(id) && id > 0 ? id : null
}

export function contextSection(name: unknown): string | null {
  if (typeof name !== 'string') return null
  if (name in contextSections) return name
  return Object.entries(contextSections).find(([, scoped]) => scoped === name)?.[0] ?? null
}

export function contextRoute(section: string, projectId: number | null) {
  const scoped = contextSections[section as keyof typeof contextSections]
  return projectId != null && scoped
    ? { name: scoped, params: { id: String(projectId) } }
    : { name: section }
}

/**
 * Switching context preserves a browser section, never transfers an object.
 * An open tool lands on the destination's own instance of that tool when it
 * has one (`findInstance`), else on the destination's overview: switching
 * never creates a tool instance as a side effect.
 */
export function contextSwitchRoute(
  route: { name?: unknown; params: Record<string, any> },
  projectId: number | null,
  findInstance?: (fullToolId: string, projectId: number | null) => string | null,
) {
  if (route.name === 'tool') {
    const fullToolId = String(route.params.fullToolId)
    const instance = findInstance?.(fullToolId, projectId)
    if (!instance) return contextRoute('home', projectId)
    return {
      name: 'tool', params: { fullToolId },
      query: { project_id: projectId == null ? '0' : String(projectId), instance },
    }
  }
  const section = contextSection(route.name)
    ?? ({ chat: 'chats', 'board-detail': 'boards', flow: 'flows' } as Record<string, string>)[String(route.name)]
    ?? 'browse'
  return contextRoute(section, projectId)
}

/**
 * The context an asset deep link (editor, lineage) opens in. The current
 * context stays when it is Everything or contains the asset. Otherwise the
 * link moves to the asset's most recently used project (`recentProjectIds`
 * is most recent first), or to Everything when the asset is in no project.
 */
export function assetLinkContext(current: number | null, assetProjectIds: number[], recentProjectIds: number[] = []): number | null {
  if (current == null || assetProjectIds.includes(current)) return current
  if (!assetProjectIds.length) return null
  return recentProjectIds.find(id => assetProjectIds.includes(id)) ?? assetProjectIds[0]
}

/** The landing section an entity route falls back to when its item can't load. */
export const entityFallbackSection: Record<string, string> = {
  chat: 'chats', 'board-detail': 'boards', flow: 'flows', 'saved-view': 'browse',
}

export function belongsToContext(tab: { type: string; projectId?: number | null; contextProjectIds?: Array<number | null> }, projectId: number | null) {
  return tab.type !== 'project' && (tab.contextProjectIds ? tab.contextProjectIds.includes(projectId) : (tab.projectId ?? null) === projectId)
}
