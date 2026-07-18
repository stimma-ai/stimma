<template>
  <div class="mb-6">
    <div class="flex items-center justify-between mb-3">
      <span class="text-xs font-semibold text-content-secondary">LoRAs</span>
      <button
        @click="$emit('refresh-loras')"
        :disabled="isRefreshing"
        type="button"
        class="text-sm text-content-muted hover:text-content disabled:opacity-50 flex items-center gap-1.5 transition-colors duration-150"
        title="Refresh LoRA list from ComfyUI"
      >
        <Spinner v-if="isRefreshing" size="sm" />
        <svg
          v-else
          xmlns="http://www.w3.org/2000/svg"
          viewBox="0 0 20 20"
          fill="currentColor"
          class="w-4 h-4"
        >
          <path fill-rule="evenodd" d="M15.312 11.424a5.5 5.5 0 01-9.201 2.466l-.312-.311h2.433a.75.75 0 000-1.5H3.989a.75.75 0 00-.75.75v4.242a.75.75 0 001.5 0v-2.43l.31.31a7 7 0 0011.712-3.138.75.75 0 00-1.449-.39zm1.23-3.723a.75.75 0 00.219-.53V2.929a.75.75 0 00-1.5 0V5.36l-.31-.31A7 7 0 003.239 8.188a.75.75 0 101.448.389A5.5 5.5 0 0113.89 6.11l.311.31h-2.432a.75.75 0 000 1.5h4.243a.75.75 0 00.53-.219z" clip-rule="evenodd" />
        </svg>
        <span class="hidden sm:inline">Refresh</span>
      </button>
    </div>
    <div class="space-y-2">
      <div
        v-for="(loraRow, index) in modelValue"
        :key="index"
        class="group flex items-center gap-3 py-2.5 border-b border-edge-subtle last:border-0 hover:bg-overlay-subtle transition-colors duration-150"
      >
        <!-- Enable/Disable Toggle -->
        <button
          @click="toggleEnabled(index)"
          type="button"
          :class="[
            'flex-shrink-0 w-8 h-4 rounded-full transition-colors relative',
            loraRow.enabled ? 'bg-accent' : 'bg-overlay-subtle'
          ]"
        >
          <span
            :class="[
              'absolute top-0.5 w-3 h-3 bg-white rounded-full transition-transform shadow-sm',
              loraRow.enabled ? 'left-4' : 'left-0.5'
            ]"
          ></span>
        </button>

        <!-- LoRA Name/Search -->
        <div class="flex-1 relative min-w-0" ref="containerRefs">
          <input v-no-autocorrect
            :ref="el => setInputRef(index, el)"
            :value="getDisplayValue(index)"
            @input="onInput(index, ($event.target as HTMLInputElement).value)"
            @focus="onFocus(index)"
            @blur="onBlur(index)"
            @keydown="onKeydown(index, $event)"
            type="text"
            placeholder="Search LoRA..."
            :class="[
              'w-full bg-transparent text-sm focus:outline-none truncate',
              loraRow.enabled ? 'text-content-secondary' : 'text-content-muted'
            ]"
          />

          <!-- Autocomplete Dropdown -->
          <Teleport to="body">
            <div
              v-if="activeDropdown === index && filteredLoras.length > 0"
              ref="dropdownRef"
              :style="dropdownStyle"
              class="fixed z-menu bg-surface border border-edge-subtle rounded-lg shadow-lg py-1 max-h-60 overflow-y-auto"
            >
              <div
                v-for="(lora, loraIndex) in filteredLoras"
                :key="lora.path"
                :ref="el => setOptionRef(loraIndex, el)"
                @mousedown.prevent="selectLora(index, lora)"
                @mouseenter="selectedIndex = loraIndex"
                :class="[
                  'px-3 py-2 text-xs cursor-pointer transition-colors duration-150',
                  loraIndex === selectedIndex ? 'bg-accent-selection/15 text-content' : 'text-content-secondary hover:bg-overlay-subtle'
                ]"
              >
                {{ lora.name }}
              </div>
            </div>
          </Teleport>
        </div>

        <!-- Weight -->
        <div class="flex items-center gap-1.5">
          <input v-no-autocorrect
            :value="formatWeight(loraRow.weight)"
            @input="updateWeight(index, ($event.target as HTMLInputElement).value)"
            @blur="formatWeightOnBlur(index)"
            type="text"
            :class="[
              'w-12 bg-transparent text-sm font-mono tabular-nums text-right focus:outline-none',
              loraRow.weight !== 1 ? 'text-accent' : (loraRow.enabled ? 'text-content-secondary' : 'text-content-muted')
            ]"
          >
          <div class="flex flex-col gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity">
            <button
              @click="incrementWeight(index)"
              type="button"
              class="text-content-muted hover:text-content text-[10px] leading-none"
            >▲</button>
            <button
              @click="decrementWeight(index)"
              type="button"
              class="text-content-muted hover:text-content text-[10px] leading-none"
            >▼</button>
          </div>
        </div>

        <!-- Remove -->
        <button
          @click="removeLoraRow(index)"
          type="button"
          class="text-content-muted opacity-0 group-hover:opacity-100 hover:text-red-400 transition-colors duration-150"
        >
          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-4 h-4">
            <path d="M6.28 5.22a.75.75 0 0 0-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 1 0 1.06 1.06L10 11.06l3.72 3.72a.75.75 0 1 0 1.06-1.06L11.06 10l3.72-3.72a.75.75 0 0 0-1.06-1.06L10 8.94 6.28 5.22Z" />
          </svg>
        </button>
      </div>

      <button
        v-if="availableLoras.length > 0"
        @click="addLoraRow"
        type="button"
        class="w-full py-2 text-sm text-content-secondary hover:text-content hover:bg-overlay-subtle rounded-md transition-colors duration-150"
      >
        + Add a LoRA
      </button>
      <div
        v-else
        class="w-full py-2 text-sm text-content-muted text-center"
      >
        No LoRAs available
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, nextTick, watch, onMounted, onUnmounted } from 'vue'
import Spinner from '../ui/Spinner.vue'

