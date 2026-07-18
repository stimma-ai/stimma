<template>
  <div class="relative" ref="containerRef">
    <button
      type="button"
      @click="toggleDropdown"
      :disabled="disabled"
      class="w-full px-3 py-2 bg-surface border border-surface-raised rounded-md text-content-secondary text-sm focus:outline-none focus:border-accent disabled:opacity-50 text-left flex items-center justify-between"
    >
      <span v-if="selectedModel" class="truncate">
        <span class="text-content-muted">{{ selectedGenerator }} /</span> {{ selectedModel }}
      </span>
      <span v-else class="text-content-muted">Select model...</span>
      <svg class="w-4 h-4 text-content-muted flex-shrink-0 ml-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7" />
      </svg>
    </button>

    <!-- Dropdown -->
    <div
      v-if="isOpen"
      class="absolute z-menu mt-1 bg-surface border border-surface-raised rounded-md shadow-lg max-h-80 overflow-y-auto min-w-[280px] w-max"
    >
      <template v-for="generator in filteredGenerators" :key="generator.name">
        <!-- Generator Header -->
        <div class="px-3 py-2 text-xs font-semibold text-content-muted bg-surface/50 sticky top-0">
          {{ generator.name }}
        </div>
        <!-- Models -->
        <button
          v-for="model in generator.models"
          :key="`${generator.name}-${model.name}`"
          @click="selectModel(generator.name, model.name)"
          :class="[
            'w-full px-3 py-2 pl-6 text-left text-sm transition-colors flex items-center justify-between gap-2',
            isSelected(generator.name, model.name)
              ? 'bg-accent-selection/15 text-accent-selection'
              : 'text-content hover:bg-surface-raised/50'
          ]"
        >
          <span class="truncate">{{ model.name }}</span>
          <span v-if="model.family" class="text-[10px] px-1.5 py-0.5 rounded bg-surface-raised/50 text-content-tertiary font-mono uppercase flex-shrink-0">
            {{ model.family }}
          </span>
        </button>
      </template>

      <div v-if="filteredGenerators.length === 0" class="px-3 py-4 text-center text-content-muted text-sm">
        No models available
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'

interface Model {
  name: string
  family?: string
  parameters?: any
  max_input_images?: number
}

interface Generator {
  name: string
  models?: Model[]
  loras?: any[]
}

interface Props {
  generators: Generator[]
  selectedGenerator: string
  selectedModel: string
  disabled?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  disabled: false
})

const emit = defineEmits<{
  (e: 'update:selectedGenerator', value: string): void
  (e: 'update:selectedModel', value: string): void
  (e: 'change', generator: string, model: string): void
}>()

const containerRef = ref<HTMLElement | null>(null)
const isOpen = ref(false)

// Filter generators to only show those with models
const filteredGenerators = computed(() => {
  return props.generators.filter(g => g.models && g.models.length > 0)
})

function toggleDropdown() {
  if (!props.disabled) {
    isOpen.value = !isOpen.value
  }
}

function isSelected(generator: string, model: string): boolean {
  return props.selectedGenerator === generator && props.selectedModel === model
}

function selectModel(generator: string, model: string) {
  emit('update:selectedGenerator', generator)
  emit('update:selectedModel', model)
  emit('change', generator, model)
  isOpen.value = false
}

// Close dropdown when clicking outside
function handleClickOutside(event: MouseEvent) {
  if (containerRef.value && !containerRef.value.contains(event.target as Node)) {
    isOpen.value = false
  }
}

onMounted(() => {
  document.addEventListener('click', handleClickOutside)
})

onUnmounted(() => {
  document.removeEventListener('click', handleClickOutside)
})
</script>
