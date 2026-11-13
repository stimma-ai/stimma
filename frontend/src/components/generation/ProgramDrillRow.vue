<template>
  <button type="button" :class="rowClass" @click="emit('open')">
    <span :class="wide ? 'shrink-0 max-w-[60%] text-content' : 'w-24 shrink-0 text-content'">{{ label }}</span>
    <span :class="['flex-1 min-w-0 truncate', wide ? 'text-right' : '', changed ? 'text-selection' : 'text-content-muted']">{{ text }}</span>
    <span
      v-if="changed"
      role="button"
      tabindex="0"
      class="shrink-0 p-0.5 coarse:p-2 coarse:-my-1.5 rounded-full text-selection hover:bg-selection/20"
      :aria-label="`Reset ${label}`"
      :data-reset="resetKey"
      @click.stop="emit('reset')"
      @keydown.enter.stop.prevent="emit('reset')"
    >
      <XMarkIcon class="w-3 h-3" />
    </span>
    <ChevronRightIcon class="w-3.5 h-4 shrink-0 text-content-muted" />
  </button>
</template>

<script setup lang="ts">
// A row that leads one level down in a card: a person's detail, a face's part, a region of
// descent. It says what is chosen there; its × puts that back. One root element, so the
// row's data attributes land on it.
import { ChevronRightIcon, XMarkIcon } from '@heroicons/vue/24/outline'

defineProps<{
  label: string
  /** What is chosen there; '' when nothing is. */
  text: string
  changed: boolean
  /** The `data-reset` of its ×. */
  resetKey: string
  /** A long label (a region's name) takes the room it needs, and what is chosen sits at the end. */
  wide?: boolean
}>()
const emit = defineEmits<{ (e: 'open'): void; (e: 'reset'): void }>()

const rowClass = 'w-full flex items-start gap-2 px-2 py-1.5 coarse:py-2.5 rounded-md text-left text-xs coarse:text-[13px] cursor-pointer hover:bg-overlay-subtle outline-none focus-visible:ring-1 focus-visible:ring-selection/60'
</script>
