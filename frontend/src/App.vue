<template>
  <!-- Keep the native startup screen in place until startup routing is resolved. -->
  <div v-if="startupPending" class="startup-screen">
    <div class="startup-drag-region" data-tauri-drag-region />
    <img class="startup-logo" src="/logo.svg" alt="Stimma" />
  </div>

  <template v-else>
    <!-- Toast notifications (global, always visible) -->
    <ToastContainer />

    <!-- Image/generation details popup (global, opened via useMediaDetailsModal) -->
    <MediaDetailsModal />

    <ReadinessPanel />

    <FirstRunTour />

    <BalanceCelebrationModal />

    <!-- In-app folder picker (global, opened via pickDirectory) -->
    <DirectoryPickerModal />

    <FeedbackRoot />

  <!-- Connection state, ahead of everything the active device owns — the
       PIN lock included. A PIN is verified by the server the window is on,
       so a lock screen over a dead connection can only fail; the connection
       screen takes over and the lock re-evaluates on the reload that follows
       a reconnect. The sidebar, browsers, and content of an unreachable
       backend are undefined, so they must not render at all — v-if, never
       v-show. -->
  <ConnectionScreen v-if="connectionState !== 'ready'" />

  <!-- Full-screen lock screen when PIN is required -->
  <div v-else-if="isLocked" class="fixed inset-0 z-top bg-surface-overlay">
    <!-- Draggable title bar region -->
    <div class="absolute top-0 left-0 right-0 h-14" data-tauri-drag-region />
    <!-- Profile switcher in top-right corner -->
    <div class="absolute top-4 right-4">
      <div class="relative lock-screen-profile-dropdown">
        <!-- Ghost trigger matching the main app top bar's profile switcher. -->
        <button
          @click="toggleLockScreenProfileDropdown"
          class="flex items-center gap-1.5 h-7 px-2 rounded-md text-[13px] text-content-secondary transition-colors cursor-pointer hover:text-content hover:bg-overlay-subtle"
          title="Switch profile"
        >
          <span class="max-w-[140px] truncate">{{ lockedProfileName }}</span>
          <svg class="w-3 h-3 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" d="m19.5 8.25-7.5 7.5-7.5-7.5" />
          </svg>
        </button>

        <transition name="menu">
          <div
            v-if="lockScreenProfileDropdownOpen"
            class="absolute top-[calc(100%+0.5rem)] right-0 bg-surface border border-edge-subtle rounded-lg shadow-[0_8px_16px_rgba(0,0,0,0.5)] z-menu min-w-[220px] overflow-hidden"
          >
            <div class="py-1">
              <div
                v-for="profile in profiles"
                :key="profile.id"
                class="w-full px-3 py-2 text-left text-xs transition-colors flex items-center gap-2 cursor-pointer"
                :class="profile.id === currentProfileId ? 'bg-accent/10 text-content' : 'text-content-secondary hover:bg-overlay-subtle hover:text-content'"
                @click="switchToProfileFromLockScreen(profile)"
              >
                <svg v-if="profile.id === currentProfileId" class="w-4 h-4 text-accent-hi flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
                  <path stroke-linecap="round" stroke-linejoin="round" d="m4.5 12.75 6 6 9-13.5" />
                </svg>
                <span v-else class="w-4 h-4 flex-shrink-0"></span>
                <span class="truncate flex-1">{{ profile.name }}</span>
                <svg v-if="profile.has_pin" class="w-3.5 h-3.5 text-content-muted flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M16.5 10.5V6.75a4.5 4.5 0 1 0-9 0v3.75m-.75 11.25h10.5a2.25 2.25 0 0 0 2.25-2.25v-6.75a2.25 2.25 0 0 0-2.25-2.25H6.75a2.25 2.25 0 0 0-2.25 2.25v6.75a2.25 2.25 0 0 0 2.25 2.25Z" />
                </svg>
              </div>
            </div>
          </div>
        </transition>
      </div>
    </div>

    <!-- Centered lock content -->
    <div class="flex items-center justify-center h-full">
      <div class="w-80">
        <!-- Lock icon and title -->
        <div class="text-center mb-6">
          <div class="w-16 h-16 mx-auto mb-4 rounded-full bg-accent/20 flex items-center justify-center">
            <svg class="w-8 h-8 text-accent" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
              <path stroke-linecap="round" stroke-linejoin="round" d="M16.5 10.5V6.75a4.5 4.5 0 1 0-9 0v3.75m-.75 11.25h10.5a2.25 2.25 0 0 0 2.25-2.25v-6.75a2.25 2.25 0 0 0-2.25-2.25H6.75a2.25 2.25 0 0 0-2.25 2.25v6.75a2.25 2.25 0 0 0 2.25 2.25Z" />
            </svg>
          </div>
          <h1 class="text-xl font-semibold text-content">Welcome back</h1>
          <p class="text-sm text-content-tertiary mt-1">{{ lockedProfileName }}</p>
        </div>

        <!-- PIN Input -->
        <div class="bg-surface border border-edge rounded-lg p-4">
          <label class="block text-sm text-content-tertiary mb-2">Enter your PIN</label>
          <input
            ref="lockScreenPinInput"
            v-model="lockScreenPin"
            type="password"
            inputmode="numeric"
            pattern="[0-9]*"
            maxlength="20"
            class="w-full px-4 py-3 bg-base border border-edge rounded-lg text-content text-center text-xl tracking-widest focus:outline-none focus:border-accent focus-visible:ring-2 ring-accent/40"
            placeholder="PIN"
            autocomplete="off"
            @keydown.enter="submitLockScreenPin"
          />
          <p v-if="lockScreenError" class="mt-2 text-sm text-red-500 text-center">
            {{ lockScreenError }}
          </p>
          <button
            @click="submitLockScreenPin"
            :disabled="!lockScreenPin || lockScreenSubmitting"
            class="w-full mt-3 px-4 py-2.5 bg-accent hover:bg-accent/90 disabled:bg-accent/50 disabled:cursor-not-allowed text-white rounded-lg font-medium transition-colors flex items-center justify-center gap-2"
          >
            <Spinner v-if="lockScreenSubmitting" size="sm" hue="border-t-white" />
            <span>{{ lockScreenSubmitting ? 'Verifying...' : 'Unlock' }}</span>
          </button>
        </div>
      </div>
    </div>
  </div>

  <!-- No-chrome mode for standalone pages like LLM trace viewer -->
  <div v-else-if="noChrome" class="w-full h-screen overflow-auto bg-base">
    <!-- Draggable title bar region -->
    <div class="sticky top-0 left-0 right-0 h-8 z-50" data-tauri-drag-region />
    <router-view />
  </div>

  <!-- Compact chrome (phones): header + content + tab bar. DESIGN.md §1.11.
       The sidebar and top bar do not exist here; their contents live in the
       header's account sheet, the Workspace hub, and the Library scope. -->
  <div v-else-if="isCompact" v-scroll-guard class="w-full h-[100dvh] flex flex-col overflow-hidden bg-base">
    <SettingsModal
      :show="settingsOpen"
      :initial-section="settingsSection"
      @close="closeSettings"
    />
    <CompactHeader v-if="!compactOverlay && !slideshowActive" @open-settings="openSettings($event)" />
    <ProjectScopeBar
      v-if="projectChrome.project && !slideshowActive && !compactOverlay"
      :project="projectChrome.project"
      :active-name="projectChrome.activeRouteName"
    />
    <div v-scroll-guard class="flex-1 min-h-0 overflow-hidden flex flex-col relative">
      <router-view v-slot="{ Component, route }">
        <KeepAlive :max="20">
          <component :is="Component" :key="getComponentKey(route)" />
        </KeepAlive>
      </router-view>
    </div>
    <CompactTabBar v-if="!compactOverlay && !slideshowActive" />
  </div>

  <!-- Normal app with sidebar and topbar -->
  <div v-else v-scroll-guard class="w-full h-screen flex overflow-hidden bg-base">
    <!-- Sidebar - fixed on wide screens, overlay on narrow -->
    <NavigationSidebar
      :is-open="sidebarOpen"
      :is-mobile="isMobile"
      @close="closeSidebar"
      @open-settings="openSettings($event)"
    />

    <!-- Settings Modal -->
    <SettingsModal
      :show="settingsOpen"
      :initial-section="settingsSection"
      @close="closeSettings"
    />

    <!-- Main area (header + content) -->
    <div v-scroll-guard class="flex-1 flex flex-col overflow-hidden">
      <!-- Static top bar -->
      <TopBar
        class="top-bar"
        @open-settings="openSettings($event)"
      />

      <ProjectScopeBar
        v-if="projectChrome.project && !slideshowActive"
        :project="projectChrome.project"
        :active-name="projectChrome.activeRouteName"
      />

      <!-- Page content -->
      <div v-scroll-guard class="flex-1 overflow-hidden flex flex-col relative">
        <router-view v-slot="{ Component, route }">
          <!-- Keep views alive to preserve state when navigating between tabs -->
          <!-- Use unique keys so each tool/chat gets its own cached instance -->
          <KeepAlive :max="20">
            <component :is="Component" :key="getComponentKey(route)" />
          </KeepAlive>
        </router-view>

      </div>
    </div>
  </div>
  </template>
