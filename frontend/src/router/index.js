import { createRouter, createWebHistory } from 'vue-router'
import { desktop } from '../desktop'
import BrowseGridView from '../views/BrowseGridView.vue'
import BoardDetailView from '../views/BoardDetailView.vue'
import BoardsLandingView from '../views/BoardsLandingView.vue'
import UploadView from '../views/UploadView.vue'
import ChatView from '../views/ChatView.vue'
import SavedViewPage from '../views/SavedViewPage.vue'
import AllToolsView from '../views/AllToolsView.vue'
import ToolView from '../views/ToolView.vue'
import ImageEditorView from '../views/ImageEditorView.vue'
import LineageView from '../views/LineageView.vue'
import ChatsLandingView from '../views/ChatsLandingView.vue'
import HomeView from '../views/HomeView.vue'
import FlowsLandingView from '../views/FlowsLandingView.vue'
import FlowView from '../views/FlowView.vue'
import ProjectLayoutView from '../views/ProjectLayoutView.vue'
import ProjectAssetsView from '../views/ProjectAssetsView.vue'
import ProjectChatsView from '../views/ProjectChatsView.vue'
import ProjectBoardsView from '../views/ProjectBoardsView.vue'
import ProjectFlowsView from '../views/ProjectFlowsView.vue'
import ProjectSettingsView from '../views/ProjectSettingsView.vue'
import ProjectToolsView from '../views/ProjectToolsView.vue'
import OnboardingView from '../views/OnboardingView.vue'
import SearchResultsView from '../views/SearchResultsView.vue'
import { useTelemetry } from '../composables/useTelemetry'
import { useWorkingContext } from '../composables/useWorkingContext'
import { assetLinkContext, contextRoute, contextSection, entityFallbackSection, projectIdFrom } from '../utils/workingContext'
import { addToast } from '../composables/useToasts'
import axios from 'axios'
import { getApiBase } from '../apiConfig'

