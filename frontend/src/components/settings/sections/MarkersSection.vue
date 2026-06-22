<template>
  <div>
    <h3 class="text-base font-medium text-content mb-4">Markers</h3>
    <p class="text-sm text-content-tertiary mb-6">
      Markers are the fastest way to organize your library. One click to mark an image as a favorite,
      flag it for review, or sort it into any category you create.
    </p>

    <!-- Marker list -->
    <div class="space-y-2">
      <div
        v-for="(marker, index) in localMarkers"
        :key="marker.id || marker._tempId || index"
        class="flex items-center gap-3 p-3 bg-surface-raised/50 rounded-lg group"
      >
        <!-- Unified marker picker (icon + color) -->
        <MarkerPicker
          :icon-ref="marker.icon_svg"
          :color="marker.color"
          @change="updateMarkerStyle(index, $event)"
        />

        <!-- Name input -->
        <input
          :value="marker.name"
          @input="updateMarker(index, 'name', $event.target.value)"
          class="flex-1 bg-surface-raised border border-edge rounded px-3 py-1.5 text-sm text-content focus:outline-none focus:border-blue-500"
          placeholder="Marker name"
        />

        <!-- 3-dots menu -->
        <button
          :ref="el => setMenuButtonRef(index, el)"
          @click="toggleMarkerMenu(index)"
          :disabled="saving"
          class="p-1.5 text-content-muted hover:text-content-secondary disabled:opacity-50"
          title="More options"
        >
          <svg class="w-4 h-4" viewBox="0 0 24 24" fill="currentColor">
            <path fill-rule="evenodd" d="M10.5 6a1.5 1.5 0 1 1 3 0 1.5 1.5 0 0 1-3 0Zm0 6a1.5 1.5 0 1 1 3 0 1.5 1.5 0 0 1-3 0Zm0 6a1.5 1.5 0 1 1 3 0 1.5 1.5 0 0 1-3 0Z" clip-rule="evenodd" />
          </svg>
        </button>
      </div>
    </div>

    <!-- Empty state -->
    <div v-if="localMarkers.length === 0" class="text-center py-8">
      <p class="text-content-tertiary mb-3">No markers yet</p>
      <p class="text-xs text-content-muted">Click "Add Marker" to create your first one</p>
    </div>

    <!-- Add marker button -->
    <div class="mt-4">
      <button
        @click="addMarker"
        :disabled="saving"
        class="flex items-center gap-2 px-4 py-2 bg-surface-raised hover:bg-surface-hover disabled:opacity-50 text-content rounded-lg font-medium transition-colors"
      >
        <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" d="M12 4v16m8-8H4" />
        </svg>
        Add Marker
      </button>
    </div>

    <!-- Saving indicator -->
    <div v-if="saving" class="mt-4 text-xs text-content-muted">
      Saving...
    </div>

    <!-- Delete confirmation modal -->
    <ConfirmModal
      :show="showDeleteConfirm"
      title="Delete Marker?"
      message="This marker will be removed and deleted from all media items. This cannot be undone."
      confirm-text="Delete"
      @confirm="executeRemoveMarker"
      @cancel="cancelRemoveMarker"
    />

    <!-- Marker menu dropdown (teleported to avoid overflow clipping) -->
    <Teleport to="body">
      <div
        v-if="openMenuIndex !== null && menuPosition"
        data-marker-menu
        class="fixed bg-surface border border-edge rounded-lg shadow-lg py-1 min-w-[140px] z-[10010]"
        :style="{ top: menuPosition.top + 'px', left: menuPosition.left + 'px' }"
      >
        <button
          @click="handleMoveUp"
          :disabled="openMenuIndex === 0"
          class="w-full flex items-center gap-2 px-3 py-2 text-sm text-content hover:bg-surface-hover disabled:opacity-40 disabled:cursor-not-allowed transition-colors text-left"
        >
          <svg class="w-4 h-4 text-content-tertiary" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M4.5 15.75l7.5-7.5 7.5 7.5" />
          </svg>
          Move Up
        </button>
        <button
          @click="handleMoveDown"
          :disabled="openMenuIndex === localMarkers.length - 1"
          class="w-full flex items-center gap-2 px-3 py-2 text-sm text-content hover:bg-surface-hover disabled:opacity-40 disabled:cursor-not-allowed transition-colors text-left"
        >
          <svg class="w-4 h-4 text-content-tertiary" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M19.5 8.25l-7.5 7.5-7.5-7.5" />
          </svg>
          Move Down
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
  </div>
</template>

<script setup>
import { ref, watch, onMounted, onUnmounted } from 'vue'
import MarkerPicker from '../MarkerPicker.vue'
import ConfirmModal from '../../ConfirmModal.vue'

const props = defineProps({
  markers: {
    type: Array,
    default: () => []
  }
})

const emit = defineEmits(['update'])

const saving = ref(false)
const showDeleteConfirm = ref(false)
const markerToRemove = ref(null)
let saveTimer = null
let tempIdCounter = 0

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