</template>

<script setup>
import axios from 'axios'
import { useTelemetry } from './composables/useTelemetry'
import { ref, computed, onMounted, onUnmounted, nextTick, provide, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

// Shell scroll guard: overflow-hidden containers can still be displaced by
// native focus scrolling (no scrollbar exists to recover, so the app "breaks"
// and looks shifted/unscrollable). Snap any displacement back immediately.
// Registered as a local directive: v-scroll-guard.
const vScrollGuard = {
  mounted(el) {
    el.__scrollGuard = () => { if (el.scrollTop) el.scrollTop = 0; if (el.scrollLeft) el.scrollLeft = 0 }
    el.addEventListener('scroll', el.__scrollGuard, { passive: true })
  },
  unmounted(el) { el.removeEventListener('scroll', el.__scrollGuard) },
}
import NavigationSidebar from './components/NavigationSidebar.vue'
import { useViewport } from './composables/useViewport'
import { clearCompactTitle } from './composables/useCompactChrome'
import CompactHeader from './components/compact/CompactHeader.vue'
import CompactTabBar from './components/compact/CompactTabBar.vue'
import Spinner from './components/ui/Spinner.vue'
import ProjectScopeBar from './components/ProjectScopeBar.vue'
import TopBar from './components/TopBar.vue'
import ToastContainer from './components/ToastContainer.vue'
import MediaDetailsModal from './components/media/MediaDetailsModal.vue'
import ReadinessPanel from './components/ReadinessPanel.vue'
import FirstRunTour from './components/FirstRunTour.vue'
import ConnectionScreen from './components/ConnectionScreen.vue'
import BalanceCelebrationModal from './components/BalanceCelebrationModal.vue'
import DirectoryPickerModal from './components/DirectoryPickerModal.vue'
import SettingsModal from './components/settings/SettingsModal.vue'
import FeedbackRoot from '@stimma/feedback-root'
import { useProfile, initWindowProfile, reportWindowProfile, openProfileWindow } from './composables/useProfile'
import { useAuth } from './composables/useAuth'
import { useReadiness } from './composables/useReadiness'
import { useMultiDevice } from './composables/useMultiDevice'
import { requestGlobalSearchFocus } from './composables/useGlobalSearch'
import {
  profileRequiresPin,
  hasCachedPin,
  cachePin,
  clearCachedPin,
  startIdleTracking,
} from './composables/usePinLock'
import { getApiBase, isTauri } from './apiConfig'
import { useSettingsApi } from './composables/useSettingsApi'
import {
  devModeRef,
  isSettingsLoaded,
  setAppModifier,
  setDevMode,
  setGenerationPreviews,
  setAppBranch,
  setCaptioningEnabled,
  setTelemetryEnabled,
} from './appConfig'
import { initFeatureFlags } from './composables/useFeatureFlags'
import { useWebSocket } from './composables/useWebSocket'
import { initAccountEvents } from './composables/useAccountEvents'
import { useUnseenActivity } from './composables/useUnseenActivity'
import { runStartupCleanup } from './utils/storageCleanup'
import { setCloudBaseUrl, fetchCloudAccount } from './composables/useCloudAccount'
import { refreshAvailableModels } from './composables/useAvailableModels'
import { useRouteRestore, getSavedRouteForProfile } from './composables/useRouteRestore'
import { useTabNavigation } from './composables/useTabNavigation'
import { useTheme } from './composables/useTheme'
import { useMediaApi } from './composables/useMediaApi'
import { useWorkspaceTabs, toolTabRoute, toolRouteTabId, editorTabRoute, editorRouteTabId } from './composables/useWorkspaceTabs'
import { useProjectRoute } from './composables/useProjectRoute'
import { useToasts } from './composables/useToasts'
import { useAppUpdater, markUpdaterOwner } from './composables/useAppUpdater'
import { useReleaseNotes } from './composables/useReleaseNotes'
import { useStimpacksApi } from './composables/useStimpacksApi'
import { setupLayoutRenderer } from './composables/useLayoutRenderer'
import { makeGlobalKey } from './utils/storageKeys'
import { adoptLegacyAcceptance } from './utils/terms'
import { updateCheckIntervalMs } from './utils/updateCheckSchedule'
import { setPrivacyLockdownActive, isPrivacyLockdownActive } from './composables/usePrivacyLockdown'

const route = useRoute()
const router = useRouter()
const { getBoard, getProject } = useMediaApi()
const { currentProfileId, profiles, loadProfiles, setCurrentProfileId } = useProfile()
const { isAuthenticated, initAuth } = useAuth()
const { checkStartupReadiness, refreshReadiness } = useReadiness()
const { fetchSettings, updateDeveloperMode } = useSettingsApi()
const { runAutoInstall, checkUpdates: checkStimpackUpdates, updateFromMarketplace } = useStimpacksApi()
import { setWildcards, setSegments } from './composables/useWildcards'
const { restoreRoute, setupPersistence } = useRouteRestore()
const { slideshowActive } = useTabNavigation()
const { setTheme } = useTheme()
const {
  allTabs, findNextTab, removeTab,
  reopenLastClosed, getNextTab, getPrevTab
} = useWorkspaceTabs()
const { getLastProjectRoute } = useProjectRoute()
const { addToast } = useToasts()
const {
  updatesEnabled,
  channel: updateChannel,
  policy: updatePolicy,
  loadPreferences: loadUpdatePreferences,
  checkForUpdates,
} = useAppUpdater()
const { initReleaseNotes } = useReleaseNotes()
const sidebarOpen = ref(false)
const settingsOpen = ref(false)
const settingsSection = ref('folders')
const startupPending = ref(true)

// Connection state is ordinary app state, not a boot precondition: the
// renderer always has the local proxy to talk to, and main pushes every
// transition. One screen then covers cold launch, satellite launch, and a
// mid-session drop.
const { connectionState, activeDeviceName, init: initMultiDevice } = useMultiDevice()

function openSettings(section = 'folders') {
  settingsSection.value = section
  settingsOpen.value = true
}

function closeSettings() {
  settingsOpen.value = false
  // The readiness panel stays open behind settings so the user can work
  // through both BYOAI steps — recheck what they configured in there.
  void refreshReadiness()
}

// Lock screen state
const isLocked = ref(false)
const lockScreenPin = ref('')
const lockScreenError = ref('')
const lockScreenSubmitting = ref(false)
const lockScreenPinInput = ref(null)
const lockScreenProfileDropdownOpen = ref(false)

// A lock screen's half-typed PIN or stale error belongs to the connection it
// was entered on. Drop both when the device goes away so the lock screen
// comes back clean after the reconnect reload.
watch(connectionState, (state) => {
  if (state !== 'ready' && isLocked.value) {
    lockScreenPin.value = ''
    lockScreenError.value = ''
  }
})

function toggleLockScreenProfileDropdown() {
  lockScreenProfileDropdownOpen.value = !lockScreenProfileDropdownOpen.value
  if (lockScreenProfileDropdownOpen.value) {
    setTimeout(() => {
      document.addEventListener('click', handleLockScreenProfileClickOutside)
    }, 0)
  } else {
    document.removeEventListener('click', handleLockScreenProfileClickOutside)
  }
}

function handleLockScreenProfileClickOutside(event) {
  const dropdown = event.target.closest('.lock-screen-profile-dropdown')
  if (!dropdown && lockScreenProfileDropdownOpen.value) {
    lockScreenProfileDropdownOpen.value = false
    document.removeEventListener('click', handleLockScreenProfileClickOutside)
  }
}

const lockedProfileName = computed(() => {
  const profile = profiles.value.find(p => p.id === currentProfileId.value)
  return profile?.name || ''
})

// Check if current route wants no chrome (sidebar/topbar)
const noChrome = computed(() => route.meta?.noChrome === true)
const projectChrome = ref({
  project: null,
  activeRouteName: '',
  surfaceLabel: ''
})

// Current project context for the global search omnibox scope chip. Follows
// the same resolution as the ProjectScopeBar: whenever that bar is visible,
// search opens scoped to that project.
provide('searchProjectScope', computed(() => projectChrome.value.project))

// Generate a unique component key for each route
// For tools and chats, include the ID so each gets its own cached instance
function getComponentKey(route) {
  if (route.name === 'tool') {
    const projectId = route.query.project_id
    // Every tool tab is an instance (?instance is injected by the router
    // guard); the key must include it or two tabs of the same tool would
    // share one KeepAlive'd ToolView.
    const instance = route.query.instance ? `-i${route.query.instance}` : ''
    if (projectId) return `tool-${route.params.fullToolId}-project-${projectId}${instance}`
    return `tool-${route.params.fullToolId}${instance}`
  }
  if (route.name === 'chat') {
    return `chat-${route.params.id}`
  }
  if (route.name === 'board-detail') {
    return `board-${route.params.id}`
  }
  if (route.name === 'saved-view') {
    return `saved-view-${route.params.id}`
  }
  // One cached editor instance per Asset (a stack belongs to its
  // asset). Without the asset in the key every asset shares one instance and
  // the second one opened shows the first one's image.
  if (route.name === 'edit-image') {
    return `editor-${route.params.assetId}`
  }
  if (route.name === 'lineage') {
    return `lineage-${route.params.mediaId}`
  }
  if (route.name === 'flow') {
    return `flow-${route.params.id}`
  }
  // Project layout: one cached instance per project, stable across its
  // sub-screens (Assets/Boards/Overview/...). Keying by id (not the bare
  // sub-route name) means leaving to a tool and returning REACTIVATES the same
  // instance instead of remounting — so scroll/state are preserved (like the
  // main browser) and the project isn't reloaded on every sub-screen switch.
  // It also stops different projects from colliding on a shared key
  // (previously both keyed to e.g. "project-assets").
  if (typeof route.name === 'string' && route.name.startsWith('project-')) {
    return `project-${route.params.id}`
  }
  // For other routes, use the route name for consistent caching
  return route.name || route.path
}

const projectRouteNameBySurface = {
  overview: 'project-overview',
  assets: 'project-assets',
  chats: 'project-chats',
  boards: 'project-boards',
  flows: 'project-flows',
  tools: 'project-tools',
  settings: 'project-settings'
}

async function resolveProjectChrome() {
  try {
    const routeName = String(route.name || '')
    let projectId = null
    let activeRouteName = ''
    let surfaceLabel = ''

    if (routeName.startsWith('project-')) {
      projectId = Number.parseInt(String(route.params.id), 10)
      activeRouteName = routeName
      surfaceLabel = routeName.replace('project-', '').replace(/^\w/, (c) => c.toUpperCase())
    } else if (routeName === 'board-detail') {
      const board = await getBoard(Number.parseInt(String(route.params.id), 10))
      projectId = board?.project_id ?? null
      activeRouteName = projectId != null ? projectRouteNameBySurface.boards : ''
      surfaceLabel = projectId != null ? 'Board' : ''
    } else if (routeName === 'chat') {
      const response = await axios.get(`${getApiBase()}/chats/${route.params.id}`)
      projectId = response.data?.project_id ?? null
      activeRouteName = projectId != null ? projectRouteNameBySurface.chats : ''
      surfaceLabel = projectId != null ? 'Chat' : ''
    } else if (routeName === 'flow') {
      const response = await axios.get(`${getApiBase()}/flows/${route.params.id}`)
      projectId = response.data?.project_id ?? null
      activeRouteName = projectId != null ? projectRouteNameBySurface.flows : ''
      surfaceLabel = projectId != null ? 'Flow' : ''
    } else if (routeName === 'tool' || routeName === 'all-tools' || routeName === 'upload') {
      const rawProjectId = route.query.project_id
      if (typeof rawProjectId === 'string' && rawProjectId.trim()) {
        projectId = Number.parseInt(rawProjectId, 10)
        activeRouteName = ''
        surfaceLabel = routeName === 'upload' ? 'Upload' : routeName === 'tool' ? 'Tool' : 'Tools'
      }
    }

    if (!projectId || !Number.isFinite(projectId)) {
      projectChrome.value = {
        project: null,
        activeRouteName: '',
        surfaceLabel: ''
      }
      return
    }

    const project = await getProject(projectId)
    projectChrome.value = {
      project,
      activeRouteName,
      surfaceLabel
    }
  } catch {
    projectChrome.value = {
      project: null,
      activeRouteName: '',
      surfaceLabel: ''
    }
  }
}

// Chrome mode comes from the one viewport source of truth (useViewport):
// wide = sidebar + top bar exactly as before; compact = the sidebar becomes
// an overlay and the compact chrome takes over. On a desktop-sized window
// isCompact is false and nothing here changes.
const { isCompact } = useViewport()
const isMobile = isCompact
// Overlay routes (onboarding, image editor) take the whole screen on compact.
const compactOverlay = computed(() => route.meta?.surface === 'overlay')
// A detail view's title must not outlive its route.
watch(() => route.fullPath, () => clearCompactTitle())

function openSidebar() {
  sidebarOpen.value = true
}

function closeSidebar() {
  sidebarOpen.value = false
}

// Auto-close the overlay sidebar when the viewport grows back to wide.
watch(isCompact, (compact) => {
  if (!compact) sidebarOpen.value = false
})

// Re-sync cloud state whenever the app regains focus. This is the general case
// of returning from an external browser flow — most importantly completing a
// Stripe subscription, after which the set of available cloud models changes
// but nothing else would refetch (the user was already signed in, so no auth
// transition fires). Throttled so rapid focus toggling doesn't spam requests.
let lastFocusSyncAt = 0
const FOCUS_SYNC_THROTTLE_MS = 4000

function handleWindowFocusSync() {
  if (typeof document !== 'undefined' && document.visibilityState === 'hidden') return
  const now = Date.now()
  if (now - lastFocusSyncAt < FOCUS_SYNC_THROTTLE_MS) return
  lastFocusSyncAt = now
  // Model availability drives the chat composer's lock, so always resync it.
  refreshAvailableModels()
  // Credits only matter (and 401s only fire) when signed in.
  if (isAuthenticated.value) fetchCloudAccount()
}

function handleVisibilitySync() {
  if (document.visibilityState === 'visible') handleWindowFocusSync()
}

function getActiveTabId() {
  if (route.name === 'tool') {
    return toolRouteTabId(route)
  }
  if (route.name === 'chat') return `chat:${route.params.id}`
  if (route.name === 'board-detail') return `board:${route.params.id}`
  if (String(route.name || '').startsWith('project-')) return `project:${route.params.id}`
  if (route.name === 'flow') return `flow:${route.params.id}`
  const editorTabId = editorRouteTabId(route)
  if (editorTabId) return editorTabId
  return null
}

function navigateToTab(tab) {
  if (tab.type === 'tool') {
    router.push(toolTabRoute(tab))
  }
  else if (tab.type === 'chat') router.push({ name: 'chat', params: { id: tab.entityId } })
  else if (tab.type === 'board') router.push({ name: 'board-detail', params: { id: tab.entityId } })
  else if (tab.type === 'project') router.push({ name: getLastProjectRoute(tab.entityId), params: { id: tab.entityId } })
  else if (tab.type === 'editor') router.push(editorTabRoute(tab))
  else if (tab.type === 'flow') router.push({ name: 'flow', params: { id: tab.entityId } })
}

async function toggleDeveloperMode() {
  const nextEnabled = !devModeRef.value

  setDevMode(nextEnabled)
  addToast(`Developer mode ${nextEnabled ? 'enabled' : 'disabled'}`, 'info', 2500)

  try {
    await updateDeveloperMode(nextEnabled)
  } catch (error) {
    setDevMode(!nextEnabled)
    addToast('Failed to update developer mode', 'error', 3000)
    console.error('[App] Failed to persist developer mode toggle:', error)
  }
}

function handleKeydown(e) {
  // Cmd/Ctrl+K: focus the global search omnibox
  if ((e.metaKey || e.ctrlKey) && !e.shiftKey && (e.key === 'k' || e.key === 'K')) {
    e.preventDefault()
    requestGlobalSearchFocus()
    return
  }

  // Cmd/Ctrl+, to open Settings
  if ((e.metaKey || e.ctrlKey) && e.key === ',') {
    e.preventDefault()
    settingsOpen.value = true
  }

  // Cmd/Ctrl+Shift+D: toggle developer mode
  if ((e.metaKey || e.ctrlKey) && e.shiftKey && e.code === 'KeyD') {
    e.preventDefault()
    void toggleDeveloperMode()
    return
  }

  // Cmd/Ctrl+Shift+L: lock the current profile now, if it has a PIN set
  if ((e.metaKey || e.ctrlKey) && e.shiftKey && e.code === 'KeyL') {
    e.preventDefault()
    lockCurrentProfileNow()
    return
  }

  // Cmd/Ctrl+R to refresh in Tauri (browser handles this natively)
  if ((e.metaKey || e.ctrlKey) && !e.shiftKey && e.key === 'r' && isTauri()) {
    e.preventDefault()
    window.location.reload()
  }

  // --- Workspace tab shortcuts ---

  // Cmd/Ctrl+W: Close active workspace tab (blocked for pinned tabs)
  if ((e.metaKey || e.ctrlKey) && !e.shiftKey && e.key === 'w') {
    const activeId = getActiveTabId()
    if (activeId) {
      e.preventDefault()
      const tab = allTabs.value.find(t => t.id === activeId)
      if (tab?.pinned) {
        addToast('Unpin this tab before closing it', 'warning', 3000)
        return
      }
      const next = findNextTab(new Set([activeId]))
      if (next) navigateToTab(next)
      else router.push({ name: 'browse' })
      removeTab(activeId)
    }
  }

  // Cmd/Ctrl+Shift+W: Close the window (same as clicking the red close button).
  // Fires the same CloseRequested event the X does; the Rust handler closes
  // this window if others are open, or hides the last one to keep the
  // backend warm rather than quitting (to the tray on Windows/Linux).
  if ((e.metaKey || e.ctrlKey) && e.shiftKey && (e.key === 'w' || e.key === 'W') && isTauri()) {
    e.preventDefault()
    void import('./desktop').then(({ desktop }) => {
      void desktop.closeCurrentWindow()
    })
    return
  }

  // Cmd/Ctrl+Shift+T: Reopen last closed tab
  if ((e.metaKey || e.ctrlKey) && e.shiftKey && (e.key === 't' || e.key === 'T')) {
    const reopened = reopenLastClosed()
    if (reopened) {
      e.preventDefault()
      navigateToTab(reopened)
    }
  }

  // Ctrl+Tab: Next tab
  if (e.ctrlKey && !e.shiftKey && e.key === 'Tab') {
    const activeId = getActiveTabId()
    if (activeId) {
      const next = getNextTab(activeId)
      if (next) {
        e.preventDefault()
        navigateToTab(next)
      }
    }
  }

  // Ctrl+Shift+Tab: Previous tab
  if (e.ctrlKey && e.shiftKey && e.key === 'Tab') {
    const activeId = getActiveTabId()
    if (activeId) {
      const prev = getPrevTab(activeId)
      if (prev) {
        e.preventDefault()
        navigateToTab(prev)
      }
    }
  }
}

// Lock screen handlers
async function submitLockScreenPin() {
  if (!lockScreenPin.value || lockScreenSubmitting.value) return

  lockScreenSubmitting.value = true
  lockScreenError.value = ''

  // On a remote server this call crosses the network, and a route that has
  // gone dark answers nothing at all. The spinner must not outlive the
  // person's patience: give up and say so rather than "Verifying..." forever.
  const abort = new AbortController()
  const timer = setTimeout(() => abort.abort(), 20_000)

  try {
    const response = await fetch(`${getApiBase()}/profiles/${currentProfileId.value}/verify-pin`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Profile-ID': currentProfileId.value
      },
      body: JSON.stringify({ pin: lockScreenPin.value }),
      signal: abort.signal
    })

    if (response.ok) {
      // Cache the PIN and unlock
      cachePin(currentProfileId.value, lockScreenPin.value)
      isLocked.value = false
      lockScreenPin.value = ''
      lockScreenError.value = ''
      // The startup settings fetch was rejected while locked, so wildcards,
      // segments, theme, etc. never loaded. Re-run it now that the PIN is cached.
      try {
        await loadAppSettings()
      } catch (e) {
        console.warn('[App] Failed to reload settings after PIN unlock:', e)
      }
    } else if (response.status === 502 || response.status === 503) {
      // The local proxy answers these itself when the active device is gone
      // or unreachable. That is a connection problem, not a PIN problem; the
      // connection screen takes over once main reports the drop.
      lockScreenError.value = `Lost connection to ${activeDeviceName.value}`
      lockScreenPin.value = ''
    } else {
      const data = await response.json().catch(() => ({}))
      lockScreenError.value = data.detail || 'Invalid PIN'
      lockScreenPin.value = ''
    }
  } catch (error) {
    lockScreenError.value = `Could not reach ${activeDeviceName.value}`
    lockScreenPin.value = ''
    console.error('[App] PIN verification error:', error)
  } finally {
    clearTimeout(timer)
    lockScreenSubmitting.value = false
    // Re-focus input after error
    await nextTick()
    lockScreenPinInput.value?.focus()
  }
}

