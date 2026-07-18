<template>
  <Modal
    :show="show"
    size="custom"
    custom-class="max-w-[500px] w-full"
    @close="cancel"
  >
    <template #header>
      <div class="flex items-center justify-between">
        <h2 class="text-lg font-semibold text-content">Add Folder</h2>
        <IconButton aria-label="Close" title="Close" @click="cancel">
          <svg class="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
          </svg>
        </IconButton>
      </div>
    </template>

    <!-- Content -->
    <div class="p-6 space-y-4">
      <p class="text-sm text-content-tertiary">
        Enter a folder Stimma may scan for external media. Stimma will not write to or delete files in it.
        The path is on the machine running the Stimma backend, which may be remote.
      </p>

      <div>
        <label class="block text-sm font-medium text-content-secondary mb-2">Folder Path</label>
        <input
          ref="inputRef"
          v-model="folderPath"
          type="text"
          class="w-full px-3 py-2 bg-overlay-subtle border border-transparent rounded-md text-sm text-content placeholder:text-content-muted outline-none focus:border-accent focus-visible:ring-2 ring-accent/40"
          placeholder="/path/to/media/folder"
          @keydown.enter="submit"
          @keydown.escape="cancel"
        />
      </div>
    </div>

    <template #footer>
      <Button variant="secondary" @click="cancel">Cancel</Button>
      <Button variant="primary" :disabled="!folderPath.trim()" @click="submit">Add Folder</Button>
    </template>
  </Modal>
</template>

<script setup>
import { ref, watch, nextTick } from 'vue'
import Modal from '../ui/Modal.vue'
import Button from '../ui/Button.vue'
import IconButton from '../ui/IconButton.vue'

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
