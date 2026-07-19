<template>
  <div class="flex h-full flex-col bg-base">
    <!-- Header (matches the boards/chats landing treatment) -->
    <div class="flex items-center justify-between border-b border-edge-subtle px-6 py-5">
      <div class="flex flex-col gap-1">
        <span class="text-[16px] font-semibold leading-none text-content">Stimpacks</span>
        <p class="text-sm text-content-tertiary">Stimpacks extend Stimma with new skills and capabilities.</p>
      </div>
      <div class="flex items-center gap-3">
        <button
          v-if="canOpenFolder"
          @click="openStimpacksFolder"
          class="flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-sm text-content-tertiary transition-colors hover:bg-overlay-subtle hover:text-content-secondary"
          title="Open the profile's stimpacks folder — packs dropped or edited here load live"
        >
          <svg class="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" d="M2.25 12.75V12A2.25 2.25 0 0 1 4.5 9.75h15A2.25 2.25 0 0 1 21.75 12v.75m-8.69-6.44-2.12-2.12a1.5 1.5 0 0 0-1.061-.44H4.5A2.25 2.25 0 0 0 2.25 6v12a2.25 2.25 0 0 0 2.25 2.25h15A2.25 2.25 0 0 0 21.75 18V9a2.25 2.25 0 0 0-2.25-2.25h-5.379a1.5 1.5 0 0 1-1.06-.44Z" />
          </svg>
          <span>Open Folder</span>
        </button>
        <button
          @click="showCatalog = true"
          class="flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-sm text-content-tertiary transition-colors hover:bg-overlay-subtle hover:text-content-secondary"
        >
          <svg class="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" d="M12 4v16m8-8H4" />
          </svg>
          <span>Add Stimpack</span>
        </button>
      </div>
    </div>

    <!-- Loading state -->
    <div v-if="loading" class="py-20 text-center text-content-muted">
      <div class="mx-auto h-6 w-6 animate-spin rounded-full border-2 border-edge border-t-content-secondary"></div>
    </div>

    <!-- Drag-drop zone + stimpack list -->
    <div
      v-else
      class="flex-1 overflow-y-auto px-6 pb-6"
      @dragover.prevent="isDragging = true"
      @dragleave.prevent="isDragging = false"
      @drop.prevent="handleDrop"
    >
      <!-- Drag overlay -->
      <div
        v-if="isDragging"
        class="mt-6 flex items-center justify-center rounded-lg border-2 border-dashed border-accent/50 bg-accent/5 py-12"
      >
        <p class="text-sm text-accent">Drop .md or .zip file to install stimpack</p>
      </div>

      <!-- Installed stimpacks grid -->
      <template v-else>
        <div v-if="stimpacks.length > 0" class="grid grid-cols-1 gap-5 pt-6 sm:grid-cols-2 xl:grid-cols-3">
          <div
            v-for="stimpack in stimpacks"
            :key="stimpack.name"
            class="group rounded-lg bg-overlay-faint p-5 transition-all hover:border-edge hover:bg-overlay-subtle"
          >
            <!-- Title + 3-dots -->
            <div class="flex items-start justify-between gap-2 mb-2">
              <h4 class="truncate text-[13px] font-semibold text-content">{{ stimpack.display_name || stimpack.name }}</h4>
              <div class="relative flex-shrink-0">
                <button
                  @click.stop="toggleContextMenu(stimpack.name)"
                  class="p-0.5 text-content-muted hover:text-content-secondary transition-colors rounded hover:bg-overlay-light"
                >
                  <svg class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
                    <path stroke-linecap="round" stroke-linejoin="round" d="M12 6.75a.75.75 0 1 1 0-1.5.75.75 0 0 1 0 1.5ZM12 12.75a.75.75 0 1 1 0-1.5.75.75 0 0 1 0 1.5ZM12 18.75a.75.75 0 1 1 0-1.5.75.75 0 0 1 0 1.5Z" />
                  </svg>
                </button>
                <div
                  v-if="openContextMenu === stimpack.name"
                  @mousedown.stop
                  class="absolute right-0 top-full mt-1 bg-surface border border-edge rounded-lg shadow-xl z-menu w-44 py-1 overflow-hidden"
                >
                  <div
                    v-if="stimpack.is_dev"
                    class="px-3 py-1.5 text-xs text-content-muted"
                  >
                    Edit in dev repo
                  </div>
                  <button
                    @click="handleValidateStimpack(stimpack)"
                    class="w-full px-3 py-1.5 text-left text-xs text-content hover:bg-surface-hover transition-colors"
                  >
                    Validate
                  </button>
                  <button
                    v-if="stimpack.tier === 'local' && !stimpack.is_dev"
                    @click="handlePublishStimpack(stimpack)"
                    class="w-full px-3 py-1.5 text-left text-xs text-content hover:bg-surface-hover transition-colors"
                  >
                    Publish to Marketplace
                  </button>
                  <button
                    @click="handleDownloadStimpackZip(stimpack); openContextMenu = null"
                    class="w-full px-3 py-1.5 text-left text-xs text-content hover:bg-surface-hover transition-colors"
                  >
                    Download as Zip
                  </button>
                  <button
                    v-if="!stimpack.is_dev"
                    @click="handleRemoveStimpack(stimpack)"
                    class="w-full px-3 py-1.5 text-left text-xs text-red-400 hover:bg-red-500/10 transition-colors"
                  >
                    Remove
                  </button>
                </div>
              </div>
            </div>

            <!-- Description -->
            <p v-if="stimpack.description" class="text-xs text-content-secondary leading-relaxed mb-3 line-clamp-2">{{ stimpack.description }}</p>

            <!-- Author row -->
            <div class="flex items-center text-[11px] text-content-muted">
              <span class="inline-flex items-center gap-1.5">
                <template v-if="stimpack.tier === 'marketplace' && marketplaceAuthor(stimpack)">
                  <img
                    v-if="marketplaceAvatarKey(stimpack) && !failedAvatars.has(marketplaceAvatarKey(stimpack))"
                    :src="avatarUrl(marketplaceAvatarKey(stimpack))"
                    alt=""
                    class="w-4 h-4 rounded-full object-cover"
                    @error="handleAvatarError(marketplaceAvatarKey(stimpack))"
                  />
                  <svg v-else class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
                    <path stroke-linecap="round" stroke-linejoin="round" d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" />
                  </svg>
                  {{ marketplaceAuthor(stimpack) }}
                </template>
                <template v-else>
                  {{ stimpack.is_dev ? 'Dev repo' : (stimpack.author === 'user' ? 'Custom' : stimpack.author) }}
                </template>
              </span>
              <span
                v-if="stimpack.is_dev"
                class="ml-2 rounded-full bg-accent/10 px-1.5 py-0.5 text-[10px] font-medium text-accent"
              >
                Dev
              </span>
            </div>

            <!-- Tags -->
            <div v-if="stimpack.tags?.length" class="flex flex-wrap gap-1.5 mt-2.5 pt-2.5 border-t border-edge-subtle">
              <span
                v-for="tag in stimpack.tags"
                :key="tag"
                class="px-2 py-0.5 rounded-md text-[11px] text-content-muted "
              >{{ tag }}</span>
            </div>
          </div>
        </div>

        <div v-else class="flex h-64 flex-col items-center justify-center text-center">
          <p class="mb-2 text-content-muted">No stimpacks yet</p>
          <p class="text-sm text-content-muted">Click <strong>Add Stimpack</strong> to browse available stimpacks, or drag and drop a .md/.zip file.</p>
        </div>
      </template>
    </div>

    <!-- Stimpack Library Modal -->
    <Teleport to="body">
      <Transition name="modal">
        <div
          v-if="showCatalog"
          class="fixed inset-0 z-modal flex items-center justify-center bg-overlay-backdrop backdrop-blur-sm"
          @click.self="showCatalog = false"
        >
          <div class="bg-surface border border-edge rounded-lg shadow-2xl w-[920px] max-w-[92vw] h-[80vh] max-h-[820px] flex flex-col overflow-hidden">
            <!-- Header -->
            <div class="flex items-center justify-between px-6 py-4 border-b border-edge">
              <div>
                <h3 class="text-lg font-semibold text-content">Stimpack Library</h3>
                <p class="text-xs text-content-muted mt-0.5">Browse and install community stimpacks from stimma.ai</p>
              </div>
              <button
                @click="showCatalog = false"
                class="w-8 h-8 flex items-center justify-center text-content-tertiary hover:text-content hover:bg-surface-raised rounded-lg transition-colors"
              >
                <svg class="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>

            <!-- Search + install from file -->
            <div class="px-6 pt-4 flex items-center gap-2">
              <input
                v-model="catalogSearch"
                @input="loadCatalog()"
                type="text"
                placeholder="Search stimpacks..."
                class="flex-1 px-3 py-2 text-sm bg-base border border-edge rounded-lg text-content placeholder-content-muted focus:outline-none focus:border-accent"
              />
              <label
                title="Install from a .md or .zip file..."
                class="flex-shrink-0 cursor-pointer flex items-center justify-center w-9 h-9 text-content-tertiary hover:text-content-secondary hover:bg-overlay-subtle border border-edge rounded-lg transition-colors"
              >
                <svg class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M3 16.5v2.25A2.25 2.25 0 0 0 5.25 21h13.5A2.25 2.25 0 0 0 21 18.75V16.5m-13.5-9L12 3m0 0 4.5 4.5M12 3v13.5" />
                </svg>
                <input type="file" accept=".md,.zip" class="hidden" @change="handleFileUpload" />
              </label>
            </div>

            <!-- Stimpack cards grid -->
            <div class="flex-1 overflow-y-auto p-6">
              <div v-if="catalogLoading" class="flex items-center justify-center py-12">
                <div class="w-6 h-6 border-2 border-edge border-t-content-secondary rounded-full animate-spin"></div>
              </div>
              <div v-else-if="catalogStimpacks.length > 0" class="grid grid-cols-3 gap-4">
                <div
                  v-for="stimpack in catalogStimpacks"
                  :key="stimpack.name"
                  class="group border rounded-lg p-5 transition-all duration-200"
                  :class="installedNames.has(stimpack.name)
                    ? 'border-edge'
                    : 'border-edge hover:border-edge-strong'"
                >
                  <!-- Title + action -->
                  <div class="flex items-start justify-between gap-2 mb-2">
                    <h4 class="text-sm font-bold text-content" style="letter-spacing: -0.01em;">{{ stimpack.displayName || stimpack.name }}</h4>
                    <button
                      v-if="!installedNames.has(stimpack.name)"
                      @click="handleInstallStimpack(stimpack)"
                      :disabled="installingStimpack === stimpack.name"
                      class="flex-shrink-0 px-2.5 py-1 text-[11px] font-medium text-accent hover:text-white bg-accent/10 hover:bg-accent rounded-md transition-all disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                      {{ installingStimpack === stimpack.name ? '...' : 'Install' }}
                    </button>
                    <button
                      v-else
                      @click="handleUninstallFromCatalog(stimpack)"
                      class="flex-shrink-0 px-2.5 py-1 text-[11px] font-medium text-content-muted hover:text-red-400 rounded-md text-red-400 hover:bg-red-500/10 transition-all"
                    >
                      Remove
                    </button>
                  </div>

                  <!-- Description -->
                  <p class="text-xs text-content-secondary leading-relaxed mb-3">{{ stimpack.shortDescription }}</p>

                  <!-- Author row -->
                  <div class="flex items-center text-[11px] text-content-muted">
                    <span class="inline-flex items-center gap-1.5">
                      <img
                        v-if="stimpack.authorAvatarKey && !failedAvatars.has(stimpack.authorAvatarKey)"
                        :src="avatarUrl(stimpack.authorAvatarKey)"
                        alt=""
                        class="w-4 h-4 rounded-full object-cover"
                        @error="failedAvatars.add(stimpack.authorAvatarKey)"
                      />
                      <svg v-else class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
                        <path stroke-linecap="round" stroke-linejoin="round" d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" />
                      </svg>
                      {{ stimpack.authorUsername || 'unknown' }}
                    </span>
                    <span v-if="stimpack.nsfw" class="ml-2 px-1.5 py-0.5 bg-red-500/20 text-red-400 rounded text-[9px] font-medium">NSFW</span>
                  </div>

                  <!-- Tags -->
                  <div v-if="stimpack.tags?.length" class="flex flex-wrap gap-1.5 mt-3 pt-3 border-t border-edge">
                    <span
                      v-for="tag in stimpack.tags"
                      :key="tag"
                      class="px-2 py-0.5 rounded-md text-[11px] text-content-muted "
                    >{{ tag }}</span>
                  </div>
                </div>
              </div>

              <div v-else class="text-center py-12 text-sm text-content-muted">
                {{ privacyLockdownActive
                  ? 'Browsing community stimpacks is disabled while Privacy Lockdown is on.'
                  : catalogSearch ? 'No stimpacks matching your search.' : 'No community stimpacks available yet.' }}
              </div>
            </div>
          </div>
        </div>
      </Transition>
    </Teleport>

    <!-- Remove Stimpack Confirmation -->
    <ConfirmModal
      :show="showRemoveConfirm"
      title="Remove Stimpack?"
      :message="pendingAction?.stimpack.tier === 'marketplace'
        ? `Remove &quot;${pendingAction?.stimpack.display_name || pendingAction?.stimpack.name}&quot;? You can re-install it from the stimpack library.`
        : `Remove &quot;${pendingAction?.stimpack.display_name || pendingAction?.stimpack.name}&quot;? This cannot be undone.`"
      confirm-text="Remove"
      @confirm="executeRemoveStimpack"
      @cancel="showRemoveConfirm = false"
    />

    <!-- Publish Confirmation -->
    <ConfirmModal
      :show="showPublishConfirm"
      title="Publish to Marketplace?"
      :message="`Publish &quot;${pendingPublish?.display_name || pendingPublish?.name}&quot; to the stimma.ai marketplace? New packs are reviewed before going live.`"
      confirm-text="Publish"
      @confirm="executePublishStimpack"
      @cancel="showPublishConfirm = false; pendingPublish = null"
    />

    <!-- Validation results -->
    <Teleport to="body">
      <Transition name="modal">
        <div
          v-if="validationResult"
          class="fixed inset-0 z-modal flex items-center justify-center bg-overlay-backdrop backdrop-blur-sm"
          @click.self="validationResult = null"
        >
          <div class="bg-surface border border-edge rounded-lg shadow-2xl w-[560px] max-w-[90vw] max-h-[70vh] flex flex-col overflow-hidden">
            <div class="flex items-center justify-between px-5 py-3.5 border-b border-edge">
              <div class="flex items-center gap-2">
                <span class="text-[13px] font-semibold text-content">Validation</span>
                <span
                  class="px-2 py-0.5 rounded-full text-[10px] font-medium"
                  :class="validationResult.valid ? 'bg-green-500/15 text-green-400' : 'bg-red-500/15 text-red-400'"
                >{{ validationResult.valid ? 'Valid' : 'Invalid' }}</span>
              </div>
              <button
                @click="validationResult = null"
                class="w-6 h-6 flex items-center justify-center rounded text-content-muted hover:text-content transition-colors"
              >
                <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M6 18 18 6M6 6l12 12" />
                </svg>
              </button>
            </div>
            <div class="flex-1 overflow-y-auto px-5 py-4 font-mono text-xs leading-relaxed">
              <p v-for="(line, i) in validationResult.report" :key="'r' + i" class="text-content-secondary whitespace-pre-wrap">{{ line }}</p>
              <p v-for="(line, i) in validationResult.warnings" :key="'w' + i" class="text-amber-400 whitespace-pre-wrap mt-1">warning: {{ line }}</p>
              <p v-for="(line, i) in validationResult.errors" :key="'e' + i" class="text-red-400 whitespace-pre-wrap mt-1">error: {{ line }}</p>
            </div>
          </div>
        </div>
      </Transition>
    </Teleport>

  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted, onUnmounted } from 'vue'
