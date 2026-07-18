<template>
  <div>
    <button
      @click="showAdvanced = !showAdvanced"
      type="button"
      class="flex items-center gap-2 text-xs font-semibold text-content-secondary hover:text-content-tertiary transition-colors"
    >
      <span :class="['transition-transform', showAdvanced ? 'rotate-90' : '']">&#9654;</span>
      Advanced
    </button>

    <div v-show="showAdvanced" class="space-y-4 mt-4">
      <!-- Prepend slot for task-specific settings that should appear first -->
      <slot name="prepend" />

      <!-- Negative Prompt -->
      <div v-if="hasParam('negative_prompt')">
        <label class="block text-xs font-medium mb-2 text-content-tertiary">Negative Prompt</label>
        <textarea v-no-autocorrect
          :value="getNegativePrompt()"
          @input="updateNegativePrompt(($event.target as HTMLTextAreaElement).value)"
          rows="2"
          placeholder="What to avoid..."
          class="w-full px-2 py-1.5 bg-base border border-edge rounded text-content text-sm resize-y focus:outline-none focus:border-accent font-sans"
        ></textarea>
      </div>

      <!-- Sampler & Scheduler Row -->
      <div class="grid grid-cols-2 gap-4" v-if="hasParam('sampler') || hasParam('scheduler')">
        <div v-if="hasParam('sampler')">
          <label class="block text-xs font-medium mb-2 text-content-tertiary">Sampler</label>
          <select
            :value="modelValue.sampler"
            @change="updateParam('sampler', ($event.target as HTMLSelectElement).value)"
            class="w-full px-2 py-1.5 bg-base border border-edge rounded text-content text-sm"
          >
            <option v-for="choice in getParamChoices('sampler')" :key="choice" :value="choice">
              {{ formatChoice(choice) }}
            </option>
          </select>
        </div>
        <div v-if="hasParam('scheduler')">
          <label class="block text-xs font-medium mb-2 text-content-tertiary">Scheduler</label>
          <select
            :value="modelValue.scheduler"
            @change="updateParam('scheduler', ($event.target as HTMLSelectElement).value)"
            class="w-full px-2 py-1.5 bg-base border border-edge rounded text-content text-sm"
          >
            <option v-for="choice in getParamChoices('scheduler')" :key="choice" :value="choice">
              {{ formatChoice(choice) }}
            </option>
          </select>
        </div>
      </div>

      <!-- Seed -->
      <div v-if="hasParam('seed')">
        <div class="flex items-center justify-between mb-2">
          <label class="text-xs font-medium text-content-tertiary">Seed</label>
          <label class="flex items-center gap-1.5 text-xs text-content-muted cursor-pointer">
            <input v-no-autocorrect
              :checked="getRandomizeSeed()"
              @change="updateRandomizeSeed(($event.target as HTMLInputElement).checked)"
              type="checkbox"
              class="w-3 h-3 rounded"
            >
            <span>Randomize</span>
          </label>
        </div>
        <input v-no-autocorrect
          :value="modelValue.seed"
          @input="updateParam('seed', parseIntOrNull(($event.target as HTMLInputElement).value))"
          type="number"
          :disabled="getRandomizeSeed()"
          class="w-full px-2 py-1.5 bg-base border border-edge rounded text-content text-sm disabled:opacity-50"
        >
      </div>

      <!-- Sliders in 2-column grid -->
      <div class="grid grid-cols-2 gap-4">
        <div v-for="param in sliderParams" :key="param.name">
          <div class="flex items-center justify-between mb-2">
            <label class="text-xs font-medium text-content-tertiary">{{ param.title }}</label>
            <span class="text-xs text-content-muted">{{ formatSliderValue(param.name, getParamValue(param.name)) }}</span>
          </div>
          <input v-no-autocorrect
            :value="getParamValue(param.name)"
            @input="updateParam(param.name, parseFloat(($event.target as HTMLInputElement).value))"
            type="range"
            :min="param.min"
            :max="param.max"
            :step="param.step"
            class="w-full h-1 bg-surface-raised rounded-sm appearance-none cursor-pointer [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-4 [&::-webkit-slider-thumb]:h-4 [&::-webkit-slider-thumb]:bg-blue-500 [&::-webkit-slider-thumb]:rounded-full"
          >
        </div>
      </div>

      <!-- Extra slot for task-specific settings -->
      <slot name="extra" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'

interface ParameterSchema {
  properties?: Record<string, {
    title?: string
    type?: string
    minimum?: number
    maximum?: number
    enum?: string[]
    default?: any
    'x-step'?: number
    'x-ui-group'?: string
    'x-ui-order'?: number
    'x-hidden'?: boolean
  }>
}

interface ModelFlags {
  supports_negative_prompt?: boolean
}

interface Props {
  modelValue: Record<string, any>
  parameterSchema?: ParameterSchema | null
  modelFlags?: ModelFlags | null
  expanded?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  parameterSchema: null,
  modelFlags: null,
  expanded: false
})

const emit = defineEmits<{
  (e: 'update:modelValue', value: Record<string, any>): void
  (e: 'update:randomize-seed', value: boolean): void
  (e: 'update:expanded', value: boolean): void
}>()

