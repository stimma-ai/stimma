<template>
  <div class="space-y-6">
    <!-- Reference Images (optional) -->
    <MediaPicker
      v-if="props.showImagePicker"
      v-model="localParams.inputImages"
      accept="image"
      :max-items="props.maxInputImages"
    />

    <!-- Prompt (optional) -->
    <div v-if="props.showPrompt">
      <label class="block text-sm font-medium mb-2 text-content-tertiary">Prompt</label>
      <AIPromptEditor
        v-model="localParams.prompt"
        :rows="8"
        :expanded="props.aiPromptExpanded"
        @update:expanded="emit('update:aiPromptExpanded', $event)"
        placeholder="Describe the edit you want to apply to the reference image(s)..."
      />
    </div>

    <!-- LoRA Selection -->
    <div v-if="availableLoras.length > 0" class="mb-6">
      <label class="block text-sm font-medium text-content-tertiary mb-3">LoRAs</label>
      <div class="space-y-2">
        <div
          v-for="(loraRow, index) in localParams.selected_loras"
          :key="index"
          class="group flex items-center gap-3 py-2 px-3 bg-surface-overlay rounded-lg hover:bg-surface transition-colors"
        >
          <!-- Enable/Disable Toggle -->
          <button
            @click="loraRow.enabled = !loraRow.enabled"
            type="button"
            :class="[
              'flex-shrink-0 w-8 h-4 rounded-full transition-colors relative',
              loraRow.enabled ? 'bg-blue-500' : 'bg-surface-hover'
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
          <div class="flex-1 relative min-w-0">
            <input v-no-autocorrect
              :ref="el => { if (el) loraInputRefs[index] = el }"
              v-model="loraRow.searchText"
              @input="onLoraSearch(index)"
              @focus="onLoraFocus(index)"
              @blur="onLoraBlur(index)"
              @keydown.down.prevent="navigateLoraResults(index, 1)"
              @keydown.up.prevent="navigateLoraResults(index, -1)"
              @keydown.enter.prevent="selectLoraResult(index)"
              @keydown.escape="closeLoraResults(index)"
              type="text"
              placeholder="Search LoRA..."
              :class="[
                'w-full bg-transparent text-sm focus:outline-none truncate',
                loraRow.enabled ? 'text-content-secondary' : 'text-content-muted'
              ]"
            />

            <!-- Autocomplete Dropdown -->
            <div
              v-if="loraRow.showResults && loraRow.filteredLoras && loraRow.filteredLoras.length > 0"
              class="absolute z-[9999] w-full mt-2 bg-surface border border-surface-raised rounded-lg shadow-xl max-h-60 overflow-y-auto"
            >
              <div
                v-for="(lora, loraIndex) in loraRow.filteredLoras"
                :key="lora.name"
                @mousedown.prevent="selectLora(index, lora.name)"
                :class="[
                  'px-3 py-2 text-sm cursor-pointer transition-colors',
                  loraIndex === loraRow.selectedIndex ? 'bg-blue-500 text-white' : 'text-content-secondary hover:bg-surface-raised'
                ]"
              >
                {{ lora.name }}
              </div>
            </div>
          </div>

          <!-- Weight -->
          <div class="flex items-center gap-1.5">
            <input v-no-autocorrect
              :value="formatWeight(loraRow.weight)"
              @input="updateWeight(index, ($event.target as HTMLInputElement).value)"
              @blur="formatWeightOnBlur(index)"
              type="text"
              :class="[
                'w-12 bg-transparent text-sm text-right focus:outline-none tabular-nums',
                loraRow.enabled ? 'text-content-secondary' : 'text-content-muted'
              ]"
            >
            <div class="flex flex-col gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity">
              <button
                @click="incrementWeight(index)"
                type="button"
                class="text-content-muted hover:text-content text-[10px] leading-none"
              >&#9650;</button>
              <button
                @click="decrementWeight(index)"
                type="button"
                class="text-content-muted hover:text-content text-[10px] leading-none"
              >&#9660;</button>
            </div>
          </div>

          <!-- Remove -->
          <button
            @click="removeLoraRow(index)"
            type="button"
            class="text-content-muted hover:text-red-500 transition-colors"
          >
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-4 h-4">
              <path d="M6.28 5.22a.75.75 0 0 0-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 1 0 1.06 1.06L10 11.06l3.72 3.72a.75.75 0 1 0 1.06-1.06L11.06 10l3.72-3.72a.75.75 0 0 0-1.06-1.06L10 8.94 6.28 5.22Z" />
            </svg>
          </button>
        </div>

        <button
          @click="addLoraRow"
          type="button"
          class="w-full py-2 text-sm text-content-muted hover:text-content-tertiary hover:bg-surface-overlay rounded-lg transition-colors"
        >
          + Add a LoRA
        </button>
      </div>
    </div>

    <!-- Advanced Parameters -->
    <AdvancedParams
      :model-value="localParams"
      :parameter-schema="parameterSchema"
      :folders="folders"
      :selected-folder="selectedFolder"
      @update:model-value="updateLocalParams"
      @update:selected-folder="$emit('update:selected-folder', $event)"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, watch } from 'vue'
