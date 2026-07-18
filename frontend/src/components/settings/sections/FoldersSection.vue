<template>
  <div>
    <div v-if="!wizard" class="mb-3">
      <h3 class="text-base font-medium text-content">Folders</h3>
      <p class="mt-1 text-xs text-content-tertiary">
        Add folders Stimma may scan for external media. Stimma never writes to or deletes files in these folders.
      </p>
    </div>

    <!-- Folder list -->
    <div class="space-y-0.5">
      <div
        v-for="(folder, index) in folders"
        :key="index"
        class="flex w-full items-center gap-4 px-1 py-3 hover:bg-overlay-subtle"
      >
        <div class="flex h-9 w-9 shrink-0 items-center justify-center text-content-secondary">
          <svg class="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
            <path stroke-linecap="round" stroke-linejoin="round" d="M2.25 12.75V12A2.25 2.25 0 0 1 4.5 9.75h15A2.25 2.25 0 0 1 21.75 12v.75m-8.69-6.44-2.12-2.12a1.5 1.5 0 0 0-1.061-.44H4.5A2.25 2.25 0 0 0 2.25 6v12a2.25 2.25 0 0 0 2.25 2.25h15A2.25 2.25 0 0 0 21.75 18V9a2.25 2.25 0 0 0-2.25-2.25h-5.379a1.5 1.5 0 0 1-1.06-.44Z" />
          </svg>
        </div>
        <div class="min-w-0 flex-1">
          <div class="flex items-center gap-2">
            <p class="truncate text-sm font-medium text-content" :title="folder.path">{{ folder.path }}</p>
            <!-- Scanning indicator -->
            <svg
              v-if="rescanning === index"
              class="w-3.5 h-3.5 text-blue-500 animate-spin flex-shrink-0"
              viewBox="0 0 24 24"
              fill="none"
            >
              <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" />
              <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
            </svg>
          </div>
          <div class="mt-0.5 flex items-center gap-1.5">
            <p class="text-xs text-content-tertiary">{{ folder.media_count?.toLocaleString() || 0 }} assets</p>
            <!-- Auto-mark indicators -->
            <template v-if="folder.markers && folder.markers.length > 0">
              <span class="text-content-muted text-xs">·</span>
              <div class="flex items-center gap-1">
                <template v-for="markerName in folder.markers" :key="markerName">
                  <span
                    v-if="getMarkerByName(markerName)"
                    class="w-3.5 h-3.5 flex items-center justify-center text-content-muted icon-container"
                    :title="'Auto-mark: ' + markerName"
                    v-html="markerIconSvg(markerName)"
                  ></span>
                </template>
              </div>
            </template>
          </div>
        </div>
        <!-- 3-dots menu -->
        <button
          :ref="el => setMenuButtonRef(index, el)"
          @click="toggleFolderMenu(index)"
          :disabled="saving"
          class="shrink-0 p-1.5 text-content-tertiary hover:text-content hover:bg-surface-hover rounded transition-colors disabled:opacity-50"
          title="More options"
        >
          <svg class="w-4 h-4" viewBox="0 0 24 24" fill="currentColor">
            <path fill-rule="evenodd" d="M10.5 6a1.5 1.5 0 1 1 3 0 1.5 1.5 0 0 1-3 0Zm0 6a1.5 1.5 0 1 1 3 0 1.5 1.5 0 0 1-3 0Zm0 6a1.5 1.5 0 1 1 3 0 1.5 1.5 0 0 1-3 0Z" clip-rule="evenodd" />
          </svg>
        </button>
      </div>

      <!-- Empty state: one contained card that IS the add-folder action -->
      <button
        v-if="folders.length === 0"
        type="button"
        @click="addFolder"
        :disabled="saving"
        class="flex w-full flex-col items-center gap-3 rounded-lg border border-dashed border-edge px-6 py-10 text-center transition-colors hover:border-blue-500/50 hover:bg-blue-500/[0.04] disabled:opacity-50"
      >
        <svg class="h-8 w-8 text-content-muted" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
          <path stroke-linecap="round" stroke-linejoin="round" d="M12 10.5v6m3-3H9m4.06-7.19-2.12-2.12a1.5 1.5 0 0 0-1.061-.44H4.5A2.25 2.25 0 0 0 2.25 6v12a2.25 2.25 0 0 0 2.25 2.25h15A2.25 2.25 0 0 0 21.75 18V9a2.25 2.25 0 0 0-2.25-2.25h-5.379a1.5 1.5 0 0 1-1.06-.44Z" />
        </svg>
        <div>
          <div class="text-sm font-medium text-blue-400">Add Folder</div>
          <div class="mt-1 text-xs text-content-tertiary">Choose a folder to scan into your library — read-only, your files are never changed.</div>
        </div>
      </button>

      <!-- Add folder row (below the existing list) -->
      <button
        v-else
        type="button"
        @click="addFolder"
        :disabled="saving"
        class="flex w-full items-center gap-4 px-1 py-3 text-left hover:bg-blue-500/[0.04] disabled:opacity-50"
      >
        <div class="flex h-9 w-9 shrink-0 items-center justify-center text-blue-400">
          <svg class="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75"><path stroke-linecap="round" d="M12 5v14M5 12h14" /></svg>
        </div>
        <div class="min-w-0 flex-1">
          <div class="text-sm font-medium text-blue-400">Add Folder</div>
          <div class="mt-0.5 truncate text-xs text-content-tertiary">Scan an external folder for media, read-only.</div>
        </div>
      </button>
    </div>

    <!-- Saving indicator -->
    <div v-if="saving" class="mt-4 text-xs text-content-muted">
      Saving...
    </div>

    <!-- Remove folder confirmation -->
    <ConfirmModal
      :show="showRemoveConfirm"
      title="Remove Folder?"
      message="Stimma will stop scanning this folder. Files on disk will not be deleted."
      confirm-text="Remove"
      @confirm="confirmRemoveFolder"
      @cancel="cancelRemoveFolder"
    />

    <!-- Add folder modal (web mode) -->
    <AddFolderModal
      :show="showAddFolderModal"
      @confirm="handleAddFolderConfirm"
      @cancel="handleAddFolderCancel"
    />

    <!-- Folder menu dropdown (teleported to avoid overflow clipping) -->
    <Teleport to="body">
      <div
        v-if="openMenuIndex !== null && menuPosition"
        data-folder-menu
        class="fixed bg-surface border border-edge rounded-lg shadow-lg py-1 min-w-[140px] z-menu"
        :style="{ top: menuPosition.top + 'px', left: menuPosition.left + 'px' }"
      >
        <button
          @click="handleScanNow"
          :disabled="rescanning === openMenuIndex"
          class="w-full flex items-center gap-2 px-3 py-2 text-sm text-content hover:bg-surface-hover disabled:opacity-50 transition-colors text-left"
        >
          <svg class="w-4 h-4 text-content-tertiary" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" d="M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0 3.181 3.183a8.25 8.25 0 0 0 13.803-3.7M4.031 9.865a8.25 8.25 0 0 1 13.803-3.7l3.181 3.182m0-4.991v4.99" />
          </svg>
          Scan Now
        </button>
        <button
          @click="handleSettings"
          class="w-full flex items-center gap-2 px-3 py-2 text-sm text-content hover:bg-surface-hover transition-colors text-left"
        >
          <svg class="w-4 h-4 text-content-tertiary" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" d="M9.594 3.94c.09-.542.56-.94 1.11-.94h2.593c.55 0 1.02.398 1.11.94l.213 1.281c.063.374.313.686.645.87.074.04.147.083.22.127.325.196.72.257 1.075.124l1.217-.456a1.125 1.125 0 0 1 1.37.49l1.296 2.247a1.125 1.125 0 0 1-.26 1.431l-1.003.827c-.293.241-.438.613-.43.992a7.723 7.723 0 0 1 0 .255c-.008.378.137.75.43.991l1.004.827c.424.35.534.955.26 1.43l-1.298 2.247a1.125 1.125 0 0 1-1.369.491l-1.217-.456c-.355-.133-.75-.072-1.076.124a6.47 6.47 0 0 1-.22.128c-.331.183-.581.495-.644.869l-.213 1.281c-.09.543-.56.94-1.11.94h-2.594c-.55 0-1.019-.398-1.11-.94l-.213-1.281c-.062-.374-.312-.686-.644-.87a6.52 6.52 0 0 1-.22-.127c-.325-.196-.72-.257-1.076-.124l-1.217.456a1.125 1.125 0 0 1-1.369-.49l-1.297-2.247a1.125 1.125 0 0 1 .26-1.431l1.004-.827c.292-.24.437-.613.43-.991a6.932 6.932 0 0 1 0-.255c.007-.38-.138-.751-.43-.992l-1.004-.827a1.125 1.125 0 0 1-.26-1.43l1.297-2.247a1.125 1.125 0 0 1 1.37-.491l1.216.456c.356.133.751.072 1.076-.124.072-.044.146-.086.22-.128.332-.183.582-.495.644-.869l.214-1.28Z" />
            <path stroke-linecap="round" stroke-linejoin="round" d="M15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z" />
          </svg>
          Settings
        </button>
        <button
          @click="handleRemove"
          class="w-full flex items-center gap-2 px-3 py-2 text-sm text-red-500 hover:bg-surface-hover transition-colors text-left"
        >
          <svg class="w-4 h-4" viewBox="0 0 24 24" fill="currentColor">
            <path fill-rule="evenodd" d="M16.5 4.478v.227a48.816 48.816 0 0 1 3.878.512.75.75 0 1 1-.256 1.478l-.209-.035-1.005 13.07a3 3 0 0 1-2.991 2.77H8.084a3 3 0 0 1-2.991-2.77L4.087 6.66l-.209.035a.75.75 0 0 1-.256-1.478A48.567 48.567 0 0 1 7.5 4.705v-.227c0-1.564 1.213-2.9 2.816-2.951a52.662 52.662 0 0 1 3.369 0c1.603.051 2.815 1.387 2.815 2.951Zm-6.136-1.452a51.196 51.196 0 0 1 3.273 0C14.39 3.05 15 3.684 15 4.478v.113a49.488 49.488 0 0 0-6 0v-.113c0-.794.609-1.428 1.364-1.452Zm-.355 5.945a.75.75 0 1 0-1.5.058l.347 9a.75.75 0 1 0 1.499-.058l-.346-9Zm5.48.058a.75.75 0 1 0-1.498-.058l-.347 9a.75.75 0 0 0 1.5.058l.345-9Z" clip-rule="evenodd" />
          </svg>
          Remove
        </button>
      </div>
    </Teleport>

    <!-- Folder settings modal -->
    <FolderSettingsModal
      :show="showFolderSettings"
      :folder="folderToEdit"
      @save="handleFolderSettingsSave"
      @cancel="showFolderSettings = false"
    />
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { isTauri } from '../../../apiConfig'
import { useMarkers } from '../../../composables/useMarkers'
import ConfirmModal from '../../ConfirmModal.vue'
import AddFolderModal from '../AddFolderModal.vue'
import FolderSettingsModal from '../FolderSettingsModal.vue'
import { sanitizeSvg } from '../../../utils/sanitizeHtml'

