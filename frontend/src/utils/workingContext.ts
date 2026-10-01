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

/** Switching context preserves a browser/tool type, never transfers an object. */
export function contextSwitchRoute(route: { name?: unknown; params: Record<string, any> }, projectId: number | null) {
  if (route.name === 'tool') {
    return {
      name: 'tool', params: { fullToolId: route.params.fullToolId },
      query: projectId == null ? {} : { project_id: String(projectId) },
    }
  }
  const section = contextSection(route.name)
    ?? ({ chat: 'chats', 'board-detail': 'boards', flow: 'flows' } as Record<string, string>)[String(route.name)]
    ?? 'browse'
  return contextRoute(section, projectId)
}

export function belongsToContext(tab: { type: string; projectId?: number | null; contextProjectIds?: Array<number | null> }, projectId: number | null) {
  return tab.type !== 'project' && (tab.contextProjectIds ? tab.contextProjectIds.includes(projectId) : (tab.projectId ?? null) === projectId)
}