const { track: trackTelemetry } = useTelemetry()

// Route to land on once a lock-screen profile switch is unlocked. Set when
// switching to a PIN-locked profile; consumed by the isLocked watcher.
let pendingSwitchRoute = null

async function switchToProfileFromLockScreen(profile) {
  // Close dropdown
  lockScreenProfileDropdownOpen.value = false
  document.removeEventListener('click', handleLockScreenProfileClickOutside)

  // If clicking current profile, do nothing
  if (profile.id === currentProfileId.value) return

  trackTelemetry('profile_switched', {}, 'settings')

  // Desktop app: each profile lives in its own window. This window stays on
  // its (locked) profile; the target profile opens or focuses its own window
  // and shows its own lock screen there if it needs a PIN.
  if (await openProfileWindow(profile.id)) return

  // The target profile's own last location — we land here after switching,
  // instead of the current profile's URL (which references objects absent from
  // the target profile).
  const targetRoute = getSavedRouteForProfile(profile.id)

  // If target profile has PIN and we don't have it cached, show lock for that
  // profile. Remember where to land so the route restores on unlock.
  if (profile.has_pin && !hasCachedPin(profile.id)) {
    setCurrentProfileId(profile.id)
    pendingSwitchRoute = targetRoute
    lockScreenPin.value = ''
    lockScreenError.value = ''
    await nextTick()
    lockScreenPinInput.value?.focus()
    return
  }

  // Otherwise switch and reload onto the target profile's route to refresh
  // profile-scoped data.
  setCurrentProfileId(profile.id)
  window.location.href = targetRoute
}

