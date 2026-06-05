<template>
  <Teleport to="body">
    <Transition name="modal">
      <div v-if="visible" class="fixed inset-0 bg-black/75 flex items-center justify-center z-[10000] p-5" @click.self="close">
        <div class="bg-surface rounded-xl max-w-[450px] w-full max-h-[80vh] flex flex-col shadow-2xl border border-edge-subtle">
          <!-- Header -->
          <div class="flex items-center justify-between px-5 py-4 border-b border-edge-subtle">
            <h3 class="text-content text-lg font-semibold">Manage Tags</h3>
            <span class="text-content-tertiary text-sm">{{ mediaIds.length }} item{{ mediaIds.length !== 1 ? 's' : '' }}</span>
          </div>

          <!-- Body -->
          <div class="px-5 py-4 overflow-y-auto flex-1 flex flex-col gap-3">
            <!-- Filter input -->
            <div class="relative flex items-center">
              <svg class="absolute left-3 w-4 h-4 text-content-muted pointer-events-none" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor">
                <path fill-rule="evenodd" d="M9 3.5a5.5 5.5 0 100 11 5.5 5.5 0 000-11zM2 9a7 7 0 1112.452 4.391l3.328 3.329a.75.75 0 11-1.06 1.06l-3.329-3.328A7 7 0 012 9z" clip-rule="evenodd" />
              </svg>
              <input v-no-autocorrect
                v-model="filterText"
                type="text"
                class="w-full py-2 px-9 bg-base border border-edge-subtle rounded-lg text-content text-sm outline-none transition-colors focus:border-edge-strong placeholder:text-content-muted"
                placeholder="Filter"
              />
              <button
                v-if="filterText"
                class="absolute right-2 bg-transparent border-none p-1 cursor-pointer text-content-muted flex items-center justify-center rounded transition-colors hover:bg-overlay-light hover:text-content-tertiary"
                @click="filterText = ''"
              >
                <svg class="w-4 h-4" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor">
                  <path d="M6.28 5.22a.75.75 0 00-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 101.06 1.06L10 11.06l3.72 3.72a.75.75 0 101.06-1.06L11.06 10l3.72-3.72a.75.75 0 00-1.06-1.06L10 8.94 6.28 5.22z" />
                </svg>
              </button>
            </div>

            <!-- Tags list -->
            <div class="flex flex-col gap-0 max-h-[350px] overflow-y-auto border border-edge-subtle rounded-lg bg-base">
              <div v-if="filteredTags.length === 0 && !showNewTagInput" class="text-center text-content-muted text-sm py-8 px-5">
                {{ filterText ? 'No matching tags' : 'No tags yet. Create one below.' }}
              </div>

              <!-- New tag input (inline when adding) -->
              <div v-if="showNewTagInput" class="flex items-center gap-2.5 py-2.5 px-4 bg-surface border-b border-edge-subtle cursor-default hover:bg-surface">
                <input v-no-autocorrect
                  ref="newTagInputRef"
                  v-model="newTagText"
                  type="text"
                  class="flex-1 py-1 px-2 bg-base border border-edge-subtle rounded-md text-content text-sm outline-none focus:border-edge-strong"
                  placeholder="Tag name..."
                  @keydown.enter="createAndAddTag"
                  @keydown.esc="cancelNewTag"
                  @blur="handleNewTagBlur"
                />
              </div>

              <label
                v-for="tag in filteredTags"
                :key="tag.id"
                class="flex items-center gap-2.5 py-2.5 px-4 cursor-pointer transition-colors border-b border-edge-subtle last:border-b-0"
                :class="getEffectiveState(tag.id) === 'all' || getEffectiveState(tag.id) === 'some' ? 'bg-overlay-light' : 'hover:bg-overlay-subtle'"
              >
                <input v-no-autocorrect
                  type="checkbox"
                  class="w-[18px] h-[18px] cursor-pointer accent-content-tertiary flex-shrink-0"
                  :checked="getEffectiveState(tag.id) === 'all'"
                  :indeterminate.prop="getEffectiveState(tag.id) === 'some'"
                  @change="toggleTag(tag.id, $event.target.checked)"
                />
                <span class="flex-1 text-content text-sm select-none">{{ tag.tag }}</span>
                <span v-if="tag.usage_count" class="text-content-muted text-[13px] select-none">({{ tag.usage_count }})</span>
              </label>
            </div>

            <!-- New tag button -->
            <button
              v-if="!showNewTagInput"
              class="flex items-center gap-1.5 py-2 px-3 bg-transparent border-none text-content-tertiary text-sm font-medium cursor-pointer rounded-md transition-colors self-start hover:bg-overlay-light hover:text-content"
              @click="startNewTag"
            >
              <svg class="w-4 h-4" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor">
                <path d="M10.75 4.75a.75.75 0 00-1.5 0v4.5h-4.5a.75.75 0 000 1.5h4.5v4.5a.75.75 0 001.5 0v-4.5h4.5a.75.75 0 000-1.5h-4.5v-4.5z" />
              </svg>
              New tag
            </button>

            <div v-if="error" class="py-2.5 px-3 bg-red-500/10 border border-red-500/30 rounded-md text-red-500 text-sm">
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
              :disabled="saving || !hasChanges"
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
import { ref, computed, watch, nextTick } from 'vue'
import { useMediaApi } from '../composables/useMediaApi'

