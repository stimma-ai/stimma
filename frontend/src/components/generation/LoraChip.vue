<template>
  <div
    :class="[
      'group flex items-center gap-1.5 py-1.5 border-b border-edge-subtle last:border-b-0 text-sm select-none cursor-pointer transition-colors',
      unavailable ? 'opacity-60' : item.enabled ? '' : 'opacity-50'
    ]"
    @pointerdown="onPointerDown"
    @click.stop="onClick"
    @contextmenu.stop.prevent="$emit('contextmenu', $event)"
  >
    <!-- Enable dot -->
    <div class="shrink-0 w-3 flex items-center justify-center">
      <div v-if="item.enabled && !unavailable" class="w-2.5 h-2.5 rounded-full bg-accent-hi" />
      <div v-else class="w-2.5 h-2.5 rounded-full border border-content-muted" />
    </div>

    <!-- Name + secondary chips -->
    <div class="flex-1 min-w-0" :title="unavailable ? item.lora + ' — not available for this tool' : item.lora">
      <div class="flex items-center gap-1">
        <span :class="['truncate text-[13px]', unavailable ? 'line-through' : (item.enabled ? 'font-medium' : '')]">{{ displayName.primary }}</span>
        <span
          v-for="chip in secondaryChips"
          :key="chip"
          class="shrink-0 text-[9px] leading-none px-1 py-0.5 rounded bg-overlay-subtle text-content-tertiary font-mono uppercase"
        >{{ chip }}</span>
      </div>
      <div v-if="showRaw && directoryPath" class="text-[9px] text-content-muted truncate mt-0.5">
        {{ directoryPath }}
      </div>
    </div>

    <!-- Weight cluster: − value + (hover reveals the steppers), ✕ far right.
         The whole row drags (root pointerdown); no grab handle needed. -->
    <button
      @click.stop="decrementWeight"
      @pointerdown.stop
      type="button"
      class="shrink-0 w-4 h-4 flex items-center justify-center text-[11px] text-content-tertiary hover:text-content opacity-0 group-hover:opacity-100 transition-opacity"
    >−</button>
    <span @pointerdown.stop @click.stop class="shrink-0">
      <ScrubValue
        :model-value="item.weight"
        @update:model-value="emitWeight"
        :min="0" :max="10" :step="0.05"
        :disabled="unavailable"
        :non-default="Math.abs(item.weight - 1) > 0.001"
        :format="(v: number) => v.toFixed(2)"
      />
    </span>
    <button
      @click.stop="incrementWeight"
      @pointerdown.stop
      type="button"
      class="shrink-0 w-4 h-4 flex items-center justify-center text-[11px] text-content-tertiary hover:text-content opacity-0 group-hover:opacity-100 transition-opacity"
    >+</button>
    <button
      @click.stop="$emit('remove')"
      @pointerdown.stop
      type="button"
      class="shrink-0 w-4 h-4 flex items-center justify-center text-content-muted hover:!text-red-500 opacity-0 group-hover:opacity-100 transition-opacity"
      title="Remove"
    >
      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-3 h-3">
        <path d="M6.28 5.22a.75.75 0 0 0-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 1 0 1.06 1.06L10 11.06l3.72 3.72a.75.75 0 1 0 1.06-1.06L11.06 10l3.72-3.72a.75.75 0 0 0-1.06-1.06L10 8.94 6.28 5.22Z" />
      </svg>
    </button>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import type { LoraPoolItem } from '../../composables/useLoraPool'
import { getDirectoryPath } from '../../composables/useLoraDisplayNames'
import ScrubValue from '../ui/ScrubValue.vue'
import type { LoraDisplayName } from '../../composables/useLoraDisplayNames'

interface Props {
  item: LoraPoolItem
  displayName: LoraDisplayName
  showRaw?: boolean
  groupId?: string | null
  unavailable?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  showRaw: false,
  groupId: null,
  unavailable: false,
})

const emit = defineEmits<{
  (e: 'toggle', event: MouseEvent): void
  (e: 'update-weight', weight: number): void
  (e: 'remove'): void
  (e: 'contextmenu', event: MouseEvent): void
  (e: 'drag-intent', event: PointerEvent, loraPath: string, groupId: string | null): void
}>()

const directoryPath = computed(() => getDirectoryPath(props.item.lora))

const secondaryChips = computed(() => {
  if (props.unavailable) return [] // keep unavailable chips quiet — drop the V9/STEP pills
  if (!props.displayName.secondary) return []
  return props.displayName.secondary.split(' ').filter(Boolean)
})

const formattedWeight = computed(() => {
  return props.item.weight.toFixed(2)
})

function emitWeight(v: number) {
  emit('update-weight', Math.round(v * 100) / 100)
}

function incrementWeight() {
  const newWeight = Math.min(10, props.item.weight + 0.05)
  emit('update-weight', Math.round(newWeight * 100) / 100)
}

function decrementWeight() {
  const newWeight = Math.max(0, props.item.weight - 0.05)
  emit('update-weight', Math.round(newWeight * 100) / 100)
}


// Drag: emit intent on pointerdown, parent decides when to start drag
const suppressClick = ref(false)

function onPointerDown(event: PointerEvent) {
  if (event.button !== 0) return // Left click only
  event.preventDefault() // Prevent text selection during drag
  suppressClick.value = false
  emit('drag-intent', event, props.item.lora, props.groupId)
}

function onClick(event: MouseEvent) {
  if (suppressClick.value) {
    suppressClick.value = false
    return
  }
  emit('toggle', event)
}

// Called by parent to suppress the click after a drag
function markDragged() {
  suppressClick.value = true
}

defineExpose({ markDragged })
</script>
