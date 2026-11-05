<script setup lang="ts">
// Atelier bottom sheet (DESIGN.md §1.11). The compact-viewport presentation
// for menus, pickers and small dialogs: teleports to body at the menu tier,
// slides up from the bottom edge, pads for the device safe area, closes on
// backdrop tap or Escape. On wide viewports callers keep using Modal /
// ContextMenu; this component is only ever rendered when useViewport says
// compact or coarse-pointer.
import { computed, nextTick, onBeforeUnmount, onUpdated, ref, watch } from 'vue'
import { ChevronDownIcon } from '@heroicons/vue/24/outline'
import { consumeEscape, isTopmostEscapeLayer } from '../../utils/escapeLayers'

const props = withDefaults(defineProps<{
  show: boolean
  /** Optional title row. Omit for menus that carry their own preview header. */
  title?: string
  /** Height cap as a viewport fraction; content scrolls inside. */
  maxHeight?: string
  /** Large interactive drawers can snap between a roomy and full height. */
  expandable?: boolean
  contentClass?: string
  closeOnBackdrop?: boolean
}>(), {
  title: '',
  maxHeight: 'var(--sheet-panel-max-h)',
  closeOnBackdrop: true,
  expandable: false,
  contentClass: '',
})

const emit = defineEmits<{ close: [] }>()

const panelRef = ref<HTMLElement | null>(null)
const layerRef = ref<HTMLElement | null>(null)
const bodyRef = ref<HTMLElement | null>(null)

// Scroll cue: a fade and a chevron while content remains below the edge.
const hasMore = ref(false)
function updateMore() {
  const el = bodyRef.value
  hasMore.value = !!el && el.scrollHeight - el.scrollTop - el.clientHeight > 8
}
watch(bodyRef, () => nextTick(updateMore), { flush: 'post' })
onUpdated(() => nextTick(updateMore))

const expanded = ref(false)
const dragHeight = ref<number | null>(null)
let drag: { id: number; y: number; height: number } | null = null
let ignoreClickUntil = 0
const availableHeight = 'calc(100dvh - var(--safe-top, 0px))'
const panelStyle = computed(() => ({
  maxHeight: props.expandable ? availableHeight : `min(${props.maxHeight}, ${availableHeight})`,
  height: props.expandable ? dragHeight.value !== null ? `${dragHeight.value}px` : expanded.value ? availableHeight : 'var(--sheet-drawer-h)' : undefined,
}))
function startResize(event: PointerEvent) {
  if (!event.isPrimary || event.button !== 0 || !panelRef.value) return
  drag = { id: event.pointerId, y: event.clientY, height: panelRef.value.getBoundingClientRect().height }
  ;(event.currentTarget as HTMLElement).setPointerCapture(event.pointerId)
}
function resize(event: PointerEvent) {
  if (!drag || drag.id !== event.pointerId) return
  dragHeight.value = Math.max(160, drag.height + drag.y - event.clientY)
}
function finishResize(event: PointerEvent) {
  if (!drag || drag.id !== event.pointerId) return
  const dy = event.clientY - drag.y
  if (Math.abs(dy) > 8) ignoreClickUntil = Date.now() + 400
  if (dy < -40) expanded.value = true
  else if (dy > 40 && expanded.value) expanded.value = false
  else if (dy > 100) close()
  drag = null
  dragHeight.value = null
}
function cancelResize() { drag = null; dragHeight.value = null }
function toggleSize() {
  if (Date.now() >= ignoreClickUntil) expanded.value = !expanded.value
}

function close() { emit('close') }

function onKeydown(e: KeyboardEvent) {
  if (!e.defaultPrevented && e.key === 'Escape' && isTopmostEscapeLayer(layerRef.value)) {
    consumeEscape(e)
    close()
  }
}

watch(() => props.show, async (show) => {
  if (show) {
    expanded.value = false
    cancelResize()
    window.addEventListener('keydown', onKeydown)
    await nextTick()
    panelRef.value?.focus()
  } else {
    window.removeEventListener('keydown', onKeydown)
  }
}, { immediate: true })

onBeforeUnmount(() => window.removeEventListener('keydown', onKeydown))
</script>

<template>
  <Teleport to="body">
    <Transition name="sheet">
      <div
        v-if="show"
        ref="layerRef"
        data-modal-layer
        data-sheet-layer
        :data-sheet-swipe="closeOnBackdrop && !expandable ? undefined : 'off'"
        class="fixed inset-0 z-menu flex flex-col justify-end bg-overlay-backdrop coarse:cursor-pointer"
        @click.self="closeOnBackdrop && close()"
      >
        <div
          ref="panelRef"
          tabindex="-1"
          role="dialog"
          class="sheet-panel relative flex flex-col bg-surface border-t border-edge shadow-2xl outline-none pb-safe pl-safe pr-safe cursor-auto"
          style="border-radius: var(--sheet-radius) var(--sheet-radius) 0 0"
          :style="panelStyle"
          :class="expandable && dragHeight === null ? 'transition-[height] duration-200 motion-reduce:transition-none' : ''"
        >
          <button v-if="expandable" type="button" class="flex-none h-12 w-full flex items-center justify-center touch-none cursor-ns-resize border-0 bg-transparent text-content-secondary" :aria-label="expanded ? 'Collapse drawer' : 'Expand drawer'" :aria-expanded="expanded" @pointerdown="startResize" @pointermove="resize" @pointerup="finishResize" @pointercancel="cancelResize" @click="toggleSize">
            <span class="rounded-full bg-overlay-light" style="width: var(--sheet-handle-w); height: var(--sheet-handle-h)"></span>
          </button>
          <div v-else class="flex-none flex items-center justify-center" style="padding-top: var(--sheet-handle-top); height: var(--sheet-pad-top)" aria-hidden="true">
            <span class="rounded-full bg-overlay-light" style="width: var(--sheet-handle-w); height: var(--sheet-handle-h)"></span>
          </div>
          <div v-if="title || $slots.header" class="flex-none px-4 pt-1" style="padding-bottom: var(--sheet-header-pb)">
            <slot name="header">
              <h2 class="text-[14px] font-semibold text-content">{{ title }}</h2>
            </slot>
          </div>
          <div ref="bodyRef" class="flex-1 min-h-0 overflow-y-auto overscroll-contain custom-scrollbar" :class="contentClass" @scroll.passive="updateMore">
            <slot />
          </div>
          <div v-if="hasMore" class="pointer-events-none absolute inset-x-0 bottom-[var(--safe-bottom,0px)] flex h-12 items-end justify-center bg-gradient-to-t from-surface to-transparent pb-1 text-content-tertiary" aria-hidden="true">
            <ChevronDownIcon class="h-4 w-4" :stroke-width="2" />
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>
