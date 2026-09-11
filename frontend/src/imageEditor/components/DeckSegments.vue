<script setup lang="ts" generic="T extends string">
/**
 * The phone deck's one segmented control (DESIGN.md §3.6a): a row of equal
 * cells, the chosen one underlined, no fills. It picks WHICH set of
 * parameters the grid beneath shows (Mixer's channel, Grading's range,
 * Detail's sub-group) or one of a few peer modes (a brush's tonal range, a
 * text preset, how the next selection gesture combines).
 */
import type { IconName } from '../ported/icons'
import ToolIcon from './ToolIcon.vue'

withDefaults(defineProps<{
  options: ReadonlyArray<{ id: T; label: string; icon?: IconName; modified?: boolean }>
  modelValue: T
  ariaLabel: string
  /** Selection contexts underline in the selection color, not the accent. */
  tone?: 'accent' | 'selection'
  disabled?: boolean
}>(), { tone: 'accent', disabled: false })
const emit = defineEmits<{ 'update:modelValue': [T] }>()
</script>

<template>
  <div class="flex" role="radiogroup" :aria-label="ariaLabel" data-deck-segments>
    <button
      v-for="option in options"
      :key="option.id"
      type="button"
      role="radio"
      class="relative flex-1 min-w-0 min-h-11 px-1 text-[13px] font-medium flex items-center justify-center gap-1.5 whitespace-nowrap"
      :class="[
        modelValue === option.id ? 'text-content' : 'text-content-secondary',
        disabled && 'opacity-50',
      ]"
      :aria-checked="modelValue === option.id"
      :disabled="disabled"
      @click="emit('update:modelValue', option.id)"
    >
      <ToolIcon v-if="option.icon" :name="option.icon" :size="15" />
      <span class="truncate">{{ option.label }}</span>
      <span
        v-if="option.modified && modelValue !== option.id"
        class="absolute top-2 right-1.5 w-1.5 h-1.5 rounded-full"
        :class="tone === 'selection' ? 'bg-selection' : 'bg-accent'"
        aria-hidden="true"
      />
      <span
        v-if="modelValue === option.id"
        class="absolute left-2 right-2 bottom-1 h-0.5 rounded-full"
        :class="tone === 'selection' ? 'bg-selection' : 'bg-accent'"
      />
    </button>
  </div>
</template>
