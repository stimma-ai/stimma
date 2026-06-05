<template>
  <div class="fixed inset-0 bg-black/50 flex items-center justify-center z-50" @click="$emit('close')">
    <div class="bg-surface border border-surface-raised rounded-lg p-6 w-[600px] max-h-[80vh] flex flex-col" @click.stop>
      <!-- Header -->
      <div class="flex items-center justify-between mb-4">
        <h3 class="text-lg font-semibold text-content">LoRAs</h3>
        <button @click="$emit('close')" class="text-content-muted hover:text-content">
          <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-5 h-5">
            <path stroke-linecap="round" stroke-linejoin="round" d="M6 18 18 6M6 6l12 12" />
          </svg>
        </button>
      </div>

      <!-- Search -->
      <div class="mb-4">
        <input v-no-autocorrect
          v-model="searchQuery"
          type="text"
          placeholder="Search LoRAs..."
          class="w-full px-3 py-2 bg-surface-overlay border border-surface-raised rounded text-content-secondary text-sm focus:outline-none focus:border-blue-500"
        >
      </div>

      <!-- LoRA List -->
      <div class="flex-1 overflow-y-auto space-y-2 mb-4">
        <div v-if="filteredLoras.length === 0" class="text-center text-content-muted py-8">
          No LoRAs found
        </div>

        <div
          v-for="lora in filteredLoras"
          :key="lora.name"
          class="p-3 bg-surface-overlay border border-surface-raised rounded hover:border-edge transition-colors"
        >
          <!-- Header Row -->
          <div class="flex items-center gap-3 mb-2">
            <input v-no-autocorrect
              type="checkbox"
              :checked="isSelected(lora.name)"
              @change="toggleLora(lora.name)"
              class="w-4 h-4 rounded"
            >
            <span class="flex-1 text-sm text-content-secondary">{{ lora.name }}</span>
          </div>

          <!-- Strength Controls (only if selected) -->
          <div v-if="isSelected(lora.name)" class="ml-7 space-y-2">
            <!-- Default Weight -->
            <div>
              <div class="flex items-center justify-between mb-1">
                <label class="text-xs text-content-tertiary">Default Strength</label>
                <span class="text-xs text-content-secondary">{{ getLoraConfig(lora.name).weight }}</span>
              </div>
              <input v-no-autocorrect
                :value="getLoraConfig(lora.name).weight"
                @input="updateWeight(lora.name, $event.target.value)"
                type="range"
                min="0"
                max="2"
                step="0.05"
                class="w-full h-1 bg-surface-raised rounded-sm appearance-none cursor-pointer [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-3 [&::-webkit-slider-thumb]:h-3 [&::-webkit-slider-thumb]:bg-blue-500 [&::-webkit-slider-thumb]:rounded-full"
              >
            </div>

            <!-- Min/Max Range (optional) -->
            <div class="flex items-center gap-2">
              <label class="flex items-center gap-1 text-xs text-content-tertiary">
                <input v-no-autocorrect
                  type="checkbox"
                  :checked="getLoraConfig(lora.name).hasRange"
                  @change="toggleRange(lora.name)"
                  class="w-3 h-3 rounded"
                >
                <span>Allow range</span>
              </label>
            </div>

            <div v-if="getLoraConfig(lora.name).hasRange" class="grid grid-cols-2 gap-2">
              <div>
                <label class="block text-xs text-content-tertiary mb-1">Min</label>
                <input v-no-autocorrect
                  :value="getLoraConfig(lora.name).min"
                  @input="updateMin(lora.name, $event.target.value)"
                  type="number"
                  step="0.05"
                  min="0"
                  max="2"
                  class="w-full px-2 py-1 bg-surface border border-surface-raised rounded text-content-secondary text-xs focus:outline-none focus:border-blue-500"
                >
              </div>
              <div>
                <label class="block text-xs text-content-tertiary mb-1">Max</label>
                <input v-no-autocorrect
                  :value="getLoraConfig(lora.name).max"
                  @input="updateMax(lora.name, $event.target.value)"
                  type="number"
                  step="0.05"
                  min="0"
                  max="2"
                  class="w-full px-2 py-1 bg-surface border border-surface-raised rounded text-content-secondary text-xs focus:outline-none focus:border-blue-500"
                >
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- Actions -->
      <div class="flex items-center justify-between pt-4 border-t border-surface-raised">
        <span class="text-sm text-content-muted">{{ selectedCount }} selected</span>
        <div class="flex items-center gap-2">
          <button
            @click="$emit('close')"
            class="px-4 py-2 bg-surface-raised hover:bg-surface-hover text-content-secondary rounded text-sm transition-colors"
          >
            Cancel
          </button>
          <button
            @click="apply"
            class="px-4 py-2 bg-blue-500 hover:bg-blue-600 text-white rounded text-sm transition-colors"
          >
            Apply
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'

interface LoraConfig {
  lora: string
  weight: number
  hasRange: boolean
  min?: number
  max?: number
}

interface Props {
  availableLoras: any[]
  selectedLoras: LoraConfig[]
}

const props = defineProps<Props>()
const emit = defineEmits(['close', 'update'])

const searchQuery = ref('')
const localSelection = ref<Map<string, LoraConfig>>(new Map())

// Initialize from props
props.selectedLoras?.forEach(lora => {
  localSelection.value.set(lora.lora, { ...lora })
})

const filteredLoras = computed(() => {
  if (!searchQuery.value) return props.availableLoras
  const query = searchQuery.value.toLowerCase()
  return props.availableLoras.filter(lora =>
    lora.name.toLowerCase().includes(query)
  )
})

const selectedCount = computed(() => localSelection.value.size)

function isSelected(loraName: string): boolean {
  return localSelection.value.has(loraName)
}

function getLoraConfig(loraName: string): LoraConfig {
  return localSelection.value.get(loraName) || {
    lora: loraName,
    weight: 1.0,
    hasRange: false,
    min: 0.5,
    max: 1.5
  }
}

function toggleLora(loraName: string) {
  if (localSelection.value.has(loraName)) {
    localSelection.value.delete(loraName)
  } else {
    localSelection.value.set(loraName, {
      lora: loraName,
      weight: 1.0,
      hasRange: false,
      min: 0.5,
      max: 1.5
    })
  }
}

function updateWeight(loraName: string, value: string) {
  const config = getLoraConfig(loraName)
  config.weight = parseFloat(value)
  localSelection.value.set(loraName, config)
}

function toggleRange(loraName: string) {
  const config = getLoraConfig(loraName)
  config.hasRange = !config.hasRange
  localSelection.value.set(loraName, config)
}

function updateMin(loraName: string, value: string) {
  const config = getLoraConfig(loraName)
  config.min = parseFloat(value)
  localSelection.value.set(loraName, config)
}

function updateMax(loraName: string, value: string) {
  const config = getLoraConfig(loraName)
  config.max = parseFloat(value)
  localSelection.value.set(loraName, config)
}

function apply() {
  const loras = Array.from(localSelection.value.values())
  emit('update', loras)
  emit('close')
}
</script>
