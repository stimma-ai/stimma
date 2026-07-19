<template>
  <Modal
    :show="show"
    size="custom"
    custom-class="w-[920px] max-w-[90vw] h-[900px] max-h-[90vh] flex flex-col overflow-hidden"
    :close-on-esc="false"
    @close="close"
  >
    <template #header>
      <div class="flex items-center justify-between">
        <h2 class="text-[16px] font-semibold text-content">Settings</h2>
        <IconButton aria-label="Close" title="Close" @click="close">
          <svg class="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
          </svg>
        </IconButton>
      </div>
    </template>

    <!-- Content -->
    <div class="flex flex-1 overflow-hidden">
      <!-- Sidebar -->
      <SettingsSidebar
        :active-section="activeSection"
        :profiles="settings?.profiles || []"
        :current-profile-id="currentProfileId"
        :llm-setup-required="llmSetupRequired"
        :generation-setup-required="generationSetupRequired"
        @select="activeSection = $event"
        @switch-profile="handleProfileSwitch"
      />

      <!-- Main content area -->
      <div class="flex-1 overflow-y-auto p-6">
        <!-- Loading state -->
        <div v-if="loading" class="flex items-center justify-center h-full">
          <Spinner size="md" />
        </div>

        <!-- Error state -->
        <div v-else-if="error" class="text-center py-12">
          <p class="text-red-400 mb-4">{{ error }}</p>
          <Button variant="secondary" @click="loadSettings">
            Retry
          </Button>
        </div>

              <!-- Profiles Section -->
              <template v-else-if="activeSection === 'profiles'">
                <ProfilesSection
                  v-if="settings"
                  :profiles="settings.profiles || []"
                  :current-profile-id="currentProfileId"
                  @update="handleProfileUpdate"
                  @create="handleProfileCreate"
                  @delete="handleProfileDelete"
                  @switch="handleProfileSwitch"
                  @reorder="handleProfileReorder"
                />
              </template>

              <!-- Folders Section -->
              <template v-else-if="activeSection === 'folders'">
                <FoldersSection
                  v-if="settings"
                  :folders="settings.folders"
                  @update="handleFoldersUpdate"
                  @rescan="handleFolderRescan"
                  @refresh="loadSettings"
                />
              </template>

              <!-- Markers Section -->
              <template v-else-if="activeSection === 'markers'">
                <MarkersSection
                  v-if="settings"
                  :markers="settings.markers"
                  @update="handleMarkersUpdate"
                />
              </template>

              <!-- Wildcards Section -->
              <template v-else-if="activeSection === 'wildcards'">
                <WildcardsSection
                  v-if="settings"
                  :wildcards="settings.wildcards || []"
                  :prompt-segments="settings.prompt_segments || []"
                  @update="handleWildcardsUpdate"
                  @update-segments="handleSegmentsUpdate"
                />
              </template>

              <!-- Generation Tools Section -->
              <template v-else-if="activeSection === 'tools'">
                <ToolProvidersSection
                  v-if="settings"
                  ref="toolProvidersSection"
                  :providers="settings.tool_providers"
                  :setup-required="generationSetupRequired"
                  @update="handleToolProviderUpdate"
                  @create="handleToolProviderCreate"
                  @delete="handleToolProviderDelete"
                />
              </template>

              <!-- Background Work Section -->
              <template v-else-if="activeSection === 'background'">
                <BackgroundWorkSection
                  v-if="settings"
                  :background-work="settings.background_work"
                  @update="handleBackgroundWorkUpdate"
                />
              </template>

              <!-- Updates Section -->
              <template v-else-if="activeSection === 'updates'">
                <UpdatesSection />
              </template>

              <!-- Account Section -->
              <template v-else-if="activeSection === 'account'">
                <AccountSection
                  :tool-providers="settings?.tool_providers || []"
                  @close="close"
                  @navigate="activeSection = $event"
                />
              </template>

              <!-- Privacy Section -->
              <template v-else-if="activeSection === 'privacy'">
                <PrivacySection
                  v-if="settings"
                  :telemetry-enabled="settings.telemetry_enabled === true"
                  :privacy-lockdown-active="settings.privacy_lockdown_active === true"
                  @telemetry-updated="handleTelemetryUpdated"
                />
              </template>

              <!-- Agent Section -->
              <template v-else-if="activeSection === 'agent'">
                <AgentSection />
              </template>

              <!-- Chat Models Section -->
              <template v-else-if="activeSection === 'ai-services'">
                <AIServicesSection
                  v-if="settings"
                  ref="aiServicesSection"
                  :llm-settings="settings.llm_settings"
                  :setup-required="llmSetupRequired"
                  @update="handleLlmSettingsUpdate"
                  @navigate="activeSection = $event"
                />
              </template>

              <!-- Model Preferences Section -->
              <template v-else-if="activeSection === 'model-preferences'">
                <ModelPreferencesSection />
              </template>

              <!-- Developer Section -->
              <template v-else-if="activeSection === 'developer'">
                <DeveloperSection
                  v-if="settings"
                  :developer-mode="settings.developer_mode"
                  :debug-force-ffmpeg-missing="settings.debug_force_ffmpeg_missing"
                  @update-developer-mode="handleDeveloperModeUpdate"
                  @update-debug-force-ffmpeg-missing="handleDebugForceFfmpegMissingUpdate"
                  @close-settings="close"
                />
              </template>
            </div>
          </div>
  </Modal>

  <!-- PIN Entry Modal for locked profiles -->
  <PinEntryModal
    :show="showPinModal"
    :profile-name="pinModalProfileName"
    :error="pinModalError"
    @submit="submitPin"
    @cancel="cancelPinEntry"
  />
