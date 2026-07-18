<template>
  <div :class="[sizeClass, 'border-2 border-edge rounded-full animate-spin flex-shrink-0', hue || 'border-t-accent']" />
</template>

<script setup lang="ts">
// Atelier Spinner — the one hand-rolled spinner treatment (STANDARDS.md §2,
// §4: inline `<svg class="animate-spin">` and bespoke bordered-div spinners
// are a review rejection outside this component). `hue` lets a caller swap
// the leading-edge color for a status-specific spinner (e.g. purple for
// "enhancing") without duplicating the border/animation recipe — pass the
// full class (e.g. `border-t-purple-500`) so Tailwind's static scanner can
// see it; a bare color stem interpolated at runtime would be purged.
import { computed } from 'vue'

const props = withDefaults(defineProps<{
  size?: 'sm' | 'md' | 'lg'
  /** Full border-t-* class for the leading edge, e.g. 'border-t-purple-500'. Defaults to accent. */
  hue?: string
}>(), {
  size: 'md',
  hue: undefined,
})

const sizeClass = computed(() => ({
  sm: 'w-3 h-3',
  md: 'w-4 h-4',
  lg: 'w-6 h-6',
}[props.size]))
</script>
