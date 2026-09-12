<script setup lang="ts">
/**
 * The phone editor's drawer for a large control (DESIGN.md §3.6a): the tone
 * curve, a color picker. It takes the deck's place at the bottom of the
 * column — the picture resizes above it, nothing is covered — and carries a
 * handle that dismisses it by tap or by a downward swipe, the way any sheet
 * does. Not a level of the row: the row is gone while it is up, and letting
 * go of the drawer brings the row back exactly where it was.
 */
const emit = defineEmits<{ close: [] }>()

let swipe: { id: number; y: number } | null = null
function down(event: PointerEvent) {
  swipe = { id: event.pointerId, y: event.clientY }
  ;(event.currentTarget as HTMLElement).setPointerCapture(event.pointerId)
}
function move(event: PointerEvent) {
  if (swipe?.id === event.pointerId && event.clientY - swipe.y > 40) { swipe = null; emit('close') }
}
function up(event: PointerEvent) {
  if (swipe?.id === event.pointerId) { swipe = null; emit('close') }
}
</script>

<template>
  <div
    class="editor-deck flex-none flex flex-col bg-base border-t border-edge-subtle pb-[max(10px,var(--safe-bottom,0px))]"
    data-drawer-chrome
    data-deck-drawer
  >
    <button
      type="button"
      class="flex-none h-8 w-full flex items-center justify-center touch-none"
      aria-label="Close"
      @pointerdown="down"
      @pointermove="move"
      @pointerup="up"
      @pointercancel="swipe = null"
    >
      <span class="w-9 h-1 rounded-full bg-overlay-light" aria-hidden="true" />
    </button>
    <div class="editor-drawer-body flex-none max-h-[64vh] overflow-y-auto px-3 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
      <slot />
    </div>
  </div>
</template>
