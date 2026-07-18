<template>
  <div class="relative w-full h-full flex flex-col bg-base">
    <!-- View Modified Bar - above the grid -->
    <div v-if="isModified && !slideshowActive" class="bg-amber-400/20 border-b border-amber-500/30 px-6 py-2 flex items-center justify-between gap-4 flex-shrink-0">
      <span class="text-content-secondary text-sm whitespace-nowrap">Saved view "{{ savedViewName }}" modified</span>
      <div class="flex items-center gap-2 flex-shrink-0">
        <Button variant="secondary" size="sm" class="whitespace-nowrap" @click="restoreOriginal">
          Restore
        </Button>
        <Button size="sm" class="whitespace-nowrap" @click="saveChanges">
          Save
        </Button>
        <Button variant="secondary" size="sm" class="whitespace-nowrap" @click="showSaveAsModal = true">
          Save As
        </Button>
      </div>
    </div>

    <!-- BrowseGridView with injected filter state -->
    <BrowseGridView
      v-if="!initializing"
      :filter-state="filters"
      :similar-search-state="similarSearchState"
      :saved-view-id="savedViewId"
      :saved-view-name="savedViewName"
      @delete-view="showDeleteConfirm = true"
      @rename-view="openRenameModal"
      @move-view="moveView"
    />

    <!-- Loading state -->
    <div v-else class="flex-1 flex items-center justify-center">
      <div class="text-content-muted">Loading...</div>
    </div>

    <!-- Save As New Modal -->
    <Modal :show="showSaveAsModal" size="sm" @close="showSaveAsModal = false">
      <template #header>
        <h3 class="text-lg font-semibold text-content">Save As New View</h3>
      </template>
      <div class="px-6 py-5">
        <input v-no-autocorrect
          v-model="newViewName"
          type="text"
          placeholder="View name"
          class="w-full bg-overlay-subtle text-content px-3 py-2 rounded-md text-sm border border-transparent placeholder:text-content-muted focus:border-accent focus-visible:ring-2 ring-accent/40 outline-none"
          @keyup.enter="saveAsNew"
          ref="saveAsInput"
        />
      </div>
      <template #footer>
        <Button variant="secondary" @click="showSaveAsModal = false">Cancel</Button>
        <Button :disabled="!newViewName.trim()" @click="saveAsNew">Save</Button>
      </template>
    </Modal>

    <!-- Delete Confirmation Modal -->
    <ConfirmDialog
      :show="showDeleteConfirm"
      title="Delete View"
      confirm-label="Delete"
      danger
      @confirm="deleteView"
      @cancel="showDeleteConfirm = false"
    >
      Are you sure you want to delete "{{ savedViewName }}"? This action cannot be undone.
    </ConfirmDialog>

    <!-- Rename Modal -->
    <Modal :show="showRenameModal" size="sm" @close="showRenameModal = false">
      <template #header>
        <h3 class="text-lg font-semibold text-content">Rename View</h3>
      </template>
      <div class="px-6 py-5">
        <input v-no-autocorrect
          v-model="renameViewName"
          type="text"
          placeholder="View name"
          class="w-full bg-overlay-subtle text-content px-3 py-2 rounded-md text-sm border placeholder:text-content-muted focus-visible:ring-2 ring-accent/40 outline-none"
          :class="renameError ? 'border-red-500' : 'border-transparent focus:border-accent'"
          @keyup.enter="renameView"
          ref="renameInput"
        />
        <p v-if="renameError" class="text-red-400 text-xs mt-1.5">{{ renameError }}</p>
      </div>
      <template #footer>
        <Button variant="secondary" @click="showRenameModal = false">Cancel</Button>
        <Button :disabled="!renameViewName.trim() || renaming" :loading="renaming" @click="renameView">Rename</Button>
      </template>
    </Modal>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, onUnmounted, nextTick, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import BrowseGridView from './BrowseGridView.vue'
import { useMediaApi } from '../composables/useMediaApi'
import { useTabNavigation } from '../composables/useTabNavigation'
import { cloneDefaultBrowseFilters, normalizeBrowseFilters } from '../constants/browseFilters'
import Modal from '../components/ui/Modal.vue'
import Button from '../components/ui/Button.vue'
import ConfirmDialog from '../components/ui/ConfirmDialog.vue'

const route = useRoute()
const router = useRouter()
const {
  getSavedView,
  updateSavedView,
  createSavedView,
  deleteSavedView,
  reorderSavedView
} = useMediaApi()
const { slideshowActive } = useTabNavigation()

// Get saved view ID from route
const savedViewId = computed(() => parseInt(route.params.id))
const savedViewName = ref('')

// Local filter state (passed to BrowseGridView)
const filters = reactive(cloneDefaultBrowseFilters())
const originalFilters = ref(cloneDefaultBrowseFilters())

// Similar search state (passed to BrowseGridView)
// Use a plain object with refs - don't wrap in reactive() to avoid auto-unwrapping
const similarSearchState = {
  active: ref(false),
  sourceItem: ref(null),
  sourceItems: ref([])
}

// State
const initializing = ref(true)

