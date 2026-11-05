<script setup lang="ts">
// One row grammar for the collection lists (chats, flows). A leading
// thumbnail, then a content column (title, and a one-line preview under it),
// then a fixed-width trailing column for the row's facts (a status or counts),
// then the date. Every column has its own edge, so facts and dates form
// straight vertical tracks down the page instead of following the end of each
// preview; the preview truncates before any fact does. The whole row is
// capped at a reading width so the date stays near the title on a wide window
// while the hover tint still runs full bleed.
//
// Narrow windows keep the same trailing column but move it under the date,
// level with the preview, so the preview never loses width to a status line.
// A row passes one lighter set of facts there (see the `narrow:` classes
// at the call site) rather than truncating the preview.
//
// The root keeps `cursor-pointer group` (acceptance specs click rows by it);
// listeners, test ids and classes fall through to it.
withDefaults(defineProps<{
  /** Row is selected (indigo wash instead of the hover tint). */
  selected?: boolean
  /** Width of the trailing facts column on wider layouts. */
  trailingWidth?: string
}>(), { selected: false, trailingWidth: '6.5rem' })
</script>

<template>
  <div
    class="group relative cursor-pointer px-page py-3 transition-colors"
    :class="selected ? 'bg-selection/15' : 'hover:bg-overlay-subtle'"
  >
    <slot name="overlay" />
    <div
      class="grid max-w-[56rem] grid-cols-[2.5rem_minmax(0,1fr)_var(--row-trail)_3.25rem] gap-x-4 gap-y-0.5 narrow:grid-cols-[2.5rem_minmax(0,1fr)_auto] narrow:gap-x-3 compact:gap-x-3"
      :style="{ '--row-trail': trailingWidth }"
    >
      <div class="col-start-1 row-span-2 row-start-1 self-center"><slot name="thumb" /></div>

      <div class="col-start-2 row-start-1 flex min-w-0 items-start"><slot name="title" /></div>
      <div v-if="$slots.preview" class="col-start-2 row-start-2 min-w-0"><slot name="preview" /></div>

      <!-- Facts: level with the title on wider layouts, level with the
           preview on narrow ones. -->
      <div
        v-if="$slots.trailing"
        class="col-start-3 row-start-1 flex h-5 min-w-0 items-center justify-end narrow:row-start-2 narrow:min-w-[2.75rem]"
      >
        <slot name="trailing" />
      </div>

      <div class="col-start-4 row-start-1 h-5 whitespace-nowrap text-right font-mono text-xs leading-5 tabular-nums text-content-tertiary narrow:col-start-3">
        <slot name="date" />
      </div>
    </div>
  </div>
</template>
