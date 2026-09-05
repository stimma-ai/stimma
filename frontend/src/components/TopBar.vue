<template>
  <div class="relative flex items-center justify-between px-4 h-14 bg-surface border-b border-edge-subtle flex-shrink-0" data-tauri-drag-region>
    <!-- Left side: navigation buttons -->
    <div class="flex items-center gap-0.5">
      <button
        class="w-7 h-7 flex items-center justify-center rounded transition-colors"
        :class="canGoBack ? 'text-content-secondary hover:bg-overlay-subtle hover:text-content cursor-pointer' : 'text-content-muted/30 cursor-default'"
        :disabled="!canGoBack"
        @click="goBack"
        title="Go back"
      >
        <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" d="M15.75 19.5L8.25 12l7.5-7.5" />
        </svg>
      </button>
      <button
        class="w-7 h-7 flex items-center justify-center rounded transition-colors"
        :class="canGoForward ? 'text-content-secondary hover:bg-overlay-subtle hover:text-content cursor-pointer' : 'text-content-muted/30 cursor-default'"
        :disabled="!canGoForward"
        @click="goForward"
        title="Go forward"
      >
        <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" d="M8.25 4.5l7.5 7.5-7.5 7.5" />
        </svg>
      </button>
    </div>

    <!-- Center: global search omnibox -->
    <!-- z-30: the translate wrapper traps the dropdown's z-index in its own
         stacking context, which must outrank the view roots (relative, z-auto) -->
    <div class="absolute left-1/2 top-0 h-full -translate-x-1/2 flex items-center z-30">
      <GlobalSearchBox />
    </div>

    <!-- Right side: controls and progress -->
    <div class="flex items-center gap-2">
      <!-- Processing indicator (only shows when there's activity or errors) -->
      <div
        v-if="hasActiveWork"
        class="relative cursor-pointer select-none processing-indicator p-2"
        @click="toggleExpanded"
        :title="progressTitle"
      >
        <BackgroundWorkIndicator />
        <transition name="expand">
          <div v-if="isExpanded" class="absolute top-[calc(100%+0.5rem)] right-0 bg-surface border border-edge rounded-lg p-4 min-w-[400px] shadow-[0_8px_16px_rgba(0,0,0,0.5)] z-menu">
            <BackgroundWorkPanel />
          </div>
        </transition>
      </div>

      <!-- Update affordance: compact icon pill that peeks open on state change and expands on hover -->
      <button
        v-if="updateState && !updatesBlockedByPrivacyLockdown"
        @click="onUpdatePillClick"
        @mouseenter="updatePillHover = true"
        @mouseleave="updatePillHover = false"
        class="flex items-center h-7 rounded-full border overflow-hidden whitespace-nowrap text-xs font-medium transition-[width,background-color] duration-200 ease-out select-none"
        :class="[
          updateState === 'restart'
            ? 'bg-green-500/15 border-green-500/50 text-green-400 hover:bg-green-500/25'
            : 'bg-accent/15 border-accent/50 text-accent-hi',
          updateState === 'available' || updateState === 'whatsnew' ? 'hover:bg-accent/25' : '',
          updateState === 'downloading' ? 'cursor-default' : '',
        ]"
        :style="{ width: updatePillExpanded ? updatePillWidth : '28px' }"
        :title="updatePillLabel"
      >
        <span class="flex-none w-[26px] flex items-center justify-center">
          <Spinner v-if="updateState === 'downloading'" size="sm" />
          <svg v-else-if="updateState === 'restart'" class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" d="M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0l3.181 3.183a8.25 8.25 0 0013.803-3.7M4.031 9.865a8.25 8.25 0 0113.803-3.7l3.181 3.182m0-4.991v4.99" />
          </svg>
          <svg v-else-if="updateState === 'whatsnew'" class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" d="M9.813 15.904 9 18.75l-.813-2.846a4.5 4.5 0 0 0-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 0 0 3.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 0 0 3.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 0 0-3.09 3.09ZM18.259 8.715 18 9.75l-.259-1.035a3.375 3.375 0 0 0-2.455-2.456L14.25 6l1.036-.259a3.375 3.375 0 0 0 2.455-2.456L18 2.25l.259 1.035a3.375 3.375 0 0 0 2.456 2.456L21.75 6l-1.035.259a3.375 3.375 0 0 0-2.456 2.456Z" />
          </svg>
          <svg v-else class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5M16.5 12L12 16.5m0 0L7.5 12m4.5 4.5V3" />
          </svg>
        </span>
        <span
          ref="updatePillLabelEl"
          class="pr-3 transition-opacity duration-150"
          :class="updatePillExpanded ? 'opacity-100 delay-75' : 'opacity-0'"
        >{{ updatePillLabel }}</span>
      </button>

      <!-- Tool-provider managers (e.g. ComfyUI): one icon per provider that
           advertises a management UI over STP. -->
      <ProviderManagerButton :show-separator="profiles.length > 1" />

      <!-- Profile picker: exists only when a second profile does -->
      <div v-if="profiles.length > 1" class="relative profile-menu">
        <!-- Ghost trigger, not a pill — bordered+filled chips aren't Atelier
             chrome; the menu carries the affordance. -->
        <button
          class="flex items-center gap-1.5 h-7 px-2 rounded-md text-[13px] text-content-secondary transition-colors cursor-pointer hover:text-content hover:bg-overlay-subtle"
          @click="toggleProfileMenu"
          title="Switch profile"
        >
          <span class="max-w-[140px] truncate">{{ currentProfileName }}</span>
          <svg class="w-3 h-3 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" d="m19.5 8.25-7.5 7.5-7.5-7.5" />
          </svg>
        </button>

        <transition name="menu">
          <div
            v-if="profileMenuOpen"
            class="absolute top-[calc(100%+0.5rem)] right-0 bg-surface border border-edge-subtle rounded-lg shadow-[0_8px_16px_rgba(0,0,0,0.5)] z-menu min-w-[220px] overflow-hidden"
          >
            <div class="py-1">
              <div
                v-for="profile in profiles"
                :key="profile.id"
                class="w-full px-3 py-2 text-left text-xs transition-colors flex items-center gap-2 cursor-pointer"
                :class="profile.id === currentProfileId ? 'bg-accent/10 text-content' : 'text-content-secondary hover:bg-overlay-subtle hover:text-content'"
                @click="selectProfile(profile.id)"
              >
                <svg v-if="profile.id === currentProfileId" class="w-4 h-4 text-accent-hi flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
                  <path stroke-linecap="round" stroke-linejoin="round" d="m4.5 12.75 6 6 9-13.5" />
                </svg>
                <span v-else class="w-4 h-4 flex-shrink-0"></span>
                <span class="truncate flex-1">{{ profile.name }}</span>
                <!-- Unlocked icon - profile has PIN and is currently unlocked (cached) -->
                <button
                  v-if="profile.has_pin && hasCachedPin(profile.id)"
                  @click.stop="lockProfile(profile.id)"
                  class="p-1 -mr-1 rounded hover:bg-overlay-light transition-colors"
                  title="Lock profile"
                >
                  <svg class="w-3.5 h-3.5 text-blue-500" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
                    <path stroke-linecap="round" stroke-linejoin="round" d="M13.5 10.5V6.75a4.5 4.5 0 1 1 9 0v3.75M3.75 21.75h10.5a2.25 2.25 0 0 0 2.25-2.25v-6.75a2.25 2.25 0 0 0-2.25-2.25H3.75a2.25 2.25 0 0 0-2.25 2.25v6.75a2.25 2.25 0 0 0 2.25 2.25Z" />
                  </svg>
                </button>
                <!-- Locked icon - profile has PIN but is locked (not cached) -->
                <svg
                  v-else-if="profile.has_pin"
                  class="w-3.5 h-3.5 text-content-muted flex-shrink-0"
                  fill="none"
                  viewBox="0 0 24 24"
                  stroke-width="2"
                  stroke="currentColor"
                >
                  <path stroke-linecap="round" stroke-linejoin="round" d="M16.5 10.5V6.75a4.5 4.5 0 1 0-9 0v3.75m-.75 11.25h10.5a2.25 2.25 0 0 0 2.25-2.25v-6.75a2.25 2.25 0 0 0-2.25-2.25H6.75a2.25 2.25 0 0 0-2.25 2.25v6.75a2.25 2.25 0 0 0 2.25 2.25Z" />
                </svg>
              </div>
              <!-- Manage Profiles -->
              <button
                @click="openProfilesSettings"
                class="w-full px-3 py-2 text-left text-sm text-content-secondary hover:bg-overlay-subtle hover:text-content flex items-center gap-2.5 transition-colors"
              >
                <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M15.75 6a3.75 3.75 0 1 1-7.5 0 3.75 3.75 0 0 1 7.5 0ZM4.501 20.118a7.5 7.5 0 0 1 14.998 0A17.933 17.933 0 0 1 12 21.75c-2.676 0-5.216-.584-7.499-1.632Z" />
                </svg>
                <span>Manage Profiles</span>
              </button>
            </div>
          </div>
        </transition>
      </div>
    </div>

    <WhatsNewModal
      :show="whatsNewOpen"
      :markdown="notesMarkdown"
      :version="notesVersion"
      @close="closeWhatsNew"
    />
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount, watch, nextTick } from 'vue'
import { useTelemetry } from '../composables/useTelemetry'
import { useRouter, useRoute } from 'vue-router'
import { useWebSocket } from '../composables/useWebSocket'
import { useProfile, openProfileWindow } from '../composables/useProfile'
import { getSavedRouteForProfile } from '../composables/useRouteRestore'
import { clearCachedPin, hasCachedPin } from '../composables/usePinLock'
import { useAppUpdater } from '../composables/useAppUpdater'
import { useReleaseNotes } from '../composables/useReleaseNotes'
import WhatsNewModal from './WhatsNewModal.vue'
import GlobalSearchBox from './search/GlobalSearchBox.vue'
import ProviderManagerButton from './ProviderManagerButton.vue'
import Spinner from './ui/Spinner.vue'
import BackgroundWorkIndicator from './BackgroundWorkIndicator.vue'
import BackgroundWorkPanel from './BackgroundWorkPanel.vue'
import { useBackgroundWork } from '../composables/useBackgroundWork'

