import { useRoute } from 'vue-router'
import { useWorkingContext } from './useWorkingContext'
import { useWorkspaceTabs } from './useWorkspaceTabs'
import { addToast } from './useToasts'

export type MovableKind = 'chat' | 'board' | 'flow'

const ENDPOINT: Record<MovableKind, { path: string; method: string; route: string }> = {
  chat: { path: '/api/chats', method: 'PATCH', route: 'chat' },
  board: { path: '/api/boards', method: 'PUT', route: 'board-detail' },
  flow: { path: '/api/flows', method: 'PATCH', route: 'flow' },
}

async function errorMessage(response: Response, kind: MovableKind) {
  let detail = ''
  try { detail = (await response.json())?.detail || '' } catch { /* not JSON */ }
  if (response.status === 409 && detail) return `Could not move the ${kind}: ${detail.charAt(0).toLowerCase()}${detail.slice(1)}.`
  if (response.status === 404) return `Could not move the ${kind}: that project no longer exists.`
  return `Could not move the ${kind}.`
}

/**
 * Moves a chat, board or flow to another project (or to the top level with
 * `null`). The open item's working context follows it, so the sidebar and
 * the destination for new work stay in step with what's on screen.
 * Resolves to the updated item, or null after showing a toast on failure.
 */
export function useEntityMove() {
  const route = useRoute()
  const { selectProject } = useWorkingContext()
  const { setTabContext } = useWorkspaceTabs()

  return async function moveToProject(kind: MovableKind, id: number | string, projectId: number | null): Promise<any | null> {
    const endpoint = ENDPOINT[kind]
    let response: Response
    try {
      response = await fetch(`${endpoint.path}/${id}`, {
        method: endpoint.method,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ project_id: projectId }),
      })
    } catch {
      addToast(`Could not move the ${kind}.`, 'error')
      return null
    }
    if (!response.ok) {
      addToast(await errorMessage(response, kind), 'error')
      return null
    }
    const updated = await response.json().catch(() => ({ id, project_id: projectId }))
    setTabContext(`${kind}:${id}`, projectId)
    if (route.name === endpoint.route && String(route.params.id) === String(id)) selectProject(projectId)
    return updated
  }
}
