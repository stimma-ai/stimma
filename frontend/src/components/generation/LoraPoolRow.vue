<template>
  <div
    :class="[
      'group flex gap-2 px-2 rounded-md text-sm transition-colors duration-150 select-none hover:bg-overlay-subtle',
      showRaw && directoryPath ? 'items-start' : 'items-center',
      showRaw && directoryPath ? 'py-2' : 'min-h-10 py-1.5',
      item.enabled
        ? 'text-content'
        : 'text-content-secondary opacity-50'
    ]"
    draggable="true"
    @dragstart="onDragStart"
    @dragend="$emit('dragend')"
    @dragover.prevent="$emit('dragover', $event)"
    @drop="$emit('drop')"
    @contextmenu.stop.prevent="$emit('contextmenu', $event)"
  >
    <!-- Toggle circle -->
    <div :class="['shrink-0 w-4 h-4 flex items-center justify-center cursor-pointer', showRaw && directoryPath ? 'mt-1.5' : '']" @click.stop="$emit('toggle', $event)">
      <div v-if="item.enabled" class="w-2.5 h-2.5 rounded-full bg-accent" />
      <div v-else class="w-2.5 h-2.5 rounded-full border border-content-muted" />
    </div>

    <!-- Name: click to toggle, drag to reorder -->
    <div
      class="flex-1 min-w-0 overflow-hidden cursor-grab active:cursor-grabbing"
      :title="item.lora"
      @click.stop="$emit('toggle', $event)"
    >
      <div class="flex items-center gap-2">
        <span class="font-medium truncate">{{ displayName.primary }}</span>
        <span
          v-for="chip in secondaryChips"
          :key="chip"
          class="shrink-0 text-[10px] leading-none px-1.5 py-0.5 rounded-md bg-overlay-subtle text-content-tertiary font-mono uppercase"
        >{{ chip }}</span>
      </div>
      <div v-if="showRaw && directoryPath" class="text-[10px] text-content-muted truncate mt-0.5">
        {{ directoryPath }}
      </div>
    </div>

    <!-- Weight stepper -->
    <div :class="['shrink-0 flex items-center bg-overlay-subtle rounded-full', showRaw && directoryPath ? 'mt-1' : '']">
      <button
        @click.stop="decrementWeight"
        type="button"
        class="w-5 h-5 flex items-center justify-center text-xs text-content-secondary hover:bg-overlay-light rounded-l-full transition-colors duration-150"
      >-</button>
      <input v-no-autocorrect
        type="text"
        :value="formattedWeight"
        @click.stop
        @input="onWeightInput"
        @blur="onWeightBlur"
        @keydown.enter="($event.target as HTMLInputElement).blur()"
        :class="['w-9 text-xs font-mono tabular-nums text-center bg-transparent border-none outline-none', item.weight !== 1 ? 'text-accent' : 'text-content']"
      />
      <button
        @click.stop="incrementWeight"
        type="button"
        class="w-5 h-5 flex items-center justify-center text-xs text-content-secondary hover:bg-overlay-light rounded-r-full transition-colors duration-150"
      >+</button>
    </div>

    <!-- Remove button -->
    <button
      @click.stop="$emit('remove')"
      type="button"
      :class="['shrink-0 w-5 h-5 flex items-center justify-center text-content-muted opacity-0 group-hover:opacity-100 hover:text-red-400 rounded-full transition-colors duration-150', showRaw && directoryPath ? 'mt-1' : '']"
      title="Remove"
    >
      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-3.5 h-3.5">
        <path d="M6.28 5.22a.75.75 0 0 0-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 1 0 1.06 1.06L10 11.06l3.72 3.72a.75.75 0 1 0 1.06-1.06L11.06 10l3.72-3.72a.75.75 0 0 0-1.06-1.06L10 8.94 6.28 5.22Z" />
      </svg>
    </button>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { LoraPoolItem } from '../../composables/useLoraPool'
import { getDirectoryPath } from '../../composables/useLoraDisplayNames'
import type { LoraDisplayName } from '../../composables/useLoraDisplayNames'

interface Props {
  item: LoraPoolItem
  index: number
  displayName: LoraDisplayName
  showRaw?: boolean
}

const props = defineProps<Props>()

const emit = defineEmits<{
  (e: 'toggle', event: MouseEvent): void
  (e: 'update-weight', weight: number): void
  (e: 'remove'): void
  (e: 'contextmenu', event: MouseEvent): void
  (e: 'dragstart', index: number): void
  (e: 'dragend'): void
  (e: 'dragover', event: DragEvent): void
  (e: 'drop'): void
}>()

const directoryPath = computed(() => getDirectoryPath(props.item.lora))

const secondaryChips = computed(() => {
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

function onDragStart(event: DragEvent) {
  event.dataTransfer?.setData('text/plain', String(props.index))
  emit('dragstart', props.index)
}
</script>
