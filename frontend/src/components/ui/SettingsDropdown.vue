<template>
  <div class="relative" ref="container">
    <button
      type="button"
      :disabled="disabled"
      @click="toggle"
      @keydown="handleButtonKeydown"
      class="flex items-center gap-1.5 text-content-secondary text-sm cursor-pointer hover:text-content transition-colors disabled:opacity-40 disabled:cursor-not-allowed disabled:hover:text-content-secondary"
      :class="[
        control ? 'min-w-52 max-w-[min(28rem,calc(100vw-2rem))] justify-between rounded-md border border-edge bg-surface-raised px-3 py-2 text-left hover:border-blue-500/50' : '',
        fill ? 'w-full' : '',
      ]"
      aria-haspopup="listbox"
      :aria-expanded="isOpen"
    >
      <span class="truncate">{{ displayValue }}</span>
      <svg
        class="w-3 h-3 text-content-muted transition-transform"
        :class="{ 'rotate-180': isOpen }"
        viewBox="0 0 12 12"
        fill="currentColor"
      >
        <path d="M3 4.5L6 8l3-3.5H3z"/>
      </svg>
    </button>

    <Teleport to="body">
      <div
        v-if="isOpen"
        class="fixed inset-0 z-[10030]"
        @click="close"
      />
      <div
        v-if="isOpen"
        ref="dropdown"
        class="fixed z-[10031] py-1 bg-surface border border-edge rounded-lg shadow-xl overflow-hidden max-w-[calc(100vw-1rem)] flex flex-col"
        :class="control ? 'min-w-52' : 'max-w-72'"
        :style="dropdownStyle"
        role="listbox"
      >
        <div v-if="searchable" class="px-2 pt-1 pb-1.5 border-b border-edge shrink-0">
          <input
            ref="searchInput"
            v-model="searchQuery"
            type="text"
            placeholder="Search..."
            class="w-full px-2 py-1 text-sm bg-overlay-faint border border-edge-subtle rounded text-content placeholder:text-content-muted focus:outline-none focus:border-blue-500/50"
            @keydown="handleDropdownKeydown"
          />
        </div>
        <div ref="optionsList" class="overflow-y-auto max-h-64 flex-1 min-h-0" tabindex="-1" @keydown="handleDropdownKeydown">
          <button
            v-for="(option, index) in filteredOptions"
            :key="option.value"
            :ref="el => setOptionRef(el, index)"
            type="button"
            :disabled="option.disabled"
            @click="select(option.value)"
            @mouseenter="option.disabled ? null : highlightedIndex = index"
            class="w-full px-3 py-1.5 text-left text-sm transition-colors truncate"
            :class="option.disabled
              ? 'cursor-not-allowed text-content-muted opacity-60'
              : index === highlightedIndex
              ? 'text-content bg-blue-500/30'
              : option.value === modelValue
                ? 'text-content bg-blue-500/10'
                : 'text-content-secondary hover:bg-surface-raised'"
            role="option"
            :aria-selected="option.value === modelValue"
          >
            {{ option.label }}
          </button>
          <div v-if="filteredOptions.length === 0" class="px-3 py-1.5 text-sm text-content-muted">
            No matches
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, nextTick, onUnmounted } from 'vue'

interface Option {
  value: string
  label: string
  disabled?: boolean
}

const props = defineProps<{
  modelValue: string
  options: Option[]
  disabled?: boolean
  control?: boolean
  fill?: boolean
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', value: string): void
}>()

// Large catalogs (e.g. MiniMax Speech's 332 voices) are unusable as a plain
// scroll list — auto-enable a search box once the option count crosses this.
const SEARCH_THRESHOLD = 12

const container = ref<HTMLElement | null>(null)
const dropdown = ref<HTMLElement | null>(null)
const optionsList = ref<HTMLElement | null>(null)
const searchInput = ref<HTMLInputElement | null>(null)
const isOpen = ref(false)
const dropdownStyle = ref<Record<string, string>>({})
const highlightedIndex = ref(0)
const searchQuery = ref('')
const optionRefs = ref<(HTMLElement | null)[]>([])

const searchable = computed(() => props.options.length > SEARCH_THRESHOLD)

const filteredOptions = computed(() => {
  const q = searchQuery.value.trim().toLowerCase()
  if (!searchable.value || !q) return props.options
  return props.options.filter(o => o.label.toLowerCase().includes(q) || o.value.toLowerCase().includes(q))
})

function setOptionRef(el: any, index: number) {
  optionRefs.value[index] = el
}

const displayValue = computed(() => {
  const option = props.options.find(o => o.value === props.modelValue)
  return option?.label || props.modelValue
})

function toggle() {
  if (isOpen.value) {
    close()
  } else {
    open()
  }
}

