/**
 * Another client closed the tab this one is showing. Same as closing it here:
 * move to the next tab. Its state is kept, so it can be brought straight back.
 */
import type { RouteLocationNormalizedLoaded, Router } from 'vue-router'
import { useToasts } from './useToasts'
import { useProjectRoute } from './useProjectRoute'
import {
  editorRouteTabId,
  editorTabRoute,
  toolRouteTabId,
  toolTabRoute,
  useWorkspaceTabs,
  type WorkspaceTab,
} from './useWorkspaceTabs'

function routeTabId(route: RouteLocationNormalizedLoaded): string | null {
  const name = String(route.name ?? '')
  const params = route.params as Record<string, string>
  if (name === 'chat') return `chat:${params.id}`
  if (name === 'board-detail') return `board:${params.id}`
  if (name === 'flow') return `flow:${params.id}`
  if (name === 'lineage') return `lineage:${params.mediaId}`
  if (name.startsWith('project-') && params.id) return `project:${params.id}`
  return toolRouteTabId(route) ?? editorRouteTabId(route)
}

function tabLocation(tab: WorkspaceTab) {
  if (tab.type === 'tool') return toolTabRoute(tab)
  if (tab.type === 'editor') return editorTabRoute(tab)
  if (tab.type === 'chat') return { name: 'chat', params: { id: tab.entityId } }
  if (tab.type === 'board') return { name: 'board-detail', params: { id: tab.entityId } }
  if (tab.type === 'flow') return { name: 'flow', params: { id: tab.entityId } }
  if (tab.type === 'lineage') return { name: 'lineage', params: { mediaId: tab.entityId } }
  return { name: useProjectRoute().getLastProjectRoute(tab.entityId), params: { id: tab.entityId } }
}

let installed = false

export function installRemoteTabClose(router: Router, route: RouteLocationNormalizedLoaded) {
  if (installed) return
  installed = true
  const { findNextTab, reopenLastClosed } = useWorkspaceTabs()
  const { addToast } = useToasts()

  window.addEventListener('workspace-tab-closed-remotely', (event) => {
    const closed = (event as CustomEvent<{ tab: WorkspaceTab }>).detail.tab
    if (routeTabId(route) !== closed.id) return
    const next = findNextTab(new Set([closed.id]))
    void router.push(next ? tabLocation(next) : { name: 'browse' })
    addToast('Closed on another device', 'info', 6000, {
      label: 'Reopen',
      onClick: () => {
        const reopened = reopenLastClosed()
        if (reopened) void router.push(tabLocation(reopened))
      },
    })
  })
}