// Access available markers for display
const { availableMarkers, init: initMarkers } = useMarkers()
initMarkers()

// Get marker details by name (case-insensitive, trimmed)
function getMarkerByName(name) {
  if (!name) return null
  const normalized = name.trim().toLowerCase()
  return availableMarkers.value.find(m => m.name?.toLowerCase() === normalized)
}

function markerIconSvg(name) {
  return sanitizeSvg(getMarkerByName(name)?.icon_svg)
}

const props = defineProps({
  folders: {
    type: Array,
    default: () => []
  },
  // Setup-wizard variant: the step provides its own header, so skip ours.
  wizard: {
    type: Boolean,
    default: false
  }
})

const emit = defineEmits(['update', 'rescan', 'refresh'])

const saving = ref(false)
const rescanning = ref(null)
const showRemoveConfirm = ref(false)
const folderToRemove = ref(null)
const showAddFolderModal = ref(false)
const showFolderSettings = ref(false)
const folderToEdit = ref(null)
const folderToEditIndex = ref(null)
let saveTimer = null

// Get display name for folder (last path segment)
function getFolderDisplayName(path) {
  if (!path) return 'Unknown'
  const segments = path.replace(/\/$/, '').split(/[/\\]/)
  return segments[segments.length - 1] || path
}

// Menu state
const openMenuIndex = ref(null)
const menuPosition = ref(null)
const menuButtonRefs = ref({})

