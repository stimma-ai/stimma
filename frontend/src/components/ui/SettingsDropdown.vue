<template>
  <div class="relative inline-block max-w-full" ref="container">
    <button
      type="button"
      :disabled="disabled"
      @click="toggle"
      @keydown="handleButtonKeydown"
      class="flex items-center gap-1.5 text-content-secondary text-sm cursor-pointer hover:text-content transition-colors disabled:opacity-40 disabled:cursor-not-allowed disabled:hover:text-content-secondary"
      :class="[
        control ? 'max-w-[min(28rem,calc(100vw-2rem))] justify-between rounded-md border border-edge bg-surface-raised px-3 py-2 text-left hover:border-accent/50' : 'max-w-full',
        control && !compact ? 'min-w-52' : '',
        fill ? 'w-full' : '',
      ]"
      aria-haspopup="listbox"
      :aria-expanded="isOpen"
    >
      <ModelVendorIcon v-if="showVendorIcons && selectedOption" :model="selectedOption.vendor" size="sm" />
      <span class="flex min-w-0 flex-1 items-baseline gap-1.5">
        <span :class="['truncate', quiet ? 'text-xs font-mono tabular-nums' : 'font-medium text-content']">{{ selectedOption?.triggerLabel || selectedOption?.label || placeholder || modelValue }}</span>
        <span
          v-if="!hideTriggerDetails && selectedOption?.description"
          class="shrink-0 text-[11px]"
          :class="selectedOption.tone === 'cloud' ? 'stimma-cloud-text font-medium' : 'text-content-muted'"
        >{{ selectedOption.description }}</span>
      </span>
      <span v-if="!hideTriggerDetails && selectedOption?.meta" class="shrink-0 text-[11px] tabular-nums text-content-muted">{{ selectedOption.meta }}</span>
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
        class="fixed inset-0 z-menu"
        @click="close"
      />
      <Transition name="menu">
      <div
        v-if="isOpen"
        ref="dropdown"
        class="fixed z-menu flex max-w-[calc(100vw-1rem)] flex-col overflow-hidden rounded-lg border border-edge bg-surface py-1 shadow-lg"
        :style="dropdownStyle"
        role="listbox"
      >
        <div v-if="searchable" class="px-2 pt-1 pb-1.5 border-b border-edge shrink-0">
          <input
            ref="searchInput"
            v-model="searchQuery"
            type="text"
            placeholder="Search..."
            class="w-full px-2 py-1 text-sm bg-overlay-faint border border-edge-subtle rounded text-content placeholder:text-content-muted focus:outline-none focus:border-accent/50"
            @keydown="handleDropdownKeydown"
          />
        </div>
        <div ref="optionsList" class="overflow-y-auto max-h-64 flex-1 min-h-0" tabindex="-1" @keydown="handleDropdownKeydown">
          <div
            v-for="(option, index) in filteredOptions"
            :key="option.value"
            :ref="el => setOptionRef(el, index)"
            @click="option.disabled ? undefined : select(option.value)"
            @mouseenter="option.disabled ? null : highlightedIndex = index"
            class="flex w-full items-center gap-2 px-3 text-left text-sm transition-colors"
            :class="[
              option.description || option.meta ? 'py-2' : 'py-1.5',
              option.disabled
                ? 'cursor-not-allowed text-content-muted opacity-60'
                : index === highlightedIndex
                  ? 'bg-accent/15'
                  : option.value === modelValue
                    ? 'bg-accent/10'
                    : 'hover:bg-surface-raised',
            ]"
            role="option"
            :aria-selected="option.value === modelValue"
            :aria-disabled="option.disabled || undefined"
          >
            <ModelVendorIcon v-if="showVendorIcons" :model="option.vendor" size="sm" />
            <span class="min-w-0 flex-1">
              <span class="flex items-baseline justify-between gap-3">
                <span class="truncate font-medium" :class="option.disabled ? 'text-content-muted' : 'text-content'">{{ option.label }}</span>
                <span v-if="option.meta" class="shrink-0 text-[11px] tabular-nums text-content-muted">{{ option.meta }}</span>
              </span>
              <span
                v-if="option.description"
                class="mt-0.5 block truncate text-[11px]"
                :class="option.tone === 'cloud' ? 'stimma-cloud-text font-medium' : 'text-content-muted'"
              >{{ option.description }}</span>
            </span>
            <button
              v-if="option.previewUrl && !option.disabled"
              type="button"
              class="flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-content-muted transition-colors duration-150 hover:bg-overlay-subtle hover:text-content focus-visible:outline-none focus-visible:ring-2 ring-accent/60"
              :class="previewingValue === option.value ? 'text-accent-hi' : ''"
              :aria-label="previewingValue === option.value ? `Stop ${option.label} preview` : `Preview ${option.label}`"
              @click.stop="togglePreview(option)"
            >
              <svg v-if="previewingValue === option.value" class="h-3.5 w-3.5" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
                <path d="M7 6.75A.75.75 0 0 1 7.75 6h2.5a.75.75 0 0 1 .75.75v10.5a.75.75 0 0 1-.75.75h-2.5a.75.75 0 0 1-.75-.75V6.75Zm6 0a.75.75 0 0 1 .75-.75h2.5a.75.75 0 0 1 .75.75v10.5a.75.75 0 0 1-.75.75h-2.5a.75.75 0 0 1-.75-.75V6.75Z" />
              </svg>
              <svg v-else class="h-3.5 w-3.5" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
                <path d="M8.25 5.824v12.352a.75.75 0 0 0 1.125.65l10.696-6.176a.75.75 0 0 0 0-1.3L9.375 5.175a.75.75 0 0 0-1.125.65Z" />
              </svg>
            </button>
            <svg v-if="option.value === modelValue" class="h-3.5 w-3.5 shrink-0 text-accent-hi" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75">
              <path stroke-linecap="round" stroke-linejoin="round" d="m4.5 12.75 6 6 9-13.5" />
            </svg>
          </div>
          <div v-if="isSearching" class="px-3 py-1.5 text-sm text-content-muted">
            Searching…
          </div>
          <div v-if="filteredOptions.length === 0 && !isSearching" class="px-3 py-1.5 text-sm text-content-muted">
            No matches
          </div>
        </div>
      </div>
      </Transition>
    </Teleport>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, nextTick, onUnmounted } from 'vue'
