<template>
  <div class="relative" ref="container">
    <button
      type="button"
      @click="toggle"
      @keydown="handleButtonKeydown"
      class="flex items-center gap-1.5 text-content-secondary text-sm cursor-pointer hover:text-content transition-colors"
    >
      <span>{{ displayValue }}</span>
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
        class="fixed inset-0 z-50"
        @click="close"
      />
      <div
        v-if="isOpen"
        ref="dropdown"
        class="fixed z-50 py-1 bg-surface border border-edge rounded-lg shadow-xl max-h-64 overflow-y-auto max-w-64"
        tabindex="-1"
        :style="dropdownStyle"
        @keydown="handleDropdownKeydown"
      >
        <button
          v-for="(option, index) in options"
          :key="option.value"
          :ref="el => setOptionRef(el, index)"
          type="button"
          @click="select(option.value)"
          @mouseenter="highlightedIndex = index"
          class="w-full px-3 py-1.5 text-left text-sm transition-colors truncate"
          :class="index === highlightedIndex
            ? 'text-content bg-blue-500/30'
            : option.value === modelValue
              ? 'text-content bg-blue-500/10'
              : 'text-content-secondary hover:bg-surface-raised'"
        >
          {{ option.label }}
        </button>
      </div>
    </Teleport>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, nextTick } from 'vue'

interface Option {
  value: string
  label: string
}

const props = defineProps<{
  modelValue: string
  options: Option[]
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', value: string): void
}>()

const container = ref<HTMLElement | null>(null)
const dropdown = ref<HTMLElement | null>(null)
const isOpen = ref(false)
const dropdownStyle = ref<Record<string, string>>({})
const highlightedIndex = ref(0)
const optionRefs = ref<(HTMLElement | null)[]>([])

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
  // Set highlighted index to current selection
  const currentIndex = props.options.findIndex(o => o.value === props.modelValue)
  highlightedIndex.value = currentIndex >= 0 ? currentIndex : 0
  isOpen.value = true
  nextTick(() => {
    positionDropdown()
    // Focus the dropdown for keyboard events
    dropdown.value?.focus()
    // Scroll highlighted item into view
    scrollToHighlighted()
  })
}

function close() {
  isOpen.value = false
}

function select(value: string) {
  emit('update:modelValue', value)
  close()
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
      highlightedIndex.value = Math.min(highlightedIndex.value + 1, props.options.length - 1)
      scrollToHighlighted()
      break
    case 'ArrowUp':
      e.preventDefault()
      highlightedIndex.value = Math.max(highlightedIndex.value - 1, 0)
      scrollToHighlighted()
      break
    case 'Enter':
      e.preventDefault()
      if (props.options[highlightedIndex.value]) {
        select(props.options[highlightedIndex.value].value)
      }
      break
    case 'Escape':
      e.preventDefault()
      close()
      break
  }
}

function positionDropdown() {
  if (!container.value) return

  const rect = container.value.getBoundingClientRect()
  const viewportHeight = window.innerHeight

  // Position below the button, right-aligned
  const top = rect.bottom + 4
  const right = window.innerWidth - rect.right

  // Check if dropdown would go off bottom of screen
  const spaceBelow = viewportHeight - rect.bottom - 8
  const dropdownHeight = Math.min(256, props.options.length * 32 + 8)

  if (spaceBelow < dropdownHeight && rect.top > dropdownHeight) {
    // Show above
    dropdownStyle.value = {
      bottom: `${viewportHeight - rect.top + 4}px`,
      right: `${right}px`,
    }
  } else {
    // Show below
    dropdownStyle.value = {
      top: `${top}px`,
      right: `${right}px`,
    }
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
</script>
