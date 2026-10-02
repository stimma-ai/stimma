import { useRoute, useRouter, type RouteLocationNormalizedLoaded, type Router } from 'vue-router'
import { useMediaApi } from './useMediaApi'
import { useWorkingContext } from './useWorkingContext'
import { useWorkspaceTabs } from './useWorkspaceTabs'
import { removeRecentEntity } from './useRecentEntities'
import { addToast } from './useToasts'
import { projectIdFrom } from '../utils/workingContext'

// Projects this window deleted, so the broadcast that follows doesn't also
// warn that the project "is no longer available".
const deletedHere = new Set<number>()

/**
 * Everything that has to happen in a window once a project is gone, whoever
 * deleted it: its tabs and their saved state go, and a window that was
 * working in it lands on Everything's Home. Safe to run more than once.
 * Returns true when this window was working in the project.
 */
export async function cleanUpDeletedProject(projectId: number, router: Router, route: RouteLocationNormalizedLoaded) {
  const { activeProjectId, selectProject, refreshProjects } = useWorkingContext()
  const { removeProjectTabs } = useWorkspaceTabs()
  const routeProject = String(route.name || '').startsWith('project-') ? projectIdFrom(route.params.id)
    : route.name === 'tool' ? projectIdFrom(route.query.project_id) : null
  const wasHere = activeProjectId.value === projectId || routeProject === projectId
  removeProjectTabs(projectId)
  removeRecentEntity('project', String(projectId))
  if (wasHere) {
    selectProject(null)
    await router.replace({ name: 'home' }).catch(() => {})
  }
  void refreshProjects()
  return wasHere
}

/** Called for the `project_deleted` broadcast. */
export async function handleProjectDeletedBroadcast(projectId: number, router: Router, route: RouteLocationNormalizedLoaded) {
  const wasHere = await cleanUpDeletedProject(projectId, router, route)
  if (deletedHere.delete(projectId)) return
  if (wasHere) addToast('This project is no longer available.', 'warning')
}

export function useProjectDeletion() {
  const router = useRouter()
  const route = useRoute()
  const { deleteProject } = useMediaApi()
  /** Deletes a project and cleans up after it. Resolves false (after a toast) on failure. */
  return async function deleteProjectAndCleanUp(projectId: number): Promise<boolean> {
    deletedHere.add(projectId)
    try {
      await deleteProject(projectId)
    } catch {
      deletedHere.delete(projectId)
      addToast('Could not delete the project.', 'warning')
      return false
    }
    await cleanUpDeletedProject(projectId, router, route)
    addToast('Project deleted', 'info')
    return true
  }
}