import { useStimpacksApi, type Stimpack, type MarketplaceStimpack } from '../../../composables/useStimpacksApi'
import { getApiBase, isTauri } from '../../../apiConfig'
import { getCurrentProfileId } from '../../../composables/useProfile'
import { addToast } from '../../../composables/useToasts'
import { usePrivacyLockdown } from '../../../composables/usePrivacyLockdown'
import ConfirmModal from '../../ConfirmModal.vue'

// Avatars proxy through the local backend, which attaches the Cloudflare
// Access headers dev cloud targets require — a direct cloud URL renders as a
// broken image there.
function avatarUrl(key: string): string {
  const profileId = getCurrentProfileId()
  return `${getApiBase()}/stimpack-marketplace/avatar/${key}?profile=${encodeURIComponent(profileId)}`
}

// Keys whose image failed to load (e.g. object missing from the target env's
// bucket) — fall back to the person icon instead of a broken image.
const failedAvatars = reactive(new Set<string>())

const {
  listStimpacks,
  deleteStimpack,
  uploadStimpack,
  browseMarketplace,
  installFromMarketplace,
  getStimpacksDir,
  validateStimpack,
  publishToMarketplace,
} = useStimpacksApi()

const { privacyLockdownActive } = usePrivacyLockdown()

// --- Local development affordances -----------------------------------------

