<script setup lang="ts">
import type { Component } from 'vue'
// One-of-N choice (DESIGN.md §1.8 selection law): teal is action and indigo
// is a selected row/tile/chip, so a segment is neither. The selected segment
// is a neutral raised fill with primary text; the rest sit on the faint track
// in secondary text. Tabs use this same control.
defineProps<{
  modelValue: string | number
  options: Array<{ label: string; value: string | number; icon?: Component }>
  ariaLabel?: string
}>()

const emit = defineEmits<{ 'update:modelValue': [value: string | number] }>()
</script>

<template>
  <div class="inline-flex w-fit flex-wrap gap-0.5 rounded-md bg-overlay-subtle p-0.5" role="radiogroup" :aria-label="ariaLabel">
    <button
      v-for="option in options"
      :key="option.value"
      type="button"
      role="radio"
      :aria-checked="modelValue === option.value"
      :class="[
        'inline-flex items-center gap-1.5 rounded px-2.5 py-1 text-xs font-medium tabular-nums transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/60',
        modelValue === option.value
          ? 'bg-overlay-medium text-content'
          : 'text-content-secondary hover:bg-overlay-subtle hover:text-content'
      ]"
      @click="emit('update:modelValue', option.value)"
    >
      <component :is="option.icon" v-if="option.icon" class="h-icon-inline w-icon-inline flex-shrink-0" />
      {{ option.label }}
    </button>
  </div>
</template>
