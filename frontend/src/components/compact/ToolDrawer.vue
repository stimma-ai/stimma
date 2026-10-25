<script setup lang="ts">
/**
 * The tool view's bottom drawer on a phone.
 *
 * Three heights: collapsed (handle + prompt), half, full. The drawer and its
 * content are one surface: dragging anywhere on it (outside text fields and
 * sliders) moves the drawer until it is full, and only then scrolls the
 * content; a flick goes to the next height. The handle also taps to toggle.
 * The prompt is pinned at the top at every height; the tool's controls
 * scroll beneath it as one column, in the order the tool renders them.
 *
 * `contentSized` is the image editor's variant: half is the body's natural
 * height, capped at `halfFraction` of the column, so a palette of four rows
 * never opens onto a wall of empty drawer, and the optional `strip` slot is
 * pinned UNDER the body at every height — collapsed shows just the strip.
 *
 * This is deliberately not the kit Sheet: the Sheet is modal and one-height.
 * Two screens use it, the tool view and the image editor, each with its own
 * `idPrefix`; nothing else may (DESIGN.md §1.11).
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'

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
  /** Half fits the body's content (up to `halfFraction`); see the header comment. */
  contentSized?: boolean
}>(), { initial: 'collapsed', chromeReserve: 150, idPrefix: 'tool-drawer', bodyClass: '', heroReserve: 96, halfFraction: 0.55, contentSized: false })

const level = ref<Level>(props.initial)
const bodyEl = ref<HTMLElement | null>(null)
const innerEl = ref<HTMLElement | null>(null)
const rootEl = ref<HTMLElement | null>(null)
const promptEl = ref<HTMLElement | null>(null)
const stripEl = ref<HTMLElement | null>(null)
const handleEl = ref<HTMLElement | null>(null)
const dragPx = ref<number | null>(null)

// Heights come from the space the drawer actually has (its flex parent:
// hero + strip + drawer), never from the window, so full height can never
// push the handle out of view. `heroReserve` is what stays visible above.
function availableH() {
  const parent = rootEl.value?.parentElement
  if (!parent) return window.innerHeight - props.chromeReserve
  // Siblings marked as chrome (the editor's header and dock) are not space the
  // drawer may take: full height is the column minus them minus the hero slice.
  let chrome = 0
  for (const sibling of Array.from(parent.children)) {
    if (sibling !== rootEl.value && (sibling as HTMLElement).dataset.drawerChrome !== undefined) {
      chrome += (sibling as HTMLElement).offsetHeight
    }
  }
  return parent.clientHeight - chrome
}
/** The chrome the drawer carries at every level: handle, pinned prompt, pinned strip. */
function chromeH() {
  // The handle row is a touch target (44px) that tucks 8px under the prompt.
  const handle = 36
  const prompt = promptEl.value?.getBoundingClientRect().height ?? 0
  const strip = stripEl.value?.getBoundingClientRect().height ?? 0
  return handle + prompt + strip
}
function heightFor(l: Level): number | null {
  if (l === 'collapsed') return null
  const full = availableH() - props.heroReserve
  if (l === 'full') return full
  const cap = Math.round(availableH() * props.halfFraction)
  if (!props.contentSized) return cap
  // Body padding is part of what the content needs to show whole.
  return Math.min(full, Math.max(chromeH(), Math.min(cap, chromeH() + bodyNaturalPx.value)))
}
const style = computed(() => {
  if (dragPx.value !== null) return { height: `${dragPx.value}px`, transition: 'none' }
  const h = heightFor(level.value)
  if (h === null) return { height: `${collapsedPx.value ?? 112}px` }
  return { height: `${h}px` }
})

// --- one gesture for the whole drawer -------------------------------------
// The drawer and its body read as ONE surface: pulling the content up grows
// the drawer until it is full and only then scrolls it; pulling down at the
// top of the content shrinks it. The handle also taps to toggle. Release
// snaps to the nearest height, or the next one in the flick's direction.
function levelHeights(): Array<[Level, number]> {
  return [['collapsed', collapsedHeight()], ['half', heightFor('half')!], ['full', heightFor('full')!]]
}
function clampH(h: number) {
  return Math.max(collapsedHeight(), Math.min(heightFor('full')!, h))
}
function settle(h: number, velocity: number) {
  const heights = levelHeights()
  const FLICK = 0.5 // px/ms
  if (Math.abs(velocity) > FLICK) {
    // A flick goes one level past wherever the finger let go.
    const ordered = velocity > 0 ? heights : [...heights].reverse()
    const next = ordered.find(([, lh]) => (velocity > 0 ? lh > h + 4 : lh < h - 4))
    level.value = next ? next[0] : ordered[ordered.length - 1][0]
  } else {
    heights.sort((a, b) => Math.abs(a[1] - h) - Math.abs(b[1] - h))
    level.value = heights[0][0]
  }
  dragPx.value = null
}
// Finger velocity (px/ms, positive = up) over the last ~100ms of the gesture.
let samples: Array<[number, number]> = []
function sample(y: number) {
  const now = performance.now()
  samples.push([now, y])
  while (samples.length > 2 && now - samples[0][0] > 100) samples.shift()
}
function velocity(): number {
  if (samples.length < 2) return 0
  const [t0, y0] = samples[0]
  const [t1, y1] = samples[samples.length - 1]
  return t1 > t0 ? (y0 - y1) / (t1 - t0) : 0
}

