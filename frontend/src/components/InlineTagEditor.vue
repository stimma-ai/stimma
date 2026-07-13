<template>
  <div class="relative w-full">
    <div
      class="flex flex-wrap gap-1 px-1.5 py-1 border border-edge-subtle rounded-md bg-surface min-h-[28px] cursor-text focus-within:border-edge-strong focus-within:ring-1 focus-within:ring-white/10"
      @click="inputRef?.focus()"
    >
      <!-- Existing tags as chips -->
      <div
        v-for="tag in localTags"
        :key="tag.id || tag.tag"
        class="inline-flex items-center gap-1 px-1.5 py-0.5 bg-overlay-light text-content rounded text-xs leading-4"
      >
        <span>{{ tag.tag }}</span>
        <button
          class="w-[18px] h-[18px] flex items-center justify-center bg-transparent border-none text-content-tertiary hover:text-content hover:bg-overlay-light rounded-sm transition-colors text-base leading-none cursor-pointer"
          @mousedown.prevent="removeAndSync(tag)"
        >
          &times;
        </button>
      </div>

      <!-- Input field -->
      <input v-no-autocorrect
        ref="inputRef"
        v-model="inputValue"
        type="text"
        class="flex-1 min-w-[80px] border-none bg-transparent text-content text-xs outline-none p-0.5 placeholder:text-content-muted"
        :placeholder="localTags.length === 0 ? 'Add tags...' : ''"
        @keydown.stop="handleKeydown"
        @blur="handleBlur"
      />
    </div>

    <!-- Autocomplete dropdown -->
    <div
      v-if="showSuggestions && filteredSuggestions.length > 0"
      class="absolute top-full left-0 right-0 mt-1 bg-surface border border-edge-subtle rounded-md max-h-[200px] overflow-y-auto z-[1000] shadow-xl"
    >
      <div
        v-for="(suggestion, index) in filteredSuggestions"
        :key="suggestion.id"
        class="px-3 py-2 cursor-pointer text-content text-sm flex justify-between items-center transition-colors"
        :class="index === selectedSuggestionIndex ? 'bg-overlay-light' : 'hover:bg-overlay-subtle'"
        @mousedown.prevent="selectSuggestion(suggestion)"
        @mouseenter="selectedSuggestionIndex = index"
      >
        {{ suggestion.tag }}
        <span v-if="suggestion.usage_count" class="text-content-muted text-xs">
          ({{ suggestion.usage_count }})
        </span>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted, nextTick } from 'vue'
import { useMediaApi } from '../composables/useMediaApi'
import { useAssetApi } from '../composables/useAssetApi'

const props = defineProps({
  mediaId: {
    type: Number,
    required: true
  },
  assetId: {
    type: Number,
    default: null
  },
  tags: {
    type: Array,
    default: () => []
  }
})

const emit = defineEmits(['close', 'tags-changed'])

const { getTags, addTagsToMedia, removeTagFromMedia, getMediaItem } = useMediaApi()
const { addTags: addTagsToAsset, removeTag: removeTagFromAsset, getAssetBrowserItem, getTags: getAssetTags } = useAssetApi()

const inputRef = ref(null)
const inputValue = ref('')
const showSuggestions = ref(false)
const selectedSuggestionIndex = ref(0)
const allTags = ref([])
const localTags = ref([])
const opCounter = ref(0)

// Initialize
onMounted(async () => {
  localTags.value = [...props.tags]
  await nextTick()
  inputRef.value?.focus()

  try {
    allTags.value = props.assetId ? await getAssetTags(true) : await getTags(true)
  } catch (error) {
    console.error('Failed to load tags:', error)
  }
})

// Filter suggestions based on input
const filteredSuggestions = computed(() => {
  if (!inputValue.value.trim()) return []

  const search = inputValue.value.toLowerCase().trim()
  const existingTagTexts = localTags.value.map(t => t.tag.toLowerCase())

  return allTags.value
    .filter(tag => {
      if (existingTagTexts.includes(tag.tag.toLowerCase())) return false
      return tag.tag.toLowerCase().includes(search)
    })
    .slice(0, 10)
})

// Show/hide suggestions on input change
watch(inputValue, (newValue) => {
  showSuggestions.value = newValue.trim().length > 0
  selectedSuggestionIndex.value = 0
})

