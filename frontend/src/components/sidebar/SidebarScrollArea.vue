<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'

// The sidebar's scrolling region. The native scrollbar is hidden; a thin
// thumb overlays the row padding instead, so it never takes layout width,
// and it shows only while the sidebar is hovered or the list is moving.
// `flat` (the phone drawer) drops every box so the rows join the parent's
// single scroller.
const props = defineProps<{ flat?: boolean }>()
const emit = defineEmits<{ edges: [edges: { above: boolean; below: boolean }] }>()

const MIN_THUMB = 24
const scroller = ref<HTMLElement | null>(null)
const content = ref<HTMLElement | null>(null)
const metrics = ref({ top: 0, height: 0, scrollable: false })
const moving = ref(false)
const dragging = ref(false)
let movingTimer: ReturnType<typeof setTimeout> | null = null
let observer: ResizeObserver | null = null

function measure() {
  const el = scroller.value
  if (!el || props.flat) return
  const range = el.scrollHeight - el.clientHeight
  const scrollable = range > 1
  const height = scrollable ? Math.max(MIN_THUMB, (el.clientHeight * el.clientHeight) / el.scrollHeight) : 0
  const top = scrollable ? (el.scrollTop / range) * (el.clientHeight - height) : 0
  metrics.value = { top, height, scrollable }
  emit('edges', { above: el.scrollTop > 1, below: range - el.scrollTop > 1 })
}

function onScroll() {
  measure()
  moving.value = true
  if (movingTimer) clearTimeout(movingTimer)
  movingTimer = setTimeout(() => { moving.value = false }, 800)
}

// The scroller's box changes with the window; the content's changes as tabs
// open, close and collapse. Either moves the thumb.
watch([scroller, content, () => props.flat], () => {
  observer?.disconnect()
  observer = null
  if (props.flat || !scroller.value || !content.value) return
  observer = new ResizeObserver(measure)
  observer.observe(scroller.value)
  observer.observe(content.value)
  measure()
}, { flush: 'post', immediate: true })

onUnmounted(() => {
  observer?.disconnect()
  if (movingTimer) clearTimeout(movingTimer)
})

let dragStartY = 0
let dragStartScroll = 0

function onThumbDown(event: PointerEvent) {
  const el = scroller.value
  if (!el || event.button !== 0) return
  event.preventDefault()
  dragging.value = true
  dragStartY = event.clientY
  dragStartScroll = el.scrollTop
  ;(event.currentTarget as HTMLElement).setPointerCapture(event.pointerId)
}

function onThumbMove(event: PointerEvent) {
  const el = scroller.value
  if (!el || !dragging.value) return
  const travel = el.clientHeight - metrics.value.height
  if (travel <= 0) return
  el.scrollTop = dragStartScroll + ((event.clientY - dragStartY) * (el.scrollHeight - el.clientHeight)) / travel
}

function onThumbUp() {
  dragging.value = false
}

// The thumb sits outside the scroller, so a wheel over it is passed on.
function onThumbWheel(event: WheelEvent) {
  const el = scroller.value
  if (!el) return
  // Firefox reports mouse wheels in lines (and pages); everything else in pixels.
  const unit = event.deltaMode === WheelEvent.DOM_DELTA_LINE ? 40 : event.deltaMode === WheelEvent.DOM_DELTA_PAGE ? el.clientHeight : 1
  el.scrollTop += event.deltaY * unit
}

const thumbStyle = computed(() => ({ top: `${metrics.value.top}px`, height: `${metrics.value.height}px` }))
</script>

<template>
  <div :class="flat ? 'contents' : 'relative min-h-[40%] flex-1 basis-0'">
    <div
      ref="scroller"
      data-testid="sidebar-scroll"
      :class="flat ? 'contents' : 'h-full overflow-y-auto overscroll-contain [scrollbar-width:none] [&::-webkit-scrollbar]:hidden'"
      @scroll.passive="onScroll"
    >
      <div ref="content" data-nav-zone :class="flat ? 'contents' : 'flex flex-col gap-0.5 px-3 pb-3 coarse:gap-0'">
        <slot />
      </div>
    </div>
    <div
      v-if="!flat && metrics.scrollable"
      data-testid="sidebar-scroll-thumb"
      aria-hidden="true"
      class="absolute right-1 z-10 w-1.5 rounded-full transition-[opacity,background-color] duration-200 motion-reduce:transition-none"
      :class="dragging
        ? 'bg-content-muted/70 opacity-100'
        : ['bg-content-muted/40 hover:bg-content-muted/70', moving ? 'opacity-100' : 'opacity-0 group-hover/sidebar:opacity-100']"
      :style="thumbStyle"
      @wheel.passive="onThumbWheel"
      @pointerdown="onThumbDown"
      @pointermove="onThumbMove"
      @pointerup="onThumbUp"
      @pointercancel="onThumbUp"
    ></div>
  </div>
</template>
