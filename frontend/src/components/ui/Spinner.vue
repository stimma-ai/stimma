<template>
  <!-- Determinate: the same ring, filled clockwise to `value`. -->
  <svg
    v-if="value != null"
    :class="[sizeClass, 'flex-shrink-0 -rotate-90']"
    viewBox="0 0 16 16"
    role="progressbar"
    aria-valuemin="0"
    aria-valuemax="100"
    :aria-valuenow="clamped"
  >
    <circle cx="8" cy="8" r="7" fill="none" stroke-width="2" class="stroke-edge" />
    <circle
      cx="8" cy="8" r="7" fill="none" stroke-width="2" stroke-linecap="round"
      :class="['transition-[stroke-dashoffset] duration-300 ease-out', stroke || 'stroke-accent']"
      :stroke-dasharray="CIRCUMFERENCE"
      :stroke-dashoffset="CIRCUMFERENCE * (1 - clamped / 100)"
      :visibility="clamped > 0 ? 'visible' : 'hidden'"
    />
  </svg>
  <div v-else :class="[sizeClass, 'border-2 border-edge rounded-full animate-spin flex-shrink-0', hue || 'border-t-accent']" />
</template>

<script setup lang="ts">
// Atelier Spinner — the one hand-rolled spinner treatment (DESIGN.md §2,
// §4: inline `<svg class="animate-spin">` and bespoke bordered-div spinners
// are a review rejection outside this component). `hue` lets a caller swap
// the leading-edge color for a status-specific spinner (e.g. purple for
// "enhancing") without duplicating the border/animation pattern — pass the
// full class (e.g. `border-t-purple-500`) so Tailwind's static scanner can
// see it; a bare color stem interpolated at runtime would be purged.
// `value` (0-100) makes it a determinate ring for work whose total is known;
// `stroke` is that ring's fill class (e.g. 'stroke-purple-500').
import { computed } from 'vue'

const CIRCUMFERENCE = 2 * Math.PI * 7

const props = withDefaults(defineProps<{
  size?: 'sm' | 'md' | 'lg'
  /** Full border-t-* class for the leading edge, e.g. 'border-t-purple-500'. Defaults to accent. */
  hue?: string
  /** 0-100: a determinate ring instead of a spinning one. */
  value?: number | null
  /** Full stroke-* class for the determinate fill. Defaults to accent. */
  stroke?: string
}>(), {
  size: 'md',
  hue: undefined,
  value: null,
  stroke: undefined,
})

const clamped = computed(() => Math.max(0, Math.min(100, props.value ?? 0)))

const sizeClass = computed(() => ({
  sm: 'w-3 h-3',
  md: 'w-4 h-4',
  lg: 'w-6 h-6',
}[props.size]))
</script>