function handleKeydown(event) {
  if (event.key === ',' || event.key === 'Tab') {
    event.preventDefault()
    commitCurrentInput()
  } else if (event.key === 'Enter') {
    event.preventDefault()
    handleEnter()
  } else if (event.key === 'Escape') {
    event.preventDefault()
    inputValue.value = ''
    showSuggestions.value = false
    emit('close')
  } else if (event.key === 'Backspace' && inputValue.value === '') {
    if (localTags.value.length > 0) {
      removeAndSync(localTags.value[localTags.value.length - 1])
    }
  } else if (event.key === 'ArrowDown') {
    event.preventDefault()
    if (showSuggestions.value && filteredSuggestions.value.length > 0) {
      selectedSuggestionIndex.value = Math.min(
        selectedSuggestionIndex.value + 1,
        filteredSuggestions.value.length - 1
      )
    }
  } else if (event.key === 'ArrowUp') {
    event.preventDefault()
    if (showSuggestions.value && filteredSuggestions.value.length > 0) {
      selectedSuggestionIndex.value = Math.max(selectedSuggestionIndex.value - 1, 0)
    }
  }
}

async function handleEnter() {
  const text = inputValue.value.trim().replace(/,\s*$/, '').trim()

  if (text) {
    // Check if a suggestion is highlighted
    if (showSuggestions.value && filteredSuggestions.value.length > 0) {
      const selected = filteredSuggestions.value[selectedSuggestionIndex.value]
      if (selected) {
        await commitAndSync(selected.tag)
      } else {
        await commitAndSync(text)
      }
    } else {
      await commitAndSync(text)
    }
  }

  emit('close')
}

function commitCurrentInput() {
  let text = inputValue.value.trim().replace(/,\s*$/, '').trim()

  // Use highlighted suggestion if available
  if (showSuggestions.value && filteredSuggestions.value.length > 0) {
    const selected = filteredSuggestions.value[selectedSuggestionIndex.value]
    if (selected) {
      text = selected.tag
    }
  }

  if (text) {
    commitAndSync(text)
  }
}

async function commitAndSync(tagText) {
  tagText = tagText.trim().toLowerCase()
  if (!tagText) return

  // Duplicate check
  if (localTags.value.some(t => t.tag.toLowerCase() === tagText)) {
    inputValue.value = ''
    showSuggestions.value = false
    selectedSuggestionIndex.value = 0
    return
  }

  // Optimistically add chip (without ID — will be replaced after fetch)
  localTags.value = [...localTags.value, { tag: tagText }]
  inputValue.value = ''
  showSuggestions.value = false
  selectedSuggestionIndex.value = 0

  const myOp = ++opCounter.value

  try {
    if (props.assetId) await addTagsToAsset(props.assetId, [tagText])
    else await addTagsToMedia(props.mediaId, [tagText])
    const media = props.assetId
      ? await getAssetBrowserItem(props.assetId)
      : await getMediaItem(props.mediaId)

    // Only apply if this is still the most recent operation
    if (opCounter.value === myOp) {
      localTags.value = media.tags || []
      emit('tags-changed', localTags.value)
    }
  } catch (error) {
    console.error('Failed to add tag:', error)
    // Revert optimistic add if still current
    if (opCounter.value === myOp) {
      localTags.value = localTags.value.filter(t => !(t.tag === tagText && !t.id))
    }
  }
}

async function removeAndSync(tag) {
  if (!tag.id) return

  // Optimistically remove
  localTags.value = localTags.value.filter(t => t.id !== tag.id)

  const myOp = ++opCounter.value

  try {
    if (props.assetId) await removeTagFromAsset(props.assetId, tag.id)
    else await removeTagFromMedia(props.mediaId, tag.id)
    // Emit updated tags
    if (opCounter.value === myOp) {
      emit('tags-changed', [...localTags.value])
    }
  } catch (error) {
    console.error('Failed to remove tag:', error)
    // Revert on failure
    if (opCounter.value === myOp) {
      localTags.value = [...localTags.value, tag]
    }
  }
}

function selectSuggestion(suggestion) {
  commitAndSync(suggestion.tag)
}

function handleBlur() {
  // Small delay to allow clicking suggestions/chip remove buttons first
  setTimeout(() => {
    // If input is still blurred after delay, treat like Escape (discard partial, close)
    if (document.activeElement !== inputRef.value) {
      inputValue.value = ''
      showSuggestions.value = false
      emit('close')
    }
  }, 200)
}
</script>
