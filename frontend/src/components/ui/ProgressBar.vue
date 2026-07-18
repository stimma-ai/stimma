<template>
  <div class="h-1 rounded-full bg-overlay-subtle overflow-hidden">
    <div
      v-if="indeterminate"
      class="h-full w-full rounded-full animate-shimmer bg-gradient-to-r from-transparent via-accent/40 to-transparent bg-[length:300%_100%]"
    />
    <div
      v-else
      :class="['h-full rounded-full transition-all duration-300 ease-out', fillClass]"
      :style="{ width: `${clampedValue}%` }"
    />
  </div>
</template>

<script setup lang="ts">
// Atelier ProgressBar — the one progress-bar treatment (STANDARDS.md §2).
// Determinate fill takes a 0-100 `value`; `indeterminate` swaps to the
// shimmer recipe (PipelineProgressBar.vue's travelling-sheen pattern) for
// "working, position unknown" states. `hue` overrides the fill color for
// status-specific bars (e.g. amber for a warning/paused run) — pass the
// full class so Tailwind's static scanner can see it.
import { computed } from 'vue'

const props = withDefaults(defineProps<{
  /** 0-100. Ignored when `indeterminate` is set. */
  value?: number
  indeterminate?: boolean
  /** Full bg-* class for the determinate fill, e.g. 'bg-amber-500'. Defaults to bg-blue-500. */
  hue?: string
}>(), {
  value: 0,
  indeterminate: false,
  hue: undefined,
})

const clampedValue = computed(() => Math.max(0, Math.min(100, props.value)))
const fillClass = computed(() => props.hue || 'bg-blue-500')
</script>
