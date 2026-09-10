<script setup lang="ts">
/**
 * The tool view's bottom drawer on a phone.
 *
 * Three heights: collapsed (handle + prompt), half, full. Drag the handle or
 * tap it to toggle. The prompt is pinned at the top at every height; the
 * tool's controls scroll beneath it as one column, in the order the tool
 * renders them.
 *
 * This is deliberately not the kit Sheet: the Sheet is modal and one-height.
 * Two screens use it, the tool view and the image editor, each with its own
 * `idPrefix`; nothing else may (DESIGN.md §1.11).
 */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

type Level = 'collapsed' | 'half' | 'full'

const props = withDefaults(defineProps<{
  /** Initial height. Tools with nothing to show yet start half-open. */
  initial?: Level
  /** Pixels the drawer leaves for the header + tab bar at full height. */
  chromeReserve?: number
  /**
   * Prefix for the teleport-target ids. The tool view keeps the default;
   * the image editor mounts its own drawer under KeepAlive at the same time,
   * so the ids must differ or a teleport lands in the wrong screen.
   */
  idPrefix?: string
  /** Extra classes on the scrolling body (the editor stacks its panels there). */
  bodyClass?: string
  /**
   * Pixels of the parent that stay visible above the drawer at full height:
   * a slice of the hero, plus whatever sibling bar sits under the drawer.
   */
  heroReserve?: number
  /** The half level, as a share of the parent's height. */
  halfFraction?: number
}>(), { initial: 'collapsed', chromeReserve: 150, idPrefix: 'tool-drawer', bodyClass: '', heroReserve: 96, halfFraction: 0.55 })

const level = ref<Level>(props.initial)
const bodyEl = ref<HTMLElement | null>(null)
const rootEl = ref<HTMLElement | null>(null)
const promptEl = ref<HTMLElement | null>(null)
const dragPx = ref<number | null>(null)

// Heights come from the space the drawer actually has (its flex parent:
// hero + strip + drawer), never from the window, so full height can never
// push the handle out of view. `heroReserve` is what stays visible above.
function availableH() {
  const parent = rootEl.value?.parentElement
  return parent ? parent.clientHeight : window.innerHeight - props.chromeReserve
}
function heightFor(l: Level): number | null {
  if (l === 'collapsed') return null
  if (l === 'half') return Math.round(availableH() * props.halfFraction)
  return availableH() - props.heroReserve
}
const style = computed(() => {
  if (dragPx.value !== null) return { height: `${dragPx.value}px`, transition: 'none' }
  const h = heightFor(level.value)
  if (h === null) return { height: `${collapsedPx.value ?? 112}px` }
  return { height: `${h}px` }
})

// --- handle: tap toggles, drag sets height and snaps on release
let startY = 0
let startH = 0
let moved = false
let activePointerId: number | null = null
function onPointerDown(e: PointerEvent) {
  if (!rootEl.value || !e.isPrimary || e.button !== 0 || activePointerId !== null) return
  activePointerId = e.pointerId
  startY = e.clientY
  startH = rootEl.value.getBoundingClientRect().height
  moved = false
  ;(e.target as HTMLElement).setPointerCapture?.(e.pointerId)
}
function onPointerMove(e: PointerEvent) {
  if (activePointerId !== e.pointerId) return
  const dy = startY - e.clientY
  if (Math.abs(dy) > 4) moved = true
  if (!moved) return
  const collapsedH = collapsedHeight()
  dragPx.value = Math.max(collapsedH, Math.min(availableH() - props.heroReserve, startH + dy))
}
function onPointerUp(e: PointerEvent) {
  if (activePointerId !== e.pointerId) return
  activePointerId = null
  if (!moved) {
    level.value = level.value === 'collapsed' ? 'half' : 'collapsed'
    dragPx.value = null
    return
  }
  const h = dragPx.value ?? startH
  const half = heightFor('half')!
  const full = heightFor('full')!
  const collapsedH = collapsedHeight()
  // Snap to the nearest level.
  const candidates: Array<[Level, number]> = [['collapsed', collapsedH], ['half', half], ['full', full]]
  candidates.sort((a, b) => Math.abs(a[1] - h) - Math.abs(b[1] - h))
  level.value = candidates[0][0]
  dragPx.value = null
}
function collapsedHeight(): number {
  // The handle row is a touch target (44px) that tucks 8px under the prompt.
  const handle = 36
  const prompt = promptEl.value?.getBoundingClientRect().height ?? 0
  return handle + prompt
}
// Collapsed is an explicit height too (measured from the pinned prompt), so
// every level change is one continuous height tween and the body below is
// simply clipped, never hidden. Re-measured whenever the prompt resizes.
const collapsedPx = ref<number | null>(null)
let promptObserver: ResizeObserver | null = null
function measureCollapsed() { collapsedPx.value = collapsedHeight() }

onMounted(() => {
  requestAnimationFrame(measureCollapsed)
  if (promptEl.value && typeof ResizeObserver !== 'undefined') {
    promptObserver = new ResizeObserver(() => measureCollapsed())
    promptObserver.observe(promptEl.value)
  }
})
onBeforeUnmount(() => { promptObserver?.disconnect() })

defineExpose({ open: (l: Level) => { level.value = l }, level })
</script>

<template>
  <div
    ref="rootEl"
    class="tool-drawer flex-none flex flex-col min-h-0 overflow-hidden bg-surface border-t border-edge rounded-t-xl shadow-[0_-10px_30px_rgba(0,0,0,0.45)] transition-[height] duration-200 ease-out"
    :style="[style, { maxHeight: `calc(100% - ${heroReserve}px)` }]"
    :data-level="level"
  >
    <div
      class="flex-none h-11 -mb-2 flex items-center justify-center touch-none cursor-grab"
      role="button"
      aria-label="Toggle controls"
      tabindex="0"
      @keydown.enter.prevent="level = level === 'collapsed' ? 'half' : 'collapsed'"
      @keydown.space.prevent="level = level === 'collapsed' ? 'half' : 'collapsed'"
      @pointerdown="onPointerDown"
      @pointermove="onPointerMove"
      @pointerup="onPointerUp"
      @pointercancel="activePointerId = null; dragPx = null"
    >
      <span class="w-9 h-1 rounded-full bg-overlay-light"></span>
    </div>

    <!-- Pinned prompt (filled by the tool view's prompt editor teleport, or
         the #pin slot). -->
    <div ref="promptEl" :id="`${idPrefix}-prompt`" class="flex-none px-3 pb-2"><slot name="pin" /></div>

    <!-- Body (filled by the tool view's controls teleport, or the default slot). -->
    <div
      ref="bodyEl"
      :id="`${idPrefix}-body`"
      class="flex-1 min-h-0 overflow-y-auto custom-scrollbar px-3 pb-safe"
      :class="[level === 'collapsed' ? 'overflow-hidden' : '', bodyClass]"
    >
      <slot />
      <!-- Keep teleported panels separate from the slot's dynamic children.
           Switching tools must never reconcile two owners in one DOM list. -->
      <div :id="`${idPrefix}-panels`" class="contents" />
    </div>
  </div>
</template>