// Opening a Finder/Explorer window needs the Tauri shell; hide in plain browsers.
const canOpenFolder = isTauri()

async function openStimpacksFolder() {
  try {
    const path = await getStimpacksDir()
    const { openPath } = await import('@tauri-apps/plugin-opener')
    await openPath(path)
  } catch (err) {
    console.error('Failed to open stimpacks folder:', err)
    addToast('Failed to open the stimpacks folder.', 'error')
  }
}

const validationResult = ref<{ valid: boolean; report: string[]; warnings: string[]; errors: string[] } | null>(null)

async function handleValidateStimpack(stimpack: Stimpack) {
  openContextMenu.value = null
  try {
    validationResult.value = await validateStimpack(stimpack.name)
  } catch (err) {
    console.error('Failed to validate stimpack:', err)
    addToast('Validation failed to run.', 'error')
  }
}

const showPublishConfirm = ref(false)
const pendingPublish = ref<Stimpack | null>(null)
const publishing = ref(false)

function handlePublishStimpack(stimpack: Stimpack) {
  openContextMenu.value = null
  pendingPublish.value = stimpack
  showPublishConfirm.value = true
}

async function executePublishStimpack() {
  if (!pendingPublish.value || publishing.value) return
  showPublishConfirm.value = false
  const stimpack = pendingPublish.value
  pendingPublish.value = null
  publishing.value = true
  try {
    const result = await publishToMarketplace(stimpack.name)
    const status = result.version?.status || result.moderation?.decision || 'submitted'
    if (status === 'approved') {
      addToast(`Published "${stimpack.display_name || stimpack.name}" v${result.version?.version ?? ''} to the marketplace.`, 'success')
    } else {
      addToast(`Submitted "${stimpack.display_name || stimpack.name}" — pending marketplace review.`, 'success')
    }
  } catch (err: any) {
    console.error('Failed to publish stimpack:', err)
    const detail = err?.response?.data?.detail
    addToast(detail ? `Publish failed: ${detail}` : 'Publish failed.', 'error')
  } finally {
    publishing.value = false
  }
}