const router = useRouter()
const route = useRoute()

const emit = defineEmits(['open-settings'])

// Navigation history tracking
const navHistory = ref([])
const navIndex = ref(-1)
let isNavAction = false

const canGoBack = computed(() => navIndex.value > 0)
const canGoForward = computed(() => navIndex.value < navHistory.value.length - 1)

function goBack() {
  if (!canGoBack.value) return
  isNavAction = true
  navIndex.value--
  router.push(navHistory.value[navIndex.value])
}

function goForward() {
  if (!canGoForward.value) return
  isNavAction = true
  navIndex.value++
  router.push(navHistory.value[navIndex.value])
}

// Track route changes
router.afterEach((to) => {
  if (isNavAction) {
    isNavAction = false
    return
  }
  // Normal navigation: truncate forward history and push new entry
  navHistory.value = navHistory.value.slice(0, navIndex.value + 1)
  navHistory.value.push(to.fullPath)
  navIndex.value = navHistory.value.length - 1
})

const { connected: wsConnected } = useWebSocket()
// Profile management
const {
  currentProfileId,
  profiles,
  isLoadingProfiles,
  setCurrentProfileId,
  loadProfiles,
} = useProfile()

// Theme

// Updates
const {
  hasUpdate,
  pendingRestart,
  isDownloading,
  updatesBlockedByPrivacyLockdown,
  downloadAndInstallUpdate,
  restartToApply,
} = useAppUpdater()

