<script setup lang="ts">
// Atelier bottom sheet (DESIGN.md §1.11). The compact-viewport presentation
// for menus, pickers and small dialogs: teleports to body at the menu tier,
// slides up from the bottom edge, pads for the device safe area, closes on
// backdrop tap or Escape. On wide viewports callers keep using Modal /
// ContextMenu; this component is only ever rendered when useViewport says
// compact or coarse-pointer.
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'

const props = withDefaults(defineProps<{
  show: boolean
  /** Optional title row. Omit for menus that carry their own preview header. */
  title?: string
  /** Height cap as a viewport fraction; content scrolls inside. */
  maxHeight?: string
  closeOnBackdrop?: boolean
}>(), {
  title: '',
  maxHeight: 'var(--sheet-panel-max-h)',
  closeOnBackdrop: true,
})

const emit = defineEmits<{ close: [] }>()

const panelRef = ref<HTMLElement | null>(null)
const layerRef = ref<HTMLElement | null>(null)

const panelStyle = computed(() => ({ maxHeight: props.maxHeight }))

function close() { emit('close') }

function isTopmostLayer(): boolean {
  const layers = document.querySelectorAll('[data-modal-layer]')
  return layers.length === 0 || layers[layers.length - 1] === layerRef.value
}

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape' && isTopmostLayer()) {
    e.stopPropagation()
    close()
  }
}

watch(() => props.show, async (show) => {
  if (show) {
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
        class="fixed inset-0 z-menu flex flex-col justify-end bg-overlay-backdrop coarse:cursor-pointer"
        @click.self="closeOnBackdrop && close()"
      >
        <div
          ref="panelRef"
          tabindex="-1"
          role="dialog"
          class="sheet-panel relative flex flex-col bg-surface border-t border-edge shadow-2xl outline-none pb-safe cursor-auto"
          style="border-radius: var(--sheet-radius) var(--sheet-radius) 0 0"
          :style="panelStyle"
        >
          <div class="flex-none flex items-center justify-center" style="padding-top: var(--sheet-handle-top); height: var(--sheet-pad-top)" aria-hidden="true">
            <span class="rounded-full bg-overlay-light" style="width: var(--sheet-handle-w); height: var(--sheet-handle-h)"></span>
          </div>
          <div v-if="title || $slots.header" class="flex-none px-4 pt-1 pb-1">
            <slot name="header">
              <h2 class="text-[14px] font-semibold text-content">{{ title }}</h2>
            </slot>
          </div>
          <div class="flex-1 min-h-0 overflow-y-auto custom-scrollbar">
            <slot />
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>