// State
const loading = ref(false)
const stimpacks = ref<Stimpack[]>([])
const catalogStimpacks = ref<MarketplaceStimpack[]>([])
const showCatalog = ref(false)
const catalogLoading = ref(false)
const catalogLoaded = ref(false)
const catalogSearch = ref('')
const installingStimpack = ref<string | null>(null)
const openContextMenu = ref<string | null>(null)
const isDragging = ref(false)
const marketplaceByName = ref<Map<string, MarketplaceStimpack>>(new Map())

// Computed
const installedNames = computed(() => new Set(stimpacks.value.map(s => s.name)))

function marketplaceAuthor(stimpack: Stimpack): string {
  return marketplaceByName.value.get(stimpack.name)?.authorUsername || stimpack.marketplace_author || ''
}

function marketplaceAvatarKey(stimpack: Stimpack): string {
  const freshKey = marketplaceByName.value.get(stimpack.name)?.authorAvatarKey
  if (freshKey) return freshKey
  return stimpack.marketplace_author_avatar_key || ''
}

function handleAvatarError(key: string) {
  if (key) failedAvatars.add(key)
}

// Data loading
async function loadStimpacks() {
  loading.value = true
  try {
    stimpacks.value = await listStimpacks()
  } catch (err) {
    console.error('Failed to load stimpacks:', err)
  } finally {
    loading.value = false
  }
}

