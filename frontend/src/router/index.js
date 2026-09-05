import { createRouter, createWebHistory } from 'vue-router'
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
import ProjectsLandingView from '../views/ProjectsLandingView.vue'
import ProjectLayoutView from '../views/ProjectLayoutView.vue'
import ProjectOverviewView from '../views/ProjectOverviewView.vue'
import ProjectAssetsView from '../views/ProjectAssetsView.vue'
import ProjectChatsView from '../views/ProjectChatsView.vue'
import ProjectBoardsView from '../views/ProjectBoardsView.vue'
import ProjectFlowsView from '../views/ProjectFlowsView.vue'
import ProjectSettingsView from '../views/ProjectSettingsView.vue'
import ProjectToolsView from '../views/ProjectToolsView.vue'
import OnboardingView from '../views/OnboardingView.vue'
import SearchResultsView from '../views/SearchResultsView.vue'
import WorkspaceView from '../views/WorkspaceView.vue'
import ForeachMockView from '../views/ForeachMockView.vue'
import { useTelemetry } from '../composables/useTelemetry'

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
    // Compact-viewport hub: the working set (pinned + open tabs). On wide
    // viewports the sidebar shows the same data, so this redirects home.
    path: '/workspace',
    name: 'workspace',
    component: WorkspaceView,
    meta: { surface: 'hub' }
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
    meta: { surface: 'hub' },
    component: ProjectsLandingView
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
        meta: { surface: 'detail' },
        component: ProjectOverviewView
      },
      {
        path: 'assets',
        name: 'project-assets',
        meta: { surface: 'detail' },
        component: ProjectAssetsView
      },
      {
        path: 'chats',
        name: 'project-chats',
        meta: { surface: 'detail' },
        component: ProjectChatsView
      },
      {
        path: 'boards',
        name: 'project-boards',
        meta: { surface: 'detail' },
        component: ProjectBoardsView
      },
      {
        path: 'flows',
        name: 'project-flows',
        meta: { surface: 'detail' },
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
        meta: { surface: 'detail' },
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
  },
  {
    path: '/dev/foreach-mock',
    name: 'dev-foreach-mock',
    component: ForeachMockView,
    meta: { surface: 'detail', skipRouteRestore: true }
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
router.beforeEach(async (to) => {
  if (to.name !== 'tool' || to.query.instance) return true
  const { whenTabsReady, useWorkspaceTabs } = await import('../composables/useWorkspaceTabs')
  // Don't hang tool navigation forever if settings never load (e.g. backend
  // unreachable at boot): after the grace period resolve against whatever tab
  // state exists — worst case a fresh instance is minted.
  await Promise.race([whenTabsReady(), new Promise(resolve => setTimeout(resolve, 4000))])
  const { resolveToolInstance } = useWorkspaceTabs()
  const projectId = to.query.project_id ? Number(to.query.project_id) : null
  const { instanceId } = resolveToolInstance(String(to.params.fullToolId), projectId)
  return {
    name: 'tool',
    meta: { surface: 'detail' },
    params: to.params,
    query: { ...to.query, instance: instanceId },
    hash: to.hash,
    replace: true
  }
})

// Track screen navigation with the catalog's `screen_viewed` event. Only
// the route NAME is sent — never the path, which can embed entity ids
// (/boards/<id>, /lineage/<mediaId>). Dev-only routes are excluded.
const { track: trackNav } = useTelemetry()
router.afterEach((to) => {
  const screen = typeof to.name === 'string' ? to.name : null
  if (!screen || screen.startsWith('dev-')) return
  trackNav('screen_viewed', { screen }, 'navigation')
})

export default router
