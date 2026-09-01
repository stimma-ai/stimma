<template>
  <div
    class="w-full px-3 py-2 text-left text-xs transition-colors flex items-center gap-2"
    :class="rowClass"
    @click="disabled ? null : $emit('select')"
  >
    <svg
      v-if="selected"
      class="w-4 h-4 text-accent-hi flex-shrink-0"
      fill="none"
      viewBox="0 0 24 24"
      stroke-width="2"
      stroke="currentColor"
    >
      <path stroke-linecap="round" stroke-linejoin="round" d="m4.5 12.75 6 6 9-13.5" />
    </svg>
    <span v-else class="w-4 h-4 flex-shrink-0" />

    <component :is="platformIcon" v-if="platformIcon" class="w-3.5 h-3.5 flex-shrink-0 text-content-muted" />

    <!-- The name gets the slack; the qualifier and route fact are fixed-width
         context and must never squeeze it into an ellipsis. -->
    <span class="truncate min-w-0 flex-1">{{ label }}</span>

    <!-- Only rendered when it is non-default. A debug or sandboxed install is
         a different library on the same machine, and without this two rows
         can look identical. -->
    <span
      v-if="qualifier"
      class="text-[11px] text-content-muted flex-shrink-0 font-mono"
    >{{ qualifier }}</span>

    <!-- Quiet route fact, never a badge: the route is context, not status. -->
    <span class="text-[11px] text-content-muted flex-shrink-0">{{ detail }}</span>
  </div>
</template>

<script setup>
import { computed, h } from 'vue'

const props = defineProps({
  label: { type: String, required: true },
  platform: { type: String, default: null },
  detail: { type: String, default: '' },
  selected: { type: Boolean, default: false },
  disabled: { type: Boolean, default: false },
  channel: { type: String, default: null },
  sandbox: { type: String, default: null },
})

/** "canary", "mdA", or "canary · mdA" — omitted entirely when both default. */
const qualifier = computed(() => {
  const parts = []
  if (props.channel && props.channel !== 'production') parts.push(props.channel)
  if (props.sandbox && props.sandbox !== 'default') parts.push(props.sandbox)
  return parts.join(' · ')
})

defineEmits(['select'])

const rowClass = computed(() => {
  if (props.disabled) return 'text-content-muted cursor-not-allowed opacity-60'
  if (props.selected) return 'bg-accent/10 text-content cursor-pointer'
  return 'text-content-secondary hover:bg-overlay-subtle hover:text-content cursor-pointer'
})

// Inline so the menu costs no extra icon imports; these are glyphs, not art.
const PLATFORM_PATHS = {
  darwin:
    'M12 20.94c1.5 0 2.75 1.06 4 1.06 3 0 6-8 6-12.22A4.91 4.91 0 0017 5c-2.22 0-4 1.44-5 2-1-.56-2.78-2-5-2a4.9 4.9 0 00-5 4.78C2 14 5 22 8 22c1.25 0 2.5-1.06 4-1.06z',
  win32: 'M3 5.5l7-1v7H3v-6zm0 13l7 1v-7H3v6zM11.5 4.2L21 3v9h-9.5V4.2zm0 15.6L21 21v-9h-9.5v7.8z',
  linux:
    'M12 2a4 4 0 00-4 4v3c0 1.5-2 3.5-2 6a6 6 0 0012 0c0-2.5-2-4.5-2-6V6a4 4 0 00-4-4z',
}

const platformIcon = computed(() => {
  const d = PLATFORM_PATHS[props.platform]
  if (!d) return null
  return () =>
    h(
      'svg',
      { fill: 'none', viewBox: '0 0 24 24', 'stroke-width': '1.5', stroke: 'currentColor' },
      [h('path', { 'stroke-linecap': 'round', 'stroke-linejoin': 'round', d })],
    )
})
</script>
