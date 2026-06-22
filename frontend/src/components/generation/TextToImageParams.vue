<template>
  <div class="space-y-4">
    <!-- LoRAs -->
    <div v-if="availableLoras.length > 0">
      <label class="block text-sm font-medium text-content-tertiary mb-2">LoRAs</label>
      <div class="space-y-2">
        <div
          v-for="(lora, index) in localParams.selectedLoras"
          :key="index"
          class="flex items-center gap-2 bg-surface rounded p-2"
        >
          <select
            v-model="lora.lora"
            class="flex-1 bg-base border border-edge rounded text-content text-xs px-2 py-1"
          >
            <option value="">Select LoRA...</option>
            <option v-for="l in availableLoras" :key="l.name" :value="l.name">
              {{ l.name }}
            </option>
          </select>
          <input v-no-autocorrect
            v-model.number="lora.weight"
            type="number"
            step="0.05"
            min="0"
            max="2"
            class="w-16 bg-base border border-edge rounded text-content text-xs px-2 py-1"
          >
          <button
            @click="removeLora(index)"
            class="text-content-muted hover:text-red-500"
          >
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-4 h-4">
              <path d="M6.28 5.22a.75.75 0 0 0-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 1 0 1.06 1.06L10 11.06l3.72 3.72a.75.75 0 1 0 1.06-1.06L11.06 10l3.72-3.72a.75.75 0 0 0-1.06-1.06L10 8.94 6.28 5.22Z" />
            </svg>
          </button>
        </div>
        <button
          @click="addLora"
          type="button"
          class="w-full py-2 text-sm text-content-muted hover:text-content-tertiary hover:bg-surface rounded transition-colors"
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
import { reactive, watch } from 'vue'
import AdvancedParams from './AdvancedParams.vue'

interface LoraSelection {
  lora: string
  weight: number
  enabled: boolean
}

interface TextToImageParameters {
  prompt: string
  negativePrompt: string
  width: number
  height: number
  cfg: number
  guidance: number
  steps: number
  sampler: string
  scheduler: string
  denoise: number
  shift: number
  seed: number | null
  randomizeSeed: boolean
  selectedLoras: LoraSelection[]
}

interface Folder {
  path: string
}

interface Props {
  modelValue: TextToImageParameters
  availableModels: any[]
  availableLoras: any[]
  parameterSchema?: any
  folders?: Folder[]
  selectedFolder?: string
}

const props = withDefaults(defineProps<Props>(), {
  parameterSchema: null,
  folders: () => [],
  selectedFolder: ''
})

const emit = defineEmits<{
  (e: 'update:modelValue', value: TextToImageParameters): void
  (e: 'update:selected-folder', value: string): void
}>()

// Local reactive copy of params
const localParams = reactive<TextToImageParameters>({
  prompt: '',
  negativePrompt: 'ugly, cartoon, 3d, video game, cg',
  width: 848,
  height: 1152,
  cfg: 3.5,
  guidance: 3.5,
  steps: 20,
  sampler: 'euler',
  scheduler: 'simple',
  denoise: 1.0,
  shift: 3.1,
  seed: null,
  randomizeSeed: true,
  selectedLoras: []
})

// Initialize from props
watch(() => props.modelValue, (newValue) => {
  if (newValue) {
    Object.assign(localParams, newValue)
  }
}, { immediate: true, deep: true })

// Emit changes
watch(localParams, (newValue) => {
  emit('update:modelValue', { ...newValue })
}, { deep: true })

function addLora() {
  localParams.selectedLoras.push({
    lora: '',
    weight: 1.0,
    enabled: true
  })
}

function removeLora(index: number) {
  localParams.selectedLoras.splice(index, 1)
}

function updateLocalParams(value: Partial<TextToImageParameters>) {
  Object.assign(localParams, value)
}
</script>
