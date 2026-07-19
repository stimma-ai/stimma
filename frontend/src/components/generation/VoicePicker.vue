<template>
  <SettingsDropdown
    :model-value="modelValue"
    @update:model-value="emit('update:modelValue', $event)"
    :options="mergedOptions"
    :search-options="searchDropdownOptions"
    :disabled="disabled"
    placeholder="Select voice"
    hide-trigger-details
    quiet
  />
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import SettingsDropdown from '../ui/SettingsDropdown.vue'

interface VoiceOption {
  value: string
  label: string
  description?: string
  category?: string
  previewUrl?: string
}

const props = defineProps<{
  modelValue: string
  options?: VoiceOption[]
  searchOptions?: (query: string) => Promise<VoiceOption[]>
  disabled?: boolean
}>()

const emit = defineEmits<{
  (event: 'update:modelValue', value: string): void
}>()

const initialRemoteOptions = ref<VoiceOption[]>([])
let initialRequest: Promise<VoiceOption[]> | null = null

function toDropdownOption(option: VoiceOption) {
  return {
    value: option.value,
    label: option.label,
    description: option.description,
    meta: option.category,
    previewUrl: option.previewUrl,
  }
}

const mergedOptions = computed(() => {
  const seen = new Set<string>()
  return [...initialRemoteOptions.value, ...(props.options ?? [])]
    .filter((option) => {
      if (seen.has(option.value)) return false
      seen.add(option.value)
      return true
    })
    .map(toDropdownOption)
})

async function searchDropdownOptions(query: string) {
  if (!props.searchOptions) return []
  if (!query.trim()) return (await loadInitialOptions()).map(toDropdownOption)
  return (await props.searchOptions(query)).map(toDropdownOption)
}

async function loadInitialOptions() {
  if (!props.searchOptions) return []
  initialRequest ??= props.searchOptions('').catch(() => [])
  initialRemoteOptions.value = await initialRequest
  return initialRemoteOptions.value
}

onMounted(() => void loadInitialOptions())
</script>
