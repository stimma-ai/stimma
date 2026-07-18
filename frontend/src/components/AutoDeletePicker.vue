<template>
  <div class="relative">
    <button
      ref="buttonRef"
      @click="toggleDropdown"
      :class="buttonClasses"
      :title="modelValue === 'never' ? 'Auto-delete disabled' : `Auto-delete after ${modelValue}`"
    >
      <!-- Trash icon -->
      <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" :class="size === 'small' ? 'w-3.5 h-3.5' : 'w-5 h-5'">
        <path stroke-linecap="round" stroke-linejoin="round" d="m14.74 9-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 0 1-2.244 2.077H8.084a2.25 2.25 0 0 1-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 0 0-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 0 1 3.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 0 0-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 0 0-7.5 0" />
      </svg>
      <!-- Show duration when not "never" -->
      <span v-if="modelValue !== 'never'">
        {{ modelValue }}
      </span>
    </button>

    <!-- Dropdown menu -->
    <div
      v-if="showDropdown"
      class="absolute right-0 mt-2 w-48 bg-surface border border-surface-raised rounded-lg shadow-lg z-menu py-1"
      @click.stop
    >
      <div class="px-3 py-2 text-xs text-content-muted border-b border-surface-raised">
        Auto-delete after
      </div>
      <button
        v-for="option in options"
        :key="option.value"
        @click="selectOption(option.value)"
        :class="[
          'w-full px-3 py-2 text-left text-sm transition-colors flex items-center justify-between',
          modelValue === option.value
            ? 'bg-blue-500/20 text-blue-500'
            : 'text-content-secondary hover:bg-surface-raised'
        ]"
      >
        <span>{{ option.label }}</span>
        <svg v-if="modelValue === option.value" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor" class="w-4 h-4">
          <path stroke-linecap="round" stroke-linejoin="round" d="m4.5 12.75 6 6 9-13.5" />
        </svg>
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'

interface Props {
  modelValue: string
  size?: 'small' | 'normal'
}

const props = withDefaults(defineProps<Props>(), {
  size: 'normal'
})

const buttonClasses = computed(() => {
  const base = 'cursor-pointer transition-colors flex items-center justify-center gap-1.5'
  const sizeClasses = props.size === 'small'
    ? 'px-2.5 h-7 rounded text-xs font-medium'
    : 'px-3 py-2 rounded-lg text-sm font-semibold'
  const colorClasses = props.modelValue !== 'never'
    ? 'bg-blue-500/20 text-blue-500'
    : props.size === 'small'
      ? 'text-content-tertiary hover:text-content hover:bg-surface'
      : 'bg-surface-raised hover:bg-surface-hover text-content'
  return `${base} ${sizeClasses} ${colorClasses}`
})
const emit = defineEmits<{
  (e: 'update:modelValue', value: string): void
}>()

const showDropdown = ref(false)
const buttonRef = ref<HTMLElement | null>(null)

const options = [
  { label: 'Never', value: 'never' },
  { label: '1 minute', value: '1m' },
  { label: '5 minutes', value: '5m' },
  { label: '30 minutes', value: '30m' },
  { label: '1 hour', value: '1h' },
  { label: '2 hours', value: '2h' },
  { label: '4 hours', value: '4h' },
  { label: '6 hours', value: '6h' },
  { label: '8 hours', value: '8h' },
  { label: '12 hours', value: '12h' },
  { label: '24 hours', value: '24h' },
  { label: '3 days', value: '3d' },
  { label: '7 days', value: '7d' },
  { label: '30 days', value: '30d' },
  { label: '90 days', value: '90d' },
]

function toggleDropdown() {
  showDropdown.value = !showDropdown.value
}

function selectOption(value: string) {
  emit('update:modelValue', value)
  showDropdown.value = false
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