function setMenuButtonRef(index, el) {
  if (el) {
    menuButtonRefs.value[index] = el
  } else {
    delete menuButtonRefs.value[index]
  }
}

function toggleFolderMenu(index) {
  if (openMenuIndex.value === index) {
    closeFolderMenu()
  } else {
    const button = menuButtonRefs.value[index]
    if (button) {
      const rect = button.getBoundingClientRect()
      menuPosition.value = {
        top: rect.bottom + 4,
        left: rect.right - 140
      }
    }
    openMenuIndex.value = index
  }
}

function closeFolderMenu() {
  openMenuIndex.value = null
  menuPosition.value = null
}

function handleScanNow() {
  const index = openMenuIndex.value
  closeFolderMenu()
  if (index !== null) {
    rescanFolder(index)
  }
}

function handleRemove() {
  const index = openMenuIndex.value
  closeFolderMenu()
  if (index !== null) {
    removeFolder(index)
  }
}

function handleSettings() {
  const index = openMenuIndex.value
  closeFolderMenu()
  if (index !== null) {
    folderToEdit.value = props.folders[index]
    folderToEditIndex.value = index
    showFolderSettings.value = true
  }
}

function handleFolderSettingsSave(updates) {
  showFolderSettings.value = false
  if (folderToEditIndex.value === null) return

  const updatedFolders = props.folders.map((folder, index) => {
    if (index === folderToEditIndex.value) {
      return {
        ...folder,
        path: updates.path,
        refresh_interval_seconds: updates.refresh_interval_seconds,
        markers: updates.markers || []
      }
    }
    return folder
  })

  immediateSave(updatedFolders)
  folderToEdit.value = null
  folderToEditIndex.value = null
}

