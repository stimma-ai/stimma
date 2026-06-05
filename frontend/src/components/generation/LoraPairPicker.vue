<template>
  <div class="mb-6" v-if="availablePairs.length > 0">
    <label class="block text-sm font-medium text-content-tertiary mb-2">Lightning LoRA Pair</label>
    <select
      :value="modelValue?.name || ''"
      @change="handleChange"
      class="w-full bg-surface-overlay border border-surface-raised rounded-lg px-3 py-2 text-content-secondary text-sm focus:outline-none focus:ring-1 focus:ring-blue-500 focus:border-blue-500"
    >
      <option value="">Use Default</option>
      <option v-for="pair in availablePairs" :key="pair.name" :value="pair.name">
        {{ pair.name }}{{ pair.description ? ` - ${pair.description}` : '' }}
      </option>
    </select>
    <p class="text-xs text-content-muted mt-1">Paired high/low noise LoRAs for Lightning mode</p>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

interface LoraPair {
  name: string
  description?: string
  high_noise_path: string
  low_noise_path: string
}

interface Props {
  modelValue: LoraPair | null
  availablePairs: LoraPair[]
}

const props = defineProps<Props>()

const emit = defineEmits<{
  (e: 'update:modelValue', value: LoraPair | null): void
}>()

// Alias for template
const availablePairs = computed(() => props.availablePairs)

function handleChange(event: Event) {
  const select = event.target as HTMLSelectElement
  const selectedName = select.value

  if (!selectedName) {
    emit('update:modelValue', null)
    return
  }

  const selectedPair = props.availablePairs.find(p => p.name === selectedName)
  if (selectedPair) {
    emit('update:modelValue', selectedPair)
  }
}
</script>