import MediaPicker from './MediaPicker.vue'
import AdvancedParams from './AdvancedParams.vue'
import AIPromptEditor from './AIPromptEditor.vue'

interface ReferenceImage {
  path: string
  filename: string
}

interface ImageEditParameters {
  inputImages: ReferenceImage[]
  prompt: string
  negativePrompt: string
  megapixels: number
  cfg: number
  guidance: number
  steps: number
  denoise: number
  shift: number
  sampler: string
  scheduler: string
  seed: number | null
  randomizeSeed: boolean
  selected_loras?: LoraRow[]
}

interface LoraRow {
  lora: string  // The path/filename for the backend
  displayName?: string  // The display name for the UI (optional for backwards compat)
  weight: number
  enabled: boolean
  searchText: string
  showResults: boolean
  filteredLoras: any[]
  selectedIndex: number
}

interface Folder {
  path: string
}

interface Props {
  modelValue: ImageEditParameters
  maxInputImages?: number
  availableLoras?: any[]
  selectedFolder?: string
  folders?: Folder[]
  showImagePicker?: boolean
  showPrompt?: boolean
  parameterSchema?: any
  aiPromptExpanded?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  maxInputImages: 3,
  availableLoras: () => [],
  selectedFolder: '',
  folders: () => [],
  showImagePicker: true,
  showPrompt: true,
  parameterSchema: null,
  aiPromptExpanded: true
})

const emit = defineEmits<{
  (e: 'update:modelValue', value: ImageEditParameters): void
  (e: 'update:selected-folder', value: string): void
  (e: 'update:aiPromptExpanded', value: boolean): void
}>()

const loraInputRefs = ref<HTMLInputElement[]>([])

// Local reactive copy of params
const localParams = reactive<ImageEditParameters>({
  inputImages: [],
  prompt: '',
  negativePrompt: 'cartoon, anime, ugly',
  megapixels: 1.0,
  cfg: 4.0,
  guidance: 3.5,
  steps: 30,
  denoise: 1.0,
  shift: 3.0,
  sampler: 'euler',
  scheduler: 'simple',
  seed: null,
  randomizeSeed: true,
  selected_loras: []
})

// Track if we're syncing to avoid feedback loops
let isSyncing = false

// Initialize from props - only sync non-lora fields to avoid breaking autocomplete
watch(() => props.modelValue, (newValue, oldValue) => {
  if (newValue && !isSyncing) {
    // Sync all fields except selected_loras (to preserve autocomplete state)
    const { selected_loras, ...rest } = newValue
    Object.assign(localParams, rest)

    // Only sync loras on initial load or when the lora list itself changes meaningfully
    // (not just UI state like showResults/filteredLoras)
    const oldLoraKeys = (oldValue?.selected_loras || []).map((l: any) => `${l.lora}:${l.weight}:${l.enabled}`).join(',')
    const newLoraKeys = (selected_loras || []).map((l: any) => `${l.lora}:${l.weight}:${l.enabled}`).join(',')

    if (oldLoraKeys !== newLoraKeys) {
      // Handle selected_loras specially to restore searchText from displayName
      const lorasToRestore = selected_loras?.map((lora: any) => ({
        ...lora,
        // Restore searchText from displayName if available, otherwise use lora (path) as fallback
        searchText: lora.displayName || lora.searchText || lora.lora || '',
        showResults: false,
        filteredLoras: [],
        selectedIndex: 0
      }))
      localParams.selected_loras = lorasToRestore || []
    }
  }
}, { immediate: true, deep: true })