function open() {
  searchQuery.value = ''
  optionRefs.value = []
  // Set highlighted index to current selection
  const currentIndex = filteredOptions.value.findIndex(o => o.value === props.modelValue && !o.disabled)
  const firstEnabled = filteredOptions.value.findIndex(o => !o.disabled)
  highlightedIndex.value = currentIndex >= 0 ? currentIndex : Math.max(0, firstEnabled)
  isOpen.value = true
  nextTick(() => {
    positionDropdown()
    // Focus the search box if present, otherwise the options list for keyboard events
    if (searchable.value) {
      searchInput.value?.focus()
    } else {
      optionsList.value?.focus()
    }
    // Scroll highlighted item into view
    scrollToHighlighted()
  })
}

function close() {
  isOpen.value = false
}

function select(value: string) {
  if (props.options.find(option => option.value === value)?.disabled) return
  emit('update:modelValue', value)
  close()
}

function moveHighlight(direction: 1 | -1) {
  let index = highlightedIndex.value
  for (let attempts = 0; attempts < filteredOptions.value.length; attempts += 1) {
    index = Math.max(0, Math.min(index + direction, filteredOptions.value.length - 1))
    if (!filteredOptions.value[index]?.disabled) {
      highlightedIndex.value = index
      scrollToHighlighted()
      return
    }
    if (index === 0 || index === filteredOptions.value.length - 1) return
  }
}

function scrollToHighlighted() {
  const el = optionRefs.value[highlightedIndex.value]
  el?.scrollIntoView({ block: 'nearest' })
}

function handleButtonKeydown(e: KeyboardEvent) {
  if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
    e.preventDefault()
    if (!isOpen.value) {
      open()
    }
  }
}

function handleDropdownKeydown(e: KeyboardEvent) {
  switch (e.key) {
    case 'ArrowDown':
      e.preventDefault()
      moveHighlight(1)
      break
    case 'ArrowUp':
      e.preventDefault()
      moveHighlight(-1)
      break
    case 'Enter':
      e.preventDefault()
      if (filteredOptions.value[highlightedIndex.value]) {
        select(filteredOptions.value[highlightedIndex.value].value)
      }
      break
    case 'Escape':
      e.preventDefault()
      close()
      break
  }
}

// Re-anchor the highlight and scroll position whenever the filtered list
// changes shape (typing narrows/widens it) so arrow-key nav stays in range.
watch(filteredOptions, () => {
  optionRefs.value = []
  highlightedIndex.value = Math.max(0, filteredOptions.value.findIndex(option => !option.disabled))
  nextTick(scrollToHighlighted)
})

function positionDropdown() {
  if (!container.value || !dropdown.value) return

  const rect = container.value.getBoundingClientRect()
  const viewportHeight = window.innerHeight
  const menuWidth = dropdown.value.offsetWidth
  const menuHeight = dropdown.value.offsetHeight

  // Right-aligned to the button, but keep the left edge on-screen
  const right = Math.max(8, Math.min(window.innerWidth - rect.right, window.innerWidth - menuWidth - 8))

  const spaceBelow = viewportHeight - rect.bottom - 12
  const spaceAbove = rect.top - 12

  if (menuHeight <= spaceBelow) {
    // Show below
    dropdownStyle.value = {
      top: `${rect.bottom + 4}px`,
      right: `${right}px`,
      ...(props.control ? { minWidth: `${rect.width}px` } : {}),
    }
  } else if (menuHeight <= spaceAbove) {
    // Show above
    dropdownStyle.value = {
      bottom: `${viewportHeight - rect.top + 4}px`,
      right: `${right}px`,
      ...(props.control ? { minWidth: `${rect.width}px` } : {}),
    }
  } else {
    // Doesn't fit either side — open on the roomier side and cap height
    const below = spaceBelow >= spaceAbove
    const space = Math.max(Math.floor(below ? spaceBelow : spaceAbove), 40)
    dropdownStyle.value = below
      ? { top: `${rect.bottom + 4}px`, right: `${right}px`, maxHeight: `${space}px`, ...(props.control ? { minWidth: `${rect.width}px` } : {}) }
      : { bottom: `${viewportHeight - rect.top + 4}px`, right: `${right}px`, maxHeight: `${space}px`, ...(props.control ? { minWidth: `${rect.width}px` } : {}) }
  }
}

// Global keydown handler for escape when open
function handleGlobalKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape' && isOpen.value) {
    close()
  }
}

watch(isOpen, (open) => {
  if (open) {
    document.addEventListener('keydown', handleGlobalKeydown)
  } else {
    document.removeEventListener('keydown', handleGlobalKeydown)
  }
})

onUnmounted(() => {
  document.removeEventListener('keydown', handleGlobalKeydown)
})
</script>
