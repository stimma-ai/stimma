<template>
  <div class="flex flex-col gap-6 h-full">
    <!-- Header -->
    <div class="flex items-center justify-between">
      <h3 class="text-base font-medium text-content">Skills</h3>
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
          @click="handleNewSkill"
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

    <!-- Drag-drop zone + skill list -->
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
        <p class="text-sm text-blue-400">Drop .md or .zip file to install skill</p>
      </div>

      <!-- Installed skills grid -->
      <template v-else>
        <!-- Count -->
        <div v-if="skills.length > 0" class="flex items-center justify-end mb-4">
          <span class="text-xs text-content-muted">{{ skills.length }} {{ skills.length === 1 ? 'skill' : 'skills' }}</span>
        </div>

        <div v-if="skills.length > 0" class="grid grid-cols-2 gap-4">
          <div
            v-for="skill in skills"
            :key="skill.name"
            class="group border border-edge rounded-2xl p-5 hover:border-edge-strong transition-all duration-200"
          >
            <!-- Title + 3-dots -->
            <div class="flex items-start justify-between gap-2 mb-2">
              <h4 class="text-sm font-bold text-content" style="letter-spacing: -0.01em;">{{ skill.display_name || skill.name }}</h4>
              <div class="relative flex-shrink-0">
                <button
                  @click.stop="toggleContextMenu(skill.name)"
                  class="p-0.5 text-content-muted hover:text-content-secondary transition-colors rounded hover:bg-overlay-light"
                >
                  <svg class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
                    <path stroke-linecap="round" stroke-linejoin="round" d="M12 6.75a.75.75 0 1 1 0-1.5.75.75 0 0 1 0 1.5ZM12 12.75a.75.75 0 1 1 0-1.5.75.75 0 0 1 0 1.5ZM12 18.75a.75.75 0 1 1 0-1.5.75.75 0 0 1 0 1.5Z" />
                  </svg>
                </button>
                <div
                  v-if="openContextMenu === skill.name"
                  @mousedown.stop
                  class="absolute right-0 top-full mt-1 bg-surface border border-edge rounded-lg shadow-xl z-[10030] w-44 py-1 overflow-hidden"
                >
                  <button
                    @click="handleEditSkill(skill)"
                    class="w-full px-3 py-1.5 text-left text-xs text-content hover:bg-overlay-light transition-colors"
                  >
                    Edit
                  </button>
                  <button
                    @click="handleDownloadSkillZip(skill); openContextMenu = null"
                    class="w-full px-3 py-1.5 text-left text-xs text-content hover:bg-overlay-light transition-colors"
                  >
                    Download as Zip
                  </button>
                  <button
                    @click="handleRemoveSkill(skill)"
                    class="w-full px-3 py-1.5 text-left text-xs text-red-400 hover:bg-overlay-light transition-colors"
                  >
                    Remove
                  </button>
                </div>
              </div>
            </div>

            <!-- Description -->
            <p v-if="skill.description" class="text-xs text-content-secondary leading-relaxed mb-3 line-clamp-2">{{ skill.description }}</p>

            <!-- Author row -->
            <div class="flex items-center text-[11px] text-content-muted">
              <span class="inline-flex items-center gap-1.5">
                <template v-if="skill.tier === 'marketplace' && skill.marketplace_author">
                  <img v-if="skill.marketplace_author_avatar_key" :src="avatarUrl(skill.marketplace_author_avatar_key)" alt="" class="w-4 h-4 rounded-full object-cover" />
                  <svg v-else class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
                    <path stroke-linecap="round" stroke-linejoin="round" d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" />
                  </svg>
                  {{ skill.marketplace_author }}
                </template>
                <template v-else>
                  {{ skill.author === 'user' ? 'Custom' : skill.author }}
                </template>
              </span>
            </div>

            <!-- Tags -->
            <div v-if="skill.tags?.length" class="flex flex-wrap gap-1.5 mt-2.5 pt-2.5 border-t border-edge">
              <span
                v-for="tag in skill.tags"
                :key="tag"
                class="px-2 py-0.5 rounded-md text-[11px] text-content-muted border border-edge-strong"
              >{{ tag }}</span>
            </div>
          </div>
        </div>

        <div v-else class="text-center py-12">
          <p class="text-sm text-content-muted">No skills installed.</p>
          <p class="text-xs text-content-muted mt-1">Click <strong>Add</strong> to browse available skills, or drag and drop a .md/.zip file.</p>
        </div>
      </template>
    </div>

    <!-- Skill Library Modal -->
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
                <h3 class="text-lg font-semibold text-content">Skill Library</h3>
                <p class="text-xs text-content-muted mt-0.5">Browse and install community skills from stimma.ai</p>
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
                placeholder="Search skills..."
                class="w-full px-3 py-2 text-sm bg-base border border-edge rounded-lg text-content placeholder-content-muted focus:outline-none focus:border-blue-500/50"
              />
            </div>

            <!-- Skill cards grid -->
            <div class="flex-1 overflow-y-auto p-6">
              <div v-if="catalogLoading" class="flex items-center justify-center py-12">
                <div class="w-6 h-6 border-2 border-edge border-t-content-secondary rounded-full animate-spin"></div>
              </div>
              <div v-else-if="catalogSkills.length > 0" class="grid grid-cols-2 gap-4">
                <div
                  v-for="skill in catalogSkills"
                  :key="skill.name"
                  class="group border rounded-2xl p-5 transition-all duration-200"
                  :class="installedNames.has(skill.name)
                    ? 'border-edge'
                    : 'border-edge hover:border-edge-strong'"
                >
                  <!-- Title + action -->
                  <div class="flex items-start justify-between gap-2 mb-2">
                    <h4 class="text-sm font-bold text-content" style="letter-spacing: -0.01em;">{{ skill.displayName || skill.name }}</h4>
                    <button
                      v-if="!installedNames.has(skill.name)"
                      @click="handleInstallSkill(skill)"
                      :disabled="installingSkill === skill.name"
                      class="flex-shrink-0 px-2.5 py-1 text-[11px] font-medium text-blue-400 hover:text-white bg-blue-500/10 hover:bg-blue-600 border border-blue-500/20 hover:border-blue-500 rounded-lg transition-all disabled:opacity-50"
                    >
                      {{ installingSkill === skill.name ? '...' : 'Install' }}
                    </button>
                    <button
                      v-else
                      @click="handleUninstallFromCatalog(skill)"
                      class="flex-shrink-0 px-2.5 py-1 text-[11px] font-medium text-content-muted hover:text-red-400 border border-edge hover:border-red-500/30 rounded-lg transition-all"
                    >
                      Remove
                    </button>
                  </div>

                  <!-- Description -->
                  <p class="text-xs text-content-secondary leading-relaxed mb-3">{{ skill.shortDescription }}</p>

                  <!-- Author row -->
                  <div class="flex items-center text-[11px] text-content-muted">
                    <span class="inline-flex items-center gap-1.5">
                      <img v-if="skill.authorAvatarKey" :src="avatarUrl(skill.authorAvatarKey)" alt="" class="w-4 h-4 rounded-full object-cover" />
                      <svg v-else class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
                        <path stroke-linecap="round" stroke-linejoin="round" d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" />
                      </svg>
                      {{ skill.authorUsername || 'unknown' }}
                    </span>
                    <span v-if="skill.nsfw" class="ml-2 px-1.5 py-0.5 bg-red-500/20 text-red-400 rounded text-[9px] font-medium">NSFW</span>
                  </div>

                  <!-- Tags -->
                  <div v-if="skill.tags?.length" class="flex flex-wrap gap-1.5 mt-3 pt-3 border-t border-edge">
                    <span
                      v-for="tag in skill.tags"
                      :key="tag"
                      class="px-2 py-0.5 rounded-md text-[11px] text-content-muted border border-edge-strong"
                    >{{ tag }}</span>
                  </div>
                </div>
              </div>

              <div v-else class="text-center py-12 text-sm text-content-muted">
                {{ catalogSearch ? 'No skills matching your search.' : 'No community skills available yet.' }}
              </div>
            </div>
          </div>
        </div>
      </Transition>
    </Teleport>

    <!-- Skill Editor Modal -->
    <SkillEditorModal
      v-if="showSkillEditor"
      :skill="editingSkill"
      @close="showSkillEditor = false"
      @save="handleSaveSkill"
    />

    <!-- Remove Skill Confirmation -->
    <ConfirmModal
      :show="showRemoveConfirm"
      title="Remove Skill?"
      :message="pendingAction?.skill.tier === 'marketplace'
        ? `Remove &quot;${pendingAction?.skill.display_name || pendingAction?.skill.name}&quot;? You can re-install it from the skill library.`
        : `Remove &quot;${pendingAction?.skill.display_name || pendingAction?.skill.name}&quot;? This cannot be undone.`"
      confirm-text="Remove"
      @confirm="executeRemoveSkill"
      @cancel="showRemoveConfirm = false"
    />

  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useSkillsApi, type Skill, type SkillDetail, type MarketplaceSkill } from '../../../composables/useSkillsApi'
