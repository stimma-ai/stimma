<template>
  <div class="space-y-4 mb-6">
    <!-- Header -->
    <label class="text-xs font-semibold text-content-secondary">Expand canvas</label>

    <!-- Padding direction controls (2x2 grid) -->
    <div class="grid grid-cols-2 gap-4">
      <!-- Top -->
      <div>
        <div class="flex items-center justify-between mb-1">
          <label class="text-xs text-content-muted">Top</label>
          <span class="text-xs text-content-muted">{{ paddingTop }}%</span>
        </div>
        <input v-no-autocorrect
          type="range"
          v-model.number="paddingTop"
          :min="0"
          :max="100"
          :step="1"
          class="w-full h-2 bg-surface-raised rounded-lg appearance-none cursor-pointer slider"
        />
      </div>

      <!-- Bottom -->
      <div>
        <div class="flex items-center justify-between mb-1">
          <label class="text-xs text-content-muted">Bottom</label>
          <span class="text-xs text-content-muted">{{ paddingBottom }}%</span>
        </div>
        <input v-no-autocorrect
          type="range"
          v-model.number="paddingBottom"
          :min="0"
          :max="100"
          :step="1"
          class="w-full h-2 bg-surface-raised rounded-lg appearance-none cursor-pointer slider"
        />
      </div>

      <!-- Left -->
      <div>
        <div class="flex items-center justify-between mb-1">
          <label class="text-xs text-content-muted">Left</label>
          <span class="text-xs text-content-muted">{{ paddingLeft }}%</span>
        </div>
        <input v-no-autocorrect
          type="range"
          v-model.number="paddingLeft"
          :min="0"
          :max="100"
          :step="1"
          class="w-full h-2 bg-surface-raised rounded-lg appearance-none cursor-pointer slider"
        />
      </div>

      <!-- Right -->
      <div>
        <div class="flex items-center justify-between mb-1">
          <label class="text-xs text-content-muted">Right</label>
          <span class="text-xs text-content-muted">{{ paddingRight }}%</span>
        </div>
        <input v-no-autocorrect
          type="range"
          v-model.number="paddingRight"
          :min="0"
          :max="100"
          :step="1"
          class="w-full h-2 bg-surface-raised rounded-lg appearance-none cursor-pointer slider"
        />
      </div>
    </div>

    <!-- Output dimensions preview -->
    <div v-if="inputWidth && inputHeight && outputDimensions" class="pt-3 border-t border-edge-subtle flex items-center justify-center gap-3 text-sm">
      <span class="text-content-tertiary">{{ inputWidth }} × {{ inputHeight }}</span>
      <svg class="w-4 h-4 text-content-muted" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 7l5 5m0 0l-5 5m5-5H6" />
      </svg>
      <span class="text-blue-500 font-medium">{{ outputDimensions.width }} × {{ outputDimensions.height }}</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

interface OutpaintSettings {
  paddingTop: number
  paddingBottom: number
  paddingLeft: number
  paddingRight: number
}

interface Props {
  modelValue: OutpaintSettings
  inputWidth?: number | null
  inputHeight?: number | null
}

const props = withDefaults(defineProps<Props>(), {
  inputWidth: null,
  inputHeight: null
})

const emit = defineEmits<{
  (e: 'update:modelValue', value: OutpaintSettings): void
}>()

// Computed with v-model support
const paddingTop = computed({
  get: () => props.modelValue.paddingTop,
  set: (val) => emit('update:modelValue', { ...props.modelValue, paddingTop: val })
})

const paddingBottom = computed({
  get: () => props.modelValue.paddingBottom,
  set: (val) => emit('update:modelValue', { ...props.modelValue, paddingBottom: val })
})

const paddingLeft = computed({
  get: () => props.modelValue.paddingLeft,
  set: (val) => emit('update:modelValue', { ...props.modelValue, paddingLeft: val })
})

const paddingRight = computed({
  get: () => props.modelValue.paddingRight,
  set: (val) => emit('update:modelValue', { ...props.modelValue, paddingRight: val })
})

// Calculate output dimensions (always percentage-based)
const outputDimensions = computed(() => {
  if (!props.inputWidth || !props.inputHeight) return null

  const top = Math.round(props.inputHeight * (props.modelValue.paddingTop / 100))
  const bottom = Math.round(props.inputHeight * (props.modelValue.paddingBottom / 100))
  const left = Math.round(props.inputWidth * (props.modelValue.paddingLeft / 100))
  const right = Math.round(props.inputWidth * (props.modelValue.paddingRight / 100))

  return {
    width: props.inputWidth + left + right,
    height: props.inputHeight + top + bottom
  }
})
</script>

<style scoped>
/* Range slider styling */
.slider {
  background: transparent;
}

.slider::-webkit-slider-thumb {
  appearance: none;
  width: 16px;
  height: 16px;
  border-radius: 50%;
  @apply bg-blue-500;
  cursor: pointer;
  transition: background 0.2s;
  margin-top: -4px;
}

.slider::-webkit-slider-thumb:hover {
  @apply bg-blue-600;
}

.slider::-moz-range-thumb {
  width: 16px;
  height: 16px;
  border-radius: 50%;
  @apply bg-blue-500;
  cursor: pointer;
  border: none;
  transition: background 0.2s;
}

.slider::-moz-range-thumb:hover {
  @apply bg-blue-600;
}

.slider::-webkit-slider-runnable-track {
  background: var(--color-surface-raised);
  border-radius: 4px;
  height: 8px;
}

.slider::-moz-range-track {
  background: var(--color-surface-raised);
  border-radius: 4px;
  height: 8px;
}
</style>
