<template>
  <div class="flex flex-col gap-6 h-full">
    <!-- Header -->
    <div class="flex items-center justify-between">
      <h3 class="text-base font-medium text-content">Stimpacks</h3>
      <div class="flex items-center gap-2">
        <label
          class="flex items-center gap-1.5 px-3 py-1.5 text-xs text-content-secondary hover:text-content bg-surface hover:bg-surface-raised border border-edge rounded-lg transition-colors cursor-pointer"
        >
          <svg class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" d="M3 16.5v2.25A2.25 2.25 0 0 0 5.25 21h13.5A2.25 2.25 0 0 0 21 18.75V16.5m-13.5-9L12 3m0 0 4.5 4.5M12 3v13.5" />
          </svg>
          Upload
          <input type="file" accept=".md,.zip" class="hidden" @change="handleFileUpload" />
        </label>
        <button
          @click="handleNewStimpack"
          class="flex items-center gap-1.5 px-3 py-1.5 text-xs text-content-secondary hover:text-content bg-surface hover:bg-surface-raised border border-edge rounded-lg transition-colors"
        >
          <svg class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
          </svg>
          New
        </button>
        <button
          @click="showCatalog = true"
          class="flex items-center gap-1.5 px-3 py-1.5 text-xs text-white bg-blue-600 hover:bg-blue-500 rounded-lg transition-colors"
        >
          <svg class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
          </svg>
          Add
        </button>
      </div>
    </div>

    <!-- Loading state -->
    <div v-if="loading" class="flex items-center justify-center py-12">
      <div class="w-6 h-6 border-2 border-edge border-t-content-secondary rounded-full animate-spin"></div>
    </div>

    <!-- Drag-drop zone + stimpack list -->
    <div
      v-else
      class="flex-1 min-h-0"
      @dragover.prevent="isDragging = true"
      @dragleave.prevent="isDragging = false"
      @drop.prevent="handleDrop"
    >
      <!-- Drag overlay -->
      <div
        v-if="isDragging"
        class="border-2 border-dashed border-blue-500/50 rounded-xl bg-blue-500/5 flex items-center justify-center py-12"
      >
        <p class="text-sm text-blue-400">Drop .md or .zip file to install stimpack</p>
      </div>

      <!-- Installed stimpacks grid -->
      <template v-else>
        <!-- Count -->
        <div v-if="stimpacks.length > 0" class="flex items-center justify-end mb-4">
          <span class="text-xs text-content-muted">{{ stimpacks.length }} {{ stimpacks.length === 1 ? 'stimpack' : 'stimpacks' }}</span>
        </div>

        <div v-if="stimpacks.length > 0" class="grid grid-cols-2 gap-4">
          <div
            v-for="stimpack in stimpacks"
            :key="stimpack.name"
            class="group border border-edge rounded-2xl p-5 hover:border-edge-strong transition-all duration-200"
          >
            <!-- Title + 3-dots -->
            <div class="flex items-start justify-between gap-2 mb-2">
              <h4 class="text-sm font-bold text-content" style="letter-spacing: -0.01em;">{{ stimpack.display_name || stimpack.name }}</h4>
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
                  class="absolute right-0 top-full mt-1 bg-surface border border-edge rounded-lg shadow-xl z-[10030] w-44 py-1 overflow-hidden"
                >
                  <button
                    v-if="!stimpack.is_dev"
                    @click="handleEditStimpack(stimpack)"
                    class="w-full px-3 py-1.5 text-left text-xs text-content hover:bg-overlay-light transition-colors"
                  >
                    Edit
                  </button>
                  <div
                    v-else
                    class="px-3 py-1.5 text-xs text-content-muted"
                  >
                    Edit in dev repo
                  </div>
                  <button
                    @click="handleDownloadStimpackZip(stimpack); openContextMenu = null"
                    class="w-full px-3 py-1.5 text-left text-xs text-content hover:bg-overlay-light transition-colors"
                  >
                    Download as Zip
                  </button>
                  <button
                    v-if="!stimpack.is_dev"
                    @click="handleRemoveStimpack(stimpack)"
                    class="w-full px-3 py-1.5 text-left text-xs text-red-400 hover:bg-overlay-light transition-colors"
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
                <template v-if="stimpack.tier === 'marketplace' && stimpack.marketplace_author">
                  <img v-if="stimpack.marketplace_author_avatar_key" :src="avatarUrl(stimpack.marketplace_author_avatar_key)" alt="" class="w-4 h-4 rounded-full object-cover" />
                  <svg v-else class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
                    <path stroke-linecap="round" stroke-linejoin="round" d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" />
                  </svg>
                  {{ stimpack.marketplace_author }}
                </template>
                <template v-else>
                  {{ stimpack.is_dev ? 'Dev repo' : (stimpack.author === 'user' ? 'Custom' : stimpack.author) }}
                </template>
              </span>
              <span
                v-if="stimpack.is_dev"
                class="ml-2 rounded-full border border-blue-500/40 bg-blue-500/10 px-1.5 py-0.5 text-[10px] font-medium text-blue-400"
              >
                Dev
              </span>
            </div>

            <!-- Tags -->
            <div v-if="stimpack.tags?.length" class="flex flex-wrap gap-1.5 mt-2.5 pt-2.5 border-t border-edge">
              <span
                v-for="tag in stimpack.tags"
                :key="tag"
                class="px-2 py-0.5 rounded-md text-[11px] text-content-muted border border-edge-strong"
              >{{ tag }}</span>
            </div>
          </div>
        </div>

        <div v-else class="text-center py-12">
          <p class="text-sm text-content-muted">No stimpacks installed.</p>
          <p class="text-xs text-content-muted mt-1">Click <strong>Add</strong> to browse available stimpacks, or drag and drop a .md/.zip file.</p>
        </div>
      </template>
    </div>

    <!-- Stimpack Library Modal -->
    <Teleport to="body">
      <Transition name="modal">
        <div
          v-if="showCatalog"
          class="fixed inset-0 z-[10020] flex items-center justify-center bg-black/60 backdrop-blur-sm"
          @click.self="showCatalog = false"
        >
          <div class="bg-surface border border-edge rounded-xl shadow-2xl w-[640px] max-w-[90vw] max-h-[80vh] flex flex-col overflow-hidden">
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

            <!-- Search -->
            <div class="px-6 pt-4">
              <input
                v-model="catalogSearch"
                @input="loadCatalog()"
                type="text"
                placeholder="Search stimpacks..."
                class="w-full px-3 py-2 text-sm bg-base border border-edge rounded-lg text-content placeholder-content-muted focus:outline-none focus:border-blue-500/50"
              />
            </div>

            <!-- Stimpack cards grid -->
            <div class="flex-1 overflow-y-auto p-6">
              <div v-if="catalogLoading" class="flex items-center justify-center py-12">
                <div class="w-6 h-6 border-2 border-edge border-t-content-secondary rounded-full animate-spin"></div>
              </div>
              <div v-else-if="catalogStimpacks.length > 0" class="grid grid-cols-2 gap-4">
                <div
                  v-for="stimpack in catalogStimpacks"
                  :key="stimpack.name"
                  class="group border rounded-2xl p-5 transition-all duration-200"
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
                      class="flex-shrink-0 px-2.5 py-1 text-[11px] font-medium text-blue-400 hover:text-white bg-blue-500/10 hover:bg-blue-600 border border-blue-500/20 hover:border-blue-500 rounded-lg transition-all disabled:opacity-50"
                    >
                      {{ installingStimpack === stimpack.name ? '...' : 'Install' }}
                    </button>
                    <button
                      v-else
                      @click="handleUninstallFromCatalog(stimpack)"
                      class="flex-shrink-0 px-2.5 py-1 text-[11px] font-medium text-content-muted hover:text-red-400 border border-edge hover:border-red-500/30 rounded-lg transition-all"
                    >
                      Remove
                    </button>
                  </div>

                  <!-- Description -->
                  <p class="text-xs text-content-secondary leading-relaxed mb-3">{{ stimpack.shortDescription }}</p>

                  <!-- Author row -->
                  <div class="flex items-center text-[11px] text-content-muted">
                    <span class="inline-flex items-center gap-1.5">
                      <img v-if="stimpack.authorAvatarKey" :src="avatarUrl(stimpack.authorAvatarKey)" alt="" class="w-4 h-4 rounded-full object-cover" />
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
                      class="px-2 py-0.5 rounded-md text-[11px] text-content-muted border border-edge-strong"
                    >{{ tag }}</span>
                  </div>
                </div>
              </div>

              <div v-else class="text-center py-12 text-sm text-content-muted">
                {{ catalogSearch ? 'No stimpacks matching your search.' : 'No community stimpacks available yet.' }}
              </div>
            </div>
          </div>
        </div>
      </Transition>
    </Teleport>

    <!-- Stimpack Editor Modal -->
    <StimpackEditorModal
      v-if="showStimpackEditor"
      :stimpack="editingStimpack"
      @close="showStimpackEditor = false"
      @save="handleSaveStimpack"
    />

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

  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useStimpacksApi, type Stimpack, type StimpackDetail, type MarketplaceStimpack } from '../../../composables/useStimpacksApi'