// Every route declares its chrome `surface`:
//   hub     — a top-level landing; on compact viewports the tab bar shows.
//   detail  — an entity screen (tool, chat, board, flow, project page); on
//             compact viewports it gets a back header. The tab bar still
//             shows — only overlays hide it.
//   overlay — a full-screen takeover (onboarding, image editor); no app chrome.
// Wide viewports render sidebar + top bar regardless. See useViewport.ts and
// DESIGN.md §1.11.
const routes = [
  {
    path: '/',
    redirect: '/home'
  },
  {
    path: '/onboarding',
    name: 'onboarding',
    component: OnboardingView,
    meta: { surface: 'overlay', noChrome: true }
  },
  {
    path: '/home',
    name: 'home',
    meta: { surface: 'hub' },
    component: HomeView
  },
  {
    // The working set is the compact header's switcher; the old hub page is gone.
    path: '/workspace',
    name: 'workspace',
    redirect: '/tools'
  },
  {
    path: '/browse',
    name: 'browse',
    meta: { surface: 'hub' },
    component: BrowseGridView
  },
  {
    path: '/search',
    name: 'search',
    meta: { surface: 'hub' },
    component: SearchResultsView
  },
  {
    path: '/boards',
    name: 'boards',
    meta: { surface: 'hub' },
    component: BoardsLandingView
  },
  {
    path: '/boards/:id',
    name: 'board-detail',
    meta: { surface: 'detail' },
    component: BoardDetailView
  },
  {
    path: '/projects',
    name: 'projects',
    redirect: to => ({ name: 'home', query: { ...to.query, projects: '1' } })
  },
  {
    path: '/projects/:id',
    component: ProjectLayoutView,
    children: [
      {
        path: '',
        redirect: { name: 'project-overview' }
      },
      {
        path: 'overview',
        name: 'project-overview',
        meta: { surface: 'hub' },
        component: HomeView
      },
      {
        path: 'assets',
        name: 'project-assets',
        meta: { surface: 'hub' },
        component: ProjectAssetsView
      },
      {
        path: 'chats',
        name: 'project-chats',
        meta: { surface: 'hub' },
        component: ProjectChatsView
      },
      {
        path: 'boards',
        name: 'project-boards',
        meta: { surface: 'hub' },
        component: ProjectBoardsView
      },
      {
        path: 'flows',
        name: 'project-flows',
        meta: { surface: 'hub' },
        component: ProjectFlowsView
      },
      {
        path: 'settings',
        name: 'project-settings',
        meta: { surface: 'detail' },
        component: ProjectSettingsView
      },
      {
        path: 'tools',
        name: 'project-tools',
        meta: { surface: 'hub' },
        component: ProjectToolsView
      }
    ]
  },
  {
    path: '/trash',
    name: 'trash',
    meta: { surface: 'hub' },
    component: BrowseGridView,
    props: { isTrashMode: true }
  },
  {
    path: '/upload',
    name: 'upload',
    meta: { surface: 'hub' },
    component: UploadView
  },
  {
    path: '/chats',
    name: 'chats',
    meta: { surface: 'hub' },
    component: ChatsLandingView
  },
  {
    path: '/chat/:id',
    name: 'chat',
    meta: { surface: 'detail' },
    component: ChatView
  },
  {
    path: '/flows',
    name: 'flows',
    meta: { surface: 'hub' },
    component: FlowsLandingView
  },
  {
    path: '/flows/:id',
    name: 'flow',
    meta: { surface: 'detail' },
    component: FlowView,
    props: true
  },
  {
    path: '/saved-view/:id',
    name: 'saved-view',
    meta: { surface: 'hub' },
    component: SavedViewPage
  },
  {
    path: '/tools',
    name: 'all-tools',
    meta: { surface: 'hub' },
    component: AllToolsView
  },
  {
    // One stack document per Asset. Reopening the same Asset resumes the same
    // document rather than creating another editor instance.
    path: '/edit-image/:assetId',
    name: 'edit-image',
    meta: { surface: 'overlay' },
    component: ImageEditorView,
    props: true
  },
  {
    path: '/lineage/:mediaId',
    name: 'lineage',
    meta: { surface: 'detail' },
    component: LineageView,
    props: true
  },
  {
    // Tool view uses full_tool_id (e.g., "builtin:ComfyUI:z-image-turbo:text-to-image")
    // The :fullToolId(.*) pattern captures the entire path including colons
    path: '/tools/:fullToolId(.*)',
    name: 'tool',
    meta: { surface: 'detail' },
    component: ToolView,
    props: true
  }
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

// Every tool navigation lands on a specific instance. Legacy entry paths
// (send-to, remix, hop, deep links, All Tools) navigate without ?instance;
// resolve it here — most-recently-active open instance matching
// (tool, project), else a freshly minted one. Callers that want an explicit
// fresh instance pass ?instance themselves.
// Loads an entity to learn its project, retrying once for a transient
// failure. Resolves null when it can't be loaded (or doesn't exist).
async function fetchOwner(url) {
  for (let attempt = 0; attempt < 2; attempt++) {
    try {
      return (await axios.get(url)).data
    } catch (err) {
      if (err?.response?.status === 404 || attempt) return null
      await new Promise(resolve => setTimeout(resolve, 400))
    }
  }
  return null
}

// The live projects an asset (editor) or media item (lineage) belongs to,
// or null when that can't be determined.
async function assetProjectIds(to) {
  try {
    let mediaId = to.params.mediaId
    if (to.name === 'edit-image') {
      const { data } = await axios.get(`${getApiBase()}/assets/${to.params.assetId}`)
      mediaId = data?.media?.id
    }
    if (mediaId == null) return null
    const { data } = await axios.get(`${getApiBase()}/media/${mediaId}/projects`)
    return Array.isArray(data) ? data.map(p => p.id).filter(id => Number.isSafeInteger(id)) : null
  } catch {
    return null
  }
}

router.beforeEach(async (to, from) => {
  if (['ios', 'android'].includes(desktop.kind) && to.name === 'onboarding') return { name: 'home', replace: true }
  delete to.meta.workingProjectId
  const context = useWorkingContext()
  const section = contextSection(to.name)
  if (to.query.projects === '1' || to.query.library === '1') {
    to.meta.workingProjectId = null
  } else if (String(to.name || '').startsWith('project-')) {
    to.meta.workingProjectId = projectIdFrom(to.params.id)
  } else if (section && context.activeProjectId.value != null) {
    return { ...contextRoute(section, context.activeProjectId.value), query: to.query, hash: to.hash, replace: true }
  } else if (section) {
    to.meta.workingProjectId = null
  } else if (['chat', 'board-detail', 'flow', 'saved-view'].includes(to.name)) {
    const kind = { chat: 'chats', 'board-detail': 'boards', flow: 'flows', 'saved-view': 'saved-views' }[to.name]
    const data = await fetchOwner(`${getApiBase()}/${kind}/${to.params.id}`)
    if (!data) {
      // Never show an item under a context it may not belong to: fall back
      // to the current context's landing page for that kind.
      const noun = { chat: 'chat', 'board-detail': 'board', flow: 'flow', 'saved-view': 'saved view' }[to.name]
      addToast(`Could not open that ${noun}.`, 'warning')
      if (from.matched.length) return false
      return { ...contextRoute(entityFallbackSection[to.name], context.activeProjectId.value), replace: true }
    }
    to.meta.workingProjectId = projectIdFrom(data.project_id)
  } else if ((to.name === 'edit-image' || to.name === 'lineage') && context.activeProjectId.value != null) {
    // An asset link keeps a context that contains the asset; otherwise it
    // moves to the asset's most recently used project, or to Everything.
    const projectIds = await assetProjectIds(to)
    if (projectIds) {
      to.meta.workingProjectId = assetLinkContext(
        context.activeProjectId.value, projectIds, context.orderedProjects.value.map(p => p.id))
    }
  } else if (to.name === 'upload' && to.query.project_id == null && context.activeProjectId.value != null) {
    return { name: 'upload', query: { ...to.query, project_id: String(context.activeProjectId.value) }, replace: true }
  }
  if (to.name !== 'tool') return true
  const { whenTabsReady, useWorkspaceTabs } = await import('../composables/useWorkspaceTabs')
  // Don't hang tool navigation forever if settings never load (e.g. backend
  // unreachable at boot): after the grace period resolve against whatever tab
  // state exists — worst case a fresh instance is minted.
  await Promise.race([whenTabsReady(), new Promise(resolve => setTimeout(resolve, 4000))])
  const { resolveToolInstance, allTabs } = useWorkspaceTabs()
  // Explicit sessions retain their own destination. Unaddressed launchers use
  // the working context, including deep links and legacy media handoff paths.
  const existing = to.query.instance
    ? allTabs.value.find(t => t.type === 'tool' && t.entityId === String(to.params.fullToolId) && t.instanceId === String(to.query.instance))
    : null
  const projectId = existing
    ? existing.projectId ?? null
    : to.query.project_id != null ? projectIdFrom(to.query.project_id) : context.activeProjectId.value
  to.meta.workingProjectId = projectId
  const query = { ...to.query }
  if (projectId != null) query.project_id = String(projectId)
  else query.project_id = '0'
  if (to.query.instance && query.project_id === to.query.project_id) return true
  if (to.query.instance) return { name: 'tool', params: to.params, query, replace: true }
  const { instanceId } = resolveToolInstance(String(to.params.fullToolId), projectId)
  return {
    name: 'tool',
    meta: { surface: 'detail' },
    params: to.params,
    query: { ...query, instance: instanceId },
    hash: to.hash,
    replace: true
  }
})

// Track screen navigation with the catalog's `screen_viewed` event. Only
// the route NAME is sent — never the path, which can embed entity ids
// (/boards/<id>, /lineage/<mediaId>). Dev-only routes are excluded.
const { track: trackNav } = useTelemetry()
router.afterEach((to, _from, failure) => {
  if (failure) return
  if ('workingProjectId' in to.meta) useWorkingContext().selectProject(to.meta.workingProjectId)
  const screen = typeof to.name === 'string' ? to.name : null
  if (!screen || screen.startsWith('dev-')) return
  trackNav('screen_viewed', { screen }, 'navigation')
})

export default router
