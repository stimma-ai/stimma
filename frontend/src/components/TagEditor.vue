<template>
  <div class="relative w-full">
    <div class="flex flex-wrap gap-1.5 p-2 border border-edge-subtle rounded-md bg-surface min-h-[42px] cursor-text focus-within:border-edge-strong focus-within:ring-1 focus-within:ring-white/10">
      <!-- Display existing tags as chips -->
      <div
        v-for="tag in modelValue"
        :key="tag.id"
        class="inline-flex items-center gap-1 px-2 py-1 bg-overlay-light text-content rounded text-sm leading-5 max-h-[26px]"
      >
        <span>{{ tag.tag }}</span>
        <button
          class="w-[18px] h-[18px] flex items-center justify-center bg-transparent border-none text-content-tertiary hover:text-content hover:bg-overlay-light rounded-sm transition-colors text-base leading-none cursor-pointer disabled:cursor-not-allowed disabled:opacity-50"
          @click="removeTag(tag)"
          :disabled="disabled"
        >
          &times;
        </button>
      </div>

      <!-- Input field -->
      <input v-no-autocorrect
        v-if="!disabled"
        ref="inputRef"
        v-model="inputValue"
        type="text"
        class="flex-1 min-w-[120px] border-none bg-transparent text-content text-sm outline-none p-1 placeholder:text-content-muted"
        :placeholder="modelValue.length === 0 ? placeholder : ''"
        @keydown="handleKeydown"
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
import { ref, computed, watch, onMounted } from 'vue'
import { useMediaApi } from '../composables/useMediaApi'

const props = defineProps({
  modelValue: {
    type: Array,
    default: () => []
  },
  disabled: {
    type: Boolean,
    default: false
  },
  placeholder: {
    type: String,
    default: 'Add tags...'
  },
  maxSuggestions: {
    type: Number,
    default: 10
  }
})

const emit = defineEmits(['update:modelValue', 'add', 'remove'])

const { getTags } = useMediaApi()

const inputRef = ref(null)
const inputValue = ref('')
const showSuggestions = ref(false)
const selectedSuggestionIndex = ref(0)
const allTags = ref([])

// Load available tags on mount
onMounted(async () => {
  try {
    allTags.value = await getTags(true) // Get with usage counts
  } catch (error) {
    console.error('Failed to load tags:', error)
  }
})

// Filter suggestions based on input
const filteredSuggestions = computed(() => {
  if (!inputValue.value.trim()) return []

  const search = inputValue.value.toLowerCase().trim()
  const existingTagTexts = props.modelValue.map(t => t.tag.toLowerCase())

  return allTags.value
    .filter(tag => {
      // Don't suggest already-added tags
      if (existingTagTexts.includes(tag.tag.toLowerCase())) return false
      // Match the input
      return tag.tag.toLowerCase().includes(search)
    })
    .slice(0, props.maxSuggestions)
})

// Watch input to show/hide suggestions
watch(inputValue, (newValue) => {
  showSuggestions.value = newValue.trim().length > 0
  selectedSuggestionIndex.value = 0
})

function handleKeydown(event) {
  const commitKeys = ['Enter', 'Tab', ',']

  if (commitKeys.includes(event.key)) {
    event.preventDefault()
    commitTag()
  } else if (event.key === 'Backspace' && inputValue.value === '') {
    // Backspace on empty input removes last tag
    if (props.modelValue.length > 0) {
      removeTag(props.modelValue[props.modelValue.length - 1])
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
  } else if (event.key === 'Escape') {
    showSuggestions.value = false
    inputValue.value = ''
  }
}

function commitTag() {
  let tagText = inputValue.value.trim()

  // If a suggestion is selected, use that
  if (showSuggestions.value && filteredSuggestions.value.length > 0) {
    const selected = filteredSuggestions.value[selectedSuggestionIndex.value]
    if (selected) {
      addTag(selected)
      return
    }
  }

  // Otherwise, create new tag from input
  if (tagText) {
    // Remove trailing comma if present
    tagText = tagText.replace(/,\s*$/, '').trim()

    if (tagText) {
      // Check if tag already exists in the list
      const existingTag = props.modelValue.find(
        t => t.tag.toLowerCase() === tagText.toLowerCase()
      )

      if (!existingTag) {
        // Create a new tag object (will be created on backend)
        addTag({ tag: tagText })
      }
    }
  }

  inputValue.value = ''
  showSuggestions.value = false
  selectedSuggestionIndex.value = 0
}

function selectSuggestion(suggestion) {
  addTag(suggestion)
}

function addTag(tag) {
  const newTags = [...props.modelValue, tag]
  emit('update:modelValue', newTags)
  emit('add', tag)

  inputValue.value = ''
  showSuggestions.value = false
  selectedSuggestionIndex.value = 0
}

function removeTag(tag) {
  if (props.disabled) return

  const newTags = props.modelValue.filter(t => t.id !== tag.id)
  emit('update:modelValue', newTags)
  emit('remove', tag)
}

function handleBlur() {
  // Small delay to allow clicking suggestions
  setTimeout(() => {
    showSuggestions.value = false
  }, 200)
}

function focus() {
  inputRef.value?.focus()
}

defineExpose({
  focus
})
</script>