const props = defineProps({
  visible: {
    type: Boolean,
    default: false
  },
  mediaIds: {
    type: Array,
    default: () => []
  },
  // Map of tag_id -> count of how many selected items have it
  currentTagCounts: {
    type: Object,
    default: () => ({})
  },
  // Array of selected media items with their tags
  selectedItems: {
    type: Array,
    default: () => []
  }
})

const emit = defineEmits(['close', 'saved'])

const { getTags, createTag, bulkTagOperation } = useMediaApi()

const availableTags = ref([])
const tagStates = ref({}) // tag_id -> 'all' | 'some' | 'none'
const pendingChanges = ref({}) // tag_id -> 'add' | 'remove' | null
const newTagText = ref('')
const filterText = ref('')
const showNewTagInput = ref(false)
const newTagInputRef = ref(null)
const creating = ref(false)
const saving = ref(false)
const error = ref(null)

// Sort and filter tags
const filteredTags = computed(() => {
  let tags = availableTags.value

  // Filter by search text
  if (filterText.value.trim()) {
    const search = filterText.value.toLowerCase()
    tags = tags.filter(tag => tag.tag.toLowerCase().includes(search))
  }

  // Sort: non-zero counts descending, then alphabetically
  return [...tags].sort((a, b) => {
    const aCount = a.usage_count || 0
    const bCount = b.usage_count || 0

    // If both have counts, sort by count descending
    if (aCount > 0 && bCount > 0) {
      return bCount - aCount
    }

    // Tags with counts come before tags without
    if (aCount > 0 && bCount === 0) return -1
    if (aCount === 0 && bCount > 0) return 1

    // Both have no count, sort alphabetically
    return a.tag.localeCompare(b.tag)
  })
})

// Compute tag states based on current counts
watch(() => [props.visible, props.currentTagCounts, props.mediaIds.length], () => {
  if (props.visible) {
    computeTagStates()
  }
}, { immediate: true, deep: true })

function computeTagStates() {
  const states = {}
  const totalItems = props.mediaIds.length

  for (const tag of availableTags.value) {
    const count = props.currentTagCounts[tag.id] || 0

    if (count === 0) {
      states[tag.id] = 'none'
    } else if (count === totalItems) {
      states[tag.id] = 'all'
    } else {
      states[tag.id] = 'some'
    }
  }

  tagStates.value = states
}

const hasChanges = computed(() => {
  return Object.keys(pendingChanges.value).length > 0
})

// Load tags when modal opens
watch(() => props.visible, async (newVisible) => {
  if (newVisible) {
    await loadTags()
    pendingChanges.value = {}
    error.value = null
    newTagText.value = ''
    filterText.value = ''
    showNewTagInput.value = false
  }
})