// Check if current profile requires PIN on startup
// Load settings and apply all the side effects that depend on them.
// Extracted so it can run both at startup and again after a PIN unlock —
// when booting on a locked profile, the startup fetch is rejected with
// "PIN required", so this must re-run once the PIN is entered or
// settings-derived state (wildcards, segments, theme, etc.) stays empty.
async function loadAppSettings() {
  const settings = await fetchSettings()
  setAppModifier(settings.bundle_id, settings.sandbox)
  // App modifier is now set, so localStorage key prefix is stable — purge
  // legacy masks/paint (now in IndexedDB) and the old tool-descriptor cache.
  runStartupCleanup()
  setCloudBaseUrl(settings.cloud_base_url)
  setDevMode(settings.developer_mode)
  setAppBranch(settings.app_branch)
  setCaptioningEnabled(settings.background_work?.captioning?.enabled)
  setGenerationPreviews({
    images: settings.show_image_generation_previews,
    videos: settings.show_video_generation_previews,
  })
  setTelemetryEnabled(settings.telemetry_enabled)
  const privacyLockdown = settings.privacy_lockdown_active === true
  setPrivacyLockdownActive(privacyLockdown)
  initFeatureFlags(useWebSocket().on)
  // Account push events (balance/entitlements) -> quiet data refreshes.
  initAccountEvents()
  // Sidebar "finished while away" dots must track even when the sidebar
  // itself is unmounted (mobile, closed), so the singleton starts here.
  useUnseenActivity()
  // Auto update checks start only once Privacy Lockdown state is known.
  void startUpdaterLoop(privacyLockdown)
  // What's New pill: fetch this version's release notes (same host as the
  // updater), once lockdown state is known.
  void initReleaseNotes(privacyLockdown)
  // Sync theme from backend config (backend is source of truth,
  // localStorage is used for instant flash prevention on load)
  if (settings.theme) {
    setTheme(settings.theme)
  }
  // Cache wildcards and prompt segments for prompt expansion
  if (settings.wildcards) {
    setWildcards(settings.wildcards)
  }
  if (settings.prompt_segments) {
    setSegments(settings.prompt_segments)
  }
  // Notify components that settings (especially bundle_id/sandbox) are now available
  window.dispatchEvent(new CustomEvent('settings-loaded'))
}

