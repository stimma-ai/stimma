<template>
  <div class="relative w-full h-full flex flex-col bg-base">
    <!-- View Modified Bar - above the grid -->
    <div v-if="isModified && !slideshowActive" class="bg-amber-400/20 border-b border-amber-500/30 px-6 py-2 flex items-center justify-between gap-4 flex-shrink-0">
      <span class="text-content-secondary text-sm whitespace-nowrap">Saved view "{{ savedViewName }}" modified</span>
      <div class="flex items-center gap-2 flex-shrink-0">
        <button
          @click="restoreOriginal"
          class="px-3 py-1 text-sm text-content-secondary hover:text-content border border-edge hover:border-edge-strong rounded transition-colors whitespace-nowrap"
        >
          Restore
        </button>
        <button
          @click="saveChanges"
          class="px-3 py-1 text-sm text-white bg-accent hover:bg-accent/90 rounded-md transition-colors whitespace-nowrap"
        >
          Save
        </button>
        <button
          @click="showSaveAsModal = true"
          class="px-3 py-1 text-sm text-content-secondary hover:text-content border border-edge hover:border-edge-strong rounded transition-colors whitespace-nowrap"
        >
          Save As
        </button>
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
    <div v-if="showSaveAsModal" class="fixed inset-0 bg-overlay-backdrop flex items-center justify-center z-modal" @click.self="showSaveAsModal = false">
      <div class="bg-surface-raised border border-edge-strong rounded-lg p-6 w-96 max-w-[90vw]" @click.stop>
        <h3 class="text-lg font-semibold text-content mb-4">Save As New View</h3>
        <input v-no-autocorrect
          v-model="newViewName"
          type="text"
          placeholder="View name"
          class="w-full bg-surface border border-edge-strong text-content px-3 py-2 rounded-md text-sm focus:outline-none focus:border-accent mb-4"
          @keyup.enter="saveAsNew"
          ref="saveAsInput"
        />
        <div class="flex gap-3">
          <button
            @click="saveAsNew"
            :disabled="!newViewName.trim()"
            class="flex-1 bg-accent text-white px-4 py-2 rounded-md text-sm font-medium cursor-pointer transition-all hover:bg-accent/90 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            Save
          </button>
          <button
            @click="showSaveAsModal = false"
            class="flex-1 bg-transparent border border-edge-strong text-content-secondary px-4 py-2 rounded-md text-sm cursor-pointer transition-all hover:bg-overlay-subtle"
          >
            Cancel
          </button>
        </div>
      </div>
    </div>

    <!-- Delete Confirmation Modal -->
    <div v-if="showDeleteConfirm" class="fixed inset-0 bg-overlay-backdrop flex items-center justify-center z-modal" @click.self="showDeleteConfirm = false">
      <div class="bg-surface-raised border border-edge-strong rounded-lg p-6 w-96 max-w-[90vw]" @click.stop>
        <h3 class="text-lg font-semibold text-content mb-2">Delete View</h3>
        <p class="text-content-secondary text-sm mb-4">Are you sure you want to delete "{{ savedViewName }}"? This action cannot be undone.</p>
        <div class="flex gap-3">
          <button
            @click="deleteView"
            class="flex-1 bg-red-600 text-white px-4 py-2 rounded-md text-sm font-medium cursor-pointer transition-all hover:bg-red-700"
          >
            Delete
          </button>
          <button
            @click="showDeleteConfirm = false"
            class="flex-1 bg-transparent border border-edge-strong text-content-secondary px-4 py-2 rounded-md text-sm cursor-pointer transition-all hover:bg-overlay-subtle"
          >
            Cancel
          </button>
        </div>
      </div>
    </div>

    <!-- Rename Modal -->
    <div v-if="showRenameModal" class="fixed inset-0 bg-overlay-backdrop flex items-center justify-center z-modal" @click.self="showRenameModal = false">
      <div class="bg-surface-raised border border-edge-strong rounded-lg p-6 w-96 max-w-[90vw]" @click.stop>
        <h3 class="text-lg font-semibold text-content mb-4">Rename View</h3>
        <input v-no-autocorrect
          v-model="renameViewName"
          type="text"
          placeholder="View name"
          class="w-full bg-surface border border-edge-strong text-content px-3 py-2 rounded-md text-sm focus:outline-none focus:border-accent"
          :class="{ 'border-red-500': renameError }"
          @keyup.enter="renameView"
          ref="renameInput"
        />
        <p v-if="renameError" class="text-red-500 text-sm mt-1 mb-3">{{ renameError }}</p>
        <div v-else class="mb-4"></div>
        <div class="flex gap-3">
          <button
            @click="renameView"
            :disabled="!renameViewName.trim() || renaming"
            class="flex-1 bg-accent text-white px-4 py-2 rounded-md text-sm font-medium cursor-pointer transition-all hover:bg-accent/90 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {{ renaming ? 'Renaming...' : 'Rename' }}
          </button>
          <button
            @click="showRenameModal = false"
            class="flex-1 bg-transparent border border-edge-strong text-content-secondary px-4 py-2 rounded-md text-sm cursor-pointer transition-all hover:bg-overlay-subtle"
          >
            Cancel
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, onUnmounted, nextTick, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import BrowseGridView from './BrowseGridView.vue'
import { useMediaApi } from '../composables/useMediaApi'
import { useTabNavigation } from '../composables/useTabNavigation'
import { cloneDefaultBrowseFilters, normalizeBrowseFilters } from '../constants/browseFilters'

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