async function loadTags() {
  try {
    availableTags.value = await getTags(true) // Get with usage counts
    computeTagStates()
  } catch (err) {
    console.error('Failed to load tags:', err)
    error.value = 'Failed to load tags'
  }
}

function getEffectiveState(tagId) {
  // If there's a pending change, it overrides the current state
  if (pendingChanges.value[tagId] === 'add') {
    return 'all'
  }
  if (pendingChanges.value[tagId] === 'remove') {
    return 'none'
  }
  return tagStates.value[tagId]
}

function toggleTag(tagId, checked) {
  const currentState = tagStates.value[tagId]

  if (checked) {
    // User wants to add this tag to all items
    if (currentState === 'all') {
      // Already all have it, no change
      delete pendingChanges.value[tagId]
    } else {
      // Some or none have it, mark for add
      pendingChanges.value[tagId] = 'add'
    }
  } else {
    // User wants to remove this tag from all items
    if (currentState === 'none') {
      // None have it, no change
      delete pendingChanges.value[tagId]
    } else {
      // Some or all have it, mark for remove
      pendingChanges.value[tagId] = 'remove'
    }
  }
}

function startNewTag() {
  showNewTagInput.value = true
  nextTick(() => {
    newTagInputRef.value?.focus()
  })
}

function cancelNewTag() {
  showNewTagInput.value = false
  newTagText.value = ''
}

function handleNewTagBlur() {
  // Small delay to allow Enter key to be processed first
  setTimeout(() => {
    if (showNewTagInput.value && !newTagText.value.trim()) {
      cancelNewTag()
    }
  }, 150)
}

async function createAndAddTag() {
  const text = newTagText.value.trim()
  if (!text) {
    cancelNewTag()
    return
  }

  creating.value = true
  error.value = null

  try {
    const newTag = await createTag(text)

    // Add to available tags (with usage_count = 0 for sorting)
    newTag.usage_count = 0
    availableTags.value.push(newTag)

    // Mark for adding to all selected items AND mark as checked
    pendingChanges.value[newTag.id] = 'add'
    tagStates.value[newTag.id] = 'none' // Will appear checked due to pendingChanges

    // Reset
    newTagText.value = ''
    showNewTagInput.value = false
  } catch (err) {
    console.error('Failed to create tag:', err)
    error.value = err.response?.data?.detail || 'Failed to create tag'
  } finally {
    creating.value = false
  }
}

async function save() {
  if (saving.value || !hasChanges.value) return

  saving.value = true
  error.value = null

  try {
    // For each pending change, determine which specific media IDs need the operation
    for (const [tagIdStr, action] of Object.entries(pendingChanges.value)) {
      const tagId = parseInt(tagIdStr)

      if (action === 'add') {
        // Find media IDs that DON'T already have this tag
        const mediaIdsToAdd = props.selectedItems
          .filter(item => !item.tags || !item.tags.some(t => t.id === tagId))
          .map(item => item.id)

        if (mediaIdsToAdd.length > 0) {
          const tag = availableTags.value.find(t => t.id === tagId)
          if (tag) {
            console.log(`Adding tag "${tag.tag}" to ${mediaIdsToAdd.length} items (skipping ${props.selectedItems.length - mediaIdsToAdd.length} that already have it)`)
            await bulkTagOperation(mediaIdsToAdd, [tag.tag], [])
          }
        } else {
          console.log(`Tag ${tagId} already on all items, skipping add`)
        }
      } else if (action === 'remove') {
        // Find media IDs that DO have this tag
        const mediaIdsToRemove = props.selectedItems
          .filter(item => item.tags && item.tags.some(t => t.id === tagId))
          .map(item => item.id)

        if (mediaIdsToRemove.length > 0) {
          console.log(`Removing tag ${tagId} from ${mediaIdsToRemove.length} items (skipping ${props.selectedItems.length - mediaIdsToRemove.length} that don't have it)`)
          await bulkTagOperation(mediaIdsToRemove, [], [tagId])
        } else {
          console.log(`Tag ${tagId} not on any items, skipping remove`)
        }
      }
    }

    emit('saved')
    close()
  } catch (err) {
    console.error('Failed to save tags:', err)
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
    event.stopPropagation()
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
