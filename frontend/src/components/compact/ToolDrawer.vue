<script setup lang="ts">
/**
 * The tool view's bottom drawer on a phone.
 *
 * Three heights: collapsed (handle + prompt), half, full. Drag the handle or
 * tap it to toggle. The prompt is pinned at the top at every height; the
 * tool's controls scroll beneath it under a sticky row of group names. The
 * groups are whatever the tool renders: any element inside the body that
 * carries `data-drawer-group="Label"` becomes a row entry, in DOM order, so a
 * video tool, an upscaler and a text-to-image tool each get their own row.
 *
 * This is deliberately not the kit Sheet: the Sheet is modal and one-height.
 * Nothing else in the app may use this component (DESIGN.md §1.11).
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'

type Level = 'collapsed' | 'half' | 'full'

const props = withDefaults(defineProps<{
  /** Initial height. Tools with nothing to show yet start half-open. */
  initial?: Level
  /** Pixels the drawer leaves for the header + tab bar at full height. */
  chromeReserve?: number
}>(), { initial: 'collapsed', chromeReserve: 150 })

const level = ref<Level>(props.initial)
const bodyEl = ref<HTMLElement | null>(null)
const rootEl = ref<HTMLElement | null>(null)
const promptEl = ref<HTMLElement | null>(null)
const dragPx = ref<number | null>(null)

// Heights come from the space the drawer actually has (its flex parent:
// hero + strip + drawer), never from the window, so full height can never
// push the handle out of view. `heroReserve` is what stays visible above.
const HERO_RESERVE = 96
function availableH() {
  const parent = rootEl.value?.parentElement
  return parent ? parent.clientHeight : window.innerHeight - props.chromeReserve
}
function heightFor(l: Level): number | null {
  if (l === 'collapsed') return null
  if (l === 'half') return Math.round(availableH() * 0.55)
  return availableH() - HERO_RESERVE
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
function onPointerDown(e: PointerEvent) {
  if (!rootEl.value) return
  startY = e.clientY
  startH = rootEl.value.getBoundingClientRect().height
  moved = false
  ;(e.target as HTMLElement).setPointerCapture?.(e.pointerId)
}
function onPointerMove(e: PointerEvent) {
  if (!e.buttons && e.pointerType === 'mouse') return
  const dy = startY - e.clientY
  if (Math.abs(dy) > 4) moved = true
  if (!moved) return
  const collapsedH = collapsedHeight()
  dragPx.value = Math.max(collapsedH, Math.min(availableH() - HERO_RESERVE, startH + dy))
}
function onPointerUp() {
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
  const handle = 28
  const prompt = promptEl.value?.getBoundingClientRect().height ?? 0
  return handle + prompt
}
// Collapsed is an explicit height too (measured from the pinned prompt), so
// every level change is one continuous height tween and the body below is
// simply clipped, never hidden. Re-measured whenever the prompt resizes.
const collapsedPx = ref<number | null>(null)
let promptObserver: ResizeObserver | null = null
function measureCollapsed() { collapsedPx.value = collapsedHeight() }

// --- groups: read from the body's data-drawer-group markers
interface Group { label: string; el: HTMLElement }
const groups = ref<Group[]>([])
const activeGroup = ref<string>('')
let observer: MutationObserver | null = null
function scanGroups() {
  const body = bodyEl.value
  if (!body) return
  const els = Array.from(body.querySelectorAll<HTMLElement>('[data-drawer-group]'))
  const seen = new Set<string>()
  groups.value = els
    .map((el) => ({ label: el.dataset.drawerGroup || '', el }))
    .filter((g) => g.label && !seen.has(g.label) && seen.add(g.label))
  updateActive()
}
function updateActive() {
  const body = bodyEl.value
  if (!body || groups.value.length === 0) { activeGroup.value = ''; return }
  const top = body.scrollTop + 12
  let current = groups.value[0].label
  for (const g of groups.value) {
    if (g.el.offsetTop - body.offsetTop <= top) current = g.label
  }
  activeGroup.value = current
}
function jumpTo(g: Group) {
  if (level.value === 'collapsed') level.value = 'half'
  g.el.scrollIntoView({ block: 'start', behavior: 'smooth' })
  activeGroup.value = g.label
}

onMounted(() => {
  requestAnimationFrame(measureCollapsed)
  if (promptEl.value && typeof ResizeObserver !== 'undefined') {
    promptObserver = new ResizeObserver(() => measureCollapsed())
    promptObserver.observe(promptEl.value)
  }
  scanGroups()
  if (bodyEl.value && typeof MutationObserver !== 'undefined') {
    observer = new MutationObserver(() => scanGroups())
    observer.observe(bodyEl.value, { childList: true, subtree: true, attributes: true, attributeFilter: ['data-drawer-group'] })
  }
})
onBeforeUnmount(() => { observer?.disconnect(); promptObserver?.disconnect() })

watch(level, (l) => { if (l !== 'collapsed') requestAnimationFrame(updateActive) })

defineExpose({ open: (l: Level) => { level.value = l }, level })
</script>

<template>
  <div
    ref="rootEl"
    class="tool-drawer flex-none flex flex-col min-h-0 max-h-[calc(100%-96px)] overflow-hidden bg-surface border-t border-edge rounded-t-xl shadow-[0_-10px_30px_rgba(0,0,0,0.45)] transition-[height] duration-200 ease-out"
    :style="style"
    :data-level="level"
  >
    <div
      class="flex-none h-7 flex items-center justify-center touch-none cursor-grab"
      role="button"
      aria-label="Toggle controls"
      @pointerdown="onPointerDown"
      @pointermove="onPointerMove"
      @pointerup="onPointerUp"
      @pointercancel="onPointerUp"
    >
      <span class="w-9 h-1 rounded-full bg-overlay-light"></span>
    </div>

    <!-- Pinned prompt (filled by the tool view's prompt editor teleport). -->
    <div ref="promptEl" id="tool-drawer-prompt" class="flex-none px-3 pb-2"></div>

    <!-- Group row: only when the drawer is open and the tool has groups. -->
    <div
      v-show="groups.length > 1"
      class="flex-none flex gap-4 px-4 h-10 items-stretch border-t border-b border-edge-subtle overflow-x-auto"
      role="tablist"
    >
      <button
        v-for="g in groups"
        :key="g.label"
        type="button"
        role="tab"
        class="flex items-center whitespace-nowrap text-[13.5px] border-b-2 border-none bg-transparent px-0"
        :class="activeGroup === g.label ? 'text-content border-b-accent' : 'text-content-tertiary border-b-transparent'"
        :style="{ borderBottom: activeGroup === g.label ? '2px solid rgb(var(--color-accent-rgb))' : '2px solid transparent' }"
        :aria-selected="activeGroup === g.label"
        @click="jumpTo(g)"
      >{{ g.label }}</button>
    </div>

    <!-- Body (filled by the tool view's controls teleport). -->
    <div
      ref="bodyEl"
      id="tool-drawer-body"
      class="flex-1 min-h-0 overflow-y-auto custom-scrollbar px-3 pb-safe"
      :class="level === 'collapsed' ? 'overflow-hidden' : ''"
      @scroll.passive="updateActive"
    ></div>
  </div>
</template>
