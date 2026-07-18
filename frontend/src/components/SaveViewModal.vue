<template>
  <Modal :show="visible" size="sm" @close="$emit('close')">
    <template #header>
      <h3 class="text-lg font-semibold text-content">Save View</h3>
    </template>

    <div class="px-6 py-5">
      <p class="text-content-tertiary text-sm mb-4">Save your current filters and sort order as a named view for quick access.</p>
      <input v-no-autocorrect
        v-model="viewName"
        type="text"
        placeholder="View name"
        class="w-full bg-overlay-subtle border border-transparent text-content px-3 py-2 rounded-md text-sm focus:outline-none focus:border-accent focus-visible:ring-2 ring-accent/40"
        :class="{ 'border-red-500': errorMessage }"
        @keyup.enter="handleSave"
        ref="nameInput"
      />
      <p v-if="errorMessage" class="text-red-500 text-sm mt-1">{{ errorMessage }}</p>
    </div>

    <template #footer>
      <Button variant="secondary" @click="$emit('close')">Cancel</Button>
      <Button variant="primary" :loading="saving" :disabled="!viewName.trim()" @click="handleSave">
        {{ saving ? 'Saving...' : 'Save' }}
      </Button>
    </template>
  </Modal>
</template>

<script setup>
import { ref, watch, nextTick } from 'vue'
import { useRouter } from 'vue-router'
import Modal from './ui/Modal.vue'
import Button from './ui/Button.vue'
import { useMediaApi } from '../composables/useMediaApi'

const props = defineProps({
  visible: {
    type: Boolean,
    default: false
  },
  filters: {
    type: Object,
    required: true
  },
  sortBy: {
    type: String,
    default: 'created_desc'
  }
})

const emit = defineEmits(['close', 'saved'])

const router = useRouter()
const { createSavedView } = useMediaApi()

const viewName = ref('')
const saving = ref(false)
const errorMessage = ref('')
const nameInput = ref(null)

// Focus input when modal opens
watch(() => props.visible, (isVisible) => {
  if (isVisible) {
    viewName.value = ''
    saving.value = false
    errorMessage.value = ''
    nextTick(() => {
      nameInput.value?.focus()
    })
  }
})

// Clear error when user types
watch(viewName, () => {
  errorMessage.value = ''
})

async function handleSave() {
  if (!viewName.value.trim() || saving.value) return

  saving.value = true
  errorMessage.value = ''
  try {
    const newView = await createSavedView(viewName.value.trim(), props.filters, props.sortBy)
    emit('saved', newView)
    emit('close')
    // Navigate to the new saved view
    router.push({ name: 'saved-view', params: { id: newView.id } })
  } catch (error) {
    console.error('Failed to save view:', error)
    // Extract error message from response
    const detail = error.response?.data?.detail
    errorMessage.value = detail || 'Failed to save view'
  } finally {
    saving.value = false
  }
}
</script>