// Emit changes
watch(localParams, (newValue) => {
  isSyncing = true
  emit('update:modelValue', { ...newValue })
  // Reset sync flag after Vue has processed the update
  setTimeout(() => { isSyncing = false }, 0)
}, { deep: true })

// Generate random seed when randomize is enabled and seed is null
watch(() => localParams.randomizeSeed, (randomize) => {
  if (randomize && localParams.seed === null) {
    localParams.seed = Math.floor(Math.random() * 4294967296)
  }
})

// LoRA functions
function addLoraRow() {
  if (!localParams.selected_loras) {
    (localParams as any).selected_loras = []
  }
  (localParams as any).selected_loras.push({
    lora: '',
    weight: 1.0,
    enabled: true,
    searchText: '',
    showResults: false,
    filteredLoras: [],
    selectedIndex: 0
  })
}

function removeLoraRow(index: number) {
  if ((localParams as any).selected_loras) {
    (localParams as any).selected_loras.splice(index, 1)
  }
}

function updateLocalParams(value: Partial<ImageEditParameters>) {
  Object.assign(localParams, value)
}

function onLoraSearch(index: number) {
  const row = (localParams as any).selected_loras[index]
  if (!row) return

  const search = row.searchText.toLowerCase()
  row.filteredLoras = props.availableLoras.filter((l: any) =>
    l.name.toLowerCase().includes(search)
  ).slice(0, 10)
  row.showResults = row.filteredLoras.length > 0
  row.selectedIndex = 0
}

function onLoraFocus(index: number) {
  const row = (localParams as any).selected_loras[index]
  if (!row) return

  if (!row.searchText) {
    row.filteredLoras = props.availableLoras.slice(0, 10)
  }
  row.showResults = row.filteredLoras.length > 0
}

function onLoraBlur(index: number) {
  // Delay to allow click on dropdown
  setTimeout(() => {
    const row = (localParams as any).selected_loras[index]
    if (row) {
      row.showResults = false
    }
  }, 150)
}

function navigateLoraResults(index: number, direction: number) {
  const row = (localParams as any).selected_loras[index]
  if (!row || !row.filteredLoras.length) return

  row.selectedIndex = Math.max(0, Math.min(row.filteredLoras.length - 1, row.selectedIndex + direction))
}

function selectLoraResult(index: number) {
  const row = (localParams as any).selected_loras[index]
  if (!row || !row.filteredLoras.length) return

  const selected = row.filteredLoras[row.selectedIndex]
  if (selected) {
    selectLora(index, selected.name)
  }
}

function closeLoraResults(index: number) {
  const row = (localParams as any).selected_loras[index]
  if (row) {
    row.showResults = false
  }
}

function selectLora(index: number, loraName: string) {
  const row = (localParams as any).selected_loras[index]
  if (row) {
    // Find the lora object to get the path (filename)
    const loraObj = props.availableLoras.find((l: any) => l.name === loraName)
    // Store the path (filename) for the backend, display name for the UI
    row.lora = loraObj?.path || loraName
    row.displayName = loraName  // Save display name for localStorage persistence
    row.searchText = loraName
    row.showResults = false
  }
}

function formatWeight(weight: number): string {
  return weight.toFixed(2)
}

function updateWeight(index: number, value: string) {
  const row = (localParams as any).selected_loras[index]
  if (row) {
    const parsed = parseFloat(value)
    if (!isNaN(parsed)) {
      row.weight = Math.max(0, Math.min(2, parsed))
    }
  }
}

function formatWeightOnBlur(index: number) {
  // Ensure proper formatting on blur
  const row = (localParams as any).selected_loras[index]
  if (row && isNaN(row.weight)) {
    row.weight = 1.0
  }
}

function incrementWeight(index: number) {
  const row = (localParams as any).selected_loras[index]
  if (row) {
    row.weight = Math.min(2, row.weight + 0.05)
  }
}

function decrementWeight(index: number) {
  const row = (localParams as any).selected_loras[index]
  if (row) {
    row.weight = Math.max(0, row.weight - 0.05)
  }
}
</script>
