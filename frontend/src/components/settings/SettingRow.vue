<script setup lang="ts">
// The settings row grammar (STANDARDS.md §3.2): label + optional one-line
// description on the left, exactly ONE control on the right. Hairline
// between rows, no row boxes, no zebra.
defineProps<{
  label: string
  description?: string
}>()
</script>

<template>
  <div class="flex items-center justify-between gap-4 py-2.5 border-b border-edge-subtle last:border-b-0">
    <span class="min-w-0">
      <span class="block text-[13px] text-content"><slot name="label">{{ label }}</slot></span>
      <span v-if="description || $slots.description" class="block text-[11.5px] text-content-tertiary mt-0.5">
        <slot name="description">{{ description }}</slot>
      </span>
    </span>
    <span class="flex items-center gap-2 flex-shrink-0">
      <slot />
    </span>
  </div>
</template>
