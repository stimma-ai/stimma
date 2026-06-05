<template>
  <Teleport to="body">
    <Transition name="modal">
      <div
        v-if="show"
        class="fixed inset-0 z-[10020] flex items-center justify-center bg-black/60 backdrop-blur-sm"
        @click.self="cancel"
      >
        <div class="bg-surface border border-edge rounded-xl shadow-2xl w-[500px] max-w-[90vw] overflow-hidden">
          <!-- Header -->
          <div class="flex items-center justify-between px-6 py-4 border-b border-edge">
            <h2 class="text-lg font-semibold text-content">Folder Settings</h2>
            <button
              @click="cancel"
              class="w-8 h-8 flex items-center justify-center text-content-tertiary hover:text-content hover:bg-surface-raised rounded-lg transition-colors"
            >
              <svg class="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>

          <!-- Content -->
          <div class="p-6 space-y-5">
            <!-- Path -->
            <div>
              <label class="block text-sm font-medium text-content-secondary mb-2">Path</label>
              <div v-if="isTauriMode" class="flex gap-2">
                <input
                  v-model="localPath"
                  type="text"
                  readonly
                  class="flex-1 px-3 py-2 bg-surface-raised/50 border border-edge rounded-lg text-content-secondary text-sm"
                />
                <button
                  @click="browsePath"
                  class="px-3 py-2 bg-surface-raised hover:bg-surface-hover border border-edge rounded-lg text-content text-sm transition-colors"
                >
                  Browse...
                </button>
              </div>
              <input
                v-else
                v-model="localPath"
                type="text"
                class="w-full px-3 py-2 bg-surface-raised border border-edge rounded-lg text-content placeholder-content-muted text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                placeholder="/path/to/media/folder"
              />
            </div>

            <!-- Scan Interval -->
            <div>
              <label class="block text-sm font-medium text-content-secondary mb-2">Scan Interval</label>
              <select
                v-model="localRefreshInterval"
                class="w-full px-3 py-2 bg-surface-raised border border-edge rounded-lg text-content text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              >
                <option :value="60">Every 1 minute</option>
                <option :value="300">Every 5 minutes</option>
                <option :value="600">Every 10 minutes</option>
                <option :value="1800">Every 30 minutes</option>
                <option :value="3600">Every 1 hour</option>
                <option :value="0">Manual only</option>
              </select>
              <p class="mt-1.5 text-xs text-content-muted">How often Stimma checks this folder for new or changed files.</p>
            </div>

            <!-- Auto-Mark -->
            <div v-if="availableMarkers.length > 0">
              <label class="block text-sm font-medium text-content-secondary mb-2">Auto-Mark</label>
              <div class="flex items-center gap-1 flex-wrap">
                <button
                  v-for="marker in availableMarkers"
                  :key="marker.id"
                  @click="toggleMarker(marker.name)"
                  :class="[
                    'w-9 h-9 rounded-lg cursor-pointer transition-all border flex items-center justify-center',
                    isMarkerSelected(marker.name)
                      ? 'bg-opacity-30 border-opacity-100'
                      : 'bg-overlay-subtle border-edge-subtle text-content-tertiary hover:bg-overlay-light hover:text-content'
                  ]"
                  :style="isMarkerSelected(marker.name) ? { backgroundColor: marker.color + '33', borderColor: marker.color, color: marker.color } : {}"
                  :title="marker.name"
                >
                  <span v-html="marker.icon_svg" class="w-4 h-4 flex-shrink-0 icon-container"></span>
                </button>
              </div>
              <p class="mt-1.5 text-xs text-content-muted">Automatically apply these markers to assets in this folder.</p>
            </div>
          </div>

          <!-- Footer -->
          <div class="flex justify-end gap-3 px-6 py-4 border-t border-edge">
            <button
              @click="cancel"
              class="px-4 py-2 text-sm font-medium text-content-secondary hover:text-content hover:bg-surface-raised rounded-lg transition-colors"
            >
              Cancel
            </button>
            <button
              @click="save"
              :disabled="!localPath.trim()"
              class="px-4 py-2 text-sm font-medium bg-blue-600 hover:bg-blue-500 disabled:bg-surface-raised disabled:text-content-muted text-white rounded-lg transition-colors"
            >
              Save
            </button>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup>
import { ref, watch, onMounted } from 'vue'
import { isTauri } from '../../apiConfig'
import { useMarkers } from '../../composables/useMarkers'

const props = defineProps({
  show: {
    type: Boolean,
    default: false
  },
  folder: {
    type: Object,
    default: null
  }
})

const emit = defineEmits(['save', 'cancel'])

const localPath = ref('')
const localRefreshInterval = ref(300)
const localMarkerNames = ref([])  // Selected marker names
const isTauriMode = isTauri()

// Access available markers
const { availableMarkers, init: initMarkers } = useMarkers()

onMounted(() => {
  initMarkers()
})

// Sync local state when modal opens or folder changes
watch(() => [props.show, props.folder], ([isOpen, folder]) => {
  if (isOpen && folder) {
    localPath.value = folder.path || ''
    localRefreshInterval.value = folder.refresh_interval_seconds ?? 300
    localMarkerNames.value = [...(folder.markers || [])]
  }
}, { immediate: true })

// Check if a marker is selected
function isMarkerSelected(markerName) {
  return localMarkerNames.value.includes(markerName)
}

// Toggle a marker on/off
function toggleMarker(markerName) {
  if (isMarkerSelected(markerName)) {
    localMarkerNames.value = localMarkerNames.value.filter(n => n !== markerName)
  } else {
    localMarkerNames.value = [...localMarkerNames.value, markerName]
  }
}

async function browsePath() {
  try {
    const { open } = await import('@tauri-apps/plugin-dialog')
    const selected = await open({
      directory: true,
      multiple: false,
      title: 'Select Folder',
      defaultPath: localPath.value || undefined
    })
    if (selected) {
      localPath.value = selected
    }
  } catch (err) {
    console.error('Failed to open folder dialog:', err)
  }
}

function save() {
  const path = localPath.value.trim()
  if (path) {
    emit('save', {
      path,
      refresh_interval_seconds: localRefreshInterval.value,
      markers: localMarkerNames.value
    })
  }
}

function cancel() {
  emit('cancel')
}
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