function toggleMarkerMenu(index) {
  if (openMenuIndex.value === index) {
    closeMarkerMenu()
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

function closeMarkerMenu() {
  openMenuIndex.value = null
  menuPosition.value = null
}

function handleMoveUp() {
  const index = openMenuIndex.value
  closeMarkerMenu()
  if (index !== null && index > 0) {
    moveMarkerUp(index)
  }
}

function handleMoveDown() {
  const index = openMenuIndex.value
  closeMarkerMenu()
  if (index !== null && index < localMarkers.value.length - 1) {
    moveMarkerDown(index)
  }
}

function handleRemove() {
  const index = openMenuIndex.value
  closeMarkerMenu()
  if (index !== null) {
    confirmRemoveMarker(index)
  }
}

// Close menu when clicking outside
function handleClickOutside(event) {
  if (openMenuIndex.value !== null) {
    const menuButton = event.target.closest('[title="More options"]')
    const menuDropdown = event.target.closest('[data-marker-menu]')
    if (!menuButton && !menuDropdown) {
      closeMarkerMenu()
    }
  }
}

function handleEscapeKey(event) {
  if (event.key === 'Escape' && openMenuIndex.value !== null) {
    closeMarkerMenu()
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

// Local markers for optimistic UI updates.
// This is the authoritative state while editing - parent uses fire-and-forget pattern.
const localMarkers = ref([...props.markers])

// Track whether we've initialized to avoid re-syncing during edits
let initialized = props.markers.length > 0

// Only sync from props on genuine fresh loads (modal reopened), not during editing.
// The parent updates settings.markers with our emitted data, which would cause a
// circular update if we blindly synced back.
watch(() => props.markers, (newMarkers, oldMarkers) => {
  // Skip if this is just the parent echoing back what we emitted
  // Detect fresh load: we haven't initialized yet, or markers changed while modal was closed
  if (!initialized && newMarkers.length > 0) {
    localMarkers.value = [...newMarkers]
    initialized = true
  }
})

// Stock marker presets - used when adding new markers
const stockPresets = [
  { name: 'Favorite', icon_svg: 'heroicons:heart', color: '#ef4444' },
  { name: 'Bookmark', icon_svg: 'heroicons:bookmark', color: '#3b82f6' },
  { name: 'Flag', icon_svg: 'heroicons:flag', color: '#f97316' },
  { name: 'Star', icon_svg: 'heroicons:star', color: '#eab308' },
  { name: 'Pin', icon_svg: 'heroicons:lock-closed', color: '#8b5cf6' },
  { name: 'Review', icon_svg: 'heroicons:eye', color: '#06b6d4' },
  { name: 'Approved', icon_svg: 'heroicons:check-circle', color: '#22c55e' },
  { name: 'Rejected', icon_svg: 'heroicons:x-circle', color: '#f43f5e' },
  { name: 'Archive', icon_svg: 'heroicons:archive-box', color: '#71717a' },
  { name: 'Idea', icon_svg: 'heroicons:light-bulb', color: '#fbbf24' },
]

// Debounced save function
function debouncedSave(markers) {
  clearTimeout(saveTimer)
  saveTimer = setTimeout(async () => {
    saving.value = true
    try {
      // Strip temp IDs before saving
      const cleanMarkers = markers.map(m => {
        const { _tempId, ...rest } = m
        return rest
      })
      await emit('update', cleanMarkers)
    } finally {
      saving.value = false
    }
  }, 300)
}

function updateMarkerStyle(index, { iconRef, color }) {
  // Update local state immediately (optimistic)
  localMarkers.value = localMarkers.value.map((marker, i) =>
    i === index ? { ...marker, icon_svg: iconRef, color } : marker
  )
  debouncedSave(localMarkers.value)
}

function updateMarker(index, field, value) {
  // Update local state immediately (optimistic)
  localMarkers.value = localMarkers.value.map((marker, i) =>
    i === index ? { ...marker, [field]: value } : marker
  )
  debouncedSave(localMarkers.value)
}

function moveMarkerUp(index) {
  if (index <= 0) return
  const updatedMarkers = [...localMarkers.value]
  const temp = updatedMarkers[index - 1]
  updatedMarkers[index - 1] = updatedMarkers[index]
  updatedMarkers[index] = temp
  localMarkers.value = updatedMarkers
  debouncedSave(updatedMarkers)
}

function moveMarkerDown(index) {
  if (index >= localMarkers.value.length - 1) return
  const updatedMarkers = [...localMarkers.value]
  const temp = updatedMarkers[index + 1]
  updatedMarkers[index + 1] = updatedMarkers[index]
  updatedMarkers[index] = temp
  localMarkers.value = updatedMarkers
  debouncedSave(updatedMarkers)
}

function confirmRemoveMarker(index) {
  markerToRemove.value = index
  showDeleteConfirm.value = true
}

function executeRemoveMarker() {
  if (markerToRemove.value !== null) {
    // Update local state immediately (optimistic) - fixes st-umg
    const updatedMarkers = [...localMarkers.value]
    updatedMarkers.splice(markerToRemove.value, 1)
    localMarkers.value = updatedMarkers
    debouncedSave(updatedMarkers)
  }
  cancelRemoveMarker()
}

function cancelRemoveMarker() {
  showDeleteConfirm.value = false
  markerToRemove.value = null
}

function addMarker() {
  // Find the next unused preset
  const usedNames = new Set(localMarkers.value.map(m => m.name.toLowerCase()))
  const usedIcons = new Set(localMarkers.value.map(m => m.icon_svg))

  let preset = stockPresets.find(p =>
    !usedNames.has(p.name.toLowerCase()) && !usedIcons.has(p.icon_svg)
  )

  // If all presets are used, create a generic one
  if (!preset) {
    const colorIndex = localMarkers.value.length % stockPresets.length
    preset = {
      name: '',
      icon_svg: 'heroicons:tag',
      color: stockPresets[colorIndex].color
    }
  }

  // Add to local state immediately with temp ID (optimistic UI - fixes st-x9o)
  const newMarker = { ...preset, _tempId: `temp-${++tempIdCounter}` }
  localMarkers.value = [...localMarkers.value, newMarker]
  debouncedSave(localMarkers.value)
}
</script>