// Modals
const showSaveAsModal = ref(false)
const showDeleteConfirm = ref(false)
const showRenameModal = ref(false)
const newViewName = ref('')
const renameViewName = ref('')
const renameError = ref('')
const renaming = ref(false)
const saveAsInput = ref(null)
const renameInput = ref(null)

// Stable stringify that sorts keys to avoid false positives from key ordering differences
function stableStringify(obj) {
  return JSON.stringify(obj, (_, v) =>
    v && typeof v === 'object' && !Array.isArray(v)
      ? Object.keys(v).sort().reduce((o, k) => { o[k] = v[k]; return o }, {})
      : v
  )
}

// Check if filters have been modified from original
const isModified = computed(() => {
  return stableStringify(filters) !== stableStringify(originalFilters.value)
})

// Saved view actions
async function restoreOriginal() {
  const original = JSON.parse(JSON.stringify(originalFilters.value))
  // Remove any keys that aren't in the original
  for (const key of Object.keys(filters)) {
    if (!(key in original)) {
      delete filters[key]
    }
  }
  Object.assign(filters, original)
  // Clear similar search state
  similarSearchState.active.value = false
  similarSearchState.sourceItem.value = null
  similarSearchState.sourceItems.value = []
}

async function saveChanges() {
  try {
    await updateSavedView(savedViewId.value, {
      filters: { ...filters },
      sortBy: filters.sortBy
    })
    originalFilters.value = JSON.parse(JSON.stringify(filters))
  } catch (error) {
    console.error('Failed to save changes:', error)
  }
}

async function saveAsNew() {
  if (!newViewName.value.trim()) return

  try {
    const newView = await createSavedView(newViewName.value.trim(), { ...filters }, filters.sortBy)
    showSaveAsModal.value = false
    newViewName.value = ''
    // Navigate to the new view
    router.push({ name: 'saved-view', params: { id: newView.id } })
  } catch (error) {
    console.error('Failed to create new view:', error)
  }
}

async function deleteView() {
  try {
    await deleteSavedView(savedViewId.value)
    showDeleteConfirm.value = false
    // Navigate back to browse
    router.push({ name: 'browse' })
  } catch (error) {
    console.error('Failed to delete view:', error)
  }
}

function openRenameModal() {
  renameViewName.value = savedViewName.value
  renameError.value = ''
  renaming.value = false
  showRenameModal.value = true
  nextTick(() => {
    renameInput.value?.focus()
    renameInput.value?.select()
  })
}

async function renameView() {
  if (!renameViewName.value.trim() || renaming.value) return

  // Don't do anything if name hasn't changed
  if (renameViewName.value.trim() === savedViewName.value) {
    showRenameModal.value = false
    return
  }

  renaming.value = true
  renameError.value = ''
  try {
    await updateSavedView(savedViewId.value, { name: renameViewName.value.trim() })
    savedViewName.value = renameViewName.value.trim()
    showRenameModal.value = false
  } catch (error) {
    console.error('Failed to rename view:', error)
    const detail = error.response?.data?.detail
    renameError.value = detail || 'Failed to rename view'
  } finally {
    renaming.value = false
  }
}

// Clear rename error when typing
watch(renameViewName, () => {
  renameError.value = ''
})

async function moveView(direction) {
  try {
    await reorderSavedView(savedViewId.value, direction)
  } catch (error) {
    console.error('Failed to move view:', error)
  }
}

// Focus input when save-as modal opens
watch(showSaveAsModal, (isOpen) => {
  if (isOpen) {
    nextTick(() => {
      saveAsInput.value?.focus()
    })
  }
})

// Watch for route changes to reload different saved view
watch(() => route.params.id, async (newId) => {
  if (newId && !initializing.value && route.name === 'saved-view') {
    await loadSavedView()
  }
})

async function loadSavedView() {
  try {
    const view = await getSavedView(savedViewId.value)
    savedViewName.value = view.name

    // Apply saved filters
    const savedFilters = normalizeBrowseFilters({
      ...view.filters,
      sortBy: view.sort_by
    })
    Object.assign(filters, savedFilters)
    originalFilters.value = JSON.parse(JSON.stringify(savedFilters))

    // Reset similar search state
    similarSearchState.active.value = false
    similarSearchState.sourceItem.value = null
    similarSearchState.sourceItems.value = []
  } catch (error) {
    console.error('Failed to load saved view:', error)
    // Navigate back to browse if view not found
    router.push({ name: 'browse' })
  }
}

async function handleProfileChanged() {
  // On profile change, navigate back to browse since saved views are profile-specific
  router.push({ name: 'browse' })
}

onMounted(async () => {
  await loadSavedView()
  initializing.value = false

  window.addEventListener('profile-changed', handleProfileChanged)
})

// Note: We intentionally do NOT reload on KeepAlive reactivation
// The component state is preserved by KeepAlive, and real-time updates
// are handled via WebSocket events. Reloading on every reactivation
// causes state loss (scroll position, slideshow state) and is unnecessary.

onUnmounted(() => {
  window.removeEventListener('profile-changed', handleProfileChanged)
})
</script>