const {
  notesMarkdown,
  notesVersion,
  hasUnseenNotes,
  whatsNewOpen,
  openWhatsNew,
  closeWhatsNew,
} = useReleaseNotes()

// Update pill: rests as a compact icon; peeks open for a few seconds when the
// state changes, and expands on hover. Width is measured from the label so the
// expand animation has a concrete px target.
const updateState = computed(() => {
  if (isDownloading.value) return 'downloading'
  if (pendingRestart.value) return 'restart'
  if (hasUpdate.value) return 'available'
  // Lowest priority: release notes for the version we're already running.
  if (hasUnseenNotes.value) return 'whatsnew'
  return null
})
const updatePillLabel = computed(() => {
  switch (updateState.value) {
    case 'downloading': return 'Updating…'
    case 'restart': return 'Restart to update'
    case 'available': return 'Update available'
    case 'whatsnew': return "What's new"
    default: return ''
  }
})
const updatePillLabelEl = ref(null)
const updatePillHover = ref(false)
const updatePillPeek = ref(false)
const updatePillWidth = ref('28px')
const updatePillExpanded = computed(() => updatePillHover.value || updatePillPeek.value)
let updatePillPeekTimer

watch(updateState, async (state) => {
  if (!state) {
    updatePillPeek.value = false
    return
  }
  await nextTick()
  const label = updatePillLabelEl.value
  // 26px icon well + label + 12px right padding + 2px borders
  if (label) updatePillWidth.value = `${26 + label.scrollWidth + 12 + 2}px`
  clearTimeout(updatePillPeekTimer)
  updatePillPeek.value = true
  updatePillPeekTimer = setTimeout(() => { updatePillPeek.value = false }, 3000)
}, { immediate: true })

