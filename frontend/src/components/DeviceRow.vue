<template>
  <!-- One grammar for every row, including the local one: a presence-badged
       icon, name + qualifier chips over a status line, and a right-hand slot
       that holds the check (selected) or the remove control (stale rows, on
       hover). Nothing is optional on the LEFT, so no row is ever indented
       relative to its neighbours. A div, not a button: the remove control is
       itself a button and buttons do not nest. -->
  <div
    class="group w-full px-3 py-1.5 text-left text-xs transition-colors flex items-center gap-2.5 cursor-pointer"
    :class="rowClass"
    role="menuitem"
    tabindex="0"
    @click="$emit('select')"
    @keydown.enter.prevent="$emit('select')"
  >
    <span class="relative w-[17px] h-[17px] flex-shrink-0">
      <svg class="w-[17px] h-[17px]" fill="none" viewBox="0 0 24 24" stroke-width="1.6" stroke="currentColor">
        <path stroke-linecap="round" stroke-linejoin="round" d="M9 17.25v1.007a3 3 0 0 1-.879 2.122L7.5 21h9l-.621-.621A3 3 0 0 1 15 18.257V17.25m6-12V15a2.25 2.25 0 0 1-2.25 2.25H5.25A2.25 2.25 0 0 1 3 15V5.25m18 0A2.25 2.25 0 0 0 18.75 3H5.25A2.25 2.25 0 0 0 3 5.25" />
      </svg>
      <!-- Presence rides the icon's corner, ringed in surface so it reads as
           a badge rather than part of the glyph. Status colours only: blue
           is never an interactive accent. -->
      <span
        class="absolute -right-0.5 -bottom-px w-[7px] h-[7px] rounded-full ring-2 ring-surface"
        :class="badgeClass"
      />
    </span>

    <span class="flex flex-col min-w-0 flex-1 gap-px">
      <!-- Name and its qualifiers travel together, so the chips read as part
           of the name rather than as a second ragged column. The name gets
           the slack and truncates; the chips never do. -->
      <span class="flex items-center gap-1.5 min-w-0">
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
      <span v-if="detail" class="text-[10.5px] text-content-muted truncate tabular-nums">{{ detail }}</span>
    </span>

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
    <!-- Housekeeping for stale rows only: removing an online server is undone
         by its next heartbeat, and trust is the account, so this was never a
         revoke. Trash, not X — the app's delete glyph. -->
    <button
      v-else-if="removable"
      class="-mr-1.5 w-6 h-6 flex items-center justify-center rounded flex-shrink-0 text-content-muted opacity-0 group-hover:opacity-100 focus-visible:opacity-100 hover:text-content hover:bg-overlay-hover transition-colors cursor-pointer bg-transparent border-none"
      title="Remove from list"
      @click.stop="$emit('remove')"
    >
      <svg class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke-width="1.6" stroke="currentColor">
        <path stroke-linecap="round" stroke-linejoin="round" d="m14.74 9-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 0 1-2.244 2.077H8.084a2.25 2.25 0 0 1-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 0 0-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 0 1 3.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 0 0-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 0 0-7.5 0" />
      </svg>
    </button>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  label: { type: String, required: true },
  /** Status line under the name: "Online", "Last seen 3 h ago", the hostname. */
  detail: { type: String, default: '' },
  selected: { type: Boolean, default: false },
  /** Offered but not up. Still selectable: you may know the machine is awake. */
  muted: { type: Boolean, default: false },
  /** Badge colour. `serving`/`online` are up; `idle`/`offline` are not. */
  presence: { type: String, default: 'idle' },
  /** Show the remove control on hover (stale rows only). */
  removable: { type: Boolean, default: false },
  channel: { type: String, default: null },
  sandbox: { type: String, default: null },
})

/**
 * Only non-default, CLASSIFIED values earn a chip; a stock install shows
 * none. The backend reports 'unknown' for a bundle id it cannot map to a
 * channel — a chip saying so would be noise, not a qualifier.
 */
const tags = computed(() => {
  const out = []
  if (props.channel && props.channel !== 'production' && props.channel !== 'unknown') out.push(props.channel)
  if (props.sandbox && props.sandbox !== 'default') out.push(props.sandbox)
  return out
})

defineEmits(['select', 'remove'])

const badgeClass = computed(() => {
  switch (props.presence) {
    case 'serving':
      return 'bg-accent-hi'
    case 'online':
      return 'bg-blue-500'
    case 'offline':
      return 'bg-content-muted/60'
    default:
      return 'bg-content-muted'
  }
})

const rowClass = computed(() => {
  if (props.selected) return 'bg-selection/15 text-content'
  if (props.muted) return 'text-content-muted hover:bg-overlay-subtle hover:text-content-secondary'
  return 'text-content-secondary hover:bg-overlay-subtle hover:text-content'
})
</script>
