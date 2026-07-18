<template>
  <div :class="compact ? '' : 'bg-surface rounded-lg p-4'">
    <div :class="['flex items-center justify-between', compact ? 'mb-2' : 'mb-4']">
      <span :class="compact ? 'text-xs font-medium text-content-tertiary' : 'text-sm font-medium text-content-secondary'">
        {{ headerLabel }}
      </span>
      <!-- Only show mode switcher if both modes are supported -->
      <div v-if="supportScaleFactor && supportResolution" :class="compact ? 'flex gap-1 bg-surface rounded p-0.5' : 'flex gap-2'">
        <button
          @click="resolutionMode = 'relative'"
          :class="compact
            ? ['px-3 py-1 text-xs font-medium rounded transition-colors', resolutionMode === 'relative' ? 'bg-surface-hover text-content' : 'text-content-tertiary hover:text-content']
            : ['px-3 py-1.5 text-xs font-medium rounded transition-colors', resolutionMode === 'relative' ? 'bg-blue-500/20 text-blue-500' : 'bg-overlay-subtle text-content-tertiary hover:text-content-secondary']"
        >
          Scale Factor
        </button>
        <button
          @click="resolutionMode = 'pixels'"
          :class="compact
            ? ['px-3 py-1 text-xs font-medium rounded transition-colors', resolutionMode === 'pixels' ? 'bg-surface-hover text-content' : 'text-content-tertiary hover:text-content']
            : ['px-3 py-1.5 text-xs font-medium rounded transition-colors', resolutionMode === 'pixels' ? 'bg-blue-500/20 text-blue-500' : 'bg-overlay-subtle text-content-tertiary hover:text-content-secondary']"
        >
          Short Edge (px)
        </button>
      </div>
    </div>

    <!-- Relative Mode (Scale Factor) -->
    <div v-if="showScaleFactorUI" :class="compact ? 'space-y-2' : 'space-y-3'">
      <div class="flex gap-2 flex-wrap mb-2">
        <button
          v-for="scale in scalePresets"
          :key="scale"
          @click="scaleFactor = scale"
          :class="compact
            ? ['px-2 py-0.5 text-xs rounded transition-colors', scaleFactor === scale ? 'bg-accent text-white' : 'bg-surface-raised text-content-secondary hover:bg-surface-hover']
            : ['px-3 py-1.5 text-sm font-medium rounded transition-colors', scaleFactor === scale ? 'bg-accent text-white' : 'bg-overlay-subtle text-content-secondary hover:bg-overlay-light']"
        >
          {{ scale }}x
        </button>
      </div>
      <div :class="compact ? 'flex items-center gap-2' : 'flex items-center gap-3'">
        <input v-no-autocorrect
          type="range"
          v-model.number="scaleFactor"
          :min="0.5"
          :max="4"
          :step="0.1"
          :class="compact
            ? 'flex-1 h-1 bg-surface-raised rounded-sm appearance-none cursor-pointer [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-4 [&::-webkit-slider-thumb]:h-4 [&::-webkit-slider-thumb]:bg-blue-500 [&::-webkit-slider-thumb]:rounded-full'
            : 'flex-1 h-2 bg-surface-raised rounded-lg appearance-none cursor-pointer slider'"
        />
        <template v-if="compact">
          <span class="text-xs text-content-tertiary w-8 text-right">{{ scaleFactor }}x</span>
        </template>
        <template v-else>
          <input v-no-autocorrect
            type="number"
            v-model.number="scaleFactor"
            :min="0.5"
            :max="4"
            :step="0.1"
            class="w-16 px-2 py-1 text-sm bg-surface-raised border border-edge-subtle rounded text-content text-center"
          />
          <span class="text-xs text-content-tertiary">x</span>
        </template>
      </div>
    </div>

    <!-- Pixels Mode (Short Edge) -->
    <div v-if="showResolutionUI" :class="compact ? 'space-y-2' : 'space-y-3'">
      <div class="flex gap-2 flex-wrap mb-2">
        <button
          v-for="preset in pixelPresets"
          :key="preset.value"
          @click="targetResolution = preset.value"
          :class="compact
            ? ['px-2 py-0.5 text-xs rounded transition-colors', targetResolution === preset.value ? 'bg-accent text-white' : 'bg-surface-raised text-content-secondary hover:bg-surface-hover']
            : ['px-3 py-1.5 text-sm font-medium rounded transition-colors', targetResolution === preset.value ? 'bg-accent text-white' : 'bg-overlay-subtle text-content-secondary hover:bg-overlay-light']"
        >
          {{ preset.label }}
        </button>
      </div>
      <div :class="compact ? 'flex items-center gap-2' : 'flex items-center gap-3'">
        <input v-no-autocorrect
          type="range"
          v-model.number="targetResolution"
          :min="480"
          :max="4320"
          :step="1"
          :class="compact
            ? 'flex-1 h-1 bg-surface-raised rounded-sm appearance-none cursor-pointer [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-4 [&::-webkit-slider-thumb]:h-4 [&::-webkit-slider-thumb]:bg-blue-500 [&::-webkit-slider-thumb]:rounded-full'
            : 'flex-1 h-2 bg-surface-raised rounded-lg appearance-none cursor-pointer slider'"
        />
        <template v-if="compact">
          <span class="text-xs text-content-tertiary w-12 text-right">{{ targetResolution }}px</span>
        </template>
        <template v-else>
          <input v-no-autocorrect
            type="number"
            v-model.number="targetResolution"
            :min="480"
            :max="4320"
            class="w-20 px-2 py-1 text-sm bg-surface-raised border border-edge-subtle rounded text-content text-center"
          />
          <span class="text-xs text-content-tertiary">px</span>
        </template>
      </div>
      <div :class="compact ? 'text-xs text-content-muted' : 'text-xs text-content-muted'">
        Target resolution applies to the shortest edge; aspect ratio is preserved.
      </div>
    </div>

    <!-- Resolution Preview (at bottom) - only shown when input dimensions available -->
    <div v-if="inputWidth && inputHeight && outputDimensions" class="mt-4 pt-3 border-t border-edge-subtle flex items-center justify-center gap-3 text-sm">
      <span class="text-content-tertiary">{{ inputWidth }} × {{ inputHeight }}</span>
      <svg class="w-4 h-4 text-content-muted" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 7l5 5m0 0l-5 5m5-5H6" />
      </svg>
      <span class="text-blue-500 font-medium">{{ outputDimensions.width }} × {{ outputDimensions.height }}</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, watch } from 'vue'

