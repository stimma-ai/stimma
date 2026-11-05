<script setup lang="ts">
// The one caret glyph (DESIGN.md §1.10): an outline chevron-down at the inline
// size. Select triggers, disclosure rows and pickers all use it; it flips when
// `open`.
import { ChevronDownIcon } from '@heroicons/vue/24/outline'

defineProps<{ open?: boolean }>()
</script>

<template>
  <ChevronDownIcon class="h-icon-inline w-icon-inline flex-none transition-transform duration-150" :class="open ? 'rotate-180' : ''" aria-hidden="true" />
</template>
