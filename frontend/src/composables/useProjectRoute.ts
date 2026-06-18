import { makeProfileKey } from '../utils/storageKeys'

/**
 * Per-project "last visited sub-route" memory.
 *
 * Projects are `/projects/:id` with child sub-screens (overview, assets, tools,
 * boards, chats, flows, settings). The bare project route redirects to overview,
 * so without memory, re-entering a project from the sidebar always lands on
 * overview and loses the sub-screen the user was last on.
 *
 * We persist, per project id, the route NAME of the last visited sub-screen,
 * keyed with the profile-scoped storage helper (mirrors getLastLibraryRoute /
 * setLastLibraryRoute in useWorkspaceTabs). Restored when navigating back into
 * the project; falls back to overview when nothing is saved.
 */

const VALID_PROJECT_ROUTE_NAMES = new Set([
  'project-overview',
  'project-assets',
  'project-tools',
  'project-boards',
  'project-chats',
  'project-flows',
  'project-settings'
])

function lastRouteKey(projectId: string | number): string {
  return makeProfileKey('project', String(projectId), 'last_route')
}

export function useProjectRoute() {
  /**
   * Get the remembered sub-route name for a project. Returns 'project-overview'
   * when nothing valid is saved.
   */
  function getLastProjectRoute(projectId: string | number): string {
    try {
      const saved = localStorage.getItem(lastRouteKey(projectId))
      if (saved && VALID_PROJECT_ROUTE_NAMES.has(saved)) return saved
    } catch {}
    return 'project-overview'
  }

  /**
   * Remember the last visited sub-route name for a project. Ignores anything
   * that isn't a known project sub-route.
   */
  function setLastProjectRoute(projectId: string | number, routeName: string | null | undefined) {
    if (!routeName || !VALID_PROJECT_ROUTE_NAMES.has(routeName)) return
    try {
      localStorage.setItem(lastRouteKey(projectId), routeName)
    } catch {}
  }

  return { getLastProjectRoute, setLastProjectRoute }
}