const props = withDefaults(defineProps<{
  modelValue: {
    resolutionMode: 'relative' | 'pixels'
    scaleFactor: number
    targetResolution: number
  }
  inputWidth?: number | null
  inputHeight?: number | null
  compact?: boolean
  /** Whether the tool supports scale_factor param */
  supportScaleFactor?: boolean
  /** Whether the tool supports resolution param */
  supportResolution?: boolean
}>(), {
  compact: false,
  supportScaleFactor: true,
  supportResolution: true,
})

const emit = defineEmits<{
  (e: 'update:modelValue', value: typeof props.modelValue): void
}>()

// Header label adapts to supported modes
const headerLabel = computed(() => {
  if (props.supportScaleFactor && !props.supportResolution) {
    return 'Scale Factor'
  }
  if (props.supportResolution && !props.supportScaleFactor) {
    return 'Target Resolution'
  }
  return 'Target Resolution'
})

// Which UI to show based on mode and support
const showScaleFactorUI = computed(() => {
  if (!props.supportScaleFactor) return false
  if (props.supportScaleFactor && !props.supportResolution) return true
  return resolutionMode.value === 'relative'
})

const showResolutionUI = computed(() => {
  if (!props.supportResolution) return false
  if (props.supportResolution && !props.supportScaleFactor) return true
  return resolutionMode.value === 'pixels'
})

// Presets
const scalePresets = [0.5, 1, 1.5, 2, 3, 4]
const pixelPresets = [
  { label: '720p', value: 720 },
  { label: '1080p', value: 1080 },
  { label: '1440p', value: 1440 },
  { label: '2160p (4K)', value: 2160 },
  { label: '4320p (8K)', value: 4320 }
]

// Computed with v-model support
const resolutionMode = computed({
  get: () => {
    // If only one mode is supported, always use that mode
    if (props.supportScaleFactor && !props.supportResolution) return 'relative'
    if (props.supportResolution && !props.supportScaleFactor) return 'pixels'
    return props.modelValue.resolutionMode
  },
  set: (val) => emit('update:modelValue', { ...props.modelValue, resolutionMode: val })
})

const scaleFactor = computed({
  get: () => props.modelValue.scaleFactor,
  set: (val) => emit('update:modelValue', { ...props.modelValue, scaleFactor: val })
})

const targetResolution = computed({
  get: () => props.modelValue.targetResolution,
  set: (val) => emit('update:modelValue', { ...props.modelValue, targetResolution: val })
})

// Ensure mode is set correctly on mount when only one mode is supported
watch(() => [props.supportScaleFactor, props.supportResolution], ([sf, res]) => {
  if (sf && !res && props.modelValue.resolutionMode !== 'relative') {
    emit('update:modelValue', { ...props.modelValue, resolutionMode: 'relative' })
  } else if (res && !sf && props.modelValue.resolutionMode !== 'pixels') {
    emit('update:modelValue', { ...props.modelValue, resolutionMode: 'pixels' })
  }
}, { immediate: true })

// Calculate output dimensions for display
const outputDimensions = computed(() => {
  if (!props.inputWidth || !props.inputHeight) return null

  if (resolutionMode.value === 'relative') {
    // Scale both dimensions by the same factor
    return {
      width: Math.round(props.inputWidth * props.modelValue.scaleFactor),
      height: Math.round(props.inputHeight * props.modelValue.scaleFactor)
    }
  } else {
    // Pixels mode: target resolution applies to SHORT edge, maintain aspect ratio
    const shortEdge = Math.min(props.inputWidth, props.inputHeight)
    const scale = props.modelValue.targetResolution / shortEdge
    return {
      width: Math.round(props.inputWidth * scale),
      height: Math.round(props.inputHeight * scale)
    }
  }
})
</script>

<style scoped>
/* Range slider styling for non-compact mode */
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
