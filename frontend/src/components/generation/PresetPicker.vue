<template>
  <div class="relative">
    <!-- Preset dropdown button -->
    <button
      ref="buttonRef"
      @click="toggleDropdown"
      class="flex items-center gap-2 px-3 py-1.5 bg-overlay-subtle hover:bg-overlay-light border border-edge-subtle rounded text-sm text-content-secondary transition-colors"
    >
      <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
        <path stroke-linecap="round" stroke-linejoin="round" d="M17.593 3.322c1.1.128 1.907 1.077 1.907 2.185V21L12 17.25 4.5 21V5.507c0-1.108.806-2.057 1.907-2.185a48.507 48.507 0 0111.186 0z" />
      </svg>
      <span>{{ displayName }}</span>
      <!-- Modified indicator dot -->
      <span v-if="isModified" class="w-1.5 h-1.5 rounded-full bg-amber-400"></span>
      <svg class="w-3 h-3 ml-1" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
        <path stroke-linecap="round" stroke-linejoin="round" d="M19.5 8.25l-7.5 7.5-7.5-7.5" />
      </svg>
    </button>

    <!-- Dropdown menu (teleported to escape overflow stacking context) -->
    <Teleport to="body">
      <Transition name="fade">
        <div
          v-if="showDropdown"
          ref="dropdownRef"
          class="fixed w-64 bg-surface border border-edge-subtle rounded-lg shadow-xl z-menu overflow-hidden"
          :style="dropdownStyle"
        >
        <!-- Loading state -->
        <div v-if="loading" class="p-4 text-center text-content-muted text-sm">
          Loading presets...
        </div>

        <template v-else>
          <!-- Action buttons when modified -->
          <div v-if="isModified" class="p-2 border-b border-edge-subtle">
            <div class="flex items-center gap-2">
              <button
                v-if="hasActivePreset"
                @click="handleSave"
                class="flex-1 px-3 py-1.5 text-sm text-white bg-accent hover:bg-accent/90 rounded-md transition-colors"
              >
                Save
              </button>
              <button
                @click="handleRevert"
                class="flex-1 px-3 py-1.5 text-sm text-content-secondary hover:text-content bg-overlay-subtle hover:bg-overlay-light rounded transition-colors"
              >
                Revert
              </button>
            </div>
          </div>

          <!-- Presets list -->
          <div v-if="presets.length > 0" class="max-h-48 overflow-y-auto">
            <button
              v-for="preset in sortedPresets"
              :key="preset.id"
              @click="selectPreset(preset)"
              class="w-full flex items-center gap-2 px-4 py-2 hover:bg-overlay-subtle text-left transition-colors"
              :class="selectedPresetId === preset.id ? 'bg-blue-500/10' : ''"
            >
              <svg
                v-if="preset.pinned"
                class="w-3.5 h-3.5 text-blue-500 flex-shrink-0"
                viewBox="0 0 24 24"
                fill="currentColor"
              >
                <path d="M16 3a1 1 0 0 1 .707.293l4 4a1 1 0 0 1-.464 1.664l-2.12.53-3.536 3.536.879 3.51a1 1 0 0 1-1.664.95L10 14.682l-5.293 5.293a1 1 0 0 1-1.414-1.414L8.586 13.268l-2.8-2.8a1 1 0 0 1 .95-1.664l3.51.879 3.536-3.536.53-2.121A1 1 0 0 1 16 3z" />
              </svg>
              <span class="flex-1 truncate text-sm text-content-secondary">{{ preset.name }}</span>
              <span v-if="preset.usage_count > 0" class="text-xs text-content-muted">
                {{ preset.usage_count }}x
              </span>
            </button>
          </div>

          <!-- Empty state -->
          <div v-else class="px-4 py-3 text-center text-content-muted text-sm">
            No saved presets
          </div>

          <!-- Divider -->
          <div class="border-t border-edge-subtle"></div>

          <!-- Actions -->
          <div class="p-2">
            <button
              @click="saveAsPreset"
              class="w-full flex items-center gap-2 px-3 py-2 hover:bg-overlay-subtle rounded text-sm text-content-secondary transition-colors"
            >
              <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
              </svg>
              Save as Preset
            </button>
            <button
              @click="handleClearPreset"
              class="w-full flex items-center gap-2 px-3 py-2 hover:bg-overlay-subtle rounded text-sm text-content-tertiary transition-colors"
            >
              <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" d="M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0l3.181 3.183a8.25 8.25 0 0013.803-3.7M4.031 9.865a8.25 8.25 0 0113.803-3.7l3.181 3.182m0-4.991v4.99" />
              </svg>
              Reset to Defaults
            </button>
          </div>
        </template>
        </div>
      </Transition>
    </Teleport>

    <!-- Save Preset Modal -->
    <Teleport to="body">
      <Transition name="fade">
        <div v-if="showSaveModal" class="fixed inset-0 bg-overlay-backdrop flex items-center justify-center z-modal" @click.self="showSaveModal = false">
          <div class="bg-surface border border-edge-subtle rounded-lg p-6 max-w-md w-full mx-4">
            <h3 class="text-lg font-semibold text-content mb-4">Save Preset</h3>
            <input v-no-autocorrect
              ref="nameInputRef"
              v-model="newPresetName"
              type="text"
              placeholder="Preset name"
              class="w-full bg-surface-overlay border border-edge-subtle text-content px-3 py-2 rounded-md text-sm focus:outline-none focus:border-accent mb-4"
              @keyup.enter="confirmSavePreset"
            />
            <div class="flex items-center gap-3 mb-4">
              <label class="flex items-center gap-2 text-sm text-content-secondary cursor-pointer">
                <input v-no-autocorrect
                  type="checkbox"
                  v-model="pinNewPreset"
                  class="w-4 h-4 rounded border-edge bg-overlay-subtle text-accent focus:ring-accent"
                />
                Pin to presets
              </label>
            </div>
            <div class="flex justify-end gap-3">
              <button
                @click="showSaveModal = false"
                class="px-4 py-2 text-content-secondary hover:text-content transition-colors"
              >
                Cancel
              </button>
              <button
                @click="confirmSavePreset"
                :disabled="!newPresetName.trim() || saving"
                class="px-4 py-2 bg-accent hover:bg-accent/90 text-white rounded-md transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {{ saving ? 'Saving...' : 'Save' }}
              </button>
            </div>
          </div>
        </div>
      </Transition>
    </Teleport>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, nextTick, watch, onUnmounted, computed } from 'vue'
