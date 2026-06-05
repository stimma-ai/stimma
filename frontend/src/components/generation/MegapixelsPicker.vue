<template>
  <div class="relative">
    <button
      ref="buttonRef"
      @click="toggleDropdown"
      :disabled="disabled"
      class="flex items-center gap-2 px-3 py-2 bg-surface border border-surface-raised rounded-md text-content-secondary text-sm hover:bg-surface-raised transition-colors whitespace-nowrap disabled:opacity-50 disabled:cursor-not-allowed"
    >
      <span>{{ megapixels.toFixed(1) }}MP</span>
      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-4 h-4 text-content-muted">
        <path fill-rule="evenodd" d="M5.22 8.22a.75.75 0 0 1 1.06 0L10 11.94l3.72-3.72a.75.75 0 1 1 1.06 1.06l-4.25 4.25a.75.75 0 0 1-1.06 0L5.22 9.28a.75.75 0 0 1 0-1.06Z" clip-rule="evenodd" />
      </svg>
    </button>

    <!-- Dropdown Menu -->
    <div
      v-if="showDropdown"
      class="fixed bg-surface border border-surface-raised rounded-lg shadow-lg z-[9999] p-3 space-y-3"
      :style="dropdownStyle"
      @click.stop
    >
      <!-- Megapixels presets -->
      <div class="flex gap-1 flex-wrap">
        <button
          v-for="preset in megapixelPresets"
          :key="preset"
          @click="selectMegapixels(preset)"
          :class="[
            'px-2 py-1 rounded text-xs font-medium transition-colors',
            Math.abs(megapixels - preset) < 0.05
              ? 'bg-blue-500 text-white'
              : 'bg-surface-overlay text-content-tertiary hover:bg-surface-raised'
          ]"
        >
          {{ preset }}MP
        </button>
      </div>

      <!-- Megapixels slider -->
      <div class="flex items-center gap-2">
        <input v-no-autocorrect
          v-model.number="megapixels"
          @input="updateMegapixels"
          type="range"
          :min="minMegapixels"
          :max="maxMegapixels"
          step="0.1"
          class="flex-1 h-1 bg-surface-raised rounded-sm appearance-none cursor-pointer [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-3 [&::-webkit-slider-thumb]:h-3 [&::-webkit-slider-thumb]:bg-blue-500 [&::-webkit-slider-thumb]:rounded-full"
        >
        <span class="text-xs text-content-muted whitespace-nowrap w-12 text-right">{{ megapixels.toFixed(1) }}MP</span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch, onMounted, onUnmounted } from 'vue'

interface Props {
  modelValue?: number
  disabled?: boolean
  minMegapixels?: number
  maxMegapixels?: number
}

const props = withDefaults(defineProps<Props>(), {
  modelValue: 1.0,
  disabled: false,
  minMegapixels: 0.3,
  maxMegapixels: 4.0
})

const emit = defineEmits<{
  (e: 'update:modelValue', value: number): void
}>()

const showDropdown = ref(false)
const buttonRef = ref<HTMLElement | null>(null)
const dropdownStyle = ref({})
const megapixels = ref(props.modelValue ?? 1.0)

const megapixelPresets = [0.5, 1.0, 1.5, 2.0, 3.0, 4.0]

// Sync with prop changes
watch(() => props.modelValue, (newVal) => {
  megapixels.value = newVal ?? 1.0
})

function toggleDropdown() {
  if (props.disabled) return

  if (!showDropdown.value && buttonRef.value) {
    const rect = buttonRef.value.getBoundingClientRect()
    const dropdownWidth = 240
    const viewportWidth = window.innerWidth
    const padding = 16

    let left = rect.left
    if (left + dropdownWidth > viewportWidth - padding) {
      left = Math.max(padding, rect.right - dropdownWidth)
    }

    dropdownStyle.value = {
      top: `${rect.bottom + 4}px`,
      left: `${left}px`
    }
  }
  showDropdown.value = !showDropdown.value
}

function selectMegapixels(value: number) {
  megapixels.value = value
  emit('update:modelValue', value)
}

function updateMegapixels() {
  emit('update:modelValue', megapixels.value)
}

// Close dropdown when clicking outside
function handleClickOutside(event: MouseEvent) {
  const target = event.target as Element
  if (showDropdown.value && buttonRef.value && !buttonRef.value.contains(target)) {
    showDropdown.value = false
  }
}

onMounted(() => {
  document.addEventListener('click', handleClickOutside)
})

onUnmounted(() => {
  document.removeEventListener('click', handleClickOutside)
})
</script>