async function loadCatalog() {
  catalogLoading.value = true
  try {
    const result = await browseMarketplace({ q: catalogSearch.value || undefined, limit: 50 })
    catalogStimpacks.value = result.stimpacks
    const nextMarketplaceByName = new Map(marketplaceByName.value)
    for (const stimpack of result.stimpacks) {
      nextMarketplaceByName.set(stimpack.name, stimpack)
    }
    marketplaceByName.value = nextMarketplaceByName
  } catch (err) {
    console.error('Failed to load marketplace:', err)
    catalogStimpacks.value = []
  } finally {
    catalogLoading.value = false
    catalogLoaded.value = true
  }
}

// Actions
function notifyStimpacksChanged() {
  window.dispatchEvent(new CustomEvent('stimpacks-changed'))
}

async function handleInstallStimpack(stimpack: MarketplaceStimpack) {
  installingStimpack.value = stimpack.name
  try {
    await installFromMarketplace(stimpack.name)
    await loadStimpacks()
    notifyStimpacksChanged()
  } catch (err) {
    console.error('Failed to install stimpack:', err)
  } finally {
    installingStimpack.value = null
  }
}

async function handleUninstallFromCatalog(stimpack: MarketplaceStimpack) {
  try {
    await deleteStimpack(stimpack.name)
    await loadStimpacks()
    notifyStimpacksChanged()
  } catch (err) {
    console.error('Failed to remove stimpack:', err)
  }
}