import ModelVendorIcon from '../models/ModelVendorIcon.vue'
import type { ModelVendorId } from '../../utils/modelVendors'

interface Option {
  value: string
  label: string
  triggerLabel?: string
  description?: string
  meta?: string
  tone?: 'cloud'
  vendor?: ModelVendorId
  disabled?: boolean
  previewUrl?: string
}

const props = defineProps<{
  modelValue: string
  options: Option[]
  disabled?: boolean
  control?: boolean
  fill?: boolean
  compact?: boolean
  /** Value-row variant (§3.3 parameters grammar): the trigger label renders
      as a quiet small value that inherits the secondary/hover color instead
      of the bold bright settings-page treatment. */
  quiet?: boolean
  hideTriggerDetails?: boolean
  menuWidth?: number
  placeholder?: string
  /** Server-backed catalog search used when an enum is too large for the schema. */
  searchOptions?: (query: string) => Promise<Option[]>
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
const remoteOptions = ref<Option[]>([])
const selectedRemoteOption = ref<Option | null>(null)
const isSearching = ref(false)
const previewingValue = ref<string | null>(null)
let searchTimer: ReturnType<typeof setTimeout> | null = null
let searchGeneration = 0
let previewAudio: HTMLAudioElement | null = null

const allOptions = computed(() => {
  const seen = new Set<string>()
  return [
    ...(selectedRemoteOption.value ? [selectedRemoteOption.value] : []),
    ...remoteOptions.value,
    ...props.options,
  ].filter((option) => {
    if (seen.has(option.value)) return false
    seen.add(option.value)
    return true
  })
})

const searchable = computed(() => !!props.searchOptions || allOptions.value.length > SEARCH_THRESHOLD)

const filteredOptions = computed(() => {
  const q = searchQuery.value.trim().toLowerCase()
  if (!searchable.value || !q) return allOptions.value
  return allOptions.value.filter(o => [o.label, o.description, o.meta, o.value].some(value => value?.toLowerCase().includes(q)))
})

function setOptionRef(el: any, index: number) {
  optionRefs.value[index] = el
}

const selectedOption = computed(() => allOptions.value.find(o => o.value === props.modelValue))
const showVendorIcons = computed(() => allOptions.value.some(option => option.vendor))

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
  scheduleRemoteSearch('')
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
  stopPreview()
}

function select(value: string) {
  const option = allOptions.value.find(candidate => candidate.value === value)
  if (option?.disabled) return
  if (option && !props.options.some(candidate => candidate.value === value)) selectedRemoteOption.value = option
  emit('update:modelValue', value)
  close()
}

function scheduleRemoteSearch(query: string) {
  if (!props.searchOptions) return
  if (searchTimer) clearTimeout(searchTimer)
  const generation = ++searchGeneration
  searchTimer = setTimeout(async () => {
    isSearching.value = true
    try {
      const options = await props.searchOptions!(query)
      if (generation === searchGeneration) remoteOptions.value = options
    } catch {
      if (generation === searchGeneration) remoteOptions.value = []
    } finally {
      if (generation === searchGeneration) isSearching.value = false
    }
  }, query ? 220 : 0)
}

function stopPreview() {
  previewAudio?.pause()
  previewAudio = null
  previewingValue.value = null
}

function togglePreview(option: Option) {
  if (!option.previewUrl) return
  if (previewingValue.value === option.value) {
    stopPreview()
    return
  }
  stopPreview()
  const audio = new Audio(option.previewUrl)
  previewAudio = audio
  previewingValue.value = option.value
  audio.addEventListener('ended', stopPreview, { once: true })
  audio.addEventListener('error', stopPreview, { once: true })
  void audio.play().catch(stopPreview)
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
  nextTick(() => {
    scrollToHighlighted()
    if (isOpen.value) positionDropdown()
  })
})

watch(searchQuery, (query) => {
  if (isOpen.value) scheduleRemoteSearch(query)
})

function positionDropdown() {
  if (!container.value || !dropdown.value) return

  const rect = container.value.getBoundingClientRect()
  const viewportHeight = window.innerHeight
  const menuWidth = Math.min(
    props.menuWidth || Math.max(rect.width, props.compact ? 176 : 208),
    window.innerWidth - 16,
  )
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
      width: `${menuWidth}px`,
    }
  } else if (menuHeight <= spaceAbove) {
    // Show above
    dropdownStyle.value = {
      bottom: `${viewportHeight - rect.top + 4}px`,
      right: `${right}px`,
      width: `${menuWidth}px`,
    }
  } else {
    // Doesn't fit either side — open on the roomier side and cap height
    const below = spaceBelow >= spaceAbove
    const space = Math.max(Math.floor(below ? spaceBelow : spaceAbove), 40)
    dropdownStyle.value = below
      ? { top: `${rect.bottom + 4}px`, right: `${right}px`, width: `${menuWidth}px`, maxHeight: `${space}px` }
      : { bottom: `${viewportHeight - rect.top + 4}px`, right: `${right}px`, width: `${menuWidth}px`, maxHeight: `${space}px` }
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
  if (searchTimer) clearTimeout(searchTimer)
  stopPreview()
})
</script>
