<script setup lang="ts">
// Compact icon + label action. Ghost at rest (no fill), a tint on hover.
// Replaces stacked full-width outline buttons: a few of these sit in one row.
defineOptions({ inheritAttrs: false })

withDefaults(defineProps<{
  disabled?: boolean
}>(), {
  disabled: false,
})
</script>

<template>
  <button
    type="button"
    v-bind="$attrs"
    class="inline-flex h-8 min-w-0 items-center gap-1.5 whitespace-nowrap rounded-md border-none bg-transparent px-2.5 text-xs font-medium text-content-secondary transition-colors duration-150 hover:bg-overlay-subtle hover:text-content focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/60 disabled:cursor-not-allowed disabled:opacity-50"
    :disabled="disabled"
  >
    <slot name="icon" />
    <slot />
  </button>
</template>
