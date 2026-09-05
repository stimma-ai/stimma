/**
 * Route → workspace tab, for chromes without the sidebar.
 *
 * On desktop NavigationSidebar watches the route and turns every visited
 * tool instance, chat, board, project, editor, lineage view and flow into a
 * workspace tab; tool state (prompt, params, LoRAs) lives on that tab's
 * instance. The compact chrome has no sidebar, so without this nothing would
 * create tabs: every visit to a tool would mint a fresh, empty instance and
 * Workspace › Open would stay empty. This is the sidebar's watcher minus its
 * own preview caches; the sidebar keeps its copy for wide viewports and this
 * one runs only when `enabled()` says the sidebar is not mounted.
 */
import { watch } from 'vue'
import type { RouteLocationNormalizedLoaded } from 'vue-router'
import { useWorkspaceTabs } from './useWorkspaceTabs'
import { useProvidersApi } from './useProvidersApi'
import { useMediaApi } from './useMediaApi'

let installed = false

export function installWorkspaceTabRoutes(route: RouteLocationNormalizedLoaded, enabled: () => boolean) {
  if (installed) return
  installed = true
  const { addTab, addEditorTab, markTabActivated, updateTabName, updateEditorMedia, setLastLibraryRoute } = useWorkspaceTabs()
  const { fetchProvidersAndTools } = useProvidersApi()
  const { getBoard, getProject } = useMediaApi() as { getBoard: (id: number) => Promise<any>; getProject: (id: number) => Promise<any> }

  async function toolName(fullToolId: string): Promise<string> {
    const fallback = fullToolId.split(':').pop() || fullToolId
    try {
      const { tools } = await fetchProvidersAndTools()
      return (tools as any[]).find((t) => t.full_tool_id === fullToolId)?.name || fallback
    } catch {
      return fallback
    }
  }

  watch(
    () => ({ name: route.name, params: { ...route.params }, projectQ: route.query.project_id, instanceQ: route.query.instance, on: enabled() }),
    (current) => {
      if (!current.on) return
      const name = current.name as string
      const params = current.params as Record<string, string>

      if (['browse', 'trash', 'saved-view', 'boards', 'chats', 'flows', 'all-tools', 'projects', 'workspace'].includes(name) || name?.startsWith('project-')) {
        setLastLibraryRoute(route.fullPath)
      }

      if (name === 'tool' && params.fullToolId) {
        const fullToolId = String(params.fullToolId)
        const rawProjectId = route.query.project_id
        const projectId = rawProjectId ? parseInt(String(Array.isArray(rawProjectId) ? rawProjectId[0] : rawProjectId), 10) : undefined
        const instanceId = route.query.instance ? String(route.query.instance) : undefined
        const scopedProject = projectId && Number.isFinite(projectId) ? projectId : undefined
        const tab = addTab('tool', fullToolId, undefined, scopedProject, undefined, instanceId)
        markTabActivated(tab.id)
        if (!tab.displayName || tab.displayName === fullToolId) {
          toolName(fullToolId).then((n) => updateTabName(tab.id, n)).catch(() => {})
        }
        if (scopedProject && !tab.projectName) {
          getProject(scopedProject).then((project) => {
            if (project) addTab('tool', fullToolId, tab.displayName, scopedProject, project.name || 'Untitled Project', instanceId)
          }).catch(() => {})
        }
      } else if (name?.startsWith('project-') && params.id) {
        const projectId = String(params.id)
        const tab = addTab('project', projectId)
        getProject(parseInt(projectId, 10)).then((project) => {
          if (project) updateTabName(tab.id, project.name || '')
        }).catch(() => {})
      } else if (name === 'chat' && params.id) {
        const chatId = String(params.id)
        const tab = addTab('chat', chatId)
        if (!tab.displayName || tab.displayName === chatId) {
          fetch(`/api/chats/${chatId}`).then((r) => (r.ok ? r.json() : null)).then((chat) => {
            if (chat) updateTabName(tab.id, chat.name || '')
          }).catch(() => {})
        }
      } else if (name === 'board-detail' && params.id) {
        const boardId = String(params.id)
        const tab = addTab('board', boardId)
        if (!tab.displayName || tab.displayName === boardId) {
          getBoard(parseInt(boardId, 10)).then((board) => {
            if (board) updateTabName(tab.id, board.name || '')
          }).catch(() => {})
        }
      } else if (name === 'edit-image' && params.assetId) {
        const assetId = String(params.assetId)
        const tab = addEditorTab(assetId)
        markTabActivated(tab.id)
        fetch(`/api/assets/${assetId}`).then((r) => (r.ok ? r.json() : null)).then((data) => {
          if (!data) return
          if (data.media?.id != null) updateEditorMedia(tab.id, String(data.media.id))
          if (data.asset?.title) updateTabName(tab.id, data.asset.title)
        }).catch(() => {})
      } else if (name === 'lineage' && params.mediaId) {
        addTab('lineage', String(params.mediaId), 'Lineage')
      } else if (name === 'flow' && params.id) {
        const flowId = String(params.id)
        const tab = addTab('flow', flowId)
        if (!tab.displayName || tab.displayName === flowId) {
          fetch(`/api/flows/${flowId}`).then((r) => (r.ok ? r.json() : null)).then((flow) => {
            if (flow) updateTabName(tab.id, flow.name || '')
          }).catch(() => {})
        }
      }
    },
    { immediate: true },
  )
}