</template>

<script setup>
import { ref, watch, nextTick, onMounted, onUnmounted, computed } from 'vue'
import { useTelemetry } from '../../composables/useTelemetry'
import { useSettingsApi } from '../../composables/useSettingsApi'
import { useWebSocket } from '../../composables/useWebSocket'
import { setDevMode, devModeRef } from '../../appConfig'
import { useProfile } from '../../composables/useProfile'
import { usePinLock } from '../../composables/usePinLock'
import { useAuth } from '../../composables/useAuth'
import { useCloudAccount } from '../../composables/useCloudAccount'
import { useAvailableModels } from '../../composables/useAvailableModels'
import { addToast } from '../../composables/useToasts'
import { hasUsableGenerationProvider, hasUsableLlmModel } from '../../utils/settingsReadiness'
import SettingsSidebar from './SettingsSidebar.vue'
import ProfilesSection from './sections/ProfilesSection.vue'
import FoldersSection from './sections/FoldersSection.vue'
import MarkersSection from './sections/MarkersSection.vue'
import ToolProvidersSection from './sections/ToolProvidersSection.vue'
import BackgroundWorkSection from './sections/BackgroundWorkSection.vue'
import UpdatesSection from './sections/UpdatesSection.vue'
import AccountSection from './sections/AccountSection.vue'
import PrivacySection from './sections/PrivacySection.vue'
import AIServicesSection from './sections/AIServicesSection.vue'
import ModelPreferencesSection from './sections/ModelPreferencesSection.vue'
import DeveloperSection from './sections/DeveloperSection.vue'
import AgentSection from './sections/AgentSection.vue'
import WildcardsSection from './sections/WildcardsSection.vue'
import PinEntryModal from '../PinEntryModal.vue'
import Modal from '../ui/Modal.vue'
import IconButton from '../ui/IconButton.vue'
import Button from '../ui/Button.vue'
import Spinner from '../ui/Spinner.vue'
import { setWildcards, setSegments } from '../../composables/useWildcards'
import { preserveConnectingToolProviderStatuses, toolProviderUpdateStartsConnection } from '../../utils/toolProviderBrands'

const props = defineProps({
  show: {
    type: Boolean,
    default: false
  },
  initialSection: {
    type: String,
    default: 'folders'
  }
})

const emit = defineEmits(['close'])

const { fetchSettings, updateFolders, updateMarkers, updateWildcards, updatePromptSegments, updateToolProvider, createToolProvider, deleteToolProvider, updateBackgroundWork, updateLlmSettings, createProfile, deleteProfile, renameProfile, rescanFolders, updateDeveloperMode, updateDebugForceFfmpegMissing, recheckFfmpeg } = useSettingsApi()
const { on, off } = useWebSocket()
const { currentProfileId, setCurrentProfileId, loadProfiles } = useProfile()
const { showPinModal, pinModalProfileId, pinModalError, submitPin, cancelPinEntry, ensurePinForProfile } = usePinLock()
const { models: availableModels, hasFetched: hasFetchedModels, fetchModels } = useAvailableModels()
const { isAuthenticated } = useAuth()
const { cloudUser, fetchCloudAccount } = useCloudAccount()

// Compute profile name for PIN modal
const pinModalProfileName = computed(() => {
  const profile = settings.value?.profiles?.find(p => p.id === pinModalProfileId.value)
  return profile?.name || ''
})

const activeSection = ref('folders')
const aiServicesSection = ref(null)
const toolProvidersSection = ref(null)
const settings = ref(null)
const loading = ref(false)
const error = ref(null)