// Confirmation state
const showRemoveConfirm = ref(false)
const pendingAction = ref<{ stimpack: Stimpack } | null>(null)

function handleRemoveStimpack(stimpack: Stimpack) {
  openContextMenu.value = null
  pendingAction.value = { stimpack }
  showRemoveConfirm.value = true
}

async function executeRemoveStimpack() {
  if (!pendingAction.value) return
  showRemoveConfirm.value = false
  const stimpack = pendingAction.value.stimpack
  pendingAction.value = null
  try {
    await deleteStimpack(stimpack.name)
    await loadStimpacks()
    notifyStimpacksChanged()
  } catch (err) {
    console.error('Failed to remove stimpack:', err)
  }
}

function handleDownloadStimpackZip(stimpack: Stimpack) {
  const profileId = getCurrentProfileId()
  const url = `${getApiBase()}/settings/stimpacks/${encodeURIComponent(stimpack.name)}/download?profile=${encodeURIComponent(profileId)}`
  const a = document.createElement('a')
  a.href = url
  a.download = `${stimpack.name}.zip`
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
}

// Context menu
function toggleContextMenu(name: string) {
  openContextMenu.value = openContextMenu.value === name ? null : name
}

// File upload / drag-drop
async function handleFileUpload(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  await doUpload(file)
  input.value = '' // Reset so same file can be re-uploaded
}

async function handleDrop(event: DragEvent) {
  isDragging.value = false
  const file = event.dataTransfer?.files?.[0]
  if (!file) return
  const ext = file.name.split('.').pop()?.toLowerCase()
  if (ext !== 'md' && ext !== 'zip') {
    addToast('Only .md and .zip files are supported.', 'error')
    return
  }
  await doUpload(file)
}

async function doUpload(file: File) {
  try {
    await uploadStimpack(file)
    await loadStimpacks()
    notifyStimpacksChanged()
  } catch (err) {
    console.error('Failed to upload stimpack:', err)
    addToast('Failed to upload stimpack. Check the file format.', 'error')
  }
}

// Click outside handler for context menus
function handleClickOutside() {
  if (openContextMenu.value) {
    openContextMenu.value = null
  }
}

onMounted(() => {
  loadStimpacks()
  loadCatalog()
  document.addEventListener('mousedown', handleClickOutside)
})

onUnmounted(() => {
  document.removeEventListener('mousedown', handleClickOutside)
})
</script>

<style scoped>
.modal-enter-active,
.modal-leave-active {
  transition: opacity 0.15s ease;
}

.modal-enter-from,
.modal-leave-to {
  opacity: 0;
}

.modal-enter-active > div,
.modal-leave-active > div {
  transition: transform 0.15s ease;
}

.modal-enter-from > div,
.modal-leave-to > div {
  transform: scale(0.95);
}
</style>