// Handle: pointer events (mouse and touch alike; it is touch-none).
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
  samples = []
  sample(e.clientY)
  ;(e.target as HTMLElement).setPointerCapture?.(e.pointerId)
}
function onPointerMove(e: PointerEvent) {
  if (activePointerId !== e.pointerId) return
  const dy = startY - e.clientY
  if (Math.abs(dy) > 4) moved = true
  if (!moved) return
  sample(e.clientY)
  dragPx.value = clampH(startH + dy)
}
function toggle() {
  if (level.value === 'collapsed') level.value = 'half'
  else if (level.value === 'half') {
    // Content-sized: a body that already shows whole has nowhere to grow, so
    // the tap folds it instead of opening onto empty drawer.
    const half = heightFor('half')!
    const fits = chromeH() + bodyNaturalPx.value <= half
    level.value = props.contentSized && !fits ? 'full' : 'collapsed'
  } else {
    // Full folds all the way: two taps close the drawer from any height, so a
    // tall panel can never trap the picture behind it.
    level.value = 'collapsed'
  }
}
function onPointerUp(e: PointerEvent) {
  if (activePointerId !== e.pointerId) return
  activePointerId = null
  if (!moved) {
    toggle()
    dragPx.value = null
    return
  }
  sample(e.clientY)
  settle(dragPx.value ?? startH, velocity())
}

// Prompt and body: touch events, so the drawer can claim a vertical drag
// before the browser turns it into a scroll. Text fields, sliders and
// anything marked data-drawer-no-drag keep their own gestures.
type TouchMode = 'pending' | 'drag' | 'native'
let touch: { id: number; x: number; y: number; h: number; inBody: boolean; mode: TouchMode; scroll: number } | null = null
const NO_DRAG = 'textarea, input, select, [contenteditable="true"], [data-drawer-no-drag]'
function onTouchStart(e: TouchEvent) {
  if (touch || e.touches.length !== 1 || !rootEl.value) return
  const target = e.target as HTMLElement
  if (handleEl.value?.contains(target) || target.closest(NO_DRAG)) return
  const t = e.touches[0]
  touch = {
    id: t.identifier, x: t.clientX, y: t.clientY,
    h: rootEl.value.getBoundingClientRect().height,
    inBody: !!bodyEl.value?.contains(target),
    mode: 'pending', scroll: bodyEl.value?.scrollTop ?? 0,
  }
  samples = []
  sample(t.clientY)
}
function onTouchMove(e: TouchEvent) {
  if (!touch) return
  const t = Array.from(e.changedTouches).find((c) => c.identifier === touch!.id)
  if (!t) return
  if (touch.mode === 'pending') {
    const dx = t.clientX - touch.x
    const dy = touch.y - t.clientY
    if (Math.abs(dx) < 3 && Math.abs(dy) < 3) return
    const full = heightFor('full')!
    const atTop = !touch.inBody || (bodyEl.value?.scrollTop ?? 0) <= 0
    if (Math.abs(dx) > Math.abs(dy)) touch.mode = 'native'
    else if (dy > 0) touch.mode = touch.h < full - 1 ? 'drag' : 'native'
    else touch.mode = atTop && touch.h > collapsedHeight() + 1 ? 'drag' : 'native'
  }
  if (touch.mode !== 'drag') return
  if (e.cancelable) e.preventDefault()
  sample(t.clientY)
  const want = touch.h + (touch.y - t.clientY)
  const h = clampH(want)
  dragPx.value = h
  // Past full, the same finger keeps going as a scroll of the content.
  if (bodyEl.value && want > h) bodyEl.value.scrollTop = touch.scroll + (want - h)
}
function onTouchEnd(e: TouchEvent) {
  if (!touch) return
  if (!Array.from(e.changedTouches).some((c) => c.identifier === touch!.id)) return
  const wasDrag = touch.mode === 'drag'
  touch = null
  if (!wasDrag) return
  settle(dragPx.value ?? 0, e.type === 'touchcancel' ? 0 : velocity())
}