export interface LoraOption {
  name: string
  path: string
}

export interface LoraRow {
  lora: string  // path for backend
  weight: number
  enabled: boolean
  searchText: string  // display name for UI
  showResults: boolean
  filteredLoras: LoraOption[]
  selectedIndex: number
}

interface Props {
  modelValue: LoraRow[]
  availableLoras: LoraOption[]
  isRefreshing?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  isRefreshing: false
})

const emit = defineEmits<{
  (e: 'update:modelValue', value: LoraRow[]): void
  (e: 'refresh-loras'): void
}>()

// Local UI state - not part of the model
const activeDropdown = ref<number | null>(null)
const searchQuery = ref('')
const selectedIndex = ref(0)
const dropdownRef = ref<HTMLElement | null>(null)
const dropdownStyle = ref<Record<string, string>>({})

const inputRefs = ref<Record<number, HTMLInputElement | null>>({})
const optionRefs = ref<Record<number, HTMLElement | null>>({})

function setInputRef(index: number, el: any) {
  if (el) {
    inputRefs.value[index] = el as HTMLInputElement
  }
}

function setOptionRef(index: number, el: any) {
  if (el) {
    optionRefs.value[index] = el as HTMLElement
  }
}

// Unicode normalization for search (also removes spaces)
function normalizeString(str: string): string {
  return str.normalize('NFD').replace(/[\u0300-\u036f]/g, '').replace(/\s+/g, '').toLowerCase()
}

// Filtered loras based on current search
const filteredLoras = computed(() => {
  const query = normalizeString(searchQuery.value)
  if (!query) {
    return props.availableLoras
  }
  return props.availableLoras.filter(lora =>
    normalizeString(lora.name).includes(query)
  )
})

// What to display in the input
function getDisplayValue(index: number): string {
  // If this row is being edited, show the search query
  if (activeDropdown.value === index) {
    return searchQuery.value
  }
  // Otherwise show the selected lora name
  return props.modelValue[index].searchText || ''
}

function updateRow(index: number, updates: Partial<LoraRow>) {
  const newValue = [...props.modelValue]
  newValue[index] = { ...newValue[index], ...updates }
  emit('update:modelValue', newValue)
}

function toggleEnabled(index: number) {
  updateRow(index, { enabled: !props.modelValue[index].enabled })
}

async function addLoraRow() {
  const newRow: LoraRow = {
    lora: '',
    weight: 1.0,
    enabled: true,
    searchText: '',
    showResults: false,
    filteredLoras: [],
    selectedIndex: 0
  }
  emit('update:modelValue', [...props.modelValue, newRow])

  // Focus the newly added input after DOM updates
  const newIndex = props.modelValue.length
  await nextTick()
  const inputElement = inputRefs.value[newIndex]
  if (inputElement) {
    inputElement.focus()
  }
}

function removeLoraRow(index: number) {
  if (activeDropdown.value === index) {
    closeDropdown()
  }
  const newValue = props.modelValue.filter((_, i) => i !== index)
  emit('update:modelValue', newValue)
}

function onInput(index: number, value: string) {
  searchQuery.value = value
  selectedIndex.value = 0
  if (activeDropdown.value !== index) {
    openDropdown(index)
  }
}

function onFocus(index: number) {
  // Initialize search with current value
  searchQuery.value = props.modelValue[index].searchText || ''
  selectedIndex.value = 0
  openDropdown(index)
}

function onBlur(index: number) {
  // Small delay to allow click on dropdown items
  setTimeout(() => {
    if (activeDropdown.value === index) {
      closeDropdown()
    }
  }, 150)
}

