<script setup lang="ts">
// Atelier Modal shell (STANDARDS.md §2, §3 "Modal" recipe). The one modal
// backdrop/card/transition implementation in the app — everything else in
// the modal family (ConfirmDialog, and eventually the ~25 ad-hoc modals in
// INVENTORY.md §2) builds on this rather than re-pasting Teleport/backdrop/
// Transition markup.
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { isTauri } from '../../apiConfig'

const props = withDefaults(defineProps<{
  show: boolean
  size?: 'sm' | 'md' | 'lg' | 'custom'
  /** Only used when size === 'custom'; passed through as the card's width class(es). */
  customClass?: string
  closeOnBackdrop?: boolean
  closeOnEsc?: boolean
  /** Nested-confirm case (a confirm launched from within another modal): z-confirm instead of z-modal. */
  nested?: boolean
  /** Picker launched from a menu/popover: one sanctioned tier above z-menu. */
  submenu?: boolean
}>(), {
  size: 'md',
  customClass: '',
  closeOnBackdrop: true,
  closeOnEsc: true,
  nested: false,
  submenu: false,
})

const emit = defineEmits<{
  close: []
}>()

const cardRef = ref<HTMLElement | null>(null)
const layerRef = ref<HTMLElement | null>(null)
let previouslyFocused: HTMLElement | null = null

const sizeClasses: Record<string, string> = {
  sm: 'max-w-[360px] w-full',
  md: 'max-w-[480px] w-full',
  lg: 'max-w-[720px] w-full',
}

const cardSizeClass = computed(() => props.size === 'custom' ? props.customClass : sizeClasses[props.size])
const zClass = computed(() => props.submenu ? 'z-submenu' : props.nested ? 'z-confirm' : 'z-modal')

// The backdrop covers the whole window, including the title-bar strip the
// TopBar/sidebar mark as a Tauri drag region, so window dragging dies while a
// modal is open. Re-declare the strip on the backdrop itself; the card sits
// above it so a tall modal's own top edge stays clickable.
const inTauri = isTauri()

function close() {
  emit('close')
}

function onBackdropClick() {
  if (props.closeOnBackdrop) close()
}

// Every open modal listens on window, and stopPropagation does not stop
// sibling listeners on the same target — so without this, one Escape inside
// a picker launched from Settings would close the picker, the folder
// dialog under it, and Settings itself. Layers teleport to body in opening
// order, so the last one in the document is the one on top.
function isTopmostLayer(): boolean {
  const layers = document.querySelectorAll('[data-modal-layer]')
  return layers.length === 0 || layers[layers.length - 1] === layerRef.value
}

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape' && props.closeOnEsc && isTopmostLayer()) {
    e.stopPropagation()
    close()
  }
}

watch(() => props.show, async (show) => {
  if (show) {
    previouslyFocused = document.activeElement as HTMLElement | null
    window.addEventListener('keydown', onKeydown)
    await nextTick()
    cardRef.value?.focus()
  } else {
    window.removeEventListener('keydown', onKeydown)
    previouslyFocused?.focus?.()
    previouslyFocused = null
  }
}, { immediate: true })

onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKeydown)
})
</script>

<template>
  <Teleport to="body">
    <Transition name="modal">
      <div
        v-if="show"
        ref="layerRef"
        data-modal-layer
        class="fixed inset-0 flex items-center justify-center bg-overlay-backdrop backdrop-blur-sm"
        :class="zClass"
        @click.self="onBackdropClick"
      >
        <div v-if="inTauri" class="absolute top-0 left-0 right-0 h-14" data-tauri-drag-region />
        <div
          ref="cardRef"
          tabindex="-1"
          class="relative bg-surface border border-edge rounded-lg shadow-2xl outline-none mx-4 compact:mx-3 compact:w-[calc(100%-1.5rem)] compact:max-w-none compact:max-h-[92dvh] compact:overflow-y-auto"
          :class="cardSizeClass"
        >
          <div v-if="$slots.header" class="px-6 py-4 border-b border-edge">
            <slot name="header" />
          </div>

          <slot />

          <div v-if="$slots.footer" class="px-6 py-4 border-t border-edge flex gap-3 justify-end">
            <slot name="footer" />
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>