/**
 * Whether the window's active device is connected. Outside the desktop shell
 * (or in a shell predating multi-device) there is exactly one backend and no
 * connection state to wait on, so that counts as ready.
 */
async function multiDeviceReady() {
  if (!isTauri()) return true
  try {
    const { desktop } = await import('./desktop')
    return (await desktop.mdGetState()).connectionState === 'ready'
  } catch {
    return true
  }
}

async function checkStartupPin() {
  try {
    // In the desktop app each window is pinned to one profile; resolve it
    // before anything profile-scoped runs.
    await initWindowProfile()

    // Fire-and-forget auth init (login is optional, not blocking)
    initAuth()

    await loadProfiles()

    // Record where this window landed so the window registry can restore it
    // on relaunch (covers the bootstrap window, which has no pinned profile).
    void reportWindowProfile(currentProfileId.value)

    // Load settings to get bundle_id/sandbox for localStorage key namespacing.
    // If the current profile is PIN-locked this is rejected ("PIN required");
    // loadAppSettings() is retried after unlock in submitLockScreenPin().
    try {
      await loadAppSettings()
    } catch (e) {
      console.warn('[App] Failed to load app identity from settings:', e)
    }

    // Marketplace maintenance is not required to render the saved workspace.
    // Let it overlap first paint; completion already announces live changes
    // through the stimpacks-changed event.
    void syncMarketplaceStimpacks()

    // Start persisting route changes
    setupPersistence()

    const profileId = currentProfileId.value
    const requiresPin = await profileRequiresPin(profileId)
    if (requiresPin && !hasCachedPin(profileId)) {
      isLocked.value = true
    } else {
      // Resolve onboarding before exposing the application shell. Otherwise
      // /home gets one paint before this asynchronous startup check redirects.
      //
      // Only when the backend actually answered, though. The onboarding flag
      // is keyed by the bundle id settings supplied; with settings unloaded
      // (backend down, errored, or a remote device still connecting) the key
      // is wrong and the flag reads as absent, which would shove an onboarded
      // user into the wizard. The connection screen owns that case; the
      // window is reloaded from the root once the device comes back.
      const startupReady = isSettingsLoaded() && (await multiDeviceReady())
      const onboarded = localStorage.getItem(makeGlobalKey('onboarding_completed')) !== null
      // The onboarding flag is scoped to the backend this window is driving,
      // so it is per server by design. Acceptance of the terms is not: carry
      // an existing one over to this install before the gate, or the first
      // switch to another server would ask for it a second time.
      if (startupReady) adoptLegacyAcceptance(onboarded)
      if (startupReady && !onboarded) {
        await router.replace({ name: 'onboarding' })
        return
      }
      // Restore saved route if not locked
      restoreRoute()
      // Onboarding already finished in some prior launch — check the
      // app-entry readiness gate (ReadinessPanel shows itself when unready).
      void checkStartupReadiness()
    }
  } catch (error) {
    console.error('[App] Failed to resolve startup state:', error)
  } finally {
    // Subscribe before clearing startupPending so the very first paint after
    // startup already reflects a device that turned out to be unreachable.
    await initMultiDevice()
    startupPending.value = false
    if (isLocked.value) {
      await nextTick()
      lockScreenPinInput.value?.focus()
    }
  }
}

