<template>
  <span
    :class="[
      'inline-block w-1.5 h-1.5 rounded-full flex-shrink-0',
      dotClass(bucket),
      pulse ? 'animate-pulse-soft' : '',
    ]"
  />
</template>

<script setup lang="ts">
// Atelier StatusDot — the one status-dot treatment (STANDARDS.md §1.9).
// Color always comes from statusColors.ts; never inline a status→color
// switch alongside this component. `pulse` is for live/actionable states
// (running, "your turn") and always uses the soft pulse recipe, never
// stock `animate-pulse`.
import { dotClass, type StatusBucket } from '../../utils/statusColors'

defineProps<{
  bucket: StatusBucket
  /** Live/actionable states only — uses animate-pulse-soft, never animate-pulse. */
  pulse?: boolean
}>()
</script>
