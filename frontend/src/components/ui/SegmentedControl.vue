<script setup lang="ts">
// One-of-N choice (DESIGN.md §1.8 selection law): teal is action and indigo
// is a selected row/tile/chip, so a segment is neither. The selected segment
// is a neutral raised fill with primary text; the rest sit on the faint track
// in secondary text. Tabs use this same control.
defineProps<{
  modelValue: string | number
  options: Array<{ label: string; value: string | number }>
  ariaLabel?: string
}>()

const emit = defineEmits<{ 'update:modelValue': [value: string | number] }>()
</script>

<template>
  <div class="inline-flex w-fit flex-wrap gap-0.5 rounded-md bg-overlay-faint p-0.5" role="radiogroup" :aria-label="ariaLabel">
    <button
      v-for="option in options"
      :key="option.value"
      type="button"
      role="radio"
      :aria-checked="modelValue === option.value"
      :class="[
        'rounded px-2.5 py-1 text-xs font-medium tabular-nums transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/60',
        modelValue === option.value
          ? 'bg-surface-raised text-content'
          : 'text-content-secondary hover:bg-overlay-subtle hover:text-content'
      ]"
      @click="emit('update:modelValue', option.value)"
    >
      {{ option.label }}
    </button>
  </div>
</template>
