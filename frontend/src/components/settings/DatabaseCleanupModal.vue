<template>
  <Teleport to="body">
    <Transition name="modal">
      <div
        v-if="show"
        class="fixed inset-0 z-[10020] flex items-center justify-center bg-black/60 backdrop-blur-sm"
        @click.self="close"
      >
        <div class="bg-surface border border-edge rounded-xl shadow-2xl w-[500px] max-w-[90vw] overflow-hidden">
          <!-- Header -->
          <div class="flex items-center justify-between px-6 py-4 border-b border-edge">
            <h2 class="text-lg font-semibold text-content">Database Cleanup</h2>
            <button
              @click="close"
              class="w-8 h-8 flex items-center justify-center text-content-tertiary hover:text-content hover:bg-surface-raised rounded-lg transition-colors"
            >
              <svg class="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>

          <!-- Loading state -->
          <div v-if="state === 'loading'" class="p-6">
            <div class="flex items-center justify-center gap-3 text-content-tertiary">
              <svg class="w-5 h-5 animate-spin" fill="none" viewBox="0 0 24 24">
                <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
              </svg>
              <span>Scanning database...</span>
            </div>
          </div>

          <!-- Error state -->
          <div v-else-if="state === 'error'" class="p-6">
            <div class="text-red-500 text-sm">
              {{ error }}
            </div>
          </div>

          <!-- Preview state -->
          <div v-else-if="state === 'preview'" class="p-6 space-y-4">
            <p class="text-sm text-content-tertiary">
              Review what will be cleaned up. This cannot be undone.
            </p>

            <!-- Nothing to clean -->
            <div v-if="preview.total_count === 0" class="bg-surface-raised/50 rounded-lg p-4">
              <p class="text-content-secondary text-sm">
                No cleanup needed. Your database is already clean.
              </p>
            </div>

            <!-- Items to clean -->
            <div v-else class="space-y-3">
              <div v-if="preview.orphaned_count > 0" class="bg-surface-raised/50 rounded-lg p-4">
                <div class="flex items-start gap-3">
                  <div class="w-8 h-8 rounded-lg bg-amber-500/20 flex items-center justify-center flex-shrink-0">
                    <svg class="w-4 h-4 text-amber-500" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
                      <path stroke-linecap="round" stroke-linejoin="round" d="M2.25 12.75V12A2.25 2.25 0 0 1 4.5 9.75h15A2.25 2.25 0 0 1 21.75 12v.75m-8.69-6.44-2.12-2.12a1.5 1.5 0 0 0-1.061-.44H4.5A2.25 2.25 0 0 0 2.25 6v12a2.25 2.25 0 0 0 2.25 2.25h15A2.25 2.25 0 0 0 21.75 18V9a2.25 2.25 0 0 0-2.25-2.25h-5.379a1.5 1.5 0 0 1-1.06-.44Z" />
                    </svg>
                  </div>
                  <div>
                    <p class="text-content font-medium">{{ preview.orphaned_count.toLocaleString() }} orphaned {{ preview.orphaned_count === 1 ? 'file' : 'files' }}</p>
                    <p class="text-content-tertiary text-sm mt-1">Files from folders no longer in your configuration</p>
                  </div>
                </div>
              </div>

              <div v-if="preview.missing_count > 0" class="bg-surface-raised/50 rounded-lg p-4">
                <div class="flex items-start gap-3">
                  <div class="w-8 h-8 rounded-lg bg-red-500/20 flex items-center justify-center flex-shrink-0">
                    <svg class="w-4 h-4 text-red-500" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
                      <path stroke-linecap="round" stroke-linejoin="round" d="m20.25 7.5-.625 10.632a2.25 2.25 0 0 1-2.247 2.118H6.622a2.25 2.25 0 0 1-2.247-2.118L3.75 7.5m6 4.125 2.25 2.25m0 0 2.25 2.25M12 13.875l2.25-2.25M12 13.875l-2.25 2.25M3.375 7.5h17.25c.621 0 1.125-.504 1.125-1.125v-1.5c0-.621-.504-1.125-1.125-1.125H3.375c-.621 0-1.125.504-1.125 1.125v1.5c0 .621.504 1.125 1.125 1.125Z" />
                    </svg>
                  </div>
                  <div>
                    <p class="text-content font-medium">{{ preview.missing_count.toLocaleString() }} missing {{ preview.missing_count === 1 ? 'file' : 'files' }}</p>
                    <p class="text-content-tertiary text-sm mt-1">Files that no longer exist on disk</p>
                  </div>
                </div>
              </div>

              <div class="bg-surface-overlay rounded-lg p-3 border border-edge">
                <p class="text-content-secondary text-sm">
                    {{ preview.total_count.toLocaleString() }} {{ preview.total_count === 1 ? 'file' : 'files' }} will be permanently forgotten
                </p>
              </div>
            </div>
          </div>

          <!-- Cleaning state -->
          <div v-else-if="state === 'cleaning'" class="p-6">
            <div class="flex items-center justify-center gap-3 text-content-tertiary">
              <svg class="w-5 h-5 animate-spin" fill="none" viewBox="0 0 24 24">
                <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
              </svg>
              <span>Cleaning up database...</span>
            </div>
          </div>

          <!-- Success state -->
          <div v-else-if="state === 'success'" class="p-6 space-y-4">
            <div class="flex items-center gap-3 text-green-500">
              <svg class="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" d="M9 12.75 11.25 15 15 9.75M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z" />
              </svg>
              <span class="font-medium">Cleanup complete</span>
            </div>

            <div class="bg-surface-raised/50 rounded-lg p-4 text-sm text-content-secondary">
              <p>Forgot {{ result.total_forgotten.toLocaleString() }} {{ result.total_forgotten === 1 ? 'file' : 'files' }}:</p>
              <ul class="mt-2 space-y-1 text-content-tertiary">
                <li v-if="result.orphaned_forgotten > 0">{{ result.orphaned_forgotten.toLocaleString() }} orphaned {{ result.orphaned_forgotten === 1 ? 'file' : 'files' }}</li>
                <li v-if="result.missing_forgotten > 0">{{ result.missing_forgotten.toLocaleString() }} missing {{ result.missing_forgotten === 1 ? 'file' : 'files' }}</li>
              </ul>
            </div>
          </div>

          <!-- Footer -->
          <div class="flex justify-end gap-3 px-6 py-4 border-t border-edge">
            <!-- Preview state buttons -->
            <template v-if="state === 'preview'">
              <button
                @click="close"
                class="px-4 py-2 text-sm font-medium text-content-secondary hover:text-content hover:bg-surface-raised rounded-lg transition-colors"
              >
                Cancel
              </button>
              <button
                v-if="preview.total_count > 0"
                @click="executeCleanup"
                class="px-4 py-2 text-sm font-medium bg-red-600 hover:bg-red-500 text-white rounded-lg transition-colors"
              >
                Forget {{ preview.total_count.toLocaleString() }} {{ preview.total_count === 1 ? 'File' : 'Files' }}
              </button>
            </template>

            <!-- Success/Error state button -->
            <template v-else-if="state === 'success' || state === 'error'">
              <button
                @click="close"
                class="px-4 py-2 text-sm font-medium bg-surface-raised hover:bg-surface-hover text-content rounded-lg transition-colors"
              >
                Close
              </button>
            </template>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup>