// Close menu when clicking outside
function handleClickOutside(event) {
  if (openMenuIndex.value !== null) {
    const menuButton = event.target.closest('[title="More options"]')
    const menuDropdown = event.target.closest('[data-folder-menu]')
    if (!menuButton && !menuDropdown) {
      closeFolderMenu()
    }
  }
}

function handleEscapeKey(event) {
  if (event.key === 'Escape' && openMenuIndex.value !== null) {
    closeFolderMenu()
  }
}

onMounted(() => {
  document.addEventListener('click', handleClickOutside)
  document.addEventListener('keydown', handleEscapeKey)
})

onUnmounted(() => {
  document.removeEventListener('click', handleClickOutside)
  document.removeEventListener('keydown', handleEscapeKey)
})

// Immediate save for add/remove operations (no debounce)
async function immediateSave(folders) {
  clearTimeout(saveTimer)
  saving.value = true
  try {
    emit('update', folders)
  } finally {
    saving.value = false
  }
}

// Rescan a folder
async function rescanFolder(index) {
  const folder = props.folders[index]
  if (!folder) return

  rescanning.value = index
  try {
    await emit('rescan', folder.path)
  } finally {
    // Keep spinning for a moment to show activity
    setTimeout(() => {
      rescanning.value = null
    }, 1000)
  }
}

function removeFolder(index) {
  folderToRemove.value = index
  showRemoveConfirm.value = true
}

async function confirmRemoveFolder() {
  if (folderToRemove.value !== null) {
    const updatedFolders = [...props.folders]
    updatedFolders.splice(folderToRemove.value, 1)
    await immediateSave(updatedFolders)
  }
  cancelRemoveFolder()
}

function cancelRemoveFolder() {
  showRemoveConfirm.value = false
  folderToRemove.value = null
}

async function addFolder() {
  // Try Tauri dialog first
  if (isTauri()) {
    try {
      const { open } = await import('@tauri-apps/plugin-dialog')
      const selected = await open({
        directory: true,
        multiple: false,
        title: 'Select Folder'
      })
      if (selected) {
        await addFolderPath(selected)
      }
    } catch (err) {
      console.warn('Tauri dialog failed, falling back to modal:', err)
      showAddFolderModal.value = true
    }
  } else {
    // Web mode: show modal
    showAddFolderModal.value = true
  }
}

async function addFolderPath(path) {
  if (!path) return

  const updatedFolders = [
    ...props.folders,
    {
      path,
      refresh_interval_seconds: 300,
      markers: []
    }
  ]
  await immediateSave(updatedFolders)
}

function handleAddFolderConfirm(path) {
  showAddFolderModal.value = false
  addFolderPath(path)
}

function handleAddFolderCancel() {
  showAddFolderModal.value = false
}

</script>