// A signed-in account with zero balance is NOT set up: the cloud provider
// stays connected and the model catalog still lists as available, so the
// balance has to gate whether Stimma Cloud counts toward readiness.
const stimmaCloudUsable = computed(() => Number(cloudUser.value?.credits ?? 0) > 0)

const llmSetupRequired = computed(() => (
  hasFetchedModels.value
  && !hasUsableLlmModel(availableModels.value, { stimmaCloudUsable: stimmaCloudUsable.value })
))

const generationSetupRequired = computed(() => {
  if (!settings.value) return false
  return !hasUsableGenerationProvider(settings.value.tool_providers, { stimmaCloudUsable: stimmaCloudUsable.value })
})

// Handle provider status changes from WebSocket
function handleProviderStatusChanged(data) {
  if (!settings.value) return

  const { provider_id, status } = data
  if (!provider_id || !status) return

  // Update the status of the matching provider
  const freshProviders = settings.value.tool_providers.map(provider =>
    provider.id === provider_id ? { ...provider, status } : provider
  )
  settings.value = {
    ...settings.value,
    tool_providers: preserveConnectingToolProviderStatuses(settings.value.tool_providers, freshProviders),
  }
}

// Handle tools_updated event (provider connected/disconnected)
// Re-fetch settings to pick up newly connected providers like Stimma Cloud
async function handleToolsUpdated() {
  if (!props.show) return
  try {
    const freshSettings = await fetchSettings()
    if (settings.value) {
      freshSettings.tool_providers = preserveConnectingToolProviderStatuses(
        settings.value.tool_providers,
        freshSettings.tool_providers,
      )
    }
    settings.value = freshSettings
  } catch (err) {
    console.error('Failed to refresh settings after tools_updated:', err)
  }
}

function close() {
  emit('close')
}

function handleKeydown(e) {
  if (e.key === 'Escape' && props.show) {
    // Don't close if Escape originated from a CodeMirror editor (e.g. exiting Vim insert mode)
    if (e.target?.closest?.('.cm-editor')) return
    if (activeSection.value === 'ai-services' && aiServicesSection.value?.handleEscape?.()) {
      e.preventDefault()
      e.stopPropagation()
      return
    }
    if (activeSection.value === 'tools' && toolProvidersSection.value?.handleEscape?.()) {
      e.preventDefault()
      e.stopPropagation()
      return
    }
    close()
  }
}

onMounted(() => {
  window.addEventListener('keydown', handleKeydown)
  on('provider_status_changed', handleProviderStatusChanged)
  on('tools_updated', handleToolsUpdated)
})

onUnmounted(() => {
  window.removeEventListener('keydown', handleKeydown)
  off('provider_status_changed', handleProviderStatusChanged)
  off('tools_updated', handleToolsUpdated)
})

async function loadSettings() {
  loading.value = true
  error.value = null
  try {
    fetchModels(null, true).catch(err => {
      console.warn('Failed to refresh model availability:', err)
    })
    // Keep the balance-gated readiness dots current (cloudUser is shared
    // reactive state, also refreshed by account_updated websocket events).
    if (isAuthenticated.value) {
      fetchCloudAccount().catch(() => {})
    }
    settings.value = await fetchSettings()
  } catch (err) {
    console.error('Failed to load settings:', err)
    error.value = 'Failed to load settings'
  } finally {
    loading.value = false
  }
}

// Fire-and-forget pattern: update local state optimistically, persist to server in background.
// This avoids race conditions with the config file watcher and provides snappy UI.
// We only reload from server when the modal first opens.

async function handleFoldersUpdate(folders, relocation = null) {
  const previousFolders = settings.value?.folders || []
  // Update local state immediately (child already has optimistic state)
  if (settings.value) {
    settings.value = { ...settings.value, folders }
  }
  // Fire-and-forget: persist to server, don't reload
  try {
    const response = await updateFolders(folders, relocation)
    if (response.relocation) {
      const count = response.relocation.media_items_updated
      addToast(`Relocated folder without reprocessing ${count.toLocaleString()} media item${count === 1 ? '' : 's'}`, 'success')
    }
  } catch (err) {
    console.error('Failed to persist folders:', err)
    if (settings.value) {
      settings.value = { ...settings.value, folders: previousFolders }
    }
    addToast(err.response?.data?.detail || 'Could not save folders', 'error')
  }
}

async function handleFolderRescan() {
  try {
    await rescanFolders()
  } catch (err) {
    console.error('Failed to trigger rescan:', err)
  }
}