// A tool without a prompt pins nothing, and collapsed would be a bare handle.
// The floor keeps a peek of the first controls (about the height a pinned
// prompt gives), so the drawer still reads as there and grabbable.
const COLLAPSED_MIN = 124
function collapsedHeight(): number {
  return Math.max(COLLAPSED_MIN, chromeH())
}
// Collapsed is an explicit height too (measured from the pinned prompt), so
// every level change is one continuous height tween and the body below is
// simply clipped, never hidden. Re-measured whenever the prompt resizes.
const collapsedPx = ref<number | null>(null)
/** The body's content height, for the content-sized half level. */
const bodyNaturalPx = ref(0)
let observer: ResizeObserver | null = null
function measure() {
  collapsedPx.value = collapsedHeight()
  const body = bodyEl.value
  const inner = innerEl.value
  if (body && inner) {
    const styles = getComputedStyle(body)
    bodyNaturalPx.value = inner.getBoundingClientRect().height
      + parseFloat(styles.paddingTop) + parseFloat(styles.paddingBottom)
  }
}
watch(level, () => { if (props.contentSized) measure() })

onMounted(() => {
  requestAnimationFrame(measure)
  // Non-passive: the drawer must be able to cancel the scroll it claims.
  rootEl.value?.addEventListener('touchmove', onTouchMove, { passive: false })
  if (typeof ResizeObserver !== 'undefined') {
    observer = new ResizeObserver(() => measure())
    if (promptEl.value) observer.observe(promptEl.value)
    if (stripEl.value) observer.observe(stripEl.value)
    if (innerEl.value) observer.observe(innerEl.value)
  }
})
onBeforeUnmount(() => {
  observer?.disconnect()
  rootEl.value?.removeEventListener('touchmove', onTouchMove)
})

defineExpose({
  open: (l: Level) => { level.value = l },
  scrollToTop: () => { if (bodyEl.value) bodyEl.value.scrollTop = 0 },
  level,
})
</script>

<template>
  <div
    ref="rootEl"
    class="tool-drawer flex-none flex flex-col min-h-0 overflow-hidden bg-surface border-t border-edge rounded-t-xl shadow-[0_-10px_30px_rgba(0,0,0,0.45)] transition-[height] duration-200 ease-out"
    :style="[style, { maxHeight: `calc(100% - ${heroReserve}px)` }]"
    :data-level="level"
    @touchstart.passive="onTouchStart"
    @touchend="onTouchEnd"
    @touchcancel="onTouchEnd"
  >
    <div
      ref="handleEl"
      class="flex-none h-11 -mb-2 flex items-center justify-center touch-none cursor-grab"
      role="button"
      aria-label="Toggle controls"
      tabindex="0"
      @keydown.enter.prevent="toggle"
      @keydown.space.prevent="toggle"
      @pointerdown="onPointerDown"
      @pointermove="onPointerMove"
      @pointerup="onPointerUp"
      @pointercancel="activePointerId = null; dragPx = null"
    >
      <span class="w-9 h-1 rounded-full bg-overlay-light"></span>
    </div>

    <!-- Pinned prompt (filled by the tool view's prompt editor teleport, or
         the #pin slot). -->
    <div ref="promptEl" :id="`${idPrefix}-prompt`" class="flex-none px-4 pb-3 empty:pb-0"><slot name="pin" /></div>

    <!-- Body (filled by the tool view's controls teleport, or the default slot). -->
    <div
      ref="bodyEl"
      :id="`${idPrefix}-body`"
      class="flex-1 min-h-0 overflow-y-auto overscroll-contain custom-scrollbar px-4"
      :class="[level === 'collapsed' ? 'overflow-hidden' : '', $slots.strip ? '' : 'pb-safe', bodyClass]"
    >
      <div ref="innerEl">
        <slot />
        <!-- Keep teleported panels separate from the slot's dynamic children.
             Switching tools must never reconcile two owners in one DOM list. -->
        <div :id="`${idPrefix}-panels`" class="contents" />
      </div>
    </div>

    <!-- Pinned strip: the editor's sub-tools, visible at every level. -->
    <div v-if="$slots.strip" ref="stripEl" class="flex-none"><slot name="strip" /></div>
  </div>
</template>
