import { createRouter, createWebHistory } from 'vue-router'
import BrowseGridView from '../views/BrowseGridView.vue'
import BoardDetailView from '../views/BoardDetailView.vue'
import BoardsLandingView from '../views/BoardsLandingView.vue'
import UploadView from '../views/UploadView.vue'
import ChatView from '../views/ChatView.vue'
import SavedViewPage from '../views/SavedViewPage.vue'
import AllToolsView from '../views/AllToolsView.vue'
import StimpacksView from '../views/StimpacksView.vue'
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
import ForeachMockView from '../views/ForeachMockView.vue'
import { useTelemetry } from '../composables/useTelemetry'

const routes = [
  {
    path: '/',
    redirect: '/home'
  },
  {
    path: '/onboarding',
    name: 'onboarding',
    component: OnboardingView,
    meta: { noChrome: true }
  },
  {
    path: '/home',
    name: 'home',
    component: HomeView
  },
  {
    path: '/browse',
    name: 'browse',
    component: BrowseGridView
  },
  {
    path: '/search',
    name: 'search',
    component: SearchResultsView
  },
  {
    path: '/boards',
    name: 'boards',
    component: BoardsLandingView
  },
  {
    path: '/boards/:id',
    name: 'board-detail',
    component: BoardDetailView
  },
  {
    path: '/projects',
    name: 'projects',
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
        component: ProjectOverviewView
      },
      {
        path: 'assets',
        name: 'project-assets',
        component: ProjectAssetsView
      },
      {
        path: 'chats',
        name: 'project-chats',
        component: ProjectChatsView
      },
      {
        path: 'boards',
        name: 'project-boards',
        component: ProjectBoardsView
      },
      {
        path: 'flows',
        name: 'project-flows',
        component: ProjectFlowsView
      },
      {
        path: 'settings',
        name: 'project-settings',
        component: ProjectSettingsView
      },
      {
        path: 'tools',
        name: 'project-tools',
        component: ProjectToolsView
      }
    ]
  },
  {
    path: '/trash',
    name: 'trash',
    component: BrowseGridView,
    props: { isTrashMode: true }
  },
  {
    path: '/upload',
    name: 'upload',
    component: UploadView
  },
  {
    path: '/chats',
    name: 'chats',
    component: ChatsLandingView
  },
  {
    path: '/chat/:id',
    name: 'chat',
    component: ChatView
  },
  {
    path: '/flows',
    name: 'flows',
    component: FlowsLandingView
  },
  {
    path: '/flows/:id',
    name: 'flow',
    component: FlowView,
    props: true
  },
  {
    path: '/saved-view/:id',
    name: 'saved-view',
    component: SavedViewPage
  },
  {
    path: '/tools',
    name: 'all-tools',
    component: AllToolsView
  },
  {
    path: '/stimpacks',
    name: 'stimpacks',
    component: StimpacksView
  },
  {
    path: '/edit-image',
    name: 'edit-image-landing',
    component: ImageEditorView,
    props: { editorId: null, mediaId: null }
  },
  {
    path: '/edit-image/:editorId',
    name: 'edit-image-empty',
    component: ImageEditorView,
    props: true
  },
  {
    path: '/edit-image/:editorId/:mediaId',
    name: 'edit-image',
    component: ImageEditorView,
    props: true
  },
  {
    path: '/lineage/:mediaId',
    name: 'lineage',
    component: LineageView,
    props: true
  },
  {
    // Tool view uses full_tool_id (e.g., "builtin:ComfyUI:z-image-turbo:text-to-image")
    // The :fullToolId(.*) pattern captures the entire path including colons
    path: '/tools/:fullToolId(.*)',
    name: 'tool',
    component: ToolView,
    props: true
  },
  {
    path: '/dev/foreach-mock',
    name: 'dev-foreach-mock',
    component: ForeachMockView,
    meta: { skipRouteRestore: true }
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