import { getApiBase } from '../../../apiConfig'
import { getCurrentProfileId } from '../../../composables/useProfile'
import { useCloudAccount } from '../../../composables/useCloudAccount'
import { addToast } from '../../../composables/useToasts'
import StimpackEditorModal from '../StimpackEditorModal.vue'
import ConfirmModal from '../../ConfirmModal.vue'

const { cloudBaseUrl } = useCloudAccount()
function avatarUrl(key: string): string {
  return `${cloudBaseUrl.value}/api/avatars/${key}`
}

const {
  listStimpacks,
  getStimpack,
  createStimpack,
  updateStimpack,
  deleteStimpack,
  uploadStimpack,
  browseMarketplace,
  installFromMarketplace,
} = useStimpacksApi()

// State
const loading = ref(false)
const stimpacks = ref<Stimpack[]>([])
const catalogStimpacks = ref<MarketplaceStimpack[]>([])
const showCatalog = ref(false)
const catalogLoading = ref(false)
const catalogSearch = ref('')
const installingStimpack = ref<string | null>(null)
const openContextMenu = ref<string | null>(null)
const isDragging = ref(false)

// Stimpack editor
const showStimpackEditor = ref(false)
const editingStimpack = ref<StimpackDetail | null>(null)

// Computed
const installedNames = computed(() => new Set(stimpacks.value.map(s => s.name)))

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
  } catch (err) {
    console.error('Failed to load marketplace:', err)
    catalogStimpacks.value = []
  } finally {
    catalogLoading.value = false
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

function handleNewStimpack() {
  editingStimpack.value = null
  showStimpackEditor.value = true
}

async function handleEditStimpack(stimpack: Stimpack) {
  openContextMenu.value = null
  try {
    editingStimpack.value = await getStimpack(stimpack.name)
    showStimpackEditor.value = true
  } catch (err) {
    console.error('Failed to load stimpack detail:', err)
  }
}

async function handleSaveStimpack(data: { name: string; display_name: string; description: string; tags: string[]; content: string }) {
  try {
    if (editingStimpack.value) {
      await updateStimpack(editingStimpack.value.name, {
        display_name: data.display_name,
        description: data.description,
        tags: data.tags,
        content: data.content,
      })
    } else {
      await createStimpack({
        name: data.name,
        display_name: data.display_name,
        description: data.description,
        tags: data.tags,
        content: data.content,
      })
    }
    showStimpackEditor.value = false
    editingStimpack.value = null
    await loadStimpacks()
    notifyStimpacksChanged()
  } catch (err) {
    console.error('Failed to save stimpack:', err)
  }
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
