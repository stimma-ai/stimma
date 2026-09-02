<template>
  <!-- One grammar for every row, including the local one: check gutter,
       name, qualifier chips, optional right-hand fact. Nothing is optional on
       the LEFT, so no row is ever indented relative to its neighbours. -->
  <button
    class="w-full px-3 py-2 text-left text-xs transition-colors flex items-center gap-2 cursor-pointer"
    :class="rowClass"
    @click="$emit('select')"
  >
    <svg
      v-if="selected"
      class="w-3.5 h-3.5 text-accent-hi flex-shrink-0"
      fill="none"
      viewBox="0 0 24 24"
      stroke-width="2"
      stroke="currentColor"
    >
      <path stroke-linecap="round" stroke-linejoin="round" d="m4.5 12.75 6 6 9-13.5" />
    </svg>
    <span v-else class="w-3.5 h-3.5 flex-shrink-0" />

    <!-- Name and its qualifiers travel together, so the chips read as part of
         the name rather than as a second ragged column. The name gets the
         slack and truncates; the chips never do. -->
    <span class="flex items-center gap-1.5 min-w-0 flex-1">
      <span class="truncate min-w-0">{{ label }}</span>
      <!-- A debug or sandboxed install is a DIFFERENT LIBRARY on the same
           machine, so without these two rows can look identical. Bare mono
           chip = read-only fact, per the design language. -->
      <span
        v-for="tag in tags"
        :key="tag"
        class="flex-shrink-0 px-1 py-px rounded bg-overlay-subtle font-mono text-[10px] leading-tight text-content-muted"
        >{{ tag }}</span
      >
    </span>

    <span v-if="detail" class="text-[11px] text-content-muted flex-shrink-0 tabular-nums">{{
      detail
    }}</span>
  </button>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  label: { type: String, required: true },
  /** Right-hand fact. Only carried when it says something — e.g. "3 h ago". */
  detail: { type: String, default: '' },
  selected: { type: Boolean, default: false },
  /** Offered but not up. Still selectable: you may know the machine is awake. */
  muted: { type: Boolean, default: false },
  channel: { type: String, default: null },
  sandbox: { type: String, default: null },
})

/** Only non-default values earn a chip; a stock install shows none. */
const tags = computed(() => {
  const out = []
  if (props.channel && props.channel !== 'production') out.push(props.channel)
  if (props.sandbox && props.sandbox !== 'default') out.push(props.sandbox)
  return out
})

defineEmits(['select'])

const rowClass = computed(() => {
  if (props.selected) return 'bg-selection/15 text-content'
  if (props.muted) return 'text-content-muted hover:bg-overlay-subtle hover:text-content-secondary'
  return 'text-content-secondary hover:bg-overlay-subtle hover:text-content'
})
</script>
