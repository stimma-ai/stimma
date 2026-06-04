<template>
  <Teleport to="body">
    <Transition name="modal">
      <div v-if="visible" class="fixed inset-0 bg-black/75 flex items-center justify-center z-[10000] p-5" @click.self="close">
        <div class="bg-surface rounded-xl max-w-[500px] w-full max-h-[80vh] flex flex-col shadow-2xl border border-edge-subtle">
          <!-- Header -->
          <div class="flex items-center justify-between px-5 py-4 border-b border-edge-subtle">
            <h3 class="text-content text-lg font-semibold">Edit Tags</h3>
            <button
              class="p-1 text-content-tertiary hover:text-content hover:bg-overlay-light rounded transition-colors"
              @click="close"
              title="Close (Esc)"
            >
              <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="w-5 h-5">
                <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>

          <!-- Body -->
          <div class="p-5 overflow-y-auto flex-1">
            <p v-if="mediaIds.length > 1" class="text-content-tertiary text-sm mb-4">
              Editing tags for {{ mediaIds.length }} items
            </p>

            <TagEditor
              ref="tagEditorRef"
              v-model="localTags"
              :placeholder="mediaIds.length > 1 ? 'Add tags to all selected items...' : 'Add tags...'"
            />

            <div v-if="error" class="mt-3 p-3 bg-red-500/10 border border-red-500/30 rounded-md text-red-500 text-sm">
              {{ error }}
            </div>
          </div>

          <!-- Footer -->
          <div class="flex gap-3 px-5 py-4 border-t border-edge-subtle justify-end">
            <button
              class="px-4 py-2 rounded-md text-sm font-medium text-content-tertiary hover:text-content hover:bg-overlay-light transition-colors"
              @click="close"
            >
              Cancel
            </button>
            <button
              class="px-4 py-2 rounded-md text-sm font-medium bg-surface-hover hover:bg-surface-active text-content transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              @click="save"
              :disabled="saving"
            >
              {{ saving ? 'Saving...' : 'Save' }}
            </button>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup>
import { ref, watch, nextTick } from 'vue'
import TagEditor from './TagEditor.vue'
import { useMediaApi } from '../composables/useMediaApi'

const props = defineProps({
  visible: {
    type: Boolean,
    default: false
  },
  mediaIds: {
    type: Array,
    default: () => []
  }
})

const emit = defineEmits(['close', 'saved'])

const { bulkTagOperation, getMediaItem } = useMediaApi()

const tagEditorRef = ref(null)
const localTags = ref([])
const initialTags = ref([])
const saving = ref(false)
const error = ref(null)

// Load existing tags when modal opens
watch(() => props.visible, async (newVisible) => {
  if (newVisible && props.mediaIds.length > 0) {
    await loadTags()
    // Focus the input after the modal opens
    await nextTick()
    tagEditorRef.value?.focus()
  } else {
    // Reset when closing
    localTags.value = []
    initialTags.value = []
    error.value = null
  }
})

async function loadTags() {
  try {
    if (props.mediaIds.length === 1) {
      // Single item: load its tags
      const media = await getMediaItem(props.mediaIds[0])
      localTags.value = media.tags || []
      initialTags.value = [...localTags.value]
    } else {
      // Multiple items: start with empty (user adds tags to all)
      localTags.value = []
      initialTags.value = []
    }
  } catch (err) {
    console.error('Failed to load tags:', err)
    error.value = 'Failed to load existing tags'
  }
}

async function save() {
  if (saving.value) return

  saving.value = true
  error.value = null

  try {
    // Determine which tags were added and removed
    const initialTagIds = new Set(initialTags.value.map(t => t.id).filter(id => id))
    const currentTagIds = new Set(localTags.value.map(t => t.id).filter(id => id))
    const currentTagTexts = localTags.value.filter(t => !t.id).map(t => t.tag)

    const addedTagTexts = currentTagTexts
    const removedTagIds = [...initialTagIds].filter(id => !currentTagIds.has(id))

    console.log('Saving tags:', {
      mediaIds: props.mediaIds,
      addedTagTexts,
      removedTagIds,
      localTags: localTags.value,
      initialTags: initialTags.value
    })

    // Call bulk tag operation
    await bulkTagOperation(
      props.mediaIds,
      addedTagTexts,
      removedTagIds
    )

    emit('saved')
    close()
  } catch (err) {
    console.error('Failed to save tags:', err)
    console.error('Error response:', err.response?.data)
    error.value = err.response?.data?.detail || 'Failed to save tags'
  } finally {
    saving.value = false
  }
}

function close() {
  if (saving.value) return
  emit('close')
}

// Handle Escape key
function handleKeydown(event) {
  if (event.key === 'Escape' && !saving.value) {
    close()
  }
}

// Add keyboard listener when modal is visible
watch(() => props.visible, (visible) => {
  if (visible) {
    document.addEventListener('keydown', handleKeydown)
  } else {
    document.removeEventListener('keydown', handleKeydown)
  }
})
</script>

<style scoped>
/* Modal transitions */
.modal-enter-active,
.modal-leave-active {
  transition: opacity 0.2s ease;
}

.modal-enter-from,
.modal-leave-to {
  opacity: 0;
}

.modal-enter-active > div,
.modal-leave-active > div {
  transition: transform 0.2s ease;
}

.modal-enter-from > div,
.modal-leave-to > div {
  transform: scale(0.95);
}
</style>
