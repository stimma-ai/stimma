<template>
  <div
    :class="[
      'rounded-lg border text-sm select-none cursor-pointer transition-colors',
      unavailable
        ? 'bg-surface-raised/20 border-edge/20 text-content-muted opacity-60'
        : item.enabled
          ? 'bg-blue-500/10 border-blue-500/30 text-content'
          : 'bg-surface-raised/30 border-edge/30 text-content-secondary'
    ]"
    @pointerdown="onPointerDown"
    @click.stop="onClick"
    @contextmenu.stop.prevent="$emit('contextmenu', $event)"
  >
    <div class="flex items-center gap-1.5 px-2 py-1.5">
      <!-- Toggle dot -->
      <div class="shrink-0 w-3 flex items-center justify-center">
        <div v-if="item.enabled && !unavailable" class="w-2.5 h-2.5 rounded-full bg-blue-500" />
        <div v-else class="w-2.5 h-2.5 rounded-full border border-content-muted" />
      </div>

      <!-- Name + secondary chips -->
      <div class="flex-1 min-w-0" :title="unavailable ? item.lora + ' — not available for this tool' : item.lora">
        <div class="flex items-center gap-1">
          <span :class="['truncate text-xs', unavailable ? 'line-through' : (item.enabled ? 'font-medium' : '')]">{{ displayName.primary }}</span>
          <span
            v-for="chip in secondaryChips"
            :key="chip"
            class="shrink-0 text-[9px] leading-none px-1 py-0.5 rounded bg-surface-raised/50 text-content-tertiary font-mono uppercase"
          >{{ chip }}</span>
        </div>
        <div v-if="showRaw && directoryPath" class="text-[9px] text-content-muted truncate mt-0.5">
          {{ directoryPath }}
        </div>
      </div>

      <!-- Weight stepper -->
      <div class="shrink-0 flex items-center bg-surface rounded-full border border-edge/50" @click.stop @pointerdown.stop>
        <button
          @click.stop="decrementWeight"
          type="button"
          class="w-5 h-5 flex items-center justify-center text-[10px] text-content-secondary hover:bg-surface-hover rounded-l-full transition-colors"
        >−</button>
        <input v-no-autocorrect
          type="text"
          :value="formattedWeight"
          @click.stop
          @input="onWeightInput"
          @blur="onWeightBlur"
          @keydown.enter="($event.target as HTMLInputElement).blur()"
          class="w-8 text-[11px] tabular-nums text-center bg-transparent border-none outline-none text-content"
        />
        <button
          @click.stop="incrementWeight"
          type="button"
          class="w-5 h-5 flex items-center justify-center text-[10px] text-content-secondary hover:bg-surface-hover rounded-r-full transition-colors"
        >+</button>
      </div>

      <!-- Remove button -->
      <button
        @click.stop="$emit('remove')"
        @pointerdown.stop
        type="button"
        class="shrink-0 w-4 h-4 flex items-center justify-center text-content-muted hover:!text-red-500 rounded-full transition-colors"
        title="Remove"
      >
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-3 h-3">
          <path d="M6.28 5.22a.75.75 0 0 0-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 1 0 1.06 1.06L10 11.06l3.72 3.72a.75.75 0 1 0 1.06-1.06L11.06 10l3.72-3.72a.75.75 0 0 0-1.06-1.06L10 8.94 6.28 5.22Z" />
        </svg>
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import type { LoraPoolItem } from '../../composables/useLoraPool'
import { getDirectoryPath } from '../../composables/useLoraDisplayNames'
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

function incrementWeight() {
  const newWeight = Math.min(10, props.item.weight + 0.05)
  emit('update-weight', Math.round(newWeight * 100) / 100)
}

function decrementWeight() {
  const newWeight = Math.max(0, props.item.weight - 0.05)
  emit('update-weight', Math.round(newWeight * 100) / 100)
}

let pendingValue = ''

function onWeightInput(event: Event) {
  pendingValue = (event.target as HTMLInputElement).value
}

function onWeightBlur(event: Event) {
  const input = event.target as HTMLInputElement
  const value = parseFloat(pendingValue || input.value)
  if (!isNaN(value)) {
    const clamped = Math.max(0, Math.min(10, value))
    emit('update-weight', Math.round(clamped * 100) / 100)
  }
  input.value = formattedWeight.value
  pendingValue = ''
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
