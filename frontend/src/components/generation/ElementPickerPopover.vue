<template>
  <!-- The element picker: MediaPickerPopover's panel, header and footer, with element
       tiles (cover + name + kind) in place of bare frames. On phones it is the app's
       bottom sheet, as the reference picker is. -->
  <Sheet v-if="isCompact" :show="true" content-class="!p-0" @close="$emit('close')">
    <div ref="panel" data-escape-layer data-element-picker class="flex flex-col">
      <ElementPickerBody v-bind="bodyProps" @pick="onPick" @new="$emit('new')" @changed="position" />
    </div>
  </Sheet>
  <Teleport v-else to="body">
    <div class="fixed inset-0 z-menu" @click="$emit('close')" />
    <div
      ref="panel" data-escape-layer data-element-picker
      class="fixed z-menu w-[min(640px,calc(100vw-16px))] bg-surface border border-edge-subtle rounded-lg shadow-lg flex flex-col overflow-hidden"
      :style="panelStyle"
    >
      <ElementPickerBody v-bind="bodyProps" @pick="onPick" @new="$emit('new')" @changed="position" />
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref } from 'vue'
import Sheet from '../ui/Sheet.vue'
import ElementPickerBody from './ElementPickerBody.vue'
import { useViewport } from '../../composables/useViewport'
import { consumeEscape, isTopmostEscapeLayer } from '../../utils/escapeLayers'

export interface PickedElement {
  asset_id: number
  revision_id: number
  name: string
  kind: string
  media_id: number
  cover_media_id: number | null
}

const props = defineProps<{
  anchorEl?: HTMLElement | null
  attachedIds: number[]
  projectId?: number | null
}>()
const emit = defineEmits<{ pick: [PickedElement]; new: []; close: [] }>()

const { isCompact } = useViewport()
const bodyProps = computed(() => ({ attachedIds: props.attachedIds, projectId: props.projectId ?? null }))

function onPick(el: PickedElement) { emit('pick', el) }

// --- Positioning: MediaPickerPopover's (below the anchor, clamped; above if roomier) ---
const panel = ref<HTMLElement | null>(null)
const panelStyle = ref<Record<string, string>>({ visibility: 'hidden' })
function position() {
  if (isCompact.value || !panel.value) return
  nextTick(() => {
    if (!panel.value) return
    const w = panel.value.offsetWidth
    const h = panel.value.offsetHeight
    if (!props.anchorEl) {
      panelStyle.value = { top: `${Math.max(8, (window.innerHeight - h) / 2)}px`, left: `${Math.max(8, (window.innerWidth - w) / 2)}px` }
      return
    }
    const rect = props.anchorEl.getBoundingClientRect()
    const left = Math.max(8, Math.min(rect.left, window.innerWidth - w - 8))
    const below = window.innerHeight - rect.bottom - 12
    const above = rect.top - 12
    let top = h <= below || below >= above ? rect.bottom + 6 : rect.top - 6 - h
    top = Math.max(8, Math.min(top, window.innerHeight - h - 8))
    panelStyle.value = { top: `${top}px`, left: `${left}px` }
  })
}
function onKeydown(e: KeyboardEvent) {
  if (isCompact.value) return  // the sheet handles its own Escape
  if (e.key === 'Escape' && isTopmostEscapeLayer(panel.value)) { consumeEscape(e); emit('close') }
}
onMounted(async () => {
  document.addEventListener('keydown', onKeydown)
  window.addEventListener('resize', position)
  await nextTick()
  position()
})
onUnmounted(() => {
  document.removeEventListener('keydown', onKeydown)
  window.removeEventListener('resize', position)
})
</script>