async function handleMarkersUpdate(markers) {
  // Update local state immediately
  if (settings.value) {
    settings.value = { ...settings.value, markers }
  }
  // Fire-and-forget: persist to server
  try {
    await updateMarkers(markers)
  } catch (err) {
    console.error('Failed to persist markers:', err)
  }
}

function handleTelemetryUpdated(enabled) {
  if (settings.value) {
    settings.value = { ...settings.value, telemetry_enabled: enabled === true }
  }
}

let wildcardsDebounceTimer = null
function handleWildcardsUpdate(wildcards) {
  // Update local state immediately
  if (settings.value) {
    settings.value = { ...settings.value, wildcards }
  }
  // Update global wildcards cache for prompt expansion
  setWildcards(wildcards)
  // Debounce the server persist to avoid toast spam on rapid tag additions
  clearTimeout(wildcardsDebounceTimer)
  wildcardsDebounceTimer = setTimeout(async () => {
    try {
      await updateWildcards(wildcards)
    } catch (err) {
      console.error('Failed to persist wildcards:', err)
    }
  }, 800)
}

let segmentsDebounceTimer = null
function handleSegmentsUpdate(promptSegments) {
  // Update local state immediately
  if (settings.value) {
    settings.value = { ...settings.value, prompt_segments: promptSegments }
  }
  // Update global segments cache for prompt expansion
  setSegments(promptSegments)
  // Debounce the server persist
  clearTimeout(segmentsDebounceTimer)
  segmentsDebounceTimer = setTimeout(async () => {
    try {
      await updatePromptSegments(promptSegments)
    } catch (err) {
      console.error('Failed to persist prompt segments:', err)
    }
  }, 800)
}

async function handleToolProviderUpdate({ providerId, data }) {
  const originalProvider = settings.value?.tool_providers.find(provider => provider.id === providerId)
  const startsConnection = toolProviderUpdateStartsConnection(data)
  // Update local state
  if (settings.value) {
    const providers = settings.value.tool_providers.map(p =>
      p.id === providerId
        ? { ...p, ...data, ...(startsConnection ? { status: 'connecting', error_message: null } : {}) }
        : p
    )
    settings.value = { ...settings.value, tool_providers: providers }
  }
  // Fire-and-forget
  try {
    await updateToolProvider(providerId, data)
  } catch (err) {
    console.error('Failed to persist tool provider:', err)
    if (settings.value && originalProvider) {
      settings.value = {
        ...settings.value,
        tool_providers: settings.value.tool_providers.map(provider => provider.id === providerId ? originalProvider : provider),
      }
    }
  }
}

async function handleToolProviderCreate(providerConfig) {
  // For creates, we need the server response to get the full provider object
  // So we do need to wait, but we add optimistically first
  const tempProvider = {
    id: providerConfig.id,
    name: providerConfig.name || providerConfig.id,
    type: providerConfig.type,
    enabled: true,
    status: 'connecting',
    command: providerConfig.command,
    args: providerConfig.args,
    url: providerConfig.url,
  }
  if (settings.value) {
    settings.value = {
      ...settings.value,
      tool_providers: [...settings.value.tool_providers, tempProvider]
    }
  }
  try {
    await createToolProvider(providerConfig)
  } catch (err) {
    console.error('Failed to create tool provider:', err)
    // Revert on error
    if (settings.value) {
      settings.value = {
        ...settings.value,
        tool_providers: settings.value.tool_providers.filter(p => p.id !== providerConfig.id)
      }
    }
    throw err
  }
}

async function handleToolProviderDelete(providerId) {
  // Store for potential revert
  const originalProviders = settings.value?.tool_providers || []
  // Optimistic delete
  if (settings.value) {
    settings.value = {
      ...settings.value,
      tool_providers: settings.value.tool_providers.filter(p => p.id !== providerId)
    }
  }
  try {
    await deleteToolProvider(providerId)
  } catch (err) {
    console.error('Failed to delete tool provider:', err)
    // Revert on error
    if (settings.value) {
      settings.value = { ...settings.value, tool_providers: originalProviders }
    }
    throw err
  }
}

async function handleBackgroundWorkUpdate(data) {
  // Update local state
  if (settings.value) {
    const bgWork = { ...settings.value.background_work }
    if (data.face_detection) {
      bgWork.face_detection = { ...bgWork.face_detection, ...data.face_detection }
    }
    if (data.clip) {
      bgWork.clip = { ...bgWork.clip, ...data.clip }
    }
    if (data.captioning) {
      bgWork.captioning = { ...bgWork.captioning, ...data.captioning }
    }
    settings.value = { ...settings.value, background_work: bgWork }
  }
  // Fire-and-forget
  try {
    await updateBackgroundWork(data)
  } catch (err) {
    console.error('Failed to persist background work settings:', err)
  }
}

