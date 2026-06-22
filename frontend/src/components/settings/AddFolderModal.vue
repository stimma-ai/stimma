<template>
  <Teleport to="body">
    <Transition name="modal">
      <div
        v-if="show"
        class="fixed inset-0 z-[10020] flex items-center justify-center bg-overlay-backdrop backdrop-blur-sm"
        @click.self="cancel"
      >
        <div class="bg-surface border border-edge rounded-xl shadow-2xl w-[500px] max-w-[90vw] overflow-hidden">
          <!-- Header -->
          <div class="flex items-center justify-between px-6 py-4 border-b border-edge">
            <h2 class="text-lg font-semibold text-content">Add Folder</h2>
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
          <div class="p-6 space-y-4">
            <p class="text-sm text-content-tertiary">
              Enter the path to a folder on the machine where the Stimma backend is running.
              This may be different from your current computer if you're accessing Stimma remotely.
            </p>

            <div>
              <label class="block text-sm font-medium text-content-secondary mb-2">Folder Path</label>
              <input
                ref="inputRef"
                v-model="folderPath"
                type="text"
                class="w-full px-3 py-2 bg-surface-raised border border-edge rounded-lg text-content placeholder-content-muted focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                placeholder="/path/to/media/folder"
                @keydown.enter="submit"
                @keydown.escape="cancel"
              />
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
              @click="submit"
              :disabled="!folderPath.trim()"
              class="px-4 py-2 text-sm font-medium bg-blue-600 hover:bg-blue-500 disabled:bg-surface-raised disabled:text-content-muted text-white rounded-lg transition-colors"
            >
              Add Folder
            </button>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup>
import { ref, watch, nextTick } from 'vue'

const props = defineProps({
  show: {
    type: Boolean,
    default: false
  }
})

const emit = defineEmits(['confirm', 'cancel'])

const folderPath = ref('')
const inputRef = ref(null)

// Auto-focus input when modal opens
watch(() => props.show, (isOpen) => {
  if (isOpen) {
    folderPath.value = ''
    nextTick(() => {
      inputRef.value?.focus()
    })
  }
})

function submit() {
  const path = folderPath.value.trim()
  if (path) {
    emit('confirm', path)
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
