<template>
  <div v-if="markers.length > 0" class="flex items-center gap-0.5">
    <!-- Quiet marker toggles (DESIGN.md §1.10): an outline glyph at rest; set =
         the marker's own color on the overlay backing, no outline. -->
    <button
      v-for="marker in markers"
      :key="marker.id"
      @click="toggleMarker(marker.id)"
      :class="[
        'w-7 h-7 coarse:w-11 coarse:h-11 rounded-md cursor-pointer transition-colors duration-150 flex items-center justify-center focus-visible:outline-none focus-visible:ring-2 ring-accent/60',
        isSelected(marker.id)
          ? 'bg-overlay-light'
          : 'text-content-secondary hover:bg-overlay-subtle hover:text-content'
      ]"
      :style="isSelected(marker.id) ? { color: marker.color } : {}"
      :title="marker.name"
      :aria-pressed="isSelected(marker.id)"
    >
      <span v-html="sanitizeSvg(marker.icon_svg)" class="w-icon-nav h-icon-nav flex-shrink-0 icon-container" :class="isSelected(marker.id) ? '' : 'marker-glyph-off'"></span>
    </button>
  </div>
</template>

<script setup lang="ts">
import { sanitizeSvg } from '../../utils/sanitizeHtml'

interface Marker {
  id: number
  name: string
  icon_svg: string
  color: string
}

interface Props {
  markers: Marker[]
  modelValue: number[]  // Selected marker IDs
}

const props = defineProps<Props>()

const emit = defineEmits<{
  (e: 'update:modelValue', value: number[]): void
}>()

function isSelected(markerId: number): boolean {
  return props.modelValue.includes(markerId)
}

function toggleMarker(markerId: number) {
  if (isSelected(markerId)) {
    emit('update:modelValue', props.modelValue.filter(id => id !== markerId))
  } else {
    emit('update:modelValue', [...props.modelValue, markerId])
  }
}
</script>