async function handleLlmSettingsUpdate({ role, data }) {
  // Optimistic update - update local LLM settings
  if (settings.value) {
    const llmSettings = settings.value.llm_settings.map(s =>
      s.role === role ? { ...s, ...data, source: data.source || s.source } : s
    )
    settings.value = { ...settings.value, llm_settings: llmSettings }
  }
  // Fire-and-forget
  try {
    await updateLlmSettings(role, data)
  } catch (err) {
    console.error('Failed to persist LLM settings:', err)
  }
}

// Keep the loaded settings snapshot in sync when developer mode is toggled
// globally (e.g. the Cmd/Ctrl+Shift+D shortcut) while the modal is open
watch(devModeRef, (enabled) => {
  if (settings.value && settings.value.developer_mode !== enabled) {
    settings.value = { ...settings.value, developer_mode: enabled }
  }
})

async function handleDeveloperModeUpdate(enabled) {
  // Optimistic update
  if (settings.value) {
    settings.value = { ...settings.value, developer_mode: enabled }
  }
  // Update global state for immediate UI visibility change
  setDevMode(enabled)
  // Fire-and-forget
  try {
    await updateDeveloperMode(enabled)
  } catch (err) {
    console.error('Failed to persist developer mode:', err)
  }
}

async function handleDebugForceFfmpegMissingUpdate(enabled) {
  // Optimistic update
  if (settings.value) {
    settings.value = { ...settings.value, debug_force_ffmpeg_missing: enabled }
  }
  try {
    await updateDebugForceFfmpegMissing(enabled)
    // Trigger an immediate recheck so the warning UI reacts right away
    await recheckFfmpeg()
  } catch (err) {
    console.error('Failed to persist debug ffmpeg-missing override:', err)
  }
}

// Profile handlers
async function handleProfileUpdate({ profileId, data }) {
  // Optimistic update
  if (settings.value) {
    const profiles = settings.value.profiles.map(p =>
      p.id === profileId ? { ...p, ...data } : p
    )
    settings.value = { ...settings.value, profiles }
  }
  // Fire-and-forget
  try {
    await renameProfile(profileId, data.name)
  } catch (err) {
    console.error('Failed to update profile:', err)
  }
}

async function handleProfileCreate(name) {
  try {
    const newProfile = await createProfile(name)
    if (settings.value) {
      settings.value = {
        ...settings.value,
        profiles: [...settings.value.profiles, newProfile]
      }
    }
  } catch (err) {
    console.error('Failed to create profile:', err)
  }
}

async function handleProfileDelete(profileId) {
  // Store for potential revert
  const originalProfiles = settings.value?.profiles || []
  // Optimistic delete
  if (settings.value) {
    settings.value = {
      ...settings.value,
      profiles: settings.value.profiles.filter(p => p.id !== profileId)
    }
  }
  // Fire-and-forget
  try {
    await deleteProfile(profileId)
    await loadProfiles()
  } catch (err) {
    console.error('Failed to delete profile:', err)
    // Revert on error
    if (settings.value) {
      settings.value = { ...settings.value, profiles: originalProfiles }
    }
  }
}

const { track: trackTelemetry } = useTelemetry()

async function handleProfileSwitch(profileId) {
  try {
    // Ensure PIN is available for the target profile before switching
    await ensurePinForProfile(profileId)
    trackTelemetry('profile_switched', {}, 'settings')
    // Update the profile ID (this dispatches profile-changed event)
    setCurrentProfileId(profileId)
    // Wait for Vue to process the change
    await nextTick()
    // Reload settings for the new profile
    await loadSettings()
  } catch (err) {
    // User cancelled PIN entry - stay on current profile
    console.log('Profile switch cancelled:', err.message)
  }
}

async function handleProfileReorder(newOrder) {
  // Reorder the local profiles array to match the new order
  if (settings.value) {
    const profileMap = new Map(settings.value.profiles.map(p => [p.id, p]))
    const reorderedProfiles = newOrder.map(id => profileMap.get(id)).filter(Boolean)
    settings.value = { ...settings.value, profiles: reorderedProfiles }
  }
  // Also refresh the global profiles state so TopBar dropdown updates
  await loadProfiles()
}

// Load settings and set active section when modal opens
watch(() => props.show, (isOpen) => {
  if (isOpen) {
    activeSection.value = props.initialSection
    loadSettings()
  }
})
</script>