import { ref, watch } from 'vue'
import { useSettingsApi } from '../../composables/useSettingsApi'

const props = defineProps({
  show: {
    type: Boolean,
    default: false
  }
})

const emit = defineEmits(['close', 'cleaned'])

const { getDatabaseCleanupPreview, executeDatabaseCleanup } = useSettingsApi()

// State: loading, error, preview, cleaning, success
const state = ref('loading')
const error = ref('')
const preview = ref({ orphaned_count: 0, missing_count: 0, total_count: 0 })
const result = ref({ orphaned_forgotten: 0, missing_forgotten: 0, total_forgotten: 0 })

// Fetch preview when modal opens
watch(() => props.show, async (isOpen) => {
  if (isOpen) {
    state.value = 'loading'
    error.value = ''
    preview.value = { orphaned_count: 0, missing_count: 0, total_count: 0 }
    result.value = { orphaned_forgotten: 0, missing_forgotten: 0, total_forgotten: 0 }

    try {
      preview.value = await getDatabaseCleanupPreview()
      state.value = 'preview'
    } catch (err) {
      error.value = err.response?.data?.detail || err.message || 'Failed to scan database'
      state.value = 'error'
    }
  }
})

async function executeCleanup() {
  state.value = 'cleaning'

  try {
    result.value = await executeDatabaseCleanup()
    state.value = 'success'
    emit('cleaned', result.value)
  } catch (err) {
    error.value = err.response?.data?.detail || err.message || 'Failed to cleanup database'
    state.value = 'error'
  }
}

function close() {
  emit('close')
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