import { getApiBase } from '../../../apiConfig'
import { getCurrentProfileId } from '../../../composables/useProfile'
import { useCloudAccount } from '../../../composables/useCloudAccount'
import SkillEditorModal from '../SkillEditorModal.vue'
import ConfirmModal from '../../ConfirmModal.vue'

const { cloudBaseUrl } = useCloudAccount()
function avatarUrl(key: string): string {
  return `${cloudBaseUrl.value}/api/avatars/${key}`
}

const {
  listSkills,
  getSkill,
  createSkill,
  updateSkill,
  deleteSkill,
  uploadSkill,
  browseMarketplace,
  installFromMarketplace,
} = useSkillsApi()

// State
const loading = ref(false)
const skills = ref<Skill[]>([])
const catalogSkills = ref<MarketplaceSkill[]>([])
const showCatalog = ref(false)
const catalogLoading = ref(false)
const catalogSearch = ref('')
const installingSkill = ref<string | null>(null)
const openContextMenu = ref<string | null>(null)
const isDragging = ref(false)

// Skill editor
const showSkillEditor = ref(false)
const editingSkill = ref<SkillDetail | null>(null)

// Computed
const installedNames = computed(() => new Set(skills.value.map(s => s.name)))

// Data loading
async function loadSkills() {
  loading.value = true
  try {
    skills.value = await listSkills()
  } catch (err) {
    console.error('Failed to load skills:', err)
  } finally {
    loading.value = false
  }
}

