<script setup lang="ts">
// One row grammar for the collection lists (chats, flows). A leading
// thumbnail, then a content column (title, and a one-line preview under it),
// then a fixed-width trailing column for the row's facts (a status or counts),
// then the date. Every column has its own edge, so facts and dates form
// straight vertical tracks down the page instead of following the end of each
// preview; the preview truncates before any fact does. Rows run the pane's full
// width, so the date lands on the same right edge as the header's controls; the
// hover tint runs full bleed and the row pads itself by the page margin.
//
// Narrow windows give the name first claim on width: it shares its line only
// with a bounded date, the preview takes the next line, and the facts sit
// together beneath them. A row passes one lighter set of facts there (see the
// `narrow:` classes at the call site) rather than truncating the name.
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
    class="group relative flex min-h-[4.25rem] cursor-pointer items-center px-page py-3 transition-colors narrow:min-h-0 narrow:py-2.5"
    :class="selected ? 'bg-selection/15' : 'hover:bg-overlay-subtle active:bg-overlay-light'"
  >
    <slot name="overlay" />
    <div
      class="grid w-full grid-cols-[2.5rem_minmax(0,1fr)_var(--row-trail)_3.25rem] gap-x-4 gap-y-0.5 narrow:grid-cols-[2.5rem_minmax(0,1fr)_3rem] narrow:gap-x-3 narrow:gap-y-0 compact:gap-x-3"
      :style="{ '--row-trail': trailingWidth }"
    >
      <div class="col-start-1 row-span-2 row-start-1 self-center narrow:row-span-3"><slot name="thumb" /></div>

      <div class="col-start-2 row-start-1 flex min-w-0 items-start"><slot name="title" /></div>
      <div v-if="$slots.preview" class="col-start-2 row-start-2 min-w-0 narrow:[grid-column:2/4]"><slot name="preview" /></div>

      <!-- Facts: level with the title on wider layouts, together beneath the
           name and preview on narrow ones. -->
      <div
        v-if="$slots.trailing"
        class="col-start-3 row-start-1 flex h-5 min-w-0 items-center justify-end narrow:[grid-column:2/4] narrow:row-start-3 narrow:mt-0.5 narrow:justify-start"
      >
        <slot name="trailing" />
      </div>

      <div class="col-start-4 row-start-1 h-5 whitespace-nowrap text-right font-mono text-xs leading-5 tabular-nums text-content-tertiary narrow:col-start-3">
        <slot name="date" />
      </div>
    </div>
  </div>
</template>