// Focus PIN input when lock screen shows, restore route when unlocking
watch(isLocked, async (locked, wasLocked) => {
  if (locked) {
    await nextTick()
    lockScreenPinInput.value?.focus()
  } else if (wasLocked) {
    // If we unlocked into a profile switch, land on that profile's route.
    // Otherwise restore this profile's saved route (only acts at the app root).
    if (pendingSwitchRoute) {
      const target = pendingSwitchRoute
      pendingSwitchRoute = null
      if (target !== route.fullPath) router.replace(target)
    } else {
      restoreRoute()
    }
    void checkStartupReadiness()
  }
})

watch(currentProfileId, (profileId, previousProfileId) => {
  if (profileId && profileId !== previousProfileId) {
    void syncMarketplaceStimpacks(profileId)
  }
})

// Window title carries the profile name so windows are tellable apart in
// Mission Control / the Window menu / alt-tab.
watch([currentProfileId, profiles], async ([profileId]) => {
  if (!isTauri()) return
  const name = profiles.value.find(p => p.id === profileId)?.name
  if (!name) return
  try {
    const { desktop } = await import('./desktop')
    await desktop.setWindowTitle(`Stimma — ${name}`)
  } catch {
    // Title is cosmetic; ignore failures.
  }
}, { immediate: true })