function onUpdatePillClick() {
  if (updateState.value === 'available') downloadAndInstallUpdate()
  else if (updateState.value === 'restart') restartToApply()
  else if (updateState.value === 'whatsnew') openWhatsNew()
}

// Profile picker menu
const profileMenuOpen = ref(false)

const currentProfileName = computed(() => {
  const current = profiles.value.find(p => p.id === currentProfileId.value)
  return current?.name || 'Profile'
})

function closeProfileMenu() {
  profileMenuOpen.value = false
  document.removeEventListener('click', handleProfileClickOutside)
}

function toggleProfileMenu() {
  profileMenuOpen.value = !profileMenuOpen.value
  if (profileMenuOpen.value) {
    setTimeout(() => {
      document.addEventListener('click', handleProfileClickOutside)
    }, 0)
  } else {
    document.removeEventListener('click', handleProfileClickOutside)
  }
}

function handleProfileClickOutside(event) {
  const menu = event.target.closest('.profile-menu')
  if (!menu && profileMenuOpen.value) {
    closeProfileMenu()
  }
}

const { track: trackTelemetry } = useTelemetry()

async function selectProfile(profileId) {
  closeProfileMenu()

  if (profileId === currentProfileId.value) return

  trackTelemetry('profile_switched', {}, 'settings')

  // Desktop app: browser-style switching — each profile lives in its own
  // window, so open (or focus) the target profile's window and leave this
  // window on its current profile.
  if (await openProfileWindow(profileId)) return

  // Land on the target profile's last location (its own per-profile route),
  // not the current profile's URL — which points at objects that don't exist
  // in the profile we're switching to. This reloads to refresh profile-scoped
  // data; the lock screen still shows if the target profile requires a PIN.
  const targetRoute = getSavedRouteForProfile(profileId)
  setCurrentProfileId(profileId)
  window.location.href = targetRoute
}

function openProfilesSettings() {
  closeProfileMenu()
  emit('open-settings', 'profiles')
}

function lockProfile(profileId) {
  trackTelemetry('profile_locked', {}, 'settings')
  clearCachedPin(profileId)
  closeProfileMenu()
  // If locking the current profile, reload to trigger lock screen
  if (profileId === currentProfileId.value) {
    window.location.reload()
  }
}

const backgroundWork = useBackgroundWork()
const { hasActiveWork, progressTitle } = backgroundWork

const isExpanded = ref(false)

function toggleExpanded(event) {
  event.stopPropagation()
  isExpanded.value = !isExpanded.value
  if (isExpanded.value) {
    // Use capture phase to ensure we always get the event
    setTimeout(() => {
      document.addEventListener('click', handleClickOutside, true)
    }, 0)
  } else {
    document.removeEventListener('click', handleClickOutside, true)
  }
}

function handleClickOutside(event) {
  // Clicks inside the widget (including the failed-items modal it opens,
  // which teleports to body) keep it open.
  const inside = event.target.closest('.processing-indicator') || event.target.closest('[data-modal-layer]')
  if (!inside && isExpanded.value) {
    isExpanded.value = false
    document.removeEventListener('click', handleClickOutside, true)
  }
}

onMounted(() => {
  // Seed navigation history with current route
  if (navHistory.value.length === 0) {
    navHistory.value.push(route.fullPath)
    navIndex.value = 0
  }
  loadProfiles()
  backgroundWork.start()
})

// Reload profiles when websocket reconnects (backend was down and came back)
watch(wsConnected, (connected, wasConnected) => {
  if (connected && wasConnected === false) {
    loadProfiles()
  }
})

onBeforeUnmount(() => {
  document.removeEventListener('click', handleClickOutside, true)
  document.removeEventListener('click', handleProfileClickOutside)
})
</script>

<style scoped>
/* Expand transition */
.expand-enter-active,
.expand-leave-active {
  transition: all 0.3s ease;
}

.expand-enter-from,
.expand-leave-to {
  opacity: 0;
  transform: translateY(-10px);
}

</style>
