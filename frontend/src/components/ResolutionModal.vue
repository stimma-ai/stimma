<template>
  <div class="fixed inset-0 bg-black/50 flex items-center justify-center z-50" @click="$emit('close')">
    <div class="bg-surface border border-surface-raised rounded-lg p-6 w-auto min-w-[400px]" @click.stop>
      <!-- Header -->
      <div class="flex items-center justify-between mb-4">
        <h3 class="text-lg font-semibold text-content">Resolution</h3>
        <button @click="$emit('close')" class="text-content-muted hover:text-content">
          <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-5 h-5">
            <path stroke-linecap="round" stroke-linejoin="round" d="M6 18 18 6M6 6l12 12" />
          </svg>
        </button>
      </div>

      <!-- Mode Toggle -->
      <div class="flex items-center gap-2 mb-4">
        <button
          @click="mode = 'aspect'"
          :class="[
            'flex-1 px-3 py-2 rounded text-sm font-medium transition-colors',
            mode === 'aspect' ? 'bg-blue-500 text-white' : 'bg-surface-overlay text-content-tertiary hover:bg-surface-raised'
          ]"
        >
          Aspect Ratio
        </button>
        <button
          @click="mode = 'manual'"
          :class="[
            'flex-1 px-3 py-2 rounded text-sm font-medium transition-colors',
            mode === 'manual' ? 'bg-blue-500 text-white' : 'bg-surface-overlay text-content-tertiary hover:bg-surface-raised'
          ]"
        >
          Manual
        </button>
      </div>

      <!-- Aspect Ratio Mode -->
      <div v-if="mode === 'aspect'" class="space-y-4">
        <!-- Aspect Ratio and Size on one row -->
        <div class="flex items-center gap-3">
          <!-- Aspect Ratio Buttons -->
          <div class="flex gap-1">
            <button
              v-for="ar in aspectRatios"
              :key="ar.label"
              @click="selectedAspectRatio = ar.label"
              :class="[
                'px-2.5 py-1.5 rounded text-sm font-medium transition-colors',
                selectedAspectRatio === ar.label
                  ? 'bg-blue-500 text-white'
                  : 'bg-surface-overlay text-content-tertiary hover:bg-surface-raised border border-surface-raised'
              ]"
            >
              {{ ar.label }}
            </button>
          </div>

          <!-- Size display -->
          <span class="text-sm text-content-secondary whitespace-nowrap">{{ megapixels.toFixed(1) }}MP • {{ computedWidth }}×{{ computedHeight }}</span>
        </div>

        <!-- Megapixel Slider -->
        <div>
          <input v-no-autocorrect
            v-model.number="megapixels"
            type="range"
            min="0.5"
            max="4.0"
            step="0.1"
            class="w-full h-1 bg-surface-raised rounded-sm appearance-none cursor-pointer [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-4 [&::-webkit-slider-thumb]:h-4 [&::-webkit-slider-thumb]:bg-blue-500 [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:cursor-pointer"
          >
        </div>
      </div>

      <!-- Manual Mode -->
      <div v-else class="space-y-4">
        <div class="flex items-center gap-3">
          <div class="flex-1">
            <label class="block text-sm text-content-tertiary mb-2">Width</label>
            <input v-no-autocorrect
              v-model.number="manualWidth"
              type="number"
              step="64"
              min="256"
              max="2048"
              class="w-full px-3 py-2 bg-surface-overlay border border-surface-raised rounded text-content-secondary text-sm focus:outline-none focus:border-blue-500"
            >
          </div>
          <button
            @click="swapDimensions"
            class="mt-7 p-2 bg-surface-raised hover:bg-surface-hover rounded text-content-tertiary transition-colors"
            title="Swap width and height"
          >
            <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-5 h-5">
              <path stroke-linecap="round" stroke-linejoin="round" d="M7.5 21 3 16.5m0 0L7.5 12M3 16.5h13.5m0-13.5L21 7.5m0 0L16.5 12M21 7.5H7.5" />
            </svg>
          </button>
          <div class="flex-1">
            <label class="block text-sm text-content-tertiary mb-2">Height</label>
            <input v-no-autocorrect
              v-model.number="manualHeight"
              type="number"
              step="64"
              min="256"
              max="2048"
              class="w-full px-3 py-2 bg-surface-overlay border border-surface-raised rounded text-content-secondary text-sm focus:outline-none focus:border-blue-500"
            >
          </div>
        </div>
      </div>

      <!-- Actions -->
      <div class="flex items-center justify-end gap-2 mt-6">
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
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'

interface Props {
  width: number
  height: number
}

const props = defineProps<Props>()
const emit = defineEmits(['close', 'update'])

const mode = ref<'aspect' | 'manual'>('aspect')
const selectedAspectRatio = ref('1:1')
const megapixels = ref(1.0)
const manualWidth = ref(props.width)
const manualHeight = ref(props.height)

const aspectRatios = [
  { label: '9:16', ratio: 9/16 },
  { label: '3:4', ratio: 3/4 },
  { label: '1:1', ratio: 1 },
  { label: '4:3', ratio: 4/3 },
  { label: '16:9', ratio: 16/9 },
]

// Compute dimensions from aspect ratio and megapixels
const computedWidth = computed(() => {
  const ar = aspectRatios.find(a => a.label === selectedAspectRatio.value)
  if (!ar) return 1024

  const totalPixels = megapixels.value * 1000000
  const height = Math.sqrt(totalPixels / ar.ratio)
  const width = height * ar.ratio

  // Round to nearest 64
  return Math.round(width / 64) * 64
})

const computedHeight = computed(() => {
  const ar = aspectRatios.find(a => a.label === selectedAspectRatio.value)
  if (!ar) return 1024

  const totalPixels = megapixels.value * 1000000
  const height = Math.sqrt(totalPixels / ar.ratio)

  // Round to nearest 64
  return Math.round(height / 64) * 64
})

// Initialize from props
watch(() => [props.width, props.height], () => {
  manualWidth.value = props.width
  manualHeight.value = props.height

  // Detect aspect ratio
  const gcd = (a: number, b: number): number => b === 0 ? a : gcd(b, a % b)
  const divisor = gcd(props.width, props.height)
  const ratioW = props.width / divisor
  const ratioH = props.height / divisor
  const ratio = ratioW / ratioH

  const matchingAr = aspectRatios.find(ar => Math.abs(ar.ratio - ratio) < 0.01)
  if (matchingAr) {
    selectedAspectRatio.value = matchingAr.label
  }

  // Calculate megapixels
  megapixels.value = Number(((props.width * props.height) / 1000000).toFixed(1))
}, { immediate: true })

function swapDimensions() {
  const temp = manualWidth.value
  manualWidth.value = manualHeight.value
  manualHeight.value = temp
}

function apply() {
  if (mode.value === 'aspect') {
    emit('update', computedWidth.value, computedHeight.value)
  } else {
    emit('update', manualWidth.value, manualHeight.value)
  }
  emit('close')
}
</script>
