<template>
  <div v-if="visible" class="fixed inset-0 bg-black/50 flex items-center justify-center z-50" @click.self="$emit('close')">
    <div class="bg-surface-raised border border-edge-strong rounded-lg p-6 w-96 max-w-[90vw]" @click.stop>
      <h3 class="text-lg font-semibold text-content mb-4">Save View</h3>
      <p class="text-content-tertiary text-sm mb-4">Save your current filters and sort order as a named view for quick access.</p>
      <input v-no-autocorrect
        v-model="viewName"
        type="text"
        placeholder="View name"
        class="w-full bg-surface border border-edge-strong text-content px-3 py-2 rounded-md text-sm focus:outline-none focus:border-indigo-500"
        :class="{ 'border-red-500': errorMessage }"
        @keyup.enter="handleSave"
        ref="nameInput"
      />
      <p v-if="errorMessage" class="text-red-500 text-sm mt-1 mb-3">{{ errorMessage }}</p>
      <div v-else class="mb-4"></div>
      <div class="flex gap-3">
        <button
          @click="handleSave"
          :disabled="!viewName.trim() || saving"
          class="flex-1 bg-indigo-500 text-white px-4 py-2 rounded-md text-sm font-medium cursor-pointer transition-all hover:bg-indigo-600 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {{ saving ? 'Saving...' : 'Save' }}
        </button>
        <button
          @click="$emit('close')"
          class="flex-1 bg-transparent border border-edge-strong text-content-secondary px-4 py-2 rounded-md text-sm cursor-pointer transition-all hover:bg-overlay-subtle"
        >
          Cancel
        </button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, watch, nextTick } from 'vue'
import { useRouter } from 'vue-router'
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