function onKeydown(index: number, event: KeyboardEvent) {
  if (activeDropdown.value !== index) return

  switch (event.key) {
    case 'ArrowDown':
      event.preventDefault()
      selectedIndex.value = Math.min(selectedIndex.value + 1, filteredLoras.value.length - 1)
      scrollSelectedIntoView()
      break
    case 'ArrowUp':
      event.preventDefault()
      selectedIndex.value = Math.max(selectedIndex.value - 1, 0)
      scrollSelectedIntoView()
      break
    case 'Enter':
      event.preventDefault()
      if (filteredLoras.value.length > 0 && selectedIndex.value >= 0) {
        selectLora(index, filteredLoras.value[selectedIndex.value])
      }
      break
    case 'Escape':
      event.preventDefault()
      closeDropdown()
      // Restore original value
      const input = inputRefs.value[index]
      if (input) {
        input.blur()
      }
      break
    case 'Tab':
      // Allow tab to work normally but close dropdown
      closeDropdown()
      break
  }
}

function scrollSelectedIntoView() {
  nextTick(() => {
    const optionEl = optionRefs.value[selectedIndex.value]
    if (optionEl) {
      optionEl.scrollIntoView({ block: 'nearest' })
    }
  })
}

function openDropdown(index: number) {
  activeDropdown.value = index
  updateDropdownPosition(index)
}

function closeDropdown() {
  activeDropdown.value = null
  searchQuery.value = ''
  selectedIndex.value = 0
}

function updateDropdownPosition(index: number) {
  nextTick(() => {
    const input = inputRefs.value[index]
    if (!input) return

    const rect = input.getBoundingClientRect()
    const viewportHeight = window.innerHeight
    const spaceBelow = viewportHeight - rect.bottom
    const spaceAbove = rect.top
    const dropdownMaxHeight = 240 // max-h-60 = 15rem = 240px

    // Position below by default, above if not enough space
    if (spaceBelow >= dropdownMaxHeight || spaceBelow >= spaceAbove) {
      dropdownStyle.value = {
        top: `${rect.bottom + 4}px`,
        left: `${rect.left}px`,
        width: `${rect.width}px`,
        maxHeight: `${Math.min(spaceBelow - 8, dropdownMaxHeight)}px`
      }
    } else {
      dropdownStyle.value = {
        bottom: `${viewportHeight - rect.top + 4}px`,
        left: `${rect.left}px`,
        width: `${rect.width}px`,
        maxHeight: `${Math.min(spaceAbove - 8, dropdownMaxHeight)}px`
      }
    }
  })
}

function selectLora(index: number, lora: LoraOption) {
  updateRow(index, {
    lora: lora.path,
    searchText: lora.name
  })
  closeDropdown()
  // Blur the input to finalize selection
  const input = inputRefs.value[index]
  if (input) {
    input.blur()
  }
}

function formatWeight(weight: number): string {
  const num = parseFloat(String(weight)) || 0
  const formatted = num.toFixed(2)
  return formatted.replace(/(\.\d)0$/, '$1')
}

function updateWeight(index: number, value: string) {
  const num = parseFloat(value)
  if (!isNaN(num)) {
    updateRow(index, { weight: Math.max(0, Math.min(10, num)) })
  }
}

function formatWeightOnBlur(index: number) {
  const loraRow = props.modelValue[index]
  const num = parseFloat(String(loraRow.weight))
  if (isNaN(num)) {
    updateRow(index, { weight: 1.0 })
  } else {
    updateRow(index, { weight: Math.max(0, Math.min(10, parseFloat(num.toFixed(2)))) })
  }
}

function incrementWeight(index: number) {
  const loraRow = props.modelValue[index]
  const newWeight = parseFloat((loraRow.weight + 0.05).toFixed(2))
  updateRow(index, { weight: Math.min(10, newWeight) })
}

function decrementWeight(index: number) {
  const loraRow = props.modelValue[index]
  const newWeight = parseFloat((loraRow.weight - 0.05).toFixed(2))
  updateRow(index, { weight: Math.max(0, newWeight) })
}

// Handle window resize to reposition dropdown
function handleResize() {
  if (activeDropdown.value !== null) {
    updateDropdownPosition(activeDropdown.value)
  }
}

// Handle scroll to reposition dropdown
function handleScroll() {
  if (activeDropdown.value !== null) {
    updateDropdownPosition(activeDropdown.value)
  }
}

onMounted(() => {
  window.addEventListener('resize', handleResize)
  window.addEventListener('scroll', handleScroll, true)
})

onUnmounted(() => {
  window.removeEventListener('resize', handleResize)
  window.removeEventListener('scroll', handleScroll, true)
})

// Watch for changes to filtered results to reset selection if needed
watch(filteredLoras, (newFiltered) => {
  if (selectedIndex.value >= newFiltered.length) {
    selectedIndex.value = Math.max(0, newFiltered.length - 1)
  }
})
</script>

<style scoped>
/* Autocomplete scrollbar styling */
.max-h-60::-webkit-scrollbar {
  -webkit-appearance: none;
  width: 8px;
}

.max-h-60::-webkit-scrollbar-track {
  background: transparent;
}

.max-h-60::-webkit-scrollbar-thumb {
  background: var(--color-scrollbar-thumb);
  border-radius: 4px;
}

.max-h-60::-webkit-scrollbar-thumb:hover {
  background: var(--color-scrollbar-thumb-hover);
}
</style>