watch(
  () => [route.name, route.params.id, route.query.project_id],
  () => {
    resolveProjectChrome()
  },
  { immediate: true }
)

// When user signs in via settings, refresh cloud-specific state (credits)
watch(isAuthenticated, async (authenticated) => {
  if (authenticated) {
    // Notify components so cloud account info can refresh
    window.dispatchEvent(new CustomEvent('settings-loaded'))
  }
})

// Cmd/Ctrl+Shift+L: lock the current profile immediately (no-op if it has no PIN)
function lockCurrentProfileNow() {
  const profile = profiles.value.find(p => p.id === currentProfileId.value)
  if (!profile?.has_pin) return

  trackTelemetry('profile_locked', {}, 'settings')
  clearCachedPin(currentProfileId.value)
  lockScreenPin.value = ''
  lockScreenError.value = ''
  isLocked.value = true
}

// Handle auto-lock event from idle timeout
function handleAutoLock(event) {
  const { profileId } = event.detail
  if (profileId === currentProfileId.value) {
    console.log('[App] Auto-lock triggered for profile:', profileId)
    trackTelemetry('profile_locked', {}, 'settings')
    isLocked.value = true
    lockScreenPin.value = ''
    lockScreenError.value = ''
  }
}

let updateIntervalId = null
let updaterLoopStarted = false
const syncedMarketplaceStimpackProfiles = new Set()
const marketplaceStimpackSyncByProfile = new Map()

