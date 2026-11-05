<script setup lang="ts">
// "New outputs": what happens to every result automatically (markers to set,
// when to trash). One collapsed row in the form's section grammar, reading as
// its state in words (`Off`, `Delete after 1h`, `Favorite · delete after 1h`); it opens a small popover holding
// both controls, each one tap away.
import { computed, nextTick, onUnmounted, ref, watch } from 'vue'
import ToolSectionHeader from './ToolSectionHeader.vue'
import AutoMarkPicker from './AutoMarkPicker.vue'
import AutoDeletePicker from '../AutoDeletePicker.vue'
import { consumeEscape, isTopmostEscapeLayer } from '../../utils/escapeLayers'

interface Marker { id: number; name: string; icon_svg: string; color: string }

const props = defineProps<{
  markers: Marker[]
  autoMarkerIds: number[]
  autoDelete: string
  /** Compact layouts: the row only reads its state and asks the caller to open
   *  the run sheet, which already carries both controls. */
  sheet?: boolean
}>()
const emit = defineEmits<{
  'update:autoMarkerIds': [value: number[]]
  'update:autoDelete': [value: string]
  configure: []
}>()

function onToggle() {
  if (props.sheet) emit('configure')
  else open.value = !open.value
}

const open = ref(false)
const headerRef = ref<InstanceType<typeof ToolSectionHeader> | null>(null)
const panel = ref<HTMLElement | null>(null)
const panelStyle = ref<Record<string, string>>({ visibility: 'hidden' })

const state = computed(() => {
  const parts: string[] = []
  const names = props.markers.filter(m => props.autoMarkerIds.includes(m.id)).map(m => m.name)
  if (names.length) parts.push(names.join(', '))
  if (props.autoDelete !== 'never') parts.push(`${names.length ? 'delete' : 'Delete'} after ${props.autoDelete}`)
  return parts.length ? parts.join(' · ') : 'Off'
})

function position() {
  const anchor = headerRef.value?.$el as HTMLElement | undefined
  if (!anchor || !panel.value) return
  const rect = anchor.getBoundingClientRect()
  const w = panel.value.offsetWidth
  const h = panel.value.offsetHeight
  const left = Math.max(8, Math.min(rect.right - w, window.innerWidth - w - 8))
  const below = window.innerHeight - rect.bottom - 12
  panelStyle.value = h <= below || below >= rect.top - 12
    ? { top: `${rect.bottom + 4}px`, left: `${left}px` }
    : { bottom: `${window.innerHeight - rect.top + 4}px`, left: `${left}px` }
}

function onKeydown(e: KeyboardEvent) {
  if (!e.defaultPrevented && e.key === 'Escape' && isTopmostEscapeLayer(panel.value)) {
    consumeEscape(e)
    open.value = false
  }
}

watch(open, (isOpen) => {
  if (isOpen) {
    nextTick(position)
    document.addEventListener('keydown', onKeydown)
    window.addEventListener('resize', position)
  } else {
    document.removeEventListener('keydown', onKeydown)
    window.removeEventListener('resize', position)
    panelStyle.value = { visibility: 'hidden' }
  }
})
onUnmounted(() => {
  document.removeEventListener('keydown', onKeydown)
  window.removeEventListener('resize', position)
})
</script>

<template>
  <div role="group" aria-label="New outputs" class="mb-3 coarse:mb-1">
    <ToolSectionHeader
      ref="headerRef"
      disclosure
      label="New outputs"
      :state="state"
      :open="open"
      @toggle="onToggle"
    />
    <Teleport v-if="!sheet" to="body">
      <template v-if="open">
        <div class="fixed inset-0 z-menu" @click="open = false" />
        <div
          ref="panel"
          data-escape-layer
          class="fixed z-menu w-72 rounded-lg border border-edge-subtle bg-surface px-3 py-1 shadow-lg"
          :style="panelStyle"
        >
          <div class="flex min-h-11 items-center justify-between gap-3">
            <span class="text-xs text-content-secondary">Auto-mark</span>
            <AutoMarkPicker
              :markers="markers"
              :model-value="autoMarkerIds"
              @update:model-value="emit('update:autoMarkerIds', $event)"
            />
          </div>
          <div class="flex min-h-11 items-center justify-between gap-3">
            <span class="text-xs text-content-secondary">Auto-delete</span>
            <div class="flex items-center gap-1.5">
              <span v-if="autoDelete === 'never'" class="text-xs text-content-muted">Off</span>
              <AutoDeletePicker
                size="small"
                :model-value="autoDelete"
                @update:model-value="emit('update:autoDelete', $event)"
              />
            </div>
          </div>
        </div>
      </template>
    </Teleport>
  </div>
</template>
