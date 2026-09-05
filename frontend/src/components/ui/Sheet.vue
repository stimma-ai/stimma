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
  maxHeight: '85dvh',
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
        class="fixed inset-0 z-menu flex flex-col justify-end bg-overlay-backdrop"
        @click.self="closeOnBackdrop && close()"
      >
        <div
          ref="panelRef"
          tabindex="-1"
          role="dialog"
          class="sheet-panel relative flex flex-col bg-surface border-t border-edge rounded-t-lg shadow-2xl outline-none pb-safe"
          :style="panelStyle"
        >
          <div class="flex-none flex items-center justify-center pt-2 pb-1" aria-hidden="true">
            <span class="w-9 h-1 rounded-full bg-overlay-light"></span>
          </div>
          <div v-if="title || $slots.header" class="flex-none px-4 py-2">
            <slot name="header">
              <h2 class="text-[15px] font-semibold text-content">{{ title }}</h2>
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