import { usePresetsApi, type Preset, type PresetState } from '../../composables/usePresetsApi'

const props = defineProps<{
  toolId: string  // Full tool ID (provider:tool format)
  currentState: PresetState
  selectedPresetId?: number | null
  activePresetName?: string | null
  isModified?: boolean
  hasActivePreset?: boolean
}>()

const emit = defineEmits<{
  (e: 'select', preset: Preset): void
  (e: 'saved', preset: Preset): void
  (e: 'save'): void
  (e: 'revert'): void
  (e: 'clear'): void
}>()

const { listPresets, getPresetsForTool, saveAsPreset: apiSaveAsPreset } = usePresetsApi()

// State
const showDropdown = ref(false)
const showSaveModal = ref(false)
const loading = ref(false)
const saving = ref(false)
const presets = ref<Preset[]>([])
const newPresetName = ref('')
const pinNewPreset = ref(false)
const nameInputRef = ref<HTMLInputElement | null>(null)
const buttonRef = ref<HTMLButtonElement | null>(null)
const dropdownRef = ref<HTMLDivElement | null>(null)
const dropdownPosition = ref({ top: 0, left: 0 })

// Computed
const displayName = computed(() => {
  if (props.activePresetName) return props.activePresetName
  return 'Presets'
})

// Sort presets: pinned first, then by usage_count descending
const sortedPresets = computed(() => {
  return [...presets.value].sort((a, b) => {
    // Pinned items first
    if (a.pinned && !b.pinned) return -1
    if (!a.pinned && b.pinned) return 1
    // Then by usage count descending
    return (b.usage_count || 0) - (a.usage_count || 0)
  })
})

// Computed style for dropdown positioning
const dropdownStyle = computed(() => ({
  top: `${dropdownPosition.value.top}px`,
  left: `${dropdownPosition.value.left}px`
}))

// Methods
async function loadPresets() {
  if (!props.toolId) return

  loading.value = true
  try {
    presets.value = await getPresetsForTool(props.toolId)
  } catch (err) {
    console.error('Failed to load presets:', err)
  } finally {
    loading.value = false
  }
}

function updateDropdownPosition() {
  if (buttonRef.value) {
    const rect = buttonRef.value.getBoundingClientRect()
    const DROPDOWN_WIDTH = 256 // w-64
    const MARGIN = 8
    // Prefer left-aligning to the button, but clamp so the dropdown stays
    // fully on-screen (shifts left when the button is near the right edge).
    const maxLeft = window.innerWidth - DROPDOWN_WIDTH - MARGIN
    const left = Math.max(MARGIN, Math.min(rect.left, maxLeft))
    dropdownPosition.value = {
      top: rect.bottom + 4,
      left
    }
  }
}

function toggleDropdown() {
  showDropdown.value = !showDropdown.value
  if (showDropdown.value) {
    updateDropdownPosition()
    loadPresets()
  }
}

function closeDropdown() {
  showDropdown.value = false
}

function selectPreset(preset: Preset) {
  emit('select', preset)
  closeDropdown()
}

function handleSave() {
  emit('save')
  closeDropdown()
}

function handleRevert() {
  emit('revert')
  closeDropdown()
}

function handleClearPreset() {
  emit('clear')
  closeDropdown()
}

function saveAsPreset() {
  closeDropdown()
  showSaveModal.value = true
  newPresetName.value = ''
  pinNewPreset.value = false
  nextTick(() => {
    nameInputRef.value?.focus()
  })
}

async function confirmSavePreset() {
  if (!newPresetName.value.trim() || saving.value) return

  saving.value = true
  try {
    const preset = await apiSaveAsPreset(
      newPresetName.value.trim(),
      props.toolId,
      props.currentState,
      pinNewPreset.value
    )
    emit('saved', preset)
    showSaveModal.value = false
    // Refresh presets list
    await loadPresets()
  } catch (err) {
    console.error('Failed to save preset:', err)
  } finally {
    saving.value = false
  }
}

// Close dropdown when clicking outside
function handleClickOutside(event: MouseEvent) {
  const target = event.target as Element
  // Check if click is inside the button or the dropdown
  const isInsideButton = buttonRef.value?.contains(target)
  const isInsideDropdown = dropdownRef.value?.contains(target)
  if (!isInsideButton && !isInsideDropdown) {
    closeDropdown()
  }
}

onMounted(() => {
  document.addEventListener('click', handleClickOutside)
})

onUnmounted(() => {
  document.removeEventListener('click', handleClickOutside)
})

// Load presets when tool changes
watch(() => props.toolId, () => {
  if (showDropdown.value) {
    loadPresets()
  }
})
</script>

<style scoped>
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.15s ease;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}
</style>