async function loadCatalog() {
  catalogLoading.value = true
  try {
    const result = await browseMarketplace({ q: catalogSearch.value || undefined, limit: 50 })
    catalogSkills.value = result.skills
  } catch (err) {
    console.error('Failed to load marketplace:', err)
    catalogSkills.value = []
  } finally {
    catalogLoading.value = false
  }
}

// Actions
function notifySkillsChanged() {
  window.dispatchEvent(new CustomEvent('skills-changed'))
}

async function handleInstallSkill(skill: MarketplaceSkill) {
  installingSkill.value = skill.name
  try {
    await installFromMarketplace(skill.name)
    await loadSkills()
    notifySkillsChanged()
  } catch (err) {
    console.error('Failed to install skill:', err)
  } finally {
    installingSkill.value = null
  }
}

async function handleUninstallFromCatalog(skill: MarketplaceSkill) {
  try {
    await deleteSkill(skill.name)
    await loadSkills()
    notifySkillsChanged()
  } catch (err) {
    console.error('Failed to remove skill:', err)
  }
}

// Confirmation state
const showRemoveConfirm = ref(false)
const pendingAction = ref<{ skill: Skill } | null>(null)

function handleRemoveSkill(skill: Skill) {
  openContextMenu.value = null
  pendingAction.value = { skill }
  showRemoveConfirm.value = true
}

async function executeRemoveSkill() {
  if (!pendingAction.value) return
  showRemoveConfirm.value = false
  const skill = pendingAction.value.skill
  pendingAction.value = null
  try {
    await deleteSkill(skill.name)
    await loadSkills()
    notifySkillsChanged()
  } catch (err) {
    console.error('Failed to remove skill:', err)
  }
}

function handleDownloadSkillZip(skill: Skill) {
  const profileId = getCurrentProfileId()
  const url = `${getApiBase()}/settings/skills/${encodeURIComponent(skill.name)}/download?profile=${encodeURIComponent(profileId)}`
  const a = document.createElement('a')
  a.href = url
  a.download = `${skill.name}.zip`
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
}

function handleNewSkill() {
  editingSkill.value = null
  showSkillEditor.value = true
}

async function handleEditSkill(skill: Skill) {
  openContextMenu.value = null
  try {
    editingSkill.value = await getSkill(skill.name)
    showSkillEditor.value = true
  } catch (err) {
    console.error('Failed to load skill detail:', err)
  }
}

async function handleSaveSkill(data: { name: string; display_name: string; description: string; tags: string[]; content: string }) {
  try {
    if (editingSkill.value) {
      await updateSkill(editingSkill.value.name, {
        display_name: data.display_name,
        description: data.description,
        tags: data.tags,
        content: data.content,
      })
    } else {
      await createSkill({
        name: data.name,
        display_name: data.display_name,
        description: data.description,
        tags: data.tags,
        content: data.content,
      })
    }
    showSkillEditor.value = false
    editingSkill.value = null
    await loadSkills()
    notifySkillsChanged()
  } catch (err) {
    console.error('Failed to save skill:', err)
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
    alert('Only .md and .zip files are supported.')
    return
  }
  await doUpload(file)
}

async function doUpload(file: File) {
  try {
    await uploadSkill(file)
    await loadSkills()
    notifySkillsChanged()
  } catch (err) {
    console.error('Failed to upload skill:', err)
    alert('Failed to upload skill. Check the file format.')
  }
}

// Click outside handler for context menus
function handleClickOutside() {
  if (openContextMenu.value) {
    openContextMenu.value = null
  }
}

onMounted(() => {
  loadSkills()
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