// Local showAdvanced synced with expanded prop
const showAdvanced = ref(props.expanded)

// Sync with prop changes
watch(() => props.expanded, (newValue) => {
  showAdvanced.value = newValue
})

// Emit changes to parent
watch(showAdvanced, (newValue) => {
  emit('update:expanded', newValue)
})

// Parameter name mapping from camelCase (frontend) to snake_case (backend)
const paramNameMap: Record<string, string> = {
  negativePrompt: 'negative_prompt',
  randomizeSeed: 'seed' // randomizeSeed uses seed param availability
}

function getBackendParamName(frontendName: string): string {
  return paramNameMap[frontendName] || frontendName
}

function hasParam(name: string): boolean {
  if (!props.parameterSchema?.properties) return true // Default to showing all if no schema
  const inSchema = name in props.parameterSchema.properties

  // Special handling for negative_prompt - can be overridden by model flag
  if (name === 'negative_prompt') {
    // If model explicitly sets the flag to true/false, use it
    // Note: null (from Python None) should be treated as "not set"
    const flag = props.modelFlags?.supports_negative_prompt
    if (flag === true || flag === false) {
      return flag && inSchema
    }
    // Default: show if in schema (for models without explicit flag)
    return inSchema
  }

  return inSchema
}

function getParamSpec(name: string) {
  return props.parameterSchema?.properties?.[name]
}

function getParamChoices(name: string): string[] {
  const spec = getParamSpec(name)
  return spec?.enum || []
}

function formatChoice(choice: string): string {
  return choice
}

function getParamValue(name: string): any {
  // Try both camelCase and snake_case versions, fall back to schema default
  const value = props.modelValue[name] ?? props.modelValue[snakeToCamel(name)]
  if (value !== undefined) return value
  // Fall back to schema default
  return getParamSpec(name)?.default
}

function snakeToCamel(str: string): string {
  return str.replace(/_([a-z])/g, (_, letter) => letter.toUpperCase())
}

function updateParam(name: string, value: any) {
  // Check which naming convention is being used and update accordingly
  const camelName = snakeToCamel(name)
  const keyToUse = name in props.modelValue ? name : camelName
  emit('update:modelValue', { ...props.modelValue, [keyToUse]: value })
}

// Negative prompt helpers - handle both negativePrompt and negative_prompt
function getNegativePrompt(): string {
  return props.modelValue.negativePrompt ?? props.modelValue.negative_prompt ?? ''
}

function updateNegativePrompt(value: string) {
  // Check which naming convention is being used
  if ('negativePrompt' in props.modelValue) {
    emit('update:modelValue', { ...props.modelValue, negativePrompt: value })
  } else {
    emit('update:modelValue', { ...props.modelValue, negative_prompt: value })
  }
}

// RandomizeSeed helpers - handle both randomizeSeed prop and external randomize
function getRandomizeSeed(): boolean {
  return props.modelValue.randomizeSeed ?? false
}

function updateRandomizeSeed(value: boolean) {
  emit('update:modelValue', { ...props.modelValue, randomizeSeed: value })
  emit('update:randomize-seed', value)
}

function parseIntOrNull(value: string): number | null {
  const parsed = parseInt(value, 10)
  return isNaN(parsed) ? null : parsed
}

function formatSliderValue(name: string, value: number): string {
  const spec = getParamSpec(name)
  // Use schema default if value is undefined
  const displayValue = value ?? spec?.default
  if (displayValue === undefined || displayValue === null) return ''
  const step = spec?.['x-step'] || 1
  if (step < 1) {
    // Determine decimal places from step
    const decimals = step.toString().split('.')[1]?.length || 1
    return displayValue.toFixed(decimals)
  }
  return String(displayValue)
}

// Compute which parameters should be shown as sliders
const sliderParams = computed(() => {
  const sliders: Array<{
    name: string
    title: string
    min: number
    max: number
    step: number
  }> = []

  // Define slider parameters in order with fallback defaults
  const sliderDefs = [
    { name: 'cfg', title: 'CFG Scale', defaultMin: 1, defaultMax: 20, defaultStep: 0.1 },
    { name: 'guidance', title: 'Guidance', defaultMin: 1, defaultMax: 10, defaultStep: 0.1 },
    { name: 'steps', title: 'Steps', defaultMin: 1, defaultMax: 100, defaultStep: 1 },
    { name: 'denoise', title: 'Denoise', defaultMin: 0, defaultMax: 1, defaultStep: 0.05 },
    { name: 'shift', title: 'Shift', defaultMin: 0, defaultMax: 10, defaultStep: 0.1 },
    { name: 'temperature', title: 'Temperature', defaultMin: 0, defaultMax: 2, defaultStep: 0.1 },
  ]

  for (const def of sliderDefs) {
    if (hasParam(def.name)) {
      const spec = getParamSpec(def.name)
      sliders.push({
        name: def.name,
        title: def.title,
        min: spec?.minimum ?? def.defaultMin,
        max: spec?.maximum ?? def.defaultMax,
        step: spec?.['x-step'] ?? def.defaultStep,
      })
    }
  }

  return sliders
})
</script>