async function syncMarketplaceStimpacks(profileId = currentProfileId.value) {
  if (isPrivacyLockdownActive()) return
  if (!profileId || syncedMarketplaceStimpackProfiles.has(profileId)) return

  const existingRun = marketplaceStimpackSyncByProfile.get(profileId)
  if (existingRun) {
    await existingRun
    return
  }

  const run = (async () => {
    let stimpacksChanged = false

    try {
      const result = await runAutoInstall()
      if ((result.installed || []).length > 0) {
        stimpacksChanged = true
      }
    } catch (error) {
      console.warn('[App] Failed to auto-install default stimpacks:', error)
    }

    try {
      const updates = await checkStimpackUpdates()
      for (const update of updates) {
        try {
          await updateFromMarketplace(update.name)
          stimpacksChanged = true
        } catch (error) {
          console.warn(`[App] Failed to update stimpack ${update.name}:`, error)
        }
      }
    } catch (error) {
      console.warn('[App] Failed to check for stimpack updates:', error)
    }

    if (stimpacksChanged) {
      window.dispatchEvent(new CustomEvent('stimpacks-changed'))
    }
    syncedMarketplaceStimpackProfiles.add(profileId)
  })()

  marketplaceStimpackSyncByProfile.set(profileId, run)
  try {
    await run
  } finally {
    marketplaceStimpackSyncByProfile.delete(profileId)
  }
}

// Started from loadAppSettings() once Privacy Lockdown state is known.
async function startUpdaterLoop(privacyLockdownActive) {
  if (!updatesEnabled.value) return
  if (privacyLockdownActive) return
  if (updaterLoopStarted) return

  // With several profile windows open, only one may run the update loop —
  // concurrent automatic downloads would collide. The Web Lock is held for
  // as long as the loop runs; if the owning window closes, a waiting window
  // acquires it and takes over.
  if (typeof navigator !== 'undefined' && navigator.locks?.request) {
    void navigator.locks.request('stimma-updater-loop', async () => {
      if (await runUpdaterLoop()) {
        return new Promise(() => {})
      }
    })
  } else {
    void runUpdaterLoop()
  }
}

// Returns true when the scheduled check loop actually started.
async function runUpdaterLoop() {
  await loadUpdatePreferences()
  // Manual mode: no scheduled checks. Leave the loop unstarted so that
  // switching to automatic/notify later can start it without a restart.
  if (updatePolicy.value === 'manual') return false

  updaterLoopStarted = true
  markUpdaterOwner()
  await checkForUpdates('auto')

  if (updateIntervalId) {
    window.clearInterval(updateIntervalId)
  }
  updateIntervalId = window.setInterval(() => {
    checkForUpdates('auto')
  }, updateCheckIntervalMs(updateChannel.value))
  return true
}

function handleOpenSettings(e) {
  openSettings(e.detail || 'folders')
}

onMounted(async () => {
  // Guard the root scrolling element the same way as the shell divs.
  const rootGuard = () => {
    const d = document.scrollingElement || document.documentElement
    if (d.scrollTop) d.scrollTop = 0
    if (d.scrollLeft) d.scrollLeft = 0
    const app = document.getElementById('app')
    if (app && app.scrollTop) app.scrollTop = 0
    if (app && app.scrollLeft) app.scrollLeft = 0
  }
  window.addEventListener('scroll', rootGuard, { passive: true })
  document.getElementById('app')?.addEventListener('scroll', rootGuard, { passive: true })

  window.addEventListener('keydown', handleKeydown)
  window.addEventListener('pin-auto-locked', handleAutoLock)
  window.addEventListener('open-settings', handleOpenSettings)
  window.addEventListener('focus', handleWindowFocusSync)
  document.addEventListener('visibilitychange', handleVisibilitySync)

  // Register the WS handler that lets the backend ask us to render
  // .stimmalayout HTML to PNG bytes via the real browser engine.
  setupLayoutRenderer()

  // Start idle tracking for PIN timeout
  startIdleTracking()

  // Check if we need PIN entry on startup. This loads settings and starts
  // the updater loop once the settings fetch succeeds.
  checkStartupPin()

})

onUnmounted(() => {
  window.removeEventListener('keydown', handleKeydown)
  window.removeEventListener('pin-auto-locked', handleAutoLock)
  window.removeEventListener('open-settings', handleOpenSettings)
  window.removeEventListener('focus', handleWindowFocusSync)
  document.removeEventListener('visibilitychange', handleVisibilitySync)
  if (updateIntervalId) {
    window.clearInterval(updateIntervalId)
    updateIntervalId = null
  }
})
</script>

<style>
/* Slide out NavigationSidebar and TopBar in slideshow focus mode */
.navigation-sidebar {
  transition: margin-left 0.3s ease, opacity 0.3s ease;
}

.top-bar {
  transition: margin-top 0.3s ease, opacity 0.3s ease;
}

body.slideshow-focus-mode .navigation-sidebar {
  margin-left: 0 !important;
  width: 0 !important; /* Override inline width style from resizable sidebar */
  flex-basis: 0 !important;
  min-width: 0 !important;
  border-right-width: 0 !important;
  opacity: 0;
  pointer-events: none;
  overflow: hidden;
}

body.slideshow-focus-mode .sidebar-overlay {
  display: none !important;
}

body.slideshow-focus-mode .top-bar {
  margin-top: -56px; /* h-14 = 3.5rem = 56px */
  opacity: 0;
  pointer-events: none;
}

body.slideshow-cursor-hidden,
body.slideshow-cursor-hidden *:not([data-context-menu] *):not([data-context-menu]) {
  cursor: none !important;
}

</style>
