<script setup lang="ts">
// The one Select trigger (DESIGN.md §2). Fill-only (§1.4), the label, then the
// one caret. It draws the trigger only: the menu or sheet it opens stays with
// the caller, which owns `open`. `active` marks a filter that is narrowing the
// list (accent tint, as a set filter reads everywhere else). Coarse pointers
// get a 44px target.
import Caret from './Caret.vue'

defineOptions({ inheritAttrs: false })
withDefaults(defineProps<{
  label: string
  open?: boolean
  active?: boolean
  disabled?: boolean
  /** Hide the caret where the row is tight and an icon says enough (compact filters). */
  caret?: boolean
}>(), { open: false, active: false, disabled: false, caret: true })
</script>

<template>
  <button
    type="button"
    v-bind="$attrs"
    :disabled="disabled"
    aria-haspopup="listbox"
    :aria-expanded="open"
    class="inline-flex min-w-0 items-center gap-2 rounded-md px-3 py-1.5 text-sm transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 ring-accent/60 disabled:opacity-50 disabled:cursor-not-allowed coarse:min-h-11"
    :class="active ? 'bg-accent/15 text-accent-hi' : 'bg-field text-content-secondary hover:bg-overlay-hover hover:text-content'"
  >
    <slot name="icon" />
    <span class="min-w-0 truncate">{{ label }}</span>
    <Caret v-if="caret" :open="open" />
  </button>
</template>
